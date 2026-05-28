from typing import ClassVar

import pytest

from webapp.deliverables.base import Generator
from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.template import TemplateConfig


class DummyGenerator(Generator):
    deliverable_type: ClassVar[str] = "valve_list"
    file_format: ClassVar[str] = "csv"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        return b"dummy,output\n"


def test_generator_must_define_deliverable_type():
    with pytest.raises(TypeError, match="deliverable_type"):
        class Bad(Generator):
            file_format: ClassVar[str] = "csv"
            def generate(self, canonical, template):
                return b""


def test_generator_must_define_file_format():
    with pytest.raises(TypeError, match="file_format"):
        class Bad(Generator):
            deliverable_type: ClassVar[str] = "valve_list"
            def generate(self, canonical, template):
                return b""


def test_dummygenerator_runs():
    gen = DummyGenerator()
    cfg = TemplateConfig(slug="x", customer_name="X", deliverables={})
    job = JobCanonical(
        job_id=1,
        canonical_schema_version="1.0.0",
        customer_template_slug="x",
        entities=[],
    )
    assert gen.generate(job, cfg) == b"dummy,output\n"
