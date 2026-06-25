import webapp.deliverables  # noqa: F401  (triggers all imports)

from webapp.deliverables.registry import REGISTRY


def test_all_generators_registered():
    assert REGISTRY.resolve("valve_list", "csv").__name__ == "ValveListCSVGenerator"
    assert REGISTRY.resolve("valve_list", "xlsx").__name__ == "ValveListXLSXGenerator"
    assert REGISTRY.resolve("instrument_index", "csv").__name__ == "InstrumentIndexCSVGenerator"
    assert REGISTRY.resolve("instrument_index", "xlsx").__name__ == "InstrumentIndexXLSXGenerator"
    assert REGISTRY.resolve("equipment_list", "xlsx").__name__ == "EquipmentListXLSXGenerator"
    assert REGISTRY.resolve("datasheet", "xlsx").__name__ == "DatasheetXLSXGenerator"
