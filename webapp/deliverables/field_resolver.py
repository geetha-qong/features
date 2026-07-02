"""Dot-notation field resolver for CanonicalEntity.

ColumnDef.field uses dot notation like 'fields.size' or
'vendor_match.catalog_fields.accuracy'. This helper walks the path
and returns the value as a string, or '' if any segment is missing.
"""

import re
from typing import Any

from pydantic import BaseModel

from webapp.deliverables.canonical import CanonicalEntity

# Engineering tags like 62-BV-151001, 62-DB-151054 — NOT valid line numbers
_ENGR_TAG_RE = re.compile(r'^\d+-[A-Z]{2,8}-\d+[A-Z]{0,2}$')
# P&ID drawing numbers like MUK-62-1-15-1003-001-24C7 — NOT valid line numbers
_PID_DRAWING_RE = re.compile(r'^[A-Z]{2,6}-\d+(?:-\d+){3,}(?:-[0-9A-Z]+)+$')


def sanitize_line_no(val: str) -> str:
    """Return '' for values that the extractor mis-classified as a line number."""
    stripped = val.strip()
    if not stripped or stripped.upper() in ('NA', 'N/A', 'NONE', '-'):
        return ''
    if _ENGR_TAG_RE.match(stripped):
        return ''
    if _PID_DRAWING_RE.match(stripped):
        return ''
    return stripped


def resolve_field(entity: CanonicalEntity, path: str) -> str:
    parts = path.split(".")
    current: Any = entity
    for part in parts:
        if current is None:
            return ""
        if isinstance(current, BaseModel):
            current = getattr(current, part, None)
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return ""
    if current is None:
        return ""
    val = str(current)
    # Sanitise line_no — the Vision API sometimes writes valve tags or P&ID
    # drawing numbers into this field; strip them so they don't appear in the
    # IO List / Instrument Index.
    if parts[-1] == "line_no":
        return sanitize_line_no(val)
    return val
