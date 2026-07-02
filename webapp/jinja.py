"""Shared Jinja2Templates instance with custom filters."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi.templating import Jinja2Templates

_IST = timezone(timedelta(hours=5, minutes=30))

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


def _to_ist(dt: datetime) -> str:
    """Convert a naive UTC datetime (from DB) to IST and format it."""
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ist_dt = dt.astimezone(_IST)
    return ist_dt.strftime("%Y-%m-%d %H:%M IST")


templates.env.filters["to_ist"] = _to_ist
