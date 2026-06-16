"""Parity gate: the taxonomy module must reproduce today's hard-coded lists
exactly. If these fail, do NOT switch consumers — fix taxonomy.json first."""
from webapp import taxonomy
from webapp.inference import CLASS_NAMES
from webapp.routers.api_v1 import _yolo_class_to_canonical


def test_class_names_match_inference_constant():
    # Same labels in the same ONNX channel order.
    assert taxonomy.class_names() == list(CLASS_NAMES)


def test_routing_matches_legacy_for_every_known_label():
    for label in CLASS_NAMES:
        assert taxonomy.yolo_to_canonical(label) == _yolo_class_to_canonical(label), label


def test_routing_matches_legacy_for_edge_cases():
    edge_labels = [
        None, "", "valve_", "valve_bv", "valve_3way_relief", "Pump_Dwg_Pump",
        "Pump/Dwg Pump", "SIS-R", "interlock", "arrow_up", "connector_in",
        "totally_unknown", "inst_", "inst_field",
    ]
    for label in edge_labels:
        assert taxonomy.yolo_to_canonical(label) == _yolo_class_to_canonical(label), label
