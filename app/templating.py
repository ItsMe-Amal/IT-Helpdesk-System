from datetime import datetime

from fastapi.templating import Jinja2Templates

from app.sla import BUSINESS_TZ

templates = Jinja2Templates(directory="app/templates")


def local_time(value: datetime, fmt: str = "%d %b %H:%M") -> str:
    """Render a naive UTC datetime in Brisbane local time."""
    if value is None:
        return "—"
    from datetime import timezone
    aware = value.replace(tzinfo=timezone.utc)
    return aware.astimezone(BUSINESS_TZ).strftime(fmt)


def duration(minutes: int) -> str:
    """Turn a minute count into something readable, e.g. '3h 20m'."""
    if minutes is None:
        return "—"
    if minutes < 0:
        minutes = 0
    hours, mins = divmod(int(minutes), 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


templates.env.filters["local_time"] = local_time
templates.env.filters["duration"] = duration