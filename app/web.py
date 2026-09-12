from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import models, sla, crud
from app.config import ACCESS_TOKEN_EXPIRE_MINUTES
from app.database import get_db
from app.deps import COOKIE_NAME, get_web_user, require_web_technician
from app.routers.tickets import ALLOWED_TRANSITIONS
from app.security import verify_password, create_access_token
from app.templating import templates

router = APIRouter(tags=["Web"])


def _sla_view(ticket):
    """Flatten the SLA state into something a template can render."""
    state = sla.sla_state(ticket)
    return {
        "state": state["state"],
        "deadline": state["deadline"],
        "remaining_minutes": int(state["remaining"].total_seconds() // 60),
    }


# ---------- Authentication ----------

@router.get("/", include_in_schema=False)
def home(request: Request):
    if request.cookies.get(COOKIE_NAME):
        return RedirectResponse("/queue", status_code=302)
    return RedirectResponse("/login", status_code=302)


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"user": None})


@router.post("/login", include_in_schema=False)
def login_submit(request: Request,
                 email: str = Form(...),
                 password: str = Form(...),
                 db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request, "login.html",
            {"user": None, "email": email,
             "error": "Incorrect email or password."},
            status_code=401,
        )

    token = create_access_token(subject=str(user.id), role=user.role)
    response = RedirectResponse("/queue", status_code=303)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,              # JavaScript cannot read it
        samesite="lax",             # not sent on cross-site POSTs
        secure=False,               # set True behind HTTPS in production
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return response


@router.get("/logout", include_in_schema=False)
def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


# ---------- Queue ----------

@router.get("/queue", response_class=HTMLResponse, include_in_schema=False)
def queue(request: Request,
          status: str = "",
          priority: int = None,
          unassigned: str = "",
          db: Session = Depends(get_db),
          user: models.User = Depends(get_web_user)):
    q = db.query(models.Ticket)

    if user.role == "requester":
        q = q.filter(models.Ticket.requester_id == user.id)

    if status:
        q = q.filter(models.Ticket.status == models.Status(status))
    else:
        q = q.filter(models.Ticket.status != models.Status.CLOSED)

    if priority:
        q = q.filter(models.Ticket.priority == priority)
    if unassigned:
        q = q.filter(models.Ticket.assignee_id.is_(None))

    tickets = (q.order_by(models.Ticket.priority.asc(),
                          models.Ticket.created_at.asc())
                .limit(200).all())

    rows = [{"ticket": t, "sla": _sla_view(t)} for t in tickets]

    return templates.TemplateResponse(request, "queue.html", {
        "user": user,
        "rows": rows,
        "statuses": list(models.Status),
        "status": status,
        "priority": priority,
        "unassigned": bool(unassigned),
    })


# ---------- Raise a ticket ----------

@router.get("/tickets/new", response_class=HTMLResponse, include_in_schema=False)
def new_ticket_page(request: Request,
                    user: models.User = Depends(get_web_user)):
    return templates.TemplateResponse(request, "new_ticket.html",
                                      {"user": user, "form": {}})


@router.post("/tickets/new", include_in_schema=False)
def new_ticket_submit(request: Request,
                      title: str = Form(...),
                      description: str = Form(""),
                      category: str = Form(""),
                      impact: str = Form(...),
                      urgency: str = Form(...),
                      db: Session = Depends(get_db),
                      user: models.User = Depends(get_web_user)):
    if len(title.strip()) < 5:
        return templates.TemplateResponse(
            request, "new_ticket.html",
            {"user": user, "error": "Title must be at least 5 characters.",
             "form": {"title": title, "description": description,
                      "category": category}},
            status_code=400,
        )

    ticket = models.Ticket(
        reference=crud.generate_reference(db),
        title=title.strip(),
        description=description.strip() or None,
        category=category or None,
        impact=models.Impact(impact),
        urgency=models.Urgency(urgency),
        requester_id=user.id,
        status=models.Status.NEW,
        created_at=crud.utcnow(),
    )
    sla.set_sla_targets(ticket)

    db.add(ticket)
    db.flush()
    crud.log_event(db, ticket, "created",
                   f"Ticket raised: P{ticket.priority}", actor_id=user.id)
    db.commit()

    return RedirectResponse(f"/tickets/{ticket.id}", status_code=303)


# ---------- Ticket detail ----------

@router.get("/tickets/{ticket_id}", response_class=HTMLResponse,
            include_in_schema=False)
def ticket_detail(request: Request, ticket_id: int,
                  db: Session = Depends(get_db),
                  user: models.User = Depends(get_web_user),
                  error: str = None):
    ticket = db.get(models.Ticket, ticket_id)
    if not ticket or (user.role == "requester" and ticket.requester_id != user.id):
        raise HTTPException(status_code=404, detail="Ticket not found")

    events = sorted(ticket.events, key=lambda e: e.timestamp)
    technicians = (db.query(models.User)
                     .filter(models.User.role.in_(("technician", "manager")))
                     .order_by(models.User.name).all())

    return templates.TemplateResponse(request, "detail.html", {
        "user": user,
        "ticket": ticket,
        "events": events,
        "sla": _sla_view(ticket),
        "transitions": sorted(ALLOWED_TRANSITIONS[ticket.status],
                              key=lambda s: s.value),
        "technicians": technicians,
        "error": error,
    })


@router.post("/tickets/{ticket_id}/comments", include_in_schema=False)
def post_comment(ticket_id: int, body: str = Form(...),
                 db: Session = Depends(get_db),
                 user: models.User = Depends(get_web_user)):
    ticket = db.get(models.Ticket, ticket_id)
    if not ticket or (user.role == "requester" and ticket.requester_id != user.id):
        raise HTTPException(status_code=404, detail="Ticket not found")

    if (ticket.first_response_at is None
            and user.role in ("technician", "manager")):
        ticket.first_response_at = crud.utcnow()

    crud.log_event(db, ticket, "comment", body.strip(), actor_id=user.id)
    db.commit()
    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)


@router.post("/tickets/{ticket_id}/status", include_in_schema=False)
def post_status(ticket_id: int,
                status: str = Form(...),
                note: str = Form(""),
                db: Session = Depends(get_db),
                user: models.User = Depends(require_web_technician)):
    ticket = db.get(models.Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    new_status = models.Status(status)
    now = crud.utcnow()

    if new_status not in ALLOWED_TRANSITIONS[ticket.status]:
        return RedirectResponse(
            f"/tickets/{ticket_id}?error=Cannot+move+from+"
            f"{ticket.status.value}+to+{new_status.value}",
            status_code=303,
        )

    if ticket.status == models.Status.ON_HOLD and ticket.paused_since:
        paused = sla.business_time_between(ticket.paused_since, now)
        ticket.paused_seconds = (ticket.paused_seconds or 0) + int(paused.total_seconds())
        ticket.paused_since = None

    if new_status == models.Status.ON_HOLD:
        ticket.paused_since = now
    if new_status == models.Status.RESOLVED:
        ticket.resolved_at = now
    if new_status == models.Status.CLOSED:
        ticket.closed_at = now

    old = ticket.status
    ticket.status = new_status

    detail = f"{old.value} -> {new_status.value}"
    if note.strip():
        detail += f" ({note.strip()})"
    crud.log_event(db, ticket, "status_change", detail, actor_id=user.id)
    db.commit()

    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)


@router.post("/tickets/{ticket_id}/assign", include_in_schema=False)
def post_assign(ticket_id: int, assignee_id: int = Form(...),
                db: Session = Depends(get_db),
                user: models.User = Depends(require_web_technician)):
    ticket = db.get(models.Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    assignee = db.get(models.User, assignee_id)
    if not assignee or assignee.role not in ("technician", "manager"):
        raise HTTPException(status_code=400, detail="Invalid assignee")

    ticket.assignee_id = assignee.id
    if ticket.status == models.Status.NEW:
        ticket.status = models.Status.ASSIGNED

    crud.log_event(db, ticket, "assigned", f"Assigned to {assignee.name}",
                   actor_id=user.id)
    db.commit()
    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)


# ---------- Dashboard ----------

@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request,
              db: Session = Depends(get_db),
              user: models.User = Depends(require_web_technician)):
    open_tickets = (db.query(models.Ticket)
                      .filter(models.Ticket.status.notin_(
                          (models.Status.RESOLVED, models.Status.CLOSED)))
                      .all())

    at_risk = breached = 0
    for t in open_tickets:
        state = sla.sla_state(t)["state"]
        if state == "at_risk":
            at_risk += 1
        elif state == "breached":
            breached += 1

    resolved = (db.query(models.Ticket)
                  .filter(models.Ticket.resolved_at.isnot(None)).all())
    met = sum(1 for t in resolved if sla.sla_state(t)["state"] == "met")
    compliance = round(met / len(resolved) * 100) if resolved else 100

    by_priority = []
    for p in (1, 2, 3, 4):
        by_priority.append({
            "priority": p,
            "count": sum(1 for t in open_tickets if t.priority == p),
            "target": int(sla.SLA_TARGETS[p][1].total_seconds() // 3600),
        })

    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "stats": {
            "open_count": len(open_tickets),
            "unassigned": sum(1 for t in open_tickets if t.assignee_id is None),
            "at_risk": at_risk,
            "breached": breached,
            "met": met,
            "resolved_total": len(resolved),
            "compliance": compliance,
        },
        "by_priority": by_priority,
    })