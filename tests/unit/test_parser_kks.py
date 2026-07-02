"""Format 5 — KKS plant-coding valve tags (the 70310-20-* drawings).

Before Format 5, the Vision pass read these tags fine but the parser dropped
every one (none of Formats 1-4 match a KKS code), so the valve list came out
empty. These tests lock in: KKS tags parse, distinct tags stay distinct
(dedup), and Formats 1-4 / noise are unaffected.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from parser import build_valve_row, parse_valve_tag


def test_kks_with_component_code():
    r = parse_valve_tag("20LCM40 BR401")
    assert r is not None and r["format"] == 5
    assert r["area"] == "20"          # KKS unit
    assert r["type_code"] == "BR"     # component code → Category (first-pass)
    assert r["serial"] == "LCM40BR401"


def test_kks_no_space_component():
    r = parse_valve_tag("20GHB44BR001")
    assert r and r["format"] == 5 and r["type_code"] == "BR" and r["serial"] == "GHB44BR001"


def test_kks_no_component_falls_back_to_system():
    r = parse_valve_tag("20GHB4461")
    assert r and r["format"] == 5
    assert r["type_code"] == "GHB"    # no component → 3-letter system code
    assert r["serial"] == "GHB4461"


def test_kks_aa_component():
    r = parse_valve_tag("20LCM17AA001")
    assert r and r["format"] == 5 and r["type_code"] == "AA" and r["serial"] == "LCM17AA001"


def test_distinct_kks_tags_get_distinct_dedup_keys():
    # Same unit + aggregate but different component must NOT collapse in dedup
    # (key = area_code + serial_no).
    rows = [
        build_valve_row({"valve_tag": t, "confidence": 0.9})
        for t in ["20LCM40 AA001", "20LCM40 BR001", "20LCM40 BR402"]
    ]
    assert all(r is not None for r in rows)
    keys = {(r.area_code, r.serial_no) for r in rows}
    assert len(keys) == 3


def test_existing_formats_unaffected():
    assert parse_valve_tag("62-BF-151031")["format"] == 1
    assert parse_valve_tag("VB15-2011A")["format"] == 2
    assert parse_valve_tag("VB15 7007")["format"] == 3
    assert parse_valve_tag("PV-01156")["format"] == 4


def test_noise_still_rejected():
    # KKS shape is specific (2d + 3L); random labels/notes must not match.
    assert parse_valve_tag("TUB-01") is None
    assert parse_valve_tag("NOTE 11") is None
    assert parse_valve_tag("") is None
