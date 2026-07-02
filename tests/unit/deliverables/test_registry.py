from typing import ClassVar

import pytest

from webapp.deliverables.base import Generator
from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.registry import GeneratorRegistry, UnknownGenerator
from webapp.deliverables.template import TemplateConfig


class StubGenerator(Generator):
    deliverable_type: ClassVar[str] = "valve_list"
    file_format: ClassVar[str] = "csv"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        return b""


def test_registry_register_and_resolve():
    reg = GeneratorRegistry()
    reg.register(StubGenerator)
    klass = reg.resolve("valve_list", "csv")
    assert klass is StubGenerator


def test_registry_resolve_unknown_raises():
    reg = GeneratorRegistry()
    with pytest.raises(UnknownGenerator, match="valve_list/csv"):
        reg.resolve("valve_list", "csv")


def test_registry_register_duplicate_raises():
    reg = GeneratorRegistry()
    reg.register(StubGenerator)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(StubGenerator)
