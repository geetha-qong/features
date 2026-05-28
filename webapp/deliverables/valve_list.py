"""Valve List deliverable generators (CSV + XLSX)."""

import csv
import io
from typing import ClassVar, List

from webapp.deliverables.base import Generator
from webapp.deliverables.canonical import CanonicalEntity, JobCanonical
from webapp.deliverables.field_resolver import resolve_field
from webapp.deliverables.registry import REGISTRY
from webapp.deliverables.template import DeliverableConfig, TemplateConfig


def _filter_valves(entities: List[CanonicalEntity]) -> List[CanonicalEntity]:
    return [e for e in entities if e.entity_class == "valve"]


def _ordered_columns(cfg: DeliverableConfig):
    return sorted(cfg.columns, key=lambda c: c.order)


class ValveListCSVGenerator(Generator):
    deliverable_type: ClassVar[str] = "valve_list"
    file_format: ClassVar[str] = "csv"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        deliv = template.deliverables["valve_list"]
        columns = _ordered_columns(deliv)
        valves = _filter_valves(canonical.entities)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([c.header for c in columns])
        for v in valves:
            writer.writerow([resolve_field(v, c.field) for c in columns])
        return buf.getvalue().encode("utf-8")


REGISTRY.register(ValveListCSVGenerator)
