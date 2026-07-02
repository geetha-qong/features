from webapp import taxonomy


def test_class_names_order_and_count():
    names = taxonomy.class_names()
    assert len(names) == 23
    assert names[0] == "valve_bv"
    assert names[12] == "Pump/Dwg Pump"
    assert names[22] == "connector_in"


def test_yolo_to_canonical_valve_suffix_upper():
    assert taxonomy.yolo_to_canonical("valve_bv") == ("valve", "BV")
    assert taxonomy.yolo_to_canonical("valve_relief_safety") == ("valve", "RELIEF_SAFETY")
    assert taxonomy.yolo_to_canonical("valve_3way_relief") == ("valve", "3WAY_RELIEF")


def test_yolo_to_canonical_instrument_and_equipment():
    assert taxonomy.yolo_to_canonical("inst_field") == ("instrument", None)
    assert taxonomy.yolo_to_canonical("interlock") == ("instrument", None)
    assert taxonomy.yolo_to_canonical("SIS-R") == ("instrument", None)
    assert taxonomy.yolo_to_canonical("Motor") == ("equipment", "MOTOR")
    assert taxonomy.yolo_to_canonical("Pump/Dwg Pump") == ("equipment", "PUMP")
    assert taxonomy.yolo_to_canonical("Pump_Dwg_Pump") == ("equipment", "PUMP")


def test_yolo_to_canonical_non_entities_and_unknown():
    assert taxonomy.yolo_to_canonical("arrow_up") == (None, None)
    assert taxonomy.yolo_to_canonical("connector_in") == (None, None)
    assert taxonomy.yolo_to_canonical("totally_unknown") == (None, None)
    assert taxonomy.yolo_to_canonical(None) == (None, None)
    assert taxonomy.yolo_to_canonical("") == (None, None)


def test_metadata_accessors():
    assert taxonomy.display_name("valve", "BV") == "Ball Valve"
    assert taxonomy.color("valve", "BF") == "#FF6B6B"
    assert taxonomy.glyph_kind("instrument", None) in {"inst_field"}
