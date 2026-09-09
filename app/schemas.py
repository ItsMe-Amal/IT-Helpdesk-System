from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Impact, Urgency, Status


# ---------- Users ----------

class UserOut(BaseModel):
    """What we send back about a user. Note: no password field, ever."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    department: Optional[str] = None


# ---------- Tickets ----------

class TicketCreate(BaseModel):
    """What a requester sends when raising a ticket."""
    title: str = Field(min_length=5, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=50)
    impact: Impact
    urgency: Urgency
    requester_id: int


class TicketAssign(BaseModel):
    assignee_id: int


class TicketStatusUpdate(BaseModel):
    status: Status
    note: Optional[str] = None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)
    author_id: int


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    event_type: str
    detail: Optional[str] = None
    actor: Optional[UserOut] = None


class SLAOut(BaseModel):
    state: str
    deadline: datetime
    remaining_minutes: int


class TicketOut(BaseModel):
    """The full ticket as returned to a client."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    reference: str
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    impact: Impact
    urgency: Urgency
    priority: int
    status: Status
    created_at: datetime
    first_response_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    response_due_at: datetime
    resolution_due_at: datetime
    requester: UserOut
    assignee: Optional[UserOut] = None


class TicketDetail(TicketOut):
    """Ticket plus its audit trail and live SLA state."""
    events: list[EventOut] = []
    sla: Optional[SLAOut] = None