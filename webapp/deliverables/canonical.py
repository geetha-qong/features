"""Pydantic models for the pipeline's internal canonical output.

Every deliverable generator consumes a JobCanonical. This is the contract
between the extraction pipeline and the deliverables subsystem. Bumping
canonical_schema_version must be recorded in FEATURES.md as type=architecture.
"""

from typing import Any, Dict, Literal, Optional, Tuple
from uuid import UUID

from pydantic import BaseModel, Field

CANONICAL_SCHEMA_VERSION = "1.0.0"

EntityClass = Literal["valve", "instrument", "equipment"]


class VendorMatch(BaseModel):
    """Vendor catalog match attached to an entity (typically an instrument)."""

    vendor_id: UUID
    vendor_name: str
    product_name: str
    part_number: str
    catalog_fields: Dict[str, Any] = Field(default_factory=dict)


class CanonicalEntity(BaseModel):
    """One detected symbol on a P&ID with its identifying text and metadata."""

    entity_id: UUID
    entity_class: EntityClass
    sub_class: str
    tag: Optional[str] = None
    pid_number: str
    sheet_number: int
    bbox: Tuple[float, float, float, float]
    fields: Dict[str, Any] = Field(default_factory=dict)
    vendor_match: Optional[VendorMatch] = None


class JobCanonical(BaseModel):
    """Top-level canonical structure for one job, consumed by every generator."""

    job_id: int
    canonical_schema_version: str
    customer_template_slug: str
    entities: list[CanonicalEntity]
