"""
Drawing-specific manual override layer.
Applied after Stage 3 (parse) and before Stage 4 (validate).

Corrections are verified from P&ID markup review by the engineer.
Structure: {drawing_stem: {"remove": [serial_list], "overrides": {serial: {field: value}}}}
"""

DRAWING_CORRECTIONS = {
    "MUK-62-1-15-1004-001-24C7-D": {
        # Serials confirmed NOT present in the P&ID (model hallucinations)
        "remove": ["151076", "151077"],
        "overrides": {
            # GL valve — pipe size shown as X" (unreadable) in drawing
            "151008": {"size": "NOT DEFINED"},
            # DB valves — model read the main 16" pipe; correct size from drawing
            "151025": {"size": "2"},
            "151026": {"size": "2"},
            # DB valves — drawing explicitly shows 1/2" next to DBB symbol
            "151027": {"size": "1/2"},
            "151028": {"size": "1/2"},
            # BF valve — engineer confirmed 16" (model read wrong tile)
            "151054": {"size": "16"},
            # BF valve — pipe size shown as X" (unreadable) in drawing
            "151069": {"size": "NOT DEFINED"},
            # Recycle BF valves — all four sit on the same line 10"-W-62151021-BGA-H
            # (model traced the LO header instead)
            "151065": {"fluid_code": "W", "line": '10"-W-62151021-BGA-H'},
            "151066": {"fluid_code": "W", "line": '10"-W-62151021-BGA-H'},
            "151067": {"fluid_code": "W", "line": '10"-W-62151021-BGA-H'},
            "151068": {"fluid_code": "W", "line": '10"-W-62151021-BGA-H'},
        },
    }
}


def apply_corrections(rows: list, drawing_stem: str) -> list:
    """Apply drawing-specific manual corrections after parsing.

    Args:
        rows: list of ValveRow objects (from parse_raw_extractions)
        drawing_stem: PDF stem with INPUT- prefix stripped
                      e.g. "MUK-62-1-15-1004-001-24C7-D"

    Returns:
        Filtered + corrected list of ValveRow objects.
    """
    config = DRAWING_CORRECTIONS.get(drawing_stem)
    if not config:
        return rows

    remove_serials = set(str(s) for s in config.get("remove", []))
    overrides = config.get("overrides", {})

    result = []
    for row in rows:
        serial = str(row.serial_no)
        if serial in remove_serials:
            print(f"  [corrections] Removed {row.area_code}-{row.category}-{serial} (not in P&ID)")
            continue
        if serial in overrides:
            for field_name, value in overrides[serial].items():
                old = getattr(row, field_name, None)
                setattr(row, field_name, value)
                print(f"  [corrections] {serial} {field_name}: {old!r} → {value!r}")
        result.append(row)

    return result
