from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.orm import Session

from app import models, schemas, sla, crud
from app.database import get_db
from app.deps import get_current_user, require_technician

router = APIRouter(prefix="/tickets", tags=["Tickets"])


ALLOWED_TRANSITIONS = {
    models.Status.NEW:         {models.Status.ASSIGNED, models.Status.IN_PROGRESS},
    models.Status.ASSIGNED:    {models.Status.IN_PROGRESS, models.Status.ON_HOLD},
    models.Status.IN_PROGRESS: {models.Status.ON_HOLD, models.Status.RESOLVED},
    models.Status.ON_HOLD:     {models.Status.IN_PROGRESS},
    models.Status.RESOLVED:    {models.Status.CLOSED, models.Status.IN_PROGRESS},
    models.Status.CLOSED:      set(),
}


def _get_ticket_or_404(db: Session, ticket_id: int) -> models.Ticket:
    ticket = db.get(models.Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


def _assert_can_view(ticket: models.Ticket, user: models.User) -> None:
    """Requesters may only see their own tickets.

    Returns 404 rather than 403: a 403 would confirm the ticket exists,
    allowing an attacker to enumerate valid ticket IDs.
    """
    if user.role == "requester" and ticket.requester_id != user.id:
        raise HTTPException(status_code=404, detail="Ticket not found")


@router.post("", response_model=schemas.TicketOut,
             status_code=http_status.HTTP_201_CREATED)
def create_ticket(payload: schemas.TicketCreate,
                  db: Session = Depends(get_db),
                  current_user: models.User = Depends(get_current_user)):
    """Raise a ticket. Requester, priority and SLA targets are all server-set."""
    ticket = models.Ticket(
        reference=crud.generate_reference(db),
        title=payload.title,
        description=payload.description,
        category=payload.category,
        impact=payload.impact,
        urgency=payload.urgency,
        requester_id=current_user.id,          # from the token, never the payload
        status=models.Status.NEW,
        created_at=crud.utcnow(),
    )
    sla.set_sla_targets(ticket)

    db.add(ticket)
    db.flush()

    crud.log_event(db, ticket, "created",
                   f"Ticket raised: P{ticket.priority}",
                   actor_id=current_user.id)

    db.commit()
    db.refresh(ticket)
    return ticket


@router.get("", response_model=list[schemas.TicketOut])
def list_tickets(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    status: models.Status = Query(default=None),
    priority: int = Query(default=None, ge=1, le=4),
    assignee_id: int = Query(default=None),
    unassigned: bool = Query(default=False),
    limit: int = Query(default=50, le=200),
):
    """The queue. Technicians see everything; requesters see only their own."""
    q = db.query(models.Ticket)

    if current_user.role == "requester":
        q = q.filter(models.Ticket.requester_id == current_user.id)

    if status:
        q = q.filter(models.Ticket.status == status)
    if priority:
        q = q.filter(models.Ticket.priority == priority)
    if assignee_id:
        q = q.filter(models.Ticket.assignee_id == assignee_id)
    if unassigned:
        q = q.filter(models.Ticket.assignee_id.is_(None))

    return (q.order_by(models.Ticket.priority.asc(),
                       models.Ticket.created_at.asc())
             .limit(limit)
             .all())


@router.get("/{ticket_id}", response_model=schemas.TicketDetail)
def get_ticket(ticket_id: int,
               db: Session = Depends(get_db),
               current_user: models.User = Depends(get_current_user)):
    """One ticket with its audit trail and live SLA state."""
    ticket = _get_ticket_or_404(db, ticket_id)
    _assert_can_view(ticket, current_user)

    state = sla.sla_state(ticket)
    detail = schemas.TicketDetail.model_validate(ticket)
    detail.sla = schemas.SLAOut(
        state=state["state"],
        deadline=state["deadline"],
        remaining_minutes=int(state["remaining"].total_seconds() // 60),
    )
    return detail


@router.patch("/{ticket_id}/assign", response_model=schemas.TicketOut)
def assign_ticket(ticket_id: int, payload: schemas.TicketAssign,
                  db: Session = Depends(get_db),
                  current_user: models.User = Depends(require_technician)):
    """Assign a ticket to a technician. Technicians and managers only."""
    ticket = _get_ticket_or_404(db, ticket_id)

    assignee = db.get(models.User, payload.assignee_id)
    if not assignee:
        raise HTTPException(status_code=400, detail="Assignee does not exist")
    if assignee.role not in ("technician", "manager"):
        raise HTTPException(status_code=400,
                            detail="Tickets can only be assigned to technicians")

    ticket.assignee_id = assignee.id
    if ticket.status == models.Status.NEW:
        ticket.status = models.Status.ASSIGNED

    crud.log_event(db, ticket, "assigned",
                   f"Assigned to {assignee.name}",
                   actor_id=current_user.id)

    db.commit()
    db.refresh(ticket)
    return ticket


@router.patch("/{ticket_id}/status", response_model=schemas.TicketOut)
def change_status(ticket_id: int, payload: schemas.TicketStatusUpdate,
                  db: Session = Depends(get_db),
                  current_user: models.User = Depends(require_technician)):
    """Move a ticket through its lifecycle, managing the SLA pause clock."""
    ticket = _get_ticket_or_404(db, ticket_id)
    new_status = payload.status
    now = crud.utcnow()

    if new_status == ticket.status:
        raise HTTPException(status_code=409, detail="Ticket already in that status")

    if new_status not in ALLOWED_TRANSITIONS[ticket.status]:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move from {ticket.status.value} to {new_status.value}",
        )

    # Leaving ON_HOLD: bank the business time spent paused
    if ticket.status == models.Status.ON_HOLD and ticket.paused_since:
        paused = sla.business_time_between(ticket.paused_since, now)
        ticket.paused_seconds = (ticket.paused_seconds or 0) + int(paused.total_seconds())
        ticket.paused_since = None

    # Entering ON_HOLD: start the pause clock
    if new_status == models.Status.ON_HOLD:
        ticket.paused_since = now

    if new_status == models.Status.RESOLVED:
        ticket.resolved_at = now
    if new_status == models.Status.CLOSED:
        ticket.closed_at = now

    old_status = ticket.status
    ticket.status = new_status

    detail = f"{old_status.value} -> {new_status.value}"
    if payload.note:
        detail += f" ({payload.note})"
    crud.log_event(db, ticket, "status_change", detail, actor_id=current_user.id)

    db.commit()
    db.refresh(ticket)
    return ticket


@router.post("/{ticket_id}/comments", response_model=schemas.EventOut,
             status_code=http_status.HTTP_201_CREATED)
def add_comment(ticket_id: int, payload: schemas.CommentCreate,
                db: Session = Depends(get_db),
                current_user: models.User = Depends(get_current_user)):
    """Add a comment. A technician's first comment stops the response clock."""
    ticket = _get_ticket_or_404(db, ticket_id)
    _assert_can_view(ticket, current_user)

    if (ticket.first_response_at is None
            and current_user.role in ("technician", "manager")):
        ticket.first_response_at = crud.utcnow()

    event = crud.log_event(db, ticket, "comment", payload.body,
                           actor_id=current_user.id)
    db.commit()
    db.refresh(event)
    return event