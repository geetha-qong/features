"""Parity gate: the taxonomy module must reproduce today's hard-coded behaviour
exactly, and so must the switched-over consumers (inference.CLASS_NAMES,
api_v1._yolo_class_to_canonical).

Phase 2 note: both consumers now READ from webapp/taxonomy.py, so comparing a
consumer against the taxonomy module would be a tautology. Instead this gate
pins everything against FROZEN LITERALS captured from the pre-switch hard-coded
lists. If these fail, do NOT change consumers — fix taxonomy.json first.
"""
from webapp import taxonomy
from webapp.inference import CLASS_NAMES
from webapp.routers.api_v1 import _yolo_class_to_canonical


# ── Frozen literals (captured from the pre-switch hard-coded code) ────────────

# Exact ONNX channel order of v1-10's 23 classes (was inference.CLASS_NAMES).
EXPECTED_CLASS_NAMES = [
    # Valves (9)
    "valve_bv",            # 0
    "valve_ncbv",          # 1
    "valve_gt",            # 2
    "valve_bf",            # 3
    "valve_ck",            # 4
    "valve_db",            # 5
    "valve_relief_safety", # 6
    "valve_gl",            # 7
    "valve_3way_relief",   # 8
    # Instruments / signals (8)
    "inst_field",          # 9
    "inst_bpcs",           # 10
    "Motor",               # 11
    "Pump/Dwg Pump",       # 12
    "inst_sis",            # 13
    "SIS-R",               # 14
    "interlock",           # 15
    "inst_local_panel",    # 16
    # Direction (6)
    "arrow_up",            # 17
    "arrow_left",          # 18
    "arrow_right",         # 19
    "arrow_down",          # 20
    "connector_out",       # 21
    "connector_in",        # 22
]

# (label -> (entity_class, sub_class)) for every known label + edge cases,
# captured from the legacy api_v1._yolo_class_to_canonical implementation.
EXPECTED_ROUTING = {
    # Valves → ("valve", suffix.upper())
    "valve_bv": ("valve", "BV"),
    "valve_ncbv": ("valve", "NCBV"),
    "valve_gt": ("valve", "GT"),
    "valve_bf": ("valve", "BF"),
    "valve_ck": ("valve", "CK"),
    "valve_db": ("valve", "DB"),
    "valve_relief_safety": ("valve", "RELIEF_SAFETY"),
    "valve_gl": ("valve", "GL"),
    "valve_3way_relief": ("valve", "3WAY_RELIEF"),
    # Instruments / signals → ("instrument", None)
    "inst_field": ("instrument", None),
    "inst_bpcs": ("instrument", None),
    "inst_sis": ("instrument", None),
    "inst_local_panel": ("instrument", None),
    "interlock": ("instrument", None),
    "SIS-R": ("instrument", None),
    # Equipment → ("equipment", sub_class) where sub_class is the canonical type
    "Motor": ("equipment", "MOTOR"),
    "Pump/Dwg Pump": ("equipment", "PUMP"),
    "Pump_Dwg_Pump": ("equipment", "PUMP"),  # legacy v1-9 underscore form
    # Direction labels → (None, None)
    "arrow_up": (None, None),
    "arrow_left": (None, None),
    "arrow_right": (None, None),
    "arrow_down": (None, None),
    "connector_out": (None, None),
    "connector_in": (None, None),
    # Edge cases
    None: (None, None),
    "": (None, None),
    "valve_": ("valve", ""),
    "inst_": ("instrument", None),
    "totally_unknown": (None, None),
}


# ── Class-name list parity ────────────────────────────────────────────────────

def test_taxonomy_class_names_match_frozen_literals():
    assert taxonomy.class_names() == EXPECTED_CLASS_NAMES


def test_inference_class_names_match_frozen_literals():
    assert list(CLASS_NAMES) == EXPECTED_CLASS_NAMES


def test_inference_class_names_count_is_23():
    # The _decode head-shape assert depends on this.
    assert len(CLASS_NAMES) == 23


# ── Routing parity ────────────────────────────────────────────────────────────

def test_taxonomy_routing_matches_frozen_literals():
    for label, expected in EXPECTED_ROUTING.items():
        assert taxonomy.yolo_to_canonical(label) == expected, label


def test_api_v1_routing_matches_frozen_literals():
    for label, expected in EXPECTED_ROUTING.items():
        assert _yolo_class_to_canonical(label) == expected, label
