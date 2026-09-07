from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo

from app.models import Impact, Urgency

# Service desk operating calendar
BUSINESS_TZ = ZoneInfo("Australia/Brisbane")
BUSINESS_START = time(8, 0)
BUSINESS_END = time(18, 0)

# ITIL priority matrix: (Impact, Urgency) -> Priority. P1 is highest.
PRIORITY_MATRIX = {
    (Impact.ORGANISATION, Urgency.CRITICAL): 1,
    (Impact.ORGANISATION, Urgency.HIGH):     1,
    (Impact.ORGANISATION, Urgency.NORMAL):   2,
    (Impact.ORGANISATION, Urgency.LOW):      3,

    (Impact.DEPARTMENT,   Urgency.CRITICAL): 1,
    (Impact.DEPARTMENT,   Urgency.HIGH):     2,
    (Impact.DEPARTMENT,   Urgency.NORMAL):   3,
    (Impact.DEPARTMENT,   Urgency.LOW):      4,

    (Impact.INDIVIDUAL,   Urgency.CRITICAL): 2,
    (Impact.INDIVIDUAL,   Urgency.HIGH):     3,
    (Impact.INDIVIDUAL,   Urgency.NORMAL):   3,
    (Impact.INDIVIDUAL,   Urgency.LOW):      4,
}

# Priority -> (first response target, resolution target), in business time
SLA_TARGETS = {
    1: (timedelta(minutes=30), timedelta(hours=4)),
    2: (timedelta(hours=2),    timedelta(hours=8)),
    3: (timedelta(hours=4),    timedelta(hours=24)),
    4: (timedelta(hours=8),    timedelta(hours=72)),
}


def calculate_priority(impact: Impact, urgency: Urgency) -> int:
    """Derive priority from impact and urgency. Never user-selected."""
    return PRIORITY_MATRIX[(impact, urgency)]


def _to_local(dt_utc: datetime) -> datetime:
    """Convert a naive UTC datetime to Brisbane local time."""
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TZ)


def local_to_utc(year, month, day, hour, minute=0) -> datetime:
    """Build a naive UTC datetime from a Brisbane wall-clock time.

    Useful for tests and seed data, where you think in local time.
    """
    local = datetime(year, month, day, hour, minute, tzinfo=BUSINESS_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def is_business_time(dt_utc: datetime) -> bool:
    """True if this moment falls inside the service desk's operating hours."""
    local = _to_local(dt_utc)
    if local.weekday() >= 5:          # 5 = Saturday, 6 = Sunday
        return False
    return BUSINESS_START <= local.time() < BUSINESS_END


def add_business_time(start: datetime, duration: timedelta) -> datetime:
    """Advance `start` by `duration`, counting only business minutes."""
    step = timedelta(minutes=1)
    current = start.replace(second=0, microsecond=0)

    # If we start outside hours, jump to the next business minute
    while not is_business_time(current):
        current += step

    remaining = duration
    while remaining > timedelta(0):
        current += step
        if is_business_time(current):
            remaining -= step
    return current


def business_time_between(start: datetime, end: datetime) -> timedelta:
    """How much business time elapsed between two moments."""
    if end <= start:
        return timedelta(0)

    step = timedelta(minutes=1)
    current = start.replace(second=0, microsecond=0)
    elapsed = timedelta(0)

    while current < end:
        if is_business_time(current):
            elapsed += step
        current += step
    return elapsed

def set_sla_targets(ticket, now: datetime = None) -> None:
    """Calculate priority and both SLA deadlines. Called at ticket creation."""
    now = now or ticket.created_at
    ticket.priority = calculate_priority(ticket.impact, ticket.urgency)
    response_target, resolution_target = SLA_TARGETS[ticket.priority]
    ticket.response_due_at = add_business_time(now, response_target)
    ticket.resolution_due_at = add_business_time(now, resolution_target)

def sla_state(ticket, now: datetime = None) -> dict:
    """Current resolution SLA status, accounting for paused (on-hold) time."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)

    # Total business time this ticket has spent on hold
    paused = timedelta(seconds=ticket.paused_seconds or 0)
    if ticket.paused_since:
        paused += business_time_between(ticket.paused_since, now)

    # Push the deadline out by the paused time
    deadline = add_business_time(ticket.resolution_due_at, paused)

    if ticket.resolved_at:
        return {
            "state": "met" if ticket.resolved_at <= deadline else "breached",
            "deadline": deadline,
            "remaining": timedelta(0),
        }

    if now >= deadline:
        return {"state": "breached", "deadline": deadline, "remaining": timedelta(0)}

    remaining = business_time_between(now, deadline)
    target = SLA_TARGETS[ticket.priority][1]
    state = "at_risk" if remaining < target * 0.25 else "on_track"

    return {"state": state, "deadline": deadline, "remaining": remaining}

