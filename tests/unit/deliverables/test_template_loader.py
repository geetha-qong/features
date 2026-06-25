import pytest

from webapp.deliverables.template_loader import TemplateNotFound, TemplateLoader


def test_loader_loads_default():
    loader = TemplateLoader()
    cfg = loader.load("default")
    assert cfg.slug == "default"
    assert "valve_list" in cfg.deliverables


def test_loader_loads_ronesans():
    loader = TemplateLoader()
    cfg = loader.load("ronesans")
    assert cfg.slug == "ronesans"


def test_loader_caches_repeated_loads():
    loader = TemplateLoader()
    first = loader.load("default")
    second = loader.load("default")
    assert first is second


def test_loader_raises_on_unknown_slug():
    loader = TemplateLoader()
    with pytest.raises(TemplateNotFound, match="nonexistent_slug"):
        loader.load("nonexistent_slug")


def test_loader_falls_back_to_default(monkeypatch):
    loader = TemplateLoader()
    cfg = loader.load_with_fallback("nonexistent_slug")
    assert cfg.slug == "default"
