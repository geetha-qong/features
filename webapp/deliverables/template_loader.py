"""Loads customer template JSON files from disk and caches parsed configs."""

import json
from pathlib import Path
from typing import Dict

from webapp.deliverables.template import TemplateConfig

TEMPLATE_DIR = Path(__file__).parent / "customer_templates"


class TemplateNotFound(KeyError):
    pass


class TemplateLoader:
    def __init__(self, template_dir: Path = TEMPLATE_DIR) -> None:
        self._template_dir = template_dir
        self._cache: Dict[str, TemplateConfig] = {}

    def load(self, slug: str) -> TemplateConfig:
        if slug in self._cache:
            return self._cache[slug]
        path = self._template_dir / f"{slug}.json"
        if not path.exists():
            raise TemplateNotFound(slug)
        raw = json.loads(path.read_text())
        cfg = TemplateConfig.model_validate(raw)
        self._cache[slug] = cfg
        return cfg

    def load_with_fallback(self, slug: str, fallback: str = "default") -> TemplateConfig:
        try:
            return self.load(slug)
        except TemplateNotFound:
            return self.load(fallback)
