from webapp.deliverables.canonical import CanonicalEntity, VendorMatch
from webapp.deliverables.field_resolver import resolve_field


def make_entity_with_vendor() -> CanonicalEntity:
    return CanonicalEntity(
        entity_id="33333333-3333-3333-3333-333333333333",
        entity_class="instrument",
        sub_class="PT",
        tag="PT-01018",
        pid_number="P-001",
        sheet_number=1,
        bbox=(0, 0, 10, 10),
        fields={"service": "Reactor outlet pressure", "signal_type": "4-20mA"},
        vendor_match=VendorMatch(
            vendor_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            vendor_name="Yokogawa",
            product_name="EJX130A",
            part_number="EJX130A-JMS5G-022NN",
            catalog_fields={"accuracy": "0.04%"},
        ),
    )


def test_resolve_simple_top_level():
    e = make_entity_with_vendor()
    assert resolve_field(e, "tag") == "PT-01018"


def test_resolve_dot_into_fields_dict():
    e = make_entity_with_vendor()
    assert resolve_field(e, "fields.service") == "Reactor outlet pressure"


def test_resolve_dot_into_nested_vendor_catalog():
    e = make_entity_with_vendor()
    assert resolve_field(e, "vendor_match.catalog_fields.accuracy") == "0.04%"


def test_resolve_missing_returns_empty_string():
    e = make_entity_with_vendor()
    assert resolve_field(e, "fields.material") == ""


def test_resolve_missing_vendor_returns_empty():
    e = CanonicalEntity(
        entity_id="44444444-4444-4444-4444-444444444444",
        entity_class="valve",
        sub_class="ball_valve",
        tag="BV-002",
        pid_number="P-001",
        sheet_number=1,
        bbox=(0, 0, 10, 10),
        fields={},
    )
    assert resolve_field(e, "vendor_match.vendor_name") == ""
