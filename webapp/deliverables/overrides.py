"""User-edit override layer over canonical.json.

Pipeline writes canonical.json (read-only). Users edit individual fields via
the studio UI; those edits land in the `entity_overrides` DB table. At
export time, `load_canonical_with_overrides` merges DB overrides on top of
the on-disk canonical and hands a fully-merged `JobCanonical` to whichever
generator the export endpoint resolved.

Design intent:
  - canonical.json stays immutable — pipeline re-runs overwrite it freely.
  - Overrides live in the DB for audit (edited_by/edited_at/prior_value) and
    for atomic concurrent writes that would be racy on the filesystem.
  - Field paths use dot notation matching CanonicalEntity's shape, e.g.
    "tag", "sub_class", "fields.size", "vendor_match.vendor_name".

Read-only fields (entity_id, entity_class, pid_number, sheet_number, bbox)
are rejected at the API layer (see `webapp/routers/entities.py`), not here
— this module trusts its caller.
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from webapp.deliverables.canonical import CanonicalEntity, JobCanonical
from webapp.deliverables.job_loader import load_canonical_for_job


# Fields on CanonicalEntity that the API will never let users edit. Kept here
# as well so the merge layer can be defensive — if a stray override row for
# one of these ever lands (manual DB insert, a bug elsewhere), we silently
# skip it rather than corrupting the canonical shape.
READ_ONLY_FIELDS = frozenset({
    "entity_id",
    "entity_class",
    "bbox",
    "pid_number",
    "sheet_number",
})

# Reserved control flag (NOT an entity field): a truthy `__rejected__` override
# means the user removed this node in Studio. Entities carrying it are dropped
# from the merged canonical (so they vanish from valve list / instrument index /
# datasheets / bulk review) and the flag is never applied as a normal field.
# See the Studio node-corrections design (2026-06-28).
REJECTED_FIELD = "__rejected__"


def _truthy(value: Any) -> bool:
    """JSON `new_value` may arrive as bool, "true"/"false", 1/0, etc."""
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)

# Vendor-dependent fields that should only appear in exports when a vendor
# has been explicitly accepted via the UI (vendor_match.vendor_name override
# is present and non-empty). Pipeline-extracted values are suppressed.
_VENDOR_DEPENDENT_FIELDS = frozenset({
    "piping_class", "calb_range_min", "calb_range_max", "calb_range_unit",
    "measuring_range_min", "measuring_range_max", "measuring_range_unit",
    "certification", "power_in", "power_out", "io_output", "datasheet_ref",
})


def _clear_vendor_fields(entity: CanonicalEntity) -> CanonicalEntity:
    data = entity.model_dump()
    data["vendor_match"] = None
    for key in _VENDOR_DEPENDENT_FIELDS:
        data.get("fields", {}).pop(key, None)
    return CanonicalEntity.model_validate(data)


def resolve_field_raw(entity: CanonicalEntity, path: str) -> Any:
    """Walk dot notation on an entity, returning the raw value (or None).

    Sibling of `field_resolver.resolve_field` which always returns str.
    We need the raw value for prior_value capture on PATCH.
    """
    parts = path.split(".")
    current: Any = entity
    for part in parts:
        if current is None:
            return None
        if isinstance(current, BaseModel):
            current = getattr(current, part, None)
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def apply_override(entity: CanonicalEntity, field_name: str, new_value: Any) -> CanonicalEntity:
    """Return a new entity with `field_name` set to `new_value`.

    Pydantic models are conceptually immutable per call site — we mutate a
    dict copy then re-validate. Read-only fields are silently skipped
    (defensive; the API guards against this upstream).
    """
    if field_name in READ_ONLY_FIELDS or field_name.startswith(tuple(f + "." for f in READ_ONLY_FIELDS)):
        return entity

    data = entity.model_dump()
    parts = field_name.split(".")

    if len(parts) == 1:
        # Top-level scalar: tag, sub_class, etc.
        data[parts[0]] = new_value
    elif len(parts) == 2:
        container, key = parts
        # Lazily create the container if it doesn't exist yet (e.g. an entity
        # without a vendor_match getting a vendor_match.vendor_name override).
        if container == "vendor_match" and data.get(container) is None:
            import uuid as _uuid
            # Bootstrap an empty vendor_match so the field can be set.
            # vendor_id is derived deterministically from the entity so it
            # stays stable across multiple override calls on the same entity.
            data[container] = {
                "vendor_id": str(_uuid.uuid5(_uuid.NAMESPACE_DNS, str(data.get("entity_id", "override")))),
                "vendor_name": "",
                "product_name": "",
                "part_number": "",
                "catalog_fields": {},
            }
        if data.get(container) is None:
            data[container] = {}
        data[container][key] = new_value
    elif len(parts) == 3:
        # 3-level nesting: vendor_match.catalog_fields.key
        container, sub_container, key = parts
        if data.get(container) is None:
            import uuid as _uuid
            data[container] = {
                "vendor_id": str(_uuid.uuid5(_uuid.NAMESPACE_DNS, str(data.get("entity_id", "override")))),
                "vendor_name": "",
                "product_name": "",
                "part_number": "",
                "catalog_fields": {},
            }
        if data[container].get(sub_container) is None:
            data[container][sub_container] = {}
        data[container][sub_container][key] = new_value
    else:
        # 4+ nesting levels not supported. Punt.
        return entity

    return CanonicalEntity.model_validate(data)


def load_canonical_with_overrides(
    output_csv_path: str,
    job_id: int,
    db: Session,
) -> JobCanonical:
    """Same contract as `load_canonical_for_job`, but applies DB overrides.

    Generators that want merged output should call this; generators that
    intentionally want the pre-edit canonical (rare) keep using
    `load_canonical_for_job`.
    """
    canonical = load_canonical_for_job(output_csv_path)

    # Late import — keeps the deliverables package importable in contexts
    # where SQLAlchemy isn't set up (e.g. CLI tooling, tests of pure
    # generator logic).
    from webapp.models import EntityOverride

    overrides = (
        db.query(EntityOverride)
        .filter(EntityOverride.job_id == job_id)
        .all()
    )

    # Group by entity_id so we apply all of one entity's overrides in one pass.
    by_entity: Dict[str, Dict[str, Any]] = {}
    for ov in overrides:
        by_entity.setdefault(ov.entity_id, {})[ov.field_name] = ov.new_value

    merged_entities = []
    for entity in canonical.entities:
        eid = str(entity.entity_id)
        # A truthy `__rejected__` override means the user removed this node —
        # drop it entirely so it disappears from every deliverable.
        if _truthy(by_entity.get(eid, {}).get(REJECTED_FIELD)):
            continue
        if eid in by_entity:
            for field_name, value in by_entity[eid].items():
                # `__rejected__` is a control flag, not an entity field.
                if field_name == REJECTED_FIELD:
                    continue
                entity = apply_override(entity, field_name, value)
        # Vendor fields are only exported when explicitly accepted via the UI
        # (vendor_match.vendor_name override is present and non-empty).
        # Pipeline-extracted vendor data is suppressed so the export only
        # shows what the user deliberately selected.
        entity_overrides = by_entity.get(eid, {})
        vendor_name = str(entity_overrides.get("vendor_match.vendor_name") or "").strip()
        if not vendor_name:
            entity = _clear_vendor_fields(entity)
        merged_entities.append(entity)

    return canonical.model_copy(update={"entities": merged_entities})


def is_field_editable(field_name: str) -> bool:
    """API helper: True if a user may PATCH this field path."""
    if field_name in READ_ONLY_FIELDS:
        return False
    if field_name.startswith(tuple(f + "." for f in READ_ONLY_FIELDS)):
        return False
    # Don't let users overwrite the schema-version or job_id by mistake.
    if field_name in {"job_id", "canonical_schema_version", "customer_template_slug"}:
        return False
    return True


def capture_prior_value(
    output_csv_path: str,
    entity_id: str,
    field_name: str,
) -> Optional[Any]:
    """Read the on-disk canonical value for a (entity, field) pair.

    Used by PATCH to snapshot prior_value before writing the override row.
    Returns None if the entity or field is absent.
    """
    canonical = load_canonical_for_job(output_csv_path)
    for entity in canonical.entities:
        if str(entity.entity_id) == entity_id:
            return resolve_field_raw(entity, field_name)
    return None
