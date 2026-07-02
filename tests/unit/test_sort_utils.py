"""Unit tests for webapp.deliverables.sort_utils.instrument_sort_key.

The integration fixtures (full job-43 and job-55 instrument tag sets) encode the
ordering validated with the user (FEATURES #117): loop number primary, then the
ISA function ladder within each loop.
"""
from webapp.deliverables.sort_utils import classify, instrument_sort_key


def _order(tags):
    return sorted(tags, key=instrument_sort_key)


# ── classify / ladder ────────────────────────────────────────────────────────

def test_classify_buckets():
    assert classify("FE")[0] == "element"
    assert classify("PG")[0] == "gauge"
    assert classify("FIT")[0] == "transmitter"   # has T
    assert classify("PDIT")[0] == "transmitter"
    assert classify("FI")[0] == "indicator"      # I, no T
    assert classify("PDI")[0] == "indicator"
    assert classify("FIC")[0] == "controller"    # C, no T
    assert classify("FV")[0] == "final_element"
    assert classify("FY")[0] == "final_element"
    assert classify("HS")[0] == "switch"
    assert classify("XS")[0] == "switch"
    assert classify("TW")[0] == "thermowell"
    assert classify("GB")[0] == "other"
    assert classify("FZIQ")[0] == "indicator"    # I present, no T
    assert classify("")[0] == "other"


def test_transmitter_before_indicator_same_loop():
    # Job-55 rule: PDIT (transmitter) before PDI (indicator).
    assert _order(["62-PDI-151025", "62-PDIT-151025"]) == \
        ["62-PDIT-151025", "62-PDI-151025"]


def test_alarm_suffix_order_h_hh_l_ll():
    assert _order(["10-PALL-1", "10-PAL-1", "10-PAHH-1", "10-PAH-1"]) == \
        ["10-PAH-1", "10-PAHH-1", "10-PAL-1", "10-PALL-1"]


def test_thermowell_first_for_temperature():
    assert _order(["5-TI-1", "5-TT-1", "5-TW-1", "5-TE-1"]) == \
        ["5-TW-1", "5-TE-1", "5-TT-1", "5-TI-1"]


def test_final_elements_and_switches_last():
    assert _order(["9-FV-1", "9-FE-1", "9-FT-1", "9-HS-1"]) == \
        ["9-FE-1", "9-FT-1", "9-FV-1", "9-HS-1"]


def test_loop_number_is_primary():
    assert _order(["61-PZIT-149110", "61-FZA-12101", "61-FZIT-12101"]) == \
        ["61-FZIT-12101", "61-FZA-12101", "61-PZIT-149110"]


def test_ab_train_suffix_groups_per_loop():
    assert _order(["61-FY-00099B", "61-FIC-00099A", "61-FY-00099A", "61-FIC-00099B"]) == \
        ["61-FIC-00099A", "61-FY-00099A", "61-FIC-00099B", "61-FY-00099B"]


def test_loop_placeholder_sorts_last():
    assert _order(["61-PG-XXXXX", "61-FE-100"]) == ["61-FE-100", "61-PG-XXXXX"]


def test_unit_number_format_code_extraction():
    # 4-segment tag (area-unit-CODE-loop): code is the first alpha segment.
    assert classify(_code_of("422-11-PT-006A")) == ("transmitter", "")


def _code_of(tag):
    from webapp.deliverables.sort_utils import _extract_code
    return _extract_code(tag)


def test_blank_tag_does_not_crash():
    assert _order(["", "62-FE-1"]) == ["62-FE-1", ""]


# ── integration: real datasets, user-validated orders ────────────────────────

def test_job55_full_order():
    tags = [
        "62-FE-151010", "62-FE-151011", "62-FI-151010", "62-FI-151011",
        "62-FIT-151010", "62-FIT-151011", "62-PDI-151022", "62-PDI-151025",
        "62-PDIT-151022", "62-PDIT-151025", "62-PZA-151023", "62-PZA-151024",
        "62-PZA-151026", "62-PZA-151027", "62-PZIT-151023", "62-PZIT-151024",
        "62-PZIT-151026", "62-PZIT-151027",
    ]
    assert _order(tags) == [
        "62-FE-151010", "62-FIT-151010", "62-FI-151010",
        "62-FE-151011", "62-FIT-151011", "62-FI-151011",
        "62-PDIT-151022", "62-PDI-151022",
        "62-PZIT-151023", "62-PZA-151023",
        "62-PZIT-151024", "62-PZA-151024",
        "62-PDIT-151025", "62-PDI-151025",
        "62-PZIT-151026", "62-PZA-151026",
        "62-PZIT-151027", "62-PZA-151027",
    ]


def test_job43_full_order():
    tags = [
        "61-FE-149114", "61-FIC-00099A", "61-FIC-00099B", "61-FIT-149114",
        "61-FV-00099A", "61-FV-00099B", "61-FY-00099A", "61-FY-00099B",
        "61-FZA-12101", "61-FZI-12101", "61-FZI-149112", "61-FZI-149113",
        "61-FZIQ-149112", "61-FZIT-12101", "61-FZIT-149112", "61-FZIT-149113",
        "61-GB-00247", "61-HS-00326", "61-HS-00327", "61-HS-00329", "61-HS-00330",
        "61-HS-00470", "61-HS-00471", "61-PG-XXXXX", "61-PZA-149110",
        "61-PZIT-149110", "61-XA-00183", "61-XS-00182",
    ]
    assert _order(tags) == [
        "61-FIC-00099A", "61-FV-00099A", "61-FY-00099A",
        "61-FIC-00099B", "61-FV-00099B", "61-FY-00099B",
        "61-XS-00182", "61-XA-00183", "61-GB-00247",
        "61-HS-00326", "61-HS-00327", "61-HS-00329", "61-HS-00330",
        "61-HS-00470", "61-HS-00471",
        "61-FZIT-12101", "61-FZI-12101", "61-FZA-12101",
        "61-PZIT-149110", "61-PZA-149110",
        "61-FZIT-149112", "61-FZI-149112", "61-FZIQ-149112",
        "61-FZIT-149113", "61-FZI-149113",
        "61-FE-149114", "61-FIT-149114",
        "61-PG-XXXXX",
    ]
