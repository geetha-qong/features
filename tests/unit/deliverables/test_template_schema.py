import pytest
from pydantic import ValidationError

from webapp.deliverables.template import ColumnDef, DeliverableConfig, TemplateConfig


def test_templateconfig_with_valve_list_columns():
    cfg = TemplateConfig(
        slug="ronesans",
        customer_name="Ronesans Engineering",
        deliverables={
            "valve_list": DeliverableConfig(
                columns=[
                    ColumnDef(field="tag", header="Tag No.", order=1),
                    ColumnDef(field="fields.size", header="Size", order=2),
                    ColumnDef(field="fields.service", header="Service", order=3),
                ],
                sheet_name="Valve List",
            )
        },
    )
    assert cfg.slug == "ronesans"
    assert len(cfg.deliverables["valve_list"].columns) == 3
    assert cfg.deliverables["valve_list"].columns[0].header == "Tag No."


def test_columndef_field_path_can_use_dot_notation():
    col = ColumnDef(field="vendor_match.catalog_fields.accuracy", header="Accuracy", order=10)
    assert col.field == "vendor_match.catalog_fields.accuracy"


def test_templateconfig_rejects_empty_slug():
    with pytest.raises(ValidationError):
        TemplateConfig(slug="", customer_name="X", deliverables={})


def test_deliverableconfig_orders_columns_consistently():
    cfg = DeliverableConfig(
        columns=[
            ColumnDef(field="tag", header="Tag", order=2),
            ColumnDef(field="fields.size", header="Size", order=1),
        ]
    )
    ordered = sorted(cfg.columns, key=lambda c: c.order)
    assert [c.header for c in ordered] == ["Size", "Tag"]
