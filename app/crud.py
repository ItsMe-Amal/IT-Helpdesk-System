from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, sla


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def generate_reference(db: Session) -> str:
    """Produce the next human-readable ticket reference, e.g. INC-2026-0001."""
    year = utcnow().year
    prefix = f"INC-{year}-"
    count = (
        db.query(func.count(models.Ticket.id))
        .filter(models.Ticket.reference.like(f"{prefix}%"))
        .scalar()
    )
    return f"{prefix}{count + 1:04d}"


def log_event(db: Session, ticket: models.Ticket, event_type: str,
              detail: str = None, actor_id: int = None) -> models.TicketEvent:
    """Append an entry to the ticket's audit trail."""
    event = models.TicketEvent(
        ticket_id=ticket.id,
        actor_id=actor_id,
        event_type=event_type,
        detail=detail,
    )
    db.add(event)
    return event
