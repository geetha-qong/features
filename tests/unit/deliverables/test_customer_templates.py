import json
from pathlib import Path

from webapp.deliverables.template import TemplateConfig

TEMPLATE_DIR = Path(__file__).parent.parent.parent.parent / "webapp" / "deliverables" / "customer_templates"


def test_default_template_parses():
    raw = json.loads((TEMPLATE_DIR / "default.json").read_text())
    cfg = TemplateConfig.model_validate(raw)
    assert cfg.slug == "default"
    assert "valve_list" in cfg.deliverables
    assert "instrument_index" in cfg.deliverables
    assert "equipment_list" in cfg.deliverables
    assert "datasheet" in cfg.deliverables


def test_ronesans_template_parses():
    raw = json.loads((TEMPLATE_DIR / "ronesans.json").read_text())
    cfg = TemplateConfig.model_validate(raw)
    assert cfg.slug == "ronesans"
    assert cfg.customer_name == "Ronesans Engineering"
    headers = [c.header for c in cfg.deliverables["valve_list"].columns]
    assert "Tag No." in headers


def test_muk_template_parses():
    raw = json.loads((TEMPLATE_DIR / "muk.json").read_text())
    cfg = TemplateConfig.model_validate(raw)
    assert cfg.slug == "muk"
    assert cfg.customer_name == "MUK Oman"
