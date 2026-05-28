"""Dot-notation field resolver for CanonicalEntity.

ColumnDef.field uses dot notation like 'fields.size' or
'vendor_match.catalog_fields.accuracy'. This helper walks the path
and returns the value as a string, or '' if any segment is missing.
"""

from typing import Any

from pydantic import BaseModel

from webapp.deliverables.canonical import CanonicalEntity


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
    return str(current)
