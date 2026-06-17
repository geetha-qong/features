"""Unit tests for the per-instrument-type IDS section schema.

These lock in the contract that `datasheet.py` relies on: each instrument
type (CV / PT / PSV) resolves to a Common section plus type-specific
sections, every field is well-formed (header + path + valid source), vendor
fields are read-only while process/user fields are editable, paths are unique
within a type, and unknown sub_classes degrade to Common-only without raising.

Import-tolerant: if `webapp.deliverables.ids_schema` doesn't exist yet (a
teammate is still building it), the whole module is skipped so the suite stays
green until the interface lands.
"""
import pytest

ids_schema = pytest.importorskip("webapp.deliverables.ids_schema")

get_ids_sections_for_type = ids_schema.get_ids_sections_for_type
normalize_subclass = ids_schema.normalize_subclass

VALID_SOURCES = {"process", "user", "vendor"}


def _all_fields(sub_class):
    fields = []
    for section in get_ids_sections_for_type(sub_class):
        fields.extend(section.fields)
    return fields


def test_pt_sections_well_formed():
    sections = get_ids_sections_for_type("PT")
    assert isinstance(sections, list)
    assert len(sections) > 0

    fields = _all_fields("PT")
    assert len(fields) > 30

    for f in fields:
        assert f.header and isinstance(f.header, str)
        assert f.path and isinstance(f.path, str)
        assert f.source in VALID_SOURCES, f"bad source: {f.source!r}"


def test_cv_has_vendor_and_process_paths():
    fields = _all_fields("CV")
    assert any(f.path.startswith("vendor_match.") for f in fields), (
        "CV should have at least one vendor_match.* path"
    )
    assert any(f.path.startswith("fields.") for f in fields), (
        "CV should have at least one fields.* (process/user) path"
    )


def test_psv_non_empty():
    sections = get_ids_sections_for_type("PSV")
    assert len(sections) > 0
    assert len(_all_fields("PSV")) > 0


def test_unknown_type_returns_common_only():
    common = get_ids_sections_for_type(None)
    unknown = get_ids_sections_for_type("ZZZ_unknown")

    # Same sections as the None (Common-only) case.
    assert [s.name for s in unknown] == [s.name for s in common]
    assert [
        (f.header, f.path) for s in unknown for f in s.fields
    ] == [
        (f.header, f.path) for s in common for f in s.fields
    ]


def test_normalize_subclass():
    assert normalize_subclass("FT") == "PT"
    assert normalize_subclass("psv") == "PSV"          # case-insensitive
    assert normalize_subclass("PSV") == "PSV"
    assert normalize_subclass("RELIEF_SAFETY") == "PSV"
    assert normalize_subclass("nonsense") is None


def test_vendor_fields_readonly_others_editable():
    for sub_class in ("CV", "PT", "PSV"):
        for f in _all_fields(sub_class):
            if f.source == "vendor":
                assert f.editable is False, (
                    f"{sub_class}: vendor field {f.path} must be editable=False"
                )
            else:  # process / user
                assert f.editable is True, (
                    f"{sub_class}: {f.source} field {f.path} must be editable=True"
                )


def test_paths_unique_within_each_type():
    for sub_class in ("CV", "PT", "PSV"):
        paths = [f.path for f in _all_fields(sub_class)]
        assert len(paths) == len(set(paths)), (
            f"{sub_class}: duplicate field paths detected"
        )
