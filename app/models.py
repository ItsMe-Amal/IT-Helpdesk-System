from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum

from app.database import Base


def utcnow():
    """Current UTC time, stored without timezone info for consistency."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Impact(str, enum.Enum):
    """How many people are affected."""
    ORGANISATION = "organisation"
    DEPARTMENT = "department"
    INDIVIDUAL = "individual"


class Urgency(str, enum.Enum):
    """How quickly it needs fixing."""
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class Status(str, enum.Enum):
    """Where the ticket sits in its lifecycle."""
    NEW = "new"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    RESOLVED = "resolved"
    CLOSED = "closed"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), default="requester", nullable=False)
    department = Column(String(100))
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(20), unique=True, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    category = Column(String(50))

    # ITIL classification
    impact = Column(Enum(Impact), nullable=False)
    urgency = Column(Enum(Urgency), nullable=False)
    priority = Column(Integer, nullable=False)      # derived, 1 = highest
    status = Column(Enum(Status), default=Status.NEW, nullable=False)

    # People
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # SLA timestamps
    created_at = Column(DateTime, default=utcnow, nullable=False)
    first_response_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    response_due_at = Column(DateTime, nullable=False)
    resolution_due_at = Column(DateTime, nullable=False)

    # SLA pause tracking
    paused_seconds = Column(Integer, default=0, nullable=False)
    paused_since = Column(DateTime, nullable=True)

    requester = relationship("User", foreign_keys=[requester_id])
    assignee = relationship("User", foreign_keys=[assignee_id])
    events = relationship("TicketEvent", back_populates="ticket",
                          cascade="all, delete-orphan")
    

class TicketEvent(Base):
    __tablename__ = "ticket_events"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    timestamp = Column(DateTime, default=utcnow, nullable=False)
    event_type = Column(String(30), nullable=False)
    detail = Column(Text)

    ticket = relationship("Ticket", back_populates="events")
    actor = relationship("User")