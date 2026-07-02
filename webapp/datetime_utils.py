"""Datetime helpers — single source of truth for UTC handling in the webapp.

Convention: all datetimes stored in the DB are UTC (written via
`datetime.now(timezone.utc)` or `datetime.utcnow()`). All datetimes sent to
the frontend are ISO 8601 with an explicit `Z` suffix so `new Date(iso)` in
the browser parses them as UTC instead of local-clock. Display in the user's
timezone is the frontend's responsibility — see `webapp/frontend/src/util/datetime.ts`.

The Z-suffix is critical: without it, the browser interprets a string like
`"2026-06-03T06:53:16"` as **local time**, which on an IST workstation
under-shifts the value by 5:30h.
"""
from datetime import datetime, timezone
from typing import Optional


def utc_iso(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a (possibly naive) UTC datetime as an ISO 8601 string with `Z` suffix.

    Naive datetimes are assumed to be UTC (matches the codebase convention of
    `datetime.utcnow()` writes). Aware datetimes are converted to UTC before
    serializing.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def utcnow() -> datetime:
    """Aware UTC `now()`. Prefer this over `datetime.utcnow()` (deprecated in 3.12)."""
    return datetime.now(timezone.utc)
