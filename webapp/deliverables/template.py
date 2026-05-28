"""Pydantic models for the per-customer deliverable template format.

A TemplateConfig is one JSON file in webapp/deliverables/customer_templates/.
Each generator reads the relevant DeliverableConfig from the chosen template
and renders the deliverable accordingly.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class ColumnDef(BaseModel):
    """One column in a tabular deliverable.

    `field` uses dot notation to navigate the canonical entity, e.g.
    "fields.size" reads CanonicalEntity.fields["size"];
    "vendor_match.catalog_fields.accuracy" reads the nested vendor field.
    """

    field: str
    header: str
    order: int


class DeliverableConfig(BaseModel):
    """Per-deliverable presentation config inside a TemplateConfig."""

    columns: List[ColumnDef] = Field(default_factory=list)
    sheet_name: Optional[str] = None
    font: str = "Calibri"


class TemplateConfig(BaseModel):
    """One customer's full template config across all deliverables."""

    slug: str
    customer_name: str
    deliverables: Dict[str, DeliverableConfig]

    @field_validator("slug")
    @classmethod
    def _slug_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("slug must be non-empty")
        return v
