"""Multi-page 'Sheet' column threading (fix/multipage-sheet-number).

Before this fix, valve dicts never carried their source page, so every
canonical entity was attributed to sheet 1. The extractor now stamps
v["page"] = tile.get("page", 0); the parser threads it into ValveRow.page
and emits a 1-based "Sheet" CSV column. These tests lock in that contract.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from parser import ValveRow, build_valve_row


def test_valve_row_sheet_is_page_plus_one():
    """A valve detected on page index 2 → CSV 'Sheet' == 3 (1-based)."""
    raw = {"valve_tag": "62-BF-151031", "line_number": "", "page": 2}
    row = build_valve_row(raw)
    assert row is not None
    assert row.page == 2
    assert row.to_csv_dict()["Sheet"] == 3


def test_valve_row_sheet_defaults_to_1_when_page_absent():
    """No 'page' key on the raw dict → page 0 → 'Sheet' == 1 (backward compatible)."""
    raw = {"valve_tag": "62-BF-151031", "line_number": ""}
    row = build_valve_row(raw)
    assert row is not None
    assert row.page == 0
    assert row.to_csv_dict()["Sheet"] == 1


def test_valve_row_csv_dict_always_has_sheet_key():
    """Default-constructed ValveRow still emits a 'Sheet' column (== 1)."""
    assert ValveRow().to_csv_dict()["Sheet"] == 1
