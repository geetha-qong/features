"""Tests for ISA-5.1 tag sort key (webapp/deliverables/tag_sort.py)."""
import pytest
from webapp.deliverables.tag_sort import tag_sort_key


def _sorted_types(type_codes, area="62", seq="001"):
    """Helper: build full tags, sort them, return just the type-code part."""
    tags = [f"{area}-{t}-{seq}" for t in type_codes]
    return [t.split("-")[1] for t in sorted(tags, key=tag_sort_key)]


# ── Suffix rank order ────────────────────────────────────────────────────────

def test_pressure_loop():
    # PG-PT-PDIT-PAH-PALL
    shuffled = ["PAH", "PT", "PALL", "PG", "PDIT"]
    assert _sorted_types(shuffled) == ["PG", "PT", "PDIT", "PAH", "PALL"]


def test_flow_loop():
    # FE-FT-FAHH
    shuffled = ["FAHH", "FT", "FE"]
    assert _sorted_types(shuffled) == ["FE", "FT", "FAHH"]


def test_temperature_loop_with_thermowell():
    # TW-TE-TG-TT-TI-TIT-TAL-TALL
    shuffled = ["TALL", "TT", "TI", "TG", "TW", "TE", "TIT", "TAL"]
    assert _sorted_types(shuffled) == ["TW", "TE", "TG", "TT", "TI", "TIT", "TAL", "TALL"]


def test_alarm_variants():
    # TE-TI-TAH-TAHH
    shuffled = ["TAHH", "TE", "TAH", "TI"]
    assert _sorted_types(shuffled) == ["TE", "TI", "TAH", "TAHH"]


def test_flow_with_indicator():
    # FE-FT-FI-FIT
    shuffled = ["FIT", "FI", "FT", "FE"]
    assert _sorted_types(shuffled) == ["FE", "FT", "FI", "FIT"]


def test_analysis_loop():
    # AE-AT-AIT
    shuffled = ["AIT", "AE", "AT"]
    assert _sorted_types(shuffled) == ["AE", "AT", "AIT"]


def test_valve_loop():
    # VE-VT-VI
    shuffled = ["VI", "VE", "VT"]
    assert _sorted_types(shuffled) == ["VE", "VT", "VI"]


def test_xmitter_loop():
    # XE-XT
    shuffled = ["XT", "XE"]
    assert _sorted_types(shuffled) == ["XE", "XT"]


# ── Thermowell exception ─────────────────────────────────────────────────────

def test_thermowell_only_sorts_first_for_T():
    # TW sorts before TE
    t_tags = ["62-TE-001", "62-TW-001", "62-TT-001"]
    assert [t.split("-")[1] for t in sorted(t_tags, key=tag_sort_key)] == ["TW", "TE", "TT"]


def test_thermowell_not_first_for_other_variables():
    # PW is not a real instrument; rank should be unknown (sorts last)
    p_tags = ["62-PT-001", "62-PG-001", "62-PW-001"]
    result = [t.split("-")[1] for t in sorted(p_tags, key=tag_sort_key)]
    assert result[0] == "PG"
    assert result[1] == "PT"
    assert result[2] == "PW"   # unknown suffix → last


# ── Natural (numeric-aware) primary sort ────────────────────────────────────

def test_natural_sort_two_part_tags():
    # FT-2 must come before FT-10 (numeric-aware, not lexicographic "FT-10" < "FT-2")
    tags = ["FT-10", "FT-2"]
    assert sorted(tags, key=tag_sort_key) == ["FT-2", "FT-10"]

    # Within the same seq number, instrument type rank applies
    tags2 = ["FT-5", "FE-5", "FAH-5"]
    assert sorted(tags2, key=tag_sort_key) == ["FE-5", "FT-5", "FAH-5"]


def test_natural_sort_three_part_tags():
    tags = ["10-FT-001", "62-FT-001", "2-FE-001", "62-FE-001"]
    result = sorted(tags, key=tag_sort_key)
    assert result == ["2-FE-001", "10-FT-001", "62-FE-001", "62-FT-001"]


def test_same_area_seq_sorted_by_type():
    tags = ["62-PT-001", "62-PG-001", "62-PAH-001"]
    result = [t.split("-")[1] for t in sorted(tags, key=tag_sort_key)]
    assert result == ["PG", "PT", "PAH"]


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_none_tag_sorts_last():
    tags = ["62-FT-001", None, "62-FE-001"]
    result = sorted(tags, key=tag_sort_key)
    assert result == ["62-FE-001", "62-FT-001", None]  # None sentinel > any real area


def test_unknown_suffix_sorts_last():
    tags = ["62-FT-001", "62-FX-001", "62-FE-001"]
    result = [t.split("-")[1] for t in sorted(tags, key=tag_sort_key)]
    assert result == ["FE", "FT", "FX"]
