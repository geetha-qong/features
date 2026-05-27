# Deliverables Template Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the customer-template engine and four deliverable generators (Valve List CSV+XLSX, Instrument Index CSV+XLSX, Equipment List XLSX, Instrument Datasheet PDF) that read the pipeline's internal canonical JSON and produce per-customer formatted files for the Qong Studio MVP.

**Architecture:** A `Generator` abstract base class with one concrete generator per (deliverable_type × file_format). Each generator takes a `JobCanonical` Pydantic model (the pipeline's internal output) + a `TemplateConfig` Pydantic model (a per-customer JSON file) and returns `bytes`. A `Registry` maps (deliverable_type, file_format) → generator class. A FastAPI router exposes `POST /api/jobs/{job_id}/export/{deliverable}` that loads the job's canonical JSON from the existing pipeline output path, picks the customer template from the project's `template_slug`, runs the generator, stores the file, and returns a download URL.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pandas, openpyxl, reportlab, pytest. Existing webapp scaffolding (`webapp/database.py`, `webapp/models.py`, `webapp/routers/`).

**Reads from spec:** `docs/decisions/01-qong-studio-mvp-design.md` §3 (deliverables), §4.1 (architecture), §4.2 (extraction pipeline), §4.4 (in-scope).

---

## File Structure

**New files (created in this plan):**

```
webapp/deliverables/
├── __init__.py                          # Package marker
├── canonical.py                         # Pydantic models for pipeline input
├── template.py                          # Pydantic models for customer templates
├── base.py                              # Abstract Generator base class
├── registry.py                          # (deliverable_type, file_format) -> Generator class
├── template_loader.py                   # Loads + caches customer template JSON files
├── valve_list.py                        # ValveListCSVGenerator + ValveListXLSXGenerator
├── instrument_index.py                  # InstrumentIndexCSVGenerator + InstrumentIndexXLSXGenerator
├── equipment_list.py                    # EquipmentListXLSXGenerator
├── datasheet.py                         # DatasheetPDFGenerator
└── customer_templates/
    ├── default.json                     # Fallback template
    ├── ronesans.json                    # Ronesans EPC template
    └── muk.json                         # MUK Oman template

webapp/routers/
└── exports.py                           # POST /api/jobs/{id}/export/{deliverable}

tests/unit/deliverables/
├── __init__.py
├── conftest.py                          # Shared fixtures (sample canonical, sample template)
├── fixtures/
│   ├── canonical_sample.json            # Hand-crafted canonical job fixture
│   ├── expected_valve_list_default.csv  # Expected CSV output (default template)
│   └── expected_valve_list_ronesans.csv # Expected CSV output (Ronesans template)
├── test_canonical_schema.py
├── test_template_loader.py
├── test_registry.py
├── test_valve_list.py
├── test_instrument_index.py
├── test_equipment_list.py
└── test_datasheet.py

tests/e2e/
└── test_exports_api.py                  # End-to-end API test
```

**Modified files:**

- `requirements-webapp.txt` — add openpyxl, reportlab, pydantic>=2 (pandas already present)
- `webapp/main.py` — register the new exports router
- (no migration needed in this plan — uses existing `Job.output_csv_path` + reads canonical from filesystem alongside existing CSV)

---

## Task 1: Add dependencies

**Files:**
- Modify: `requirements-webapp.txt`

- [ ] **Step 1: Read current requirements file**

Run: `cat requirements-webapp.txt`

- [ ] **Step 2: Append the three new dependencies**

Add these three lines to the end of `requirements-webapp.txt`:

```
openpyxl>=3.1.0,<4.0.0
reportlab>=4.2.0,<5.0.0
pydantic>=2.7.0,<3.0.0
```

- [ ] **Step 3: Rebuild the web image**

Run: `docker compose build web`
Expected: build succeeds, image tagged.

- [ ] **Step 4: Smoke-test imports inside the container**

Run: `docker compose run --rm web python3 -c "import openpyxl, reportlab, pydantic; print(openpyxl.__version__, reportlab.Version, pydantic.VERSION)"`
Expected: prints three version strings, no errors.

- [ ] **Step 5: Commit**

```bash
git add requirements-webapp.txt
git commit -m "feat(deliverables): add openpyxl, reportlab, pydantic>=2 deps"
```

---

## Task 2: Canonical input schema

**Files:**
- Create: `webapp/deliverables/__init__.py`
- Create: `webapp/deliverables/canonical.py`
- Create: `tests/unit/deliverables/__init__.py`
- Create: `tests/unit/deliverables/conftest.py`
- Create: `tests/unit/deliverables/fixtures/canonical_sample.json`
- Create: `tests/unit/deliverables/test_canonical_schema.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_canonical_schema.py`:

```python
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from webapp.deliverables.canonical import CanonicalEntity, JobCanonical, VendorMatch

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_jobcanonical_parses_sample_fixture():
    raw = json.loads((FIXTURE_DIR / "canonical_sample.json").read_text())
    job = JobCanonical.model_validate(raw)
    assert job.job_id == 41
    assert job.canonical_schema_version == "1.0.0"
    assert job.customer_template_slug == "ronesans"
    assert len(job.entities) == 4
    valve = next(e for e in job.entities if e.entity_class == "valve")
    assert valve.tag == "GV-001"
    assert valve.fields["size"] == "4in"
    instr = next(e for e in job.entities if e.entity_class == "instrument")
    assert instr.tag == "PT-01018"
    assert instr.vendor_match is not None
    assert instr.vendor_match.vendor_name == "Yokogawa"


def test_jobcanonical_rejects_unknown_entity_class():
    bad = {
        "job_id": 1,
        "canonical_schema_version": "1.0.0",
        "customer_template_slug": "default",
        "entities": [
            {
                "entity_id": "00000000-0000-0000-0000-000000000001",
                "entity_class": "alien",
                "sub_class": "ufo",
                "tag": "X-1",
                "pid_number": "P-001",
                "sheet_number": 1,
                "bbox": [0, 0, 10, 10],
                "fields": {},
            }
        ],
    }
    with pytest.raises(ValidationError):
        JobCanonical.model_validate(bad)


def test_canonicalentity_optional_vendormatch():
    entity = CanonicalEntity(
        entity_id="00000000-0000-0000-0000-000000000002",
        entity_class="valve",
        sub_class="gate_valve",
        tag="GV-002",
        pid_number="P-001",
        sheet_number=1,
        bbox=(0, 0, 10, 10),
        fields={"size": "2in"},
    )
    assert entity.vendor_match is None
```

- [ ] **Step 2: Create the fixture and empty package files**

Create `webapp/deliverables/__init__.py` (empty file).

Create `tests/unit/deliverables/__init__.py` (empty file).

Create `tests/unit/deliverables/conftest.py`:

```python
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def canonical_sample_path() -> Path:
    return FIXTURE_DIR / "canonical_sample.json"
```

Create `tests/unit/deliverables/fixtures/canonical_sample.json`:

```json
{
  "job_id": 41,
  "canonical_schema_version": "1.0.0",
  "customer_template_slug": "ronesans",
  "entities": [
    {
      "entity_id": "11111111-1111-1111-1111-111111111111",
      "entity_class": "valve",
      "sub_class": "gate_valve",
      "tag": "GV-001",
      "pid_number": "P-001",
      "sheet_number": 1,
      "bbox": [100.0, 200.0, 150.0, 250.0],
      "fields": {"size": "4in", "service": "Process Water", "material": "CS"}
    },
    {
      "entity_id": "22222222-2222-2222-2222-222222222222",
      "entity_class": "valve",
      "sub_class": "ball_valve",
      "tag": "BV-002",
      "pid_number": "P-001",
      "sheet_number": 1,
      "bbox": [300.0, 200.0, 350.0, 250.0],
      "fields": {"size": "2in", "service": "Instrument Air", "material": "SS316"}
    },
    {
      "entity_id": "33333333-3333-3333-3333-333333333333",
      "entity_class": "instrument",
      "sub_class": "PT",
      "tag": "PT-01018",
      "pid_number": "P-001",
      "sheet_number": 1,
      "bbox": [500.0, 200.0, 540.0, 240.0],
      "fields": {"service": "Reactor outlet pressure", "signal_type": "4-20mA HART"},
      "vendor_match": {
        "vendor_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "vendor_name": "Yokogawa",
        "product_name": "EJX130A",
        "part_number": "EJX130A-JMS5G-022NN",
        "catalog_fields": {
          "range_min": "0",
          "range_max": "150 bar",
          "accuracy": "0.04%",
          "body_material": "316L SS"
        }
      }
    },
    {
      "entity_id": "44444444-4444-4444-4444-444444444444",
      "entity_class": "equipment",
      "sub_class": "vessel",
      "tag": "V-101",
      "pid_number": "P-001",
      "sheet_number": 1,
      "bbox": [700.0, 100.0, 900.0, 400.0],
      "fields": {"duty": "Reactor", "volume": "12 m3"}
    }
  ]
}
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_canonical_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webapp.deliverables.canonical'`

- [ ] **Step 4: Implement the canonical schema**

Create `webapp/deliverables/canonical.py`:

```python
"""Pydantic models for the pipeline's internal canonical output.

Every deliverable generator consumes a JobCanonical. This is the contract
between the extraction pipeline and the deliverables subsystem. Bumping
canonical_schema_version must be recorded in FEATURES.md as type=architecture.
"""

from typing import Any, Dict, Literal, Optional, Tuple
from uuid import UUID

from pydantic import BaseModel, Field

CANONICAL_SCHEMA_VERSION = "1.0.0"

EntityClass = Literal["valve", "instrument", "equipment"]


class VendorMatch(BaseModel):
    """Vendor catalog match attached to an entity (typically an instrument)."""

    vendor_id: UUID
    vendor_name: str
    product_name: str
    part_number: str
    catalog_fields: Dict[str, Any] = Field(default_factory=dict)


class CanonicalEntity(BaseModel):
    """One detected symbol on a P&ID with its identifying text and metadata."""

    entity_id: UUID
    entity_class: EntityClass
    sub_class: str
    tag: Optional[str] = None
    pid_number: str
    sheet_number: int
    bbox: Tuple[float, float, float, float]
    fields: Dict[str, Any] = Field(default_factory=dict)
    vendor_match: Optional[VendorMatch] = None


class JobCanonical(BaseModel):
    """Top-level canonical structure for one job, consumed by every generator."""

    job_id: int
    canonical_schema_version: str
    customer_template_slug: str
    entities: list[CanonicalEntity]
```

- [ ] **Step 5: Run the tests and commit**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_canonical_schema.py -v`
Expected: 3 PASSED.

```bash
git add webapp/deliverables/__init__.py webapp/deliverables/canonical.py tests/unit/deliverables/__init__.py tests/unit/deliverables/conftest.py tests/unit/deliverables/fixtures/canonical_sample.json tests/unit/deliverables/test_canonical_schema.py
git commit -m "feat(deliverables): canonical pipeline-output schema (v1.0.0)"
```

---

## Task 3: Customer template schema

**Files:**
- Create: `webapp/deliverables/template.py`
- Create: `tests/unit/deliverables/test_template_schema.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_template_schema.py`:

```python
import pytest
from pydantic import ValidationError

from webapp.deliverables.template import ColumnDef, DeliverableConfig, TemplateConfig


def test_templateconfig_with_valve_list_columns():
    cfg = TemplateConfig(
        slug="ronesans",
        customer_name="Ronesans Engineering",
        deliverables={
            "valve_list": DeliverableConfig(
                columns=[
                    ColumnDef(field="tag", header="Tag No.", order=1),
                    ColumnDef(field="fields.size", header="Size", order=2),
                    ColumnDef(field="fields.service", header="Service", order=3),
                ],
                sheet_name="Valve List",
            )
        },
    )
    assert cfg.slug == "ronesans"
    assert len(cfg.deliverables["valve_list"].columns) == 3
    assert cfg.deliverables["valve_list"].columns[0].header == "Tag No."


def test_columndef_field_path_can_use_dot_notation():
    col = ColumnDef(field="vendor_match.catalog_fields.accuracy", header="Accuracy", order=10)
    assert col.field == "vendor_match.catalog_fields.accuracy"


def test_templateconfig_rejects_empty_slug():
    with pytest.raises(ValidationError):
        TemplateConfig(slug="", customer_name="X", deliverables={})


def test_deliverableconfig_orders_columns_consistently():
    cfg = DeliverableConfig(
        columns=[
            ColumnDef(field="tag", header="Tag", order=2),
            ColumnDef(field="fields.size", header="Size", order=1),
        ]
    )
    ordered = sorted(cfg.columns, key=lambda c: c.order)
    assert [c.header for c in ordered] == ["Size", "Tag"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_template_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webapp.deliverables.template'`

- [ ] **Step 3: Implement the template schema**

Create `webapp/deliverables/template.py`:

```python
"""Pydantic models for the per-customer deliverable template format.

A TemplateConfig is one JSON file in webapp/deliverables/customer_templates/.
Each generator reads the relevant DeliverableConfig from the chosen template
and renders the deliverable accordingly.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class ColumnDef(BaseModel):
    """One column in a tabular deliverable.

    `field` uses dot notation to navigate the canonical entity, e.g.
    "fields.size" reads CanonicalEntity.fields["size"];
    "vendor_match.catalog_fields.accuracy" reads the nested vendor field.
    """

    field: str
    header: str
    order: int


class DeliverableConfig(BaseModel):
    """Per-deliverable presentation config inside a TemplateConfig."""

    columns: List[ColumnDef] = Field(default_factory=list)
    sheet_name: Optional[str] = None
    font: str = "Calibri"


class TemplateConfig(BaseModel):
    """One customer's full template config across all deliverables."""

    slug: str
    customer_name: str
    deliverables: Dict[str, DeliverableConfig]

    @field_validator("slug")
    @classmethod
    def _slug_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("slug must be non-empty")
        return v
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_template_schema.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/template.py tests/unit/deliverables/test_template_schema.py
git commit -m "feat(deliverables): customer template config schema"
```

---

## Task 4: Generator base class

**Files:**
- Create: `webapp/deliverables/base.py`
- Create: `tests/unit/deliverables/test_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_base.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webapp.deliverables.base'`

- [ ] **Step 3: Implement the base class**

Create `webapp/deliverables/base.py`:

```python
"""Abstract base for deliverable generators.

Subclasses must define deliverable_type and file_format as ClassVars, and
implement generate(canonical, template) -> bytes.
"""

from abc import ABC, abstractmethod
from typing import ClassVar

from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.template import TemplateConfig


class Generator(ABC):
    deliverable_type: ClassVar[str]
    file_format: ClassVar[str]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "deliverable_type" not in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} must define class attribute 'deliverable_type'"
            )
        if "file_format" not in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} must define class attribute 'file_format'"
            )

    @abstractmethod
    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        """Render the deliverable as raw bytes (file content)."""
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_base.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/base.py tests/unit/deliverables/test_base.py
git commit -m "feat(deliverables): abstract Generator base class"
```

---

## Task 5: Generator registry

**Files:**
- Create: `webapp/deliverables/registry.py`
- Create: `tests/unit/deliverables/test_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_registry.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the registry**

Create `webapp/deliverables/registry.py`:

```python
"""Map (deliverable_type, file_format) -> Generator subclass.

Concrete generators register themselves at import time. The router uses
the registry to look up which generator to instantiate for a given request.
"""

from typing import Dict, Tuple, Type

from webapp.deliverables.base import Generator


class UnknownGenerator(KeyError):
    pass


class GeneratorRegistry:
    def __init__(self) -> None:
        self._registry: Dict[Tuple[str, str], Type[Generator]] = {}

    def register(self, generator_cls: Type[Generator]) -> None:
        key = (generator_cls.deliverable_type, generator_cls.file_format)
        if key in self._registry:
            raise ValueError(f"{key[0]}/{key[1]} is already registered")
        self._registry[key] = generator_cls

    def resolve(self, deliverable_type: str, file_format: str) -> Type[Generator]:
        key = (deliverable_type, file_format)
        if key not in self._registry:
            raise UnknownGenerator(f"{deliverable_type}/{file_format}")
        return self._registry[key]


REGISTRY = GeneratorRegistry()
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_registry.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/registry.py tests/unit/deliverables/test_registry.py
git commit -m "feat(deliverables): generator registry"
```

---

## Task 6: Default + Ronesans + MUK customer templates

**Files:**
- Create: `webapp/deliverables/customer_templates/default.json`
- Create: `webapp/deliverables/customer_templates/ronesans.json`
- Create: `webapp/deliverables/customer_templates/muk.json`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_customer_templates.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_customer_templates.py -v`
Expected: FAIL — `FileNotFoundError` on `default.json`.

- [ ] **Step 3: Create the three customer template files**

Create `webapp/deliverables/customer_templates/default.json`:

```json
{
  "slug": "default",
  "customer_name": "Qong Default",
  "deliverables": {
    "valve_list": {
      "sheet_name": "Valve List",
      "columns": [
        {"field": "tag", "header": "Tag", "order": 1},
        {"field": "sub_class", "header": "Type", "order": 2},
        {"field": "fields.size", "header": "Size", "order": 3},
        {"field": "fields.service", "header": "Service", "order": 4},
        {"field": "fields.material", "header": "Material", "order": 5},
        {"field": "pid_number", "header": "P&ID", "order": 6}
      ]
    },
    "instrument_index": {
      "sheet_name": "Instrument Index",
      "columns": [
        {"field": "tag", "header": "Tag", "order": 1},
        {"field": "sub_class", "header": "Type", "order": 2},
        {"field": "fields.service", "header": "Service", "order": 3},
        {"field": "fields.signal_type", "header": "Signal", "order": 4},
        {"field": "pid_number", "header": "P&ID", "order": 5}
      ]
    },
    "equipment_list": {
      "sheet_name": "Equipment List",
      "columns": [
        {"field": "tag", "header": "Tag", "order": 1},
        {"field": "sub_class", "header": "Type", "order": 2},
        {"field": "fields.duty", "header": "Duty", "order": 3},
        {"field": "fields.volume", "header": "Volume", "order": 4},
        {"field": "pid_number", "header": "P&ID", "order": 5}
      ]
    },
    "datasheet": {
      "columns": [
        {"field": "tag", "header": "Tag", "order": 1},
        {"field": "sub_class", "header": "Type", "order": 2},
        {"field": "fields.service", "header": "Service", "order": 3},
        {"field": "fields.signal_type", "header": "Signal Type", "order": 4},
        {"field": "vendor_match.vendor_name", "header": "Manufacturer", "order": 5},
        {"field": "vendor_match.product_name", "header": "Model", "order": 6},
        {"field": "vendor_match.part_number", "header": "Part Number", "order": 7},
        {"field": "vendor_match.catalog_fields.range_min", "header": "Range Min", "order": 8},
        {"field": "vendor_match.catalog_fields.range_max", "header": "Range Max", "order": 9},
        {"field": "vendor_match.catalog_fields.accuracy", "header": "Accuracy", "order": 10},
        {"field": "vendor_match.catalog_fields.body_material", "header": "Body Material", "order": 11}
      ]
    }
  }
}
```

Create `webapp/deliverables/customer_templates/ronesans.json`:

```json
{
  "slug": "ronesans",
  "customer_name": "Ronesans Engineering",
  "deliverables": {
    "valve_list": {
      "sheet_name": "VALVE LIST",
      "font": "Arial",
      "columns": [
        {"field": "tag", "header": "Tag No.", "order": 1},
        {"field": "fields.size", "header": "Size", "order": 2},
        {"field": "sub_class", "header": "Valve Type", "order": 3},
        {"field": "fields.service", "header": "Service Description", "order": 4},
        {"field": "fields.material", "header": "Body Material", "order": 5},
        {"field": "pid_number", "header": "P&ID Ref.", "order": 6},
        {"field": "sheet_number", "header": "Sheet", "order": 7}
      ]
    },
    "instrument_index": {
      "sheet_name": "INSTRUMENT INDEX",
      "font": "Arial",
      "columns": [
        {"field": "tag", "header": "Instrument Tag", "order": 1},
        {"field": "sub_class", "header": "Type", "order": 2},
        {"field": "fields.service", "header": "Description", "order": 3},
        {"field": "fields.signal_type", "header": "Signal", "order": 4},
        {"field": "pid_number", "header": "P&ID Ref.", "order": 5}
      ]
    },
    "equipment_list": {
      "sheet_name": "EQUIPMENT LIST",
      "font": "Arial",
      "columns": [
        {"field": "tag", "header": "Equipment Tag", "order": 1},
        {"field": "sub_class", "header": "Equipment Type", "order": 2},
        {"field": "fields.duty", "header": "Service Duty", "order": 3},
        {"field": "fields.volume", "header": "Capacity", "order": 4},
        {"field": "pid_number", "header": "P&ID Ref.", "order": 5}
      ]
    },
    "datasheet": {
      "font": "Arial",
      "columns": [
        {"field": "tag", "header": "Tag No.", "order": 1},
        {"field": "sub_class", "header": "Type", "order": 2},
        {"field": "fields.service", "header": "Service", "order": 3},
        {"field": "fields.signal_type", "header": "Signal Type", "order": 4},
        {"field": "vendor_match.vendor_name", "header": "Manufacturer", "order": 5},
        {"field": "vendor_match.product_name", "header": "Model", "order": 6},
        {"field": "vendor_match.part_number", "header": "Part No.", "order": 7},
        {"field": "vendor_match.catalog_fields.range_min", "header": "Range Min", "order": 8},
        {"field": "vendor_match.catalog_fields.range_max", "header": "Range Max", "order": 9},
        {"field": "vendor_match.catalog_fields.accuracy", "header": "Accuracy", "order": 10},
        {"field": "vendor_match.catalog_fields.body_material", "header": "Body Material", "order": 11}
      ]
    }
  }
}
```

Create `webapp/deliverables/customer_templates/muk.json`:

```json
{
  "slug": "muk",
  "customer_name": "MUK Oman",
  "deliverables": {
    "valve_list": {
      "sheet_name": "Valve List",
      "columns": [
        {"field": "tag", "header": "Tag", "order": 1},
        {"field": "sub_class", "header": "Type", "order": 2},
        {"field": "fields.size", "header": "Line Size", "order": 3},
        {"field": "fields.service", "header": "Service", "order": 4},
        {"field": "pid_number", "header": "Drawing", "order": 5}
      ]
    },
    "instrument_index": {
      "sheet_name": "Instrument Index",
      "columns": [
        {"field": "tag", "header": "Tag", "order": 1},
        {"field": "sub_class", "header": "Type", "order": 2},
        {"field": "fields.service", "header": "Service", "order": 3},
        {"field": "pid_number", "header": "Drawing", "order": 4}
      ]
    },
    "equipment_list": {
      "sheet_name": "Equipment List",
      "columns": [
        {"field": "tag", "header": "Tag", "order": 1},
        {"field": "sub_class", "header": "Type", "order": 2},
        {"field": "fields.duty", "header": "Service", "order": 3},
        {"field": "pid_number", "header": "Drawing", "order": 4}
      ]
    },
    "datasheet": {
      "columns": [
        {"field": "tag", "header": "Tag", "order": 1},
        {"field": "sub_class", "header": "Type", "order": 2},
        {"field": "fields.service", "header": "Service", "order": 3},
        {"field": "vendor_match.vendor_name", "header": "Mfg", "order": 4},
        {"field": "vendor_match.product_name", "header": "Model", "order": 5},
        {"field": "vendor_match.catalog_fields.accuracy", "header": "Accuracy", "order": 6}
      ]
    }
  }
}
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_customer_templates.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/customer_templates/ tests/unit/deliverables/test_customer_templates.py
git commit -m "feat(deliverables): default, ronesans, muk customer templates"
```

---

## Task 7: Template loader with caching

**Files:**
- Create: `webapp/deliverables/template_loader.py`
- Create: `tests/unit/deliverables/test_template_loader.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_template_loader.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_template_loader.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the loader**

Create `webapp/deliverables/template_loader.py`:

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_template_loader.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/template_loader.py tests/unit/deliverables/test_template_loader.py
git commit -m "feat(deliverables): template loader with caching + fallback"
```

---

## Task 8: Field-path resolver helper

**Files:**
- Create: `webapp/deliverables/field_resolver.py`
- Create: `tests/unit/deliverables/test_field_resolver.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_field_resolver.py`:

```python
from webapp.deliverables.canonical import CanonicalEntity, VendorMatch
from webapp.deliverables.field_resolver import resolve_field


def make_entity_with_vendor() -> CanonicalEntity:
    return CanonicalEntity(
        entity_id="33333333-3333-3333-3333-333333333333",
        entity_class="instrument",
        sub_class="PT",
        tag="PT-01018",
        pid_number="P-001",
        sheet_number=1,
        bbox=(0, 0, 10, 10),
        fields={"service": "Reactor outlet pressure", "signal_type": "4-20mA"},
        vendor_match=VendorMatch(
            vendor_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            vendor_name="Yokogawa",
            product_name="EJX130A",
            part_number="EJX130A-JMS5G-022NN",
            catalog_fields={"accuracy": "0.04%"},
        ),
    )


def test_resolve_simple_top_level():
    e = make_entity_with_vendor()
    assert resolve_field(e, "tag") == "PT-01018"


def test_resolve_dot_into_fields_dict():
    e = make_entity_with_vendor()
    assert resolve_field(e, "fields.service") == "Reactor outlet pressure"


def test_resolve_dot_into_nested_vendor_catalog():
    e = make_entity_with_vendor()
    assert resolve_field(e, "vendor_match.catalog_fields.accuracy") == "0.04%"


def test_resolve_missing_returns_empty_string():
    e = make_entity_with_vendor()
    assert resolve_field(e, "fields.material") == ""


def test_resolve_missing_vendor_returns_empty():
    e = CanonicalEntity(
        entity_id="44444444-4444-4444-4444-444444444444",
        entity_class="valve",
        sub_class="ball_valve",
        tag="BV-002",
        pid_number="P-001",
        sheet_number=1,
        bbox=(0, 0, 10, 10),
        fields={},
    )
    assert resolve_field(e, "vendor_match.vendor_name") == ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_field_resolver.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the resolver**

Create `webapp/deliverables/field_resolver.py`:

```python
"""Dot-notation field resolver for CanonicalEntity.

ColumnDef.field uses dot notation like 'fields.size' or
'vendor_match.catalog_fields.accuracy'. This helper walks the path
and returns the value as a string, or '' if any segment is missing.
"""

from typing import Any

from pydantic import BaseModel

from webapp.deliverables.canonical import CanonicalEntity


def resolve_field(entity: CanonicalEntity, path: str) -> str:
    parts = path.split(".")
    current: Any = entity
    for part in parts:
        if current is None:
            return ""
        if isinstance(current, BaseModel):
            current = getattr(current, part, None)
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return ""
    if current is None:
        return ""
    return str(current)
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_field_resolver.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/field_resolver.py tests/unit/deliverables/test_field_resolver.py
git commit -m "feat(deliverables): dot-notation field resolver"
```

---

## Task 9: Valve List CSV generator

**Files:**
- Create: `webapp/deliverables/valve_list.py`
- Create: `tests/unit/deliverables/test_valve_list.py`
- Create: `tests/unit/deliverables/fixtures/expected_valve_list_default.csv`
- Create: `tests/unit/deliverables/fixtures/expected_valve_list_ronesans.csv`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_valve_list.py`:

```python
import json
from pathlib import Path

from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.template_loader import TemplateLoader
from webapp.deliverables.valve_list import ValveListCSVGenerator

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_sample() -> JobCanonical:
    raw = json.loads((FIXTURE_DIR / "canonical_sample.json").read_text())
    return JobCanonical.model_validate(raw)


def test_valvelist_csv_default_template():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = ValveListCSVGenerator().generate(job, tpl)
    expected = (FIXTURE_DIR / "expected_valve_list_default.csv").read_bytes()
    assert out == expected


def test_valvelist_csv_ronesans_template():
    job = load_sample()
    tpl = TemplateLoader().load("ronesans")
    out = ValveListCSVGenerator().generate(job, tpl)
    expected = (FIXTURE_DIR / "expected_valve_list_ronesans.csv").read_bytes()
    assert out == expected


def test_valvelist_csv_filters_to_valves_only():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = ValveListCSVGenerator().generate(job, tpl).decode("utf-8")
    assert "GV-001" in out
    assert "BV-002" in out
    assert "PT-01018" not in out
    assert "V-101" not in out


def test_valvelist_csv_class_attrs():
    assert ValveListCSVGenerator.deliverable_type == "valve_list"
    assert ValveListCSVGenerator.file_format == "csv"
```

Create `tests/unit/deliverables/fixtures/expected_valve_list_default.csv` (use `\r\n` line endings — that's what Python's csv writer produces):

```
Tag,Type,Size,Service,Material,P&ID
GV-001,gate_valve,4in,Process Water,CS,P-001
BV-002,ball_valve,2in,Instrument Air,SS316,P-001
```

Create `tests/unit/deliverables/fixtures/expected_valve_list_ronesans.csv`:

```
Tag No.,Size,Valve Type,Service Description,Body Material,P&ID Ref.,Sheet
GV-001,4in,gate_valve,Process Water,CS,P-001,1
BV-002,2in,ball_valve,Instrument Air,SS316,P-001,1
```

Note: when you save these `.csv` fixture files, ensure they use `\r\n` (CRLF) line endings — Python's `csv.writer` defaults to that. The test reads bytes, so line endings must match exactly. In editors: VS Code → "CRLF" in status bar before saving.

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_valve_list.py -v`
Expected: FAIL — `ModuleNotFoundError: webapp.deliverables.valve_list`.

- [ ] **Step 3: Implement ValveListCSVGenerator**

Create `webapp/deliverables/valve_list.py`:

```python
"""Valve List deliverable generators (CSV + XLSX)."""

import csv
import io
from typing import ClassVar, List

from webapp.deliverables.base import Generator
from webapp.deliverables.canonical import CanonicalEntity, JobCanonical
from webapp.deliverables.field_resolver import resolve_field
from webapp.deliverables.registry import REGISTRY
from webapp.deliverables.template import DeliverableConfig, TemplateConfig


def _filter_valves(entities: List[CanonicalEntity]) -> List[CanonicalEntity]:
    return [e for e in entities if e.entity_class == "valve"]


def _ordered_columns(cfg: DeliverableConfig):
    return sorted(cfg.columns, key=lambda c: c.order)


class ValveListCSVGenerator(Generator):
    deliverable_type: ClassVar[str] = "valve_list"
    file_format: ClassVar[str] = "csv"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        deliv = template.deliverables["valve_list"]
        columns = _ordered_columns(deliv)
        valves = _filter_valves(canonical.entities)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([c.header for c in columns])
        for v in valves:
            writer.writerow([resolve_field(v, c.field) for c in columns])
        return buf.getvalue().encode("utf-8")


REGISTRY.register(ValveListCSVGenerator)
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_valve_list.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/valve_list.py tests/unit/deliverables/test_valve_list.py tests/unit/deliverables/fixtures/expected_valve_list_default.csv tests/unit/deliverables/fixtures/expected_valve_list_ronesans.csv
git commit -m "feat(deliverables): Valve List CSV generator + default/ronesans tests"
```

---

## Task 10: Valve List XLSX generator

**Files:**
- Modify: `webapp/deliverables/valve_list.py` (add ValveListXLSXGenerator)
- Modify: `tests/unit/deliverables/test_valve_list.py` (add XLSX tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/deliverables/test_valve_list.py`:

```python
import openpyxl

from webapp.deliverables.valve_list import ValveListXLSXGenerator


def test_valvelist_xlsx_default_template():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out_bytes = ValveListXLSXGenerator().generate(job, tpl)
    wb = openpyxl.load_workbook(io.BytesIO(out_bytes))
    ws = wb["Valve List"]
    headers = [c.value for c in ws[1]]
    assert headers == ["Tag", "Type", "Size", "Service", "Material", "P&ID"]
    row2 = [c.value for c in ws[2]]
    assert row2 == ["GV-001", "gate_valve", "4in", "Process Water", "CS", "P-001"]


def test_valvelist_xlsx_uses_ronesans_sheet_name():
    job = load_sample()
    tpl = TemplateLoader().load("ronesans")
    out_bytes = ValveListXLSXGenerator().generate(job, tpl)
    wb = openpyxl.load_workbook(io.BytesIO(out_bytes))
    assert "VALVE LIST" in wb.sheetnames


def test_valvelist_xlsx_class_attrs():
    assert ValveListXLSXGenerator.deliverable_type == "valve_list"
    assert ValveListXLSXGenerator.file_format == "xlsx"
```

Add `import io` near the top of the file if not already present.

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_valve_list.py -v`
Expected: FAIL — `ImportError: cannot import name 'ValveListXLSXGenerator'`.

- [ ] **Step 3: Add the XLSX generator**

Append to `webapp/deliverables/valve_list.py`:

```python
import io as _io  # avoid shadowing local 'io' usage in functions

from openpyxl import Workbook
from openpyxl.styles import Font


class ValveListXLSXGenerator(Generator):
    deliverable_type: ClassVar[str] = "valve_list"
    file_format: ClassVar[str] = "xlsx"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        deliv = template.deliverables["valve_list"]
        columns = _ordered_columns(deliv)
        valves = _filter_valves(canonical.entities)
        wb = Workbook()
        ws = wb.active
        ws.title = deliv.sheet_name or "Valve List"
        ws.append([c.header for c in columns])
        header_font = Font(name=deliv.font, bold=True)
        for cell in ws[1]:
            cell.font = header_font
        for v in valves:
            ws.append([resolve_field(v, c.field) for c in columns])
        buf = _io.BytesIO()
        wb.save(buf)
        return buf.getvalue()


REGISTRY.register(ValveListXLSXGenerator)
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_valve_list.py -v`
Expected: 7 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/valve_list.py tests/unit/deliverables/test_valve_list.py
git commit -m "feat(deliverables): Valve List XLSX generator"
```

---

## Task 11: Instrument Index CSV + XLSX generators

**Files:**
- Create: `webapp/deliverables/instrument_index.py`
- Create: `tests/unit/deliverables/test_instrument_index.py`
- Create: `tests/unit/deliverables/fixtures/expected_instrument_index_default.csv`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_instrument_index.py`:

```python
import io
import json
from pathlib import Path

import openpyxl

from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.instrument_index import (
    InstrumentIndexCSVGenerator,
    InstrumentIndexXLSXGenerator,
)
from webapp.deliverables.template_loader import TemplateLoader

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_sample() -> JobCanonical:
    raw = json.loads((FIXTURE_DIR / "canonical_sample.json").read_text())
    return JobCanonical.model_validate(raw)


def test_instrumentindex_csv_default():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = InstrumentIndexCSVGenerator().generate(job, tpl)
    expected = (FIXTURE_DIR / "expected_instrument_index_default.csv").read_bytes()
    assert out == expected


def test_instrumentindex_filters_to_instruments():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = InstrumentIndexCSVGenerator().generate(job, tpl).decode("utf-8")
    assert "PT-01018" in out
    assert "GV-001" not in out
    assert "V-101" not in out


def test_instrumentindex_xlsx_sheet_name():
    job = load_sample()
    tpl = TemplateLoader().load("ronesans")
    out_bytes = InstrumentIndexXLSXGenerator().generate(job, tpl)
    wb = openpyxl.load_workbook(io.BytesIO(out_bytes))
    assert "INSTRUMENT INDEX" in wb.sheetnames


def test_instrumentindex_class_attrs():
    assert InstrumentIndexCSVGenerator.deliverable_type == "instrument_index"
    assert InstrumentIndexCSVGenerator.file_format == "csv"
    assert InstrumentIndexXLSXGenerator.file_format == "xlsx"
```

Create `tests/unit/deliverables/fixtures/expected_instrument_index_default.csv` (CRLF line endings):

```
Tag,Type,Service,Signal,P&ID
PT-01018,PT,Reactor outlet pressure,4-20mA HART,P-001
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_instrument_index.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement instrument_index.py**

Create `webapp/deliverables/instrument_index.py`:

```python
"""Instrument Index deliverable generators (CSV + XLSX)."""

import csv
import io
from typing import ClassVar, List

from openpyxl import Workbook
from openpyxl.styles import Font

from webapp.deliverables.base import Generator
from webapp.deliverables.canonical import CanonicalEntity, JobCanonical
from webapp.deliverables.field_resolver import resolve_field
from webapp.deliverables.registry import REGISTRY
from webapp.deliverables.template import DeliverableConfig, TemplateConfig


def _filter_instruments(entities: List[CanonicalEntity]) -> List[CanonicalEntity]:
    return [e for e in entities if e.entity_class == "instrument"]


def _ordered_columns(cfg: DeliverableConfig):
    return sorted(cfg.columns, key=lambda c: c.order)


class InstrumentIndexCSVGenerator(Generator):
    deliverable_type: ClassVar[str] = "instrument_index"
    file_format: ClassVar[str] = "csv"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        deliv = template.deliverables["instrument_index"]
        columns = _ordered_columns(deliv)
        instruments = _filter_instruments(canonical.entities)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([c.header for c in columns])
        for e in instruments:
            writer.writerow([resolve_field(e, c.field) for c in columns])
        return buf.getvalue().encode("utf-8")


class InstrumentIndexXLSXGenerator(Generator):
    deliverable_type: ClassVar[str] = "instrument_index"
    file_format: ClassVar[str] = "xlsx"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        deliv = template.deliverables["instrument_index"]
        columns = _ordered_columns(deliv)
        instruments = _filter_instruments(canonical.entities)
        wb = Workbook()
        ws = wb.active
        ws.title = deliv.sheet_name or "Instrument Index"
        ws.append([c.header for c in columns])
        header_font = Font(name=deliv.font, bold=True)
        for cell in ws[1]:
            cell.font = header_font
        for e in instruments:
            ws.append([resolve_field(e, c.field) for c in columns])
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()


REGISTRY.register(InstrumentIndexCSVGenerator)
REGISTRY.register(InstrumentIndexXLSXGenerator)
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_instrument_index.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/instrument_index.py tests/unit/deliverables/test_instrument_index.py tests/unit/deliverables/fixtures/expected_instrument_index_default.csv
git commit -m "feat(deliverables): Instrument Index CSV + XLSX generators"
```

---

## Task 12: Equipment List XLSX generator

**Files:**
- Create: `webapp/deliverables/equipment_list.py`
- Create: `tests/unit/deliverables/test_equipment_list.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_equipment_list.py`:

```python
import io
import json
from pathlib import Path

import openpyxl

from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.equipment_list import EquipmentListXLSXGenerator
from webapp.deliverables.template_loader import TemplateLoader

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_sample() -> JobCanonical:
    raw = json.loads((FIXTURE_DIR / "canonical_sample.json").read_text())
    return JobCanonical.model_validate(raw)


def test_equipmentlist_xlsx_default():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out_bytes = EquipmentListXLSXGenerator().generate(job, tpl)
    wb = openpyxl.load_workbook(io.BytesIO(out_bytes))
    ws = wb["Equipment List"]
    headers = [c.value for c in ws[1]]
    assert headers == ["Tag", "Type", "Duty", "Volume", "P&ID"]
    row2 = [c.value for c in ws[2]]
    assert row2 == ["V-101", "vessel", "Reactor", "12 m3", "P-001"]


def test_equipmentlist_filters_to_equipment():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out_bytes = EquipmentListXLSXGenerator().generate(job, tpl)
    wb = openpyxl.load_workbook(io.BytesIO(out_bytes))
    ws = wb["Equipment List"]
    tags = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]
    assert "V-101" in tags
    assert "GV-001" not in tags
    assert "PT-01018" not in tags


def test_equipmentlist_class_attrs():
    assert EquipmentListXLSXGenerator.deliverable_type == "equipment_list"
    assert EquipmentListXLSXGenerator.file_format == "xlsx"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_equipment_list.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement equipment_list.py**

Create `webapp/deliverables/equipment_list.py`:

```python
"""Equipment List deliverable generator (XLSX)."""

import io
from typing import ClassVar, List

from openpyxl import Workbook
from openpyxl.styles import Font

from webapp.deliverables.base import Generator
from webapp.deliverables.canonical import CanonicalEntity, JobCanonical
from webapp.deliverables.field_resolver import resolve_field
from webapp.deliverables.registry import REGISTRY
from webapp.deliverables.template import DeliverableConfig, TemplateConfig


def _filter_equipment(entities: List[CanonicalEntity]) -> List[CanonicalEntity]:
    return [e for e in entities if e.entity_class == "equipment"]


def _ordered_columns(cfg: DeliverableConfig):
    return sorted(cfg.columns, key=lambda c: c.order)


class EquipmentListXLSXGenerator(Generator):
    deliverable_type: ClassVar[str] = "equipment_list"
    file_format: ClassVar[str] = "xlsx"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        deliv = template.deliverables["equipment_list"]
        columns = _ordered_columns(deliv)
        equipment = _filter_equipment(canonical.entities)
        wb = Workbook()
        ws = wb.active
        ws.title = deliv.sheet_name or "Equipment List"
        ws.append([c.header for c in columns])
        header_font = Font(name=deliv.font, bold=True)
        for cell in ws[1]:
            cell.font = header_font
        for e in equipment:
            ws.append([resolve_field(e, c.field) for c in columns])
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()


REGISTRY.register(EquipmentListXLSXGenerator)
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_equipment_list.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/equipment_list.py tests/unit/deliverables/test_equipment_list.py
git commit -m "feat(deliverables): Equipment List XLSX generator"
```

---

## Task 13: Datasheet PDF generator

**Files:**
- Create: `webapp/deliverables/datasheet.py`
- Create: `tests/unit/deliverables/test_datasheet.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_datasheet.py`:

```python
import io
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.datasheet import DatasheetPDFGenerator
from webapp.deliverables.template_loader import TemplateLoader

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_sample() -> JobCanonical:
    raw = json.loads((FIXTURE_DIR / "canonical_sample.json").read_text())
    return JobCanonical.model_validate(raw)


def extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_datasheet_pdf_contains_instrument_tag():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = DatasheetPDFGenerator().generate(job, tpl)
    text = extract_text(out)
    assert "PT-01018" in text
    assert "Yokogawa" in text
    assert "EJX130A" in text
    assert "0.04%" in text


def test_datasheet_pdf_one_page_per_instrument():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = DatasheetPDFGenerator().generate(job, tpl)
    reader = PdfReader(io.BytesIO(out))
    instrument_count = sum(1 for e in job.entities if e.entity_class == "instrument")
    assert len(reader.pages) == instrument_count


def test_datasheet_pdf_starts_with_pdf_magic():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = DatasheetPDFGenerator().generate(job, tpl)
    assert out[:4] == b"%PDF"


def test_datasheet_class_attrs():
    assert DatasheetPDFGenerator.deliverable_type == "datasheet"
    assert DatasheetPDFGenerator.file_format == "pdf"
```

Add `pypdf>=4.0.0,<5.0.0` to `requirements-webapp.txt` (used only in tests, but easier to share with the runtime image than to maintain a separate test-only requirements file). Run `docker compose build web` again before continuing.

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_datasheet.py -v`
Expected: FAIL — `webapp.deliverables.datasheet` not found.

- [ ] **Step 3: Implement DatasheetPDFGenerator**

Create `webapp/deliverables/datasheet.py`:

```python
"""Instrument Datasheet deliverable generator (PDF).

One A4 page per instrument. Each page renders the column list defined in
the template's 'datasheet' section as a two-column 'Field / Value' table.
"""

import io
from typing import ClassVar, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from webapp.deliverables.base import Generator
from webapp.deliverables.canonical import CanonicalEntity, JobCanonical
from webapp.deliverables.field_resolver import resolve_field
from webapp.deliverables.registry import REGISTRY
from webapp.deliverables.template import DeliverableConfig, TemplateConfig


def _filter_instruments(entities: List[CanonicalEntity]) -> List[CanonicalEntity]:
    return [e for e in entities if e.entity_class == "instrument"]


def _ordered_columns(cfg: DeliverableConfig):
    return sorted(cfg.columns, key=lambda c: c.order)


class DatasheetPDFGenerator(Generator):
    deliverable_type: ClassVar[str] = "datasheet"
    file_format: ClassVar[str] = "pdf"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        deliv = template.deliverables["datasheet"]
        columns = _ordered_columns(deliv)
        instruments = _filter_instruments(canonical.entities)

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )
        styles = getSampleStyleSheet()
        story = []

        for idx, instr in enumerate(instruments):
            tag = instr.tag or instr.sub_class
            story.append(Paragraph(
                f"Instrument Datasheet — {tag}",
                styles["Title"],
            ))
            story.append(Spacer(1, 0.5 * cm))
            table_data = [["Field", "Value"]]
            for col in columns:
                value = resolve_field(instr, col.field)
                table_data.append([col.header, value])
            table = Table(table_data, colWidths=[6 * cm, 10 * cm])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(table)
            if idx < len(instruments) - 1:
                story.append(PageBreak())

        doc.build(story)
        return buf.getvalue()


REGISTRY.register(DatasheetPDFGenerator)
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_datasheet.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/datasheet.py tests/unit/deliverables/test_datasheet.py requirements-webapp.txt
git commit -m "feat(deliverables): Datasheet PDF generator (reportlab)"
```

---

## Task 14: Generator package-level import (auto-register all generators)

**Files:**
- Modify: `webapp/deliverables/__init__.py`
- Create: `tests/unit/deliverables/test_package_init.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_package_init.py`:

```python
import webapp.deliverables  # noqa: F401  (triggers all imports)

from webapp.deliverables.registry import REGISTRY


def test_all_generators_registered():
    assert REGISTRY.resolve("valve_list", "csv").__name__ == "ValveListCSVGenerator"
    assert REGISTRY.resolve("valve_list", "xlsx").__name__ == "ValveListXLSXGenerator"
    assert REGISTRY.resolve("instrument_index", "csv").__name__ == "InstrumentIndexCSVGenerator"
    assert REGISTRY.resolve("instrument_index", "xlsx").__name__ == "InstrumentIndexXLSXGenerator"
    assert REGISTRY.resolve("equipment_list", "xlsx").__name__ == "EquipmentListXLSXGenerator"
    assert REGISTRY.resolve("datasheet", "pdf").__name__ == "DatasheetPDFGenerator"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_package_init.py -v`
Expected: FAIL — `UnknownGenerator: valve_list/csv` (because nothing has imported the generator modules yet).

- [ ] **Step 3: Replace the empty __init__.py with explicit imports**

Replace the contents of `webapp/deliverables/__init__.py` with:

```python
"""Deliverables subsystem — generators + customer templates.

Importing this package registers all generators in REGISTRY. The router
imports this package once at startup so the registry is populated.
"""

from webapp.deliverables import datasheet  # noqa: F401
from webapp.deliverables import equipment_list  # noqa: F401
from webapp.deliverables import instrument_index  # noqa: F401
from webapp.deliverables import valve_list  # noqa: F401
from webapp.deliverables.registry import REGISTRY  # noqa: F401
```

- [ ] **Step 4: Run the test**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_package_init.py -v`
Expected: PASS.

Also re-run the whole deliverables suite to confirm nothing broke:

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/ -v`
Expected: all previous tests still PASS (count: ≥ 30).

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/__init__.py tests/unit/deliverables/test_package_init.py
git commit -m "feat(deliverables): auto-register all generators on package import"
```

---

## Task 15: Job-canonical loader (reads canonical JSON from job_outputs)

**Files:**
- Create: `webapp/deliverables/job_loader.py`
- Create: `tests/unit/deliverables/test_job_loader.py`

The canonical JSON is what the pipeline writes to disk alongside the existing `valve_list.csv`. In MVP it lives at `job_outputs/{org_id}/{job_id}/canonical.json` (jobs ≥ 40) or `job_outputs/{job_id}/canonical.json` (legacy jobs ≤ 39). The path comes from the existing `Job.output_csv_path` row in Postgres — replace the basename `valve_list.csv` with `canonical.json`.

For Plan A, we do NOT write canonical.json from the pipeline (that's a separate plan covering pipeline-side changes). For now the loader just reads the file if it exists. A future plan adds pipeline-side writing.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_job_loader.py`:

```python
import json
from pathlib import Path

import pytest

from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.job_loader import (
    JobCanonicalNotFound,
    canonical_path_for_job,
    load_canonical_for_job,
)


def test_canonical_path_orgscoped(tmp_path):
    csv_path = tmp_path / "12" / "41" / "valve_list.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("")
    assert canonical_path_for_job(str(csv_path)) == str(csv_path.parent / "canonical.json")


def test_canonical_path_legacy(tmp_path):
    csv_path = tmp_path / "33" / "valve_list.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("")
    assert canonical_path_for_job(str(csv_path)) == str(csv_path.parent / "canonical.json")


def test_load_canonical_missing(tmp_path):
    csv_path = tmp_path / "1" / "valve_list.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("")
    with pytest.raises(JobCanonicalNotFound):
        load_canonical_for_job(str(csv_path))


def test_load_canonical_present(tmp_path):
    csv_path = tmp_path / "1" / "valve_list.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("")
    canonical = {
        "job_id": 1,
        "canonical_schema_version": "1.0.0",
        "customer_template_slug": "default",
        "entities": [],
    }
    (csv_path.parent / "canonical.json").write_text(json.dumps(canonical))
    result = load_canonical_for_job(str(csv_path))
    assert isinstance(result, JobCanonical)
    assert result.job_id == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_job_loader.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement job_loader.py**

Create `webapp/deliverables/job_loader.py`:

```python
"""Locate and load the canonical JSON for a job, alongside its CSV output."""

import json
import os
from pathlib import Path

from webapp.deliverables.canonical import JobCanonical


class JobCanonicalNotFound(FileNotFoundError):
    pass


def canonical_path_for_job(output_csv_path: str) -> str:
    """Map a job's existing output_csv_path to its canonical.json sibling."""
    parent = Path(output_csv_path).parent
    return str(parent / "canonical.json")


def load_canonical_for_job(output_csv_path: str) -> JobCanonical:
    """Load and parse canonical.json that sits next to the job's CSV output.

    Raises JobCanonicalNotFound if the file does not exist.
    """
    path = canonical_path_for_job(output_csv_path)
    if not os.path.exists(path):
        raise JobCanonicalNotFound(path)
    raw = json.loads(Path(path).read_text())
    return JobCanonical.model_validate(raw)
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_job_loader.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/job_loader.py tests/unit/deliverables/test_job_loader.py
git commit -m "feat(deliverables): job canonical-JSON loader (reads from job_outputs)"
```

---

## Task 16: Export storage helper

**Files:**
- Create: `webapp/deliverables/storage.py`
- Create: `tests/unit/deliverables/test_storage.py`

Generated files are written next to the job's existing artefacts at `{job_output_dir}/exports/{deliverable_type}.{ext}`. The download URL is served from the existing `/api/jobs/{id}/files/...` route.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deliverables/test_storage.py`:

```python
from pathlib import Path

from webapp.deliverables.storage import store_export


def test_store_export_writes_file_to_exports_subdir(tmp_path):
    csv_path = tmp_path / "42" / "valve_list.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("")

    out_path = store_export(
        output_csv_path=str(csv_path),
        deliverable_type="valve_list",
        file_format="xlsx",
        content=b"\x50\x4b\x03\x04PK fake xlsx",
    )

    assert Path(out_path).exists()
    assert Path(out_path).read_bytes() == b"\x50\x4b\x03\x04PK fake xlsx"
    assert Path(out_path).name == "valve_list.xlsx"
    assert Path(out_path).parent.name == "exports"


def test_store_export_overwrites_existing(tmp_path):
    csv_path = tmp_path / "42" / "valve_list.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("")

    store_export(str(csv_path), "valve_list", "csv", b"first")
    out_path = store_export(str(csv_path), "valve_list", "csv", b"second")

    assert Path(out_path).read_bytes() == b"second"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_storage.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement storage.py**

Create `webapp/deliverables/storage.py`:

```python
"""Persist generated deliverables to disk alongside job outputs."""

from pathlib import Path


def store_export(
    output_csv_path: str,
    deliverable_type: str,
    file_format: str,
    content: bytes,
) -> str:
    """Write `content` to {job_dir}/exports/{deliverable_type}.{file_format}.

    Returns the absolute path of the written file. Creates the exports/
    directory if missing. Overwrites any existing file of the same name.
    """
    job_dir = Path(output_csv_path).parent
    exports_dir = job_dir / "exports"
    exports_dir.mkdir(exist_ok=True)
    out_path = exports_dir / f"{deliverable_type}.{file_format}"
    out_path.write_bytes(content)
    return str(out_path)
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/test_storage.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webapp/deliverables/storage.py tests/unit/deliverables/test_storage.py
git commit -m "feat(deliverables): file storage helper alongside job_outputs"
```

---

## Task 17: FastAPI router — POST /api/jobs/{id}/export/{deliverable}/{format}

**Files:**
- Create: `webapp/routers/exports.py`
- Modify: `webapp/main.py` (register router)
- Create: `tests/e2e/test_exports_api.py`

The endpoint:
1. Loads the Job row from Postgres by `job_id` (404 if missing).
2. Loads `canonical.json` from the job output directory (404 if missing — the pipeline must have written it first; for now we test by writing canonical.json by hand into the fixture job dir).
3. Loads the customer template for the canonical's `customer_template_slug`, falling back to "default".
4. Resolves the generator from REGISTRY (400 if `deliverable_type/file_format` is unknown).
5. Calls `generator.generate(canonical, template)` to produce bytes.
6. Stores via `store_export(...)` and returns the file directly as a download response.

For the E2E test we'll use the existing webapp test infrastructure (`tests/e2e/`). Inspect `tests/conftest.py` and `tests/e2e/` to see existing fixtures before writing the test — pattern-match.

- [ ] **Step 1: Inspect existing E2E fixtures**

Run: `docker compose exec web ls tests/e2e/`
Run: `docker compose exec web cat tests/conftest.py`

Note the existing fixtures (TestClient, DB session, fixture job creation). You will reuse them in step 2.

- [ ] **Step 2: Write the failing E2E test**

Create `tests/e2e/test_exports_api.py`. The skeleton below uses the conventions from your existing `tests/e2e/` files — adjust fixture names if the existing pattern differs.

```python
import json
from pathlib import Path

import pytest


@pytest.fixture
def job_with_canonical(tmp_path, db_session, test_client):
    """Create a Job row + write canonical.json into its output dir."""
    from webapp.models import Job

    job_dir = tmp_path / "1"
    job_dir.mkdir()
    csv_path = job_dir / "valve_list.csv"
    csv_path.write_text("")
    canonical = {
        "job_id": 9999,
        "canonical_schema_version": "1.0.0",
        "customer_template_slug": "default",
        "entities": [
            {
                "entity_id": "11111111-1111-1111-1111-111111111111",
                "entity_class": "valve",
                "sub_class": "gate_valve",
                "tag": "GV-001",
                "pid_number": "P-001",
                "sheet_number": 1,
                "bbox": [0, 0, 10, 10],
                "fields": {"size": "4in", "service": "Process Water", "material": "CS"},
            }
        ],
    }
    (job_dir / "canonical.json").write_text(json.dumps(canonical))

    job = Job(id=9999, output_csv_path=str(csv_path))
    db_session.add(job)
    db_session.commit()
    yield job


def test_export_valve_list_csv(test_client, job_with_canonical):
    response = test_client.post(f"/api/jobs/{job_with_canonical.id}/export/valve_list/csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    body = response.content.decode("utf-8")
    assert "GV-001" in body
    assert "Process Water" in body


def test_export_valve_list_xlsx(test_client, job_with_canonical):
    response = test_client.post(f"/api/jobs/{job_with_canonical.id}/export/valve_list/xlsx")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    assert response.content[:2] == b"PK"  # ZIP magic — xlsx is a ZIP


def test_export_unknown_deliverable_returns_400(test_client, job_with_canonical):
    response = test_client.post(f"/api/jobs/{job_with_canonical.id}/export/unknown/csv")
    assert response.status_code == 400


def test_export_unknown_job_returns_404(test_client):
    response = test_client.post("/api/jobs/999999/export/valve_list/csv")
    assert response.status_code == 404


def test_export_job_without_canonical_returns_404(test_client, db_session, tmp_path):
    from webapp.models import Job

    job_dir = tmp_path / "no_canonical"
    job_dir.mkdir()
    csv_path = job_dir / "valve_list.csv"
    csv_path.write_text("")
    job = Job(id=9998, output_csv_path=str(csv_path))
    db_session.add(job)
    db_session.commit()
    response = test_client.post(f"/api/jobs/{job.id}/export/valve_list/csv")
    assert response.status_code == 404
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `docker compose exec web python3 -m pytest tests/e2e/test_exports_api.py -v`
Expected: FAIL — `404 not found` for the new endpoint (because router doesn't exist yet).

- [ ] **Step 4: Implement the router and register it**

Create `webapp/routers/exports.py`:

```python
"""POST /api/jobs/{job_id}/export/{deliverable_type}/{file_format}

Generates and returns one customer deliverable for one job.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from webapp.database import get_db
from webapp.deliverables.job_loader import (
    JobCanonicalNotFound,
    load_canonical_for_job,
)
from webapp.deliverables.registry import REGISTRY, UnknownGenerator
from webapp.deliverables.storage import store_export
from webapp.deliverables.template_loader import TemplateLoader
from webapp.models import Job

router = APIRouter(prefix="/api/jobs", tags=["exports"])

_loader = TemplateLoader()


CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


@router.post(
    "/{job_id}/export/{deliverable_type}/{file_format}",
    responses={
        200: {"description": "Deliverable bytes"},
        400: {"description": "Unknown deliverable type or format"},
        404: {"description": "Job or canonical.json not found"},
    },
)
def export_deliverable(
    job_id: int,
    deliverable_type: str,
    file_format: str,
    db: Session = Depends(get_db),
) -> Response:
    job: Optional[Job] = db.get(Job, job_id)
    if job is None or not job.output_csv_path:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")

    try:
        canonical = load_canonical_for_job(job.output_csv_path)
    except JobCanonicalNotFound:
        raise HTTPException(
            status_code=404,
            detail=f"canonical.json missing for job {job_id}",
        )

    try:
        generator_cls = REGISTRY.resolve(deliverable_type, file_format)
    except UnknownGenerator:
        raise HTTPException(
            status_code=400,
            detail=f"unknown deliverable: {deliverable_type}/{file_format}",
        )

    template = _loader.load_with_fallback(canonical.customer_template_slug)
    content = generator_cls().generate(canonical, template)

    store_export(job.output_csv_path, deliverable_type, file_format, content)

    media_type = CONTENT_TYPES.get(file_format, "application/octet-stream")
    filename = f"{deliverable_type}.{file_format}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

Modify `webapp/main.py` to register the router. Read the file first to find the right location:

Run: `docker compose exec web grep -n "include_router\|app = FastAPI" webapp/main.py`

Pattern-match on the existing `app.include_router(...)` calls. Add after the last one:

```python
from webapp.routers import exports as exports_router

app.include_router(exports_router.router)
```

Also ensure `webapp.deliverables` is imported once at startup so the registry populates. Add near the other imports at the top:

```python
import webapp.deliverables  # noqa: F401 — populates generator registry
```

- [ ] **Step 5: Run the tests and commit**

Run: `docker compose exec web python3 -m pytest tests/e2e/test_exports_api.py -v`
Expected: 5 PASSED.

Then run the full deliverables suite + the new E2E to make sure nothing regressed:

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/ tests/e2e/test_exports_api.py -v`
Expected: all green.

```bash
git add webapp/routers/exports.py webapp/main.py tests/e2e/test_exports_api.py
git commit -m "feat(deliverables): POST /api/jobs/{id}/export/{type}/{format} endpoint"
```

---

## Task 18: Document the subsystem

**Files:**
- Create: `docs/claude/deliverables.md`
- Modify: `CLAUDE.md` (add to Detail Index)
- Modify: `FEATURES.md` (append entry)

- [ ] **Step 1: Write the doc**

Create `docs/claude/deliverables.md`:

```markdown
# Deliverables subsystem

The `webapp/deliverables/` package generates customer-facing files (Valve
List CSV/XLSX, Instrument Index CSV/XLSX, Equipment List XLSX, Instrument
Datasheet PDF) from the pipeline's internal canonical JSON.

## Architecture

- `canonical.py` — Pydantic models for the pipeline's output. `JobCanonical`
  is the single contract between the extraction pipeline and the
  generators. Schema version is pinned at `CANONICAL_SCHEMA_VERSION =
  "1.0.0"`. Bumping it is a `FEATURES.md` entry of type `architecture`.
- `template.py` — Pydantic models for per-customer JSON templates.
- `customer_templates/*.json` — One JSON file per customer (`default`,
  `ronesans`, `muk`, …). Adding a new customer = one file, no code.
- `base.py` — Abstract `Generator` base class.
- `registry.py` — Maps `(deliverable_type, file_format)` -> `Generator`
  subclass. Module-level `REGISTRY` is populated at import time.
- `field_resolver.py` — Dot-notation field reader for `CanonicalEntity`.
- `template_loader.py` — Loads + caches customer JSON templates.
- `job_loader.py` — Reads `canonical.json` from the job output directory.
- `storage.py` — Persists generated files to `{job_dir}/exports/`.
- Concrete generators: `valve_list.py`, `instrument_index.py`,
  `equipment_list.py`, `datasheet.py`.

## Endpoint

`POST /api/jobs/{job_id}/export/{deliverable_type}/{file_format}` →
returns the deliverable bytes with the appropriate `Content-Type` +
`Content-Disposition: attachment` header. Also persists the file at
`{job_output_dir}/exports/{deliverable_type}.{file_format}`.

Returns 404 if job or canonical.json missing; 400 if the deliverable
type or format is unknown.

## Adding a new customer

1. Copy `webapp/deliverables/customer_templates/default.json` to
   `{customer_slug}.json`.
2. Edit columns/headers/sheet names per the EPC's preferred output.
3. The pipeline writes `customer_template_slug` into `canonical.json`
   when the job is run for that customer's project.
4. No code changes required.

## Adding a new deliverable type

1. Add the entity-class filter and one or more generators in a new
   module under `webapp/deliverables/`.
2. Register each new generator in the module body via
   `REGISTRY.register(...)`.
3. Import the new module from `webapp/deliverables/__init__.py`.
4. Add a `deliverables.{new_type}` section to each
   `customer_templates/*.json` file (or rely on `default.json` only).
5. Write tests under `tests/unit/deliverables/`.

## Adding a new file format for an existing deliverable

1. Add a new `Generator` subclass in the same module as the existing
   format (e.g. add `ValveListPDFGenerator` next to the CSV/XLSX classes).
2. Register it; the registry distinguishes by `(deliverable_type,
   file_format)`.

## Tests

- Unit: `tests/unit/deliverables/`
- E2E: `tests/e2e/test_exports_api.py`

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/
tests/e2e/test_exports_api.py -v`
```

- [ ] **Step 2: Add to CLAUDE.md detail index**

Modify `CLAUDE.md`. Find the section starting with `## Detail Index` and add a new bullet under it:

```markdown
- [`docs/claude/deliverables.md`](docs/claude/deliverables.md) — Deliverables subsystem (Valve List / Instrument Index / Equipment List / Datasheet generators + per-customer templates)
```

- [ ] **Step 3: Append a FEATURES.md entry**

Add a new entry at the top of the entries list in `FEATURES.md` (after the header / format block, before #08):

```markdown
## [YYYY-MM-DD] #09 — Deliverables subsystem shipped (Valve List / Instrument Index / Equipment List / Datasheet generators + per-customer templates)

**Type:** feature
**Stage:** webapp, export
**Status:** shipped

**Why:** Per `docs/decisions/01-qong-studio-mvp-design.md` Plan A. The MVP
customer experience hinges on four deliverables in per-EPC templates;
this subsystem is the production path for all four.

**What:** `webapp/deliverables/` package — Pydantic canonical schema
(v1.0.0), per-customer JSON template format, generator registry, four
concrete generators (Valve List CSV/XLSX, Instrument Index CSV/XLSX,
Equipment List XLSX, Datasheet PDF) and the `POST /api/jobs/{id}/export/
{type}/{format}` endpoint. Three customer templates landed: default,
ronesans, muk. Pipeline-side `canonical.json` writing is intentionally
out of scope for this plan — a follow-up plan will wire the extraction
pipeline to emit canonical.json next to valve_list.csv.

**Result:** End-to-end test passes: given a hand-crafted canonical.json
fixture, the endpoint returns valid CSV/XLSX/PDF in the expected
template. ~33 unit tests + 5 E2E tests, all green.

**Notes:** Replace `YYYY-MM-DD` above with today's date when this commit
lands. The customer_template_slug "default" is the fallback; jobs whose
project sets no template still produce a usable deliverable.
```

Set the date to whatever today is when this commit actually lands. (Run
`date +%Y-%m-%d` before editing.)

- [ ] **Step 4: Confirm no doc broke**

Run: `docker compose exec web python3 -m pytest tests/unit/deliverables/ tests/e2e/test_exports_api.py -v`
Expected: all green (no code change in this task; just regression check).

- [ ] **Step 5: Commit**

```bash
git add docs/claude/deliverables.md CLAUDE.md FEATURES.md
git commit -m "docs(deliverables): subsystem docs + CLAUDE.md index + FEATURES.md #09"
```

---

## Final task: Full-suite smoke test + push

- [ ] **Step 1: Run the full repo test suite to confirm no regression**

Run: `docker compose exec web python3 -m pytest tests/unit/ tests/e2e/ -v`
Expected: all green (previous tests + ~38 new tests added in this plan).

- [ ] **Step 2: Push the branch**

```bash
git push origin feature/digital-twin
```

- [ ] **Step 3: Update SESSION_STATE.md**

Open `SESSION_STATE.md` and overwrite per the project convention. Record:
- What this session shipped: Plan A complete (18 tasks)
- Where to resume: Plan B (Qong Studio review canvas) is the natural next plan.
- Open carry-over: the pipeline doesn't yet write `canonical.json` — that lands in a follow-up plan (Plan A.5) before Plan A becomes useful to real customers.

- [ ] **Step 4: Final commit**

```bash
git add SESSION_STATE.md
git commit -m "chore(session): handoff after Plan A (deliverables subsystem)"
git push origin feature/digital-twin
```

---

## Self-review (run before declaring plan complete)

1. **Spec coverage:** Plan A covers spec §3 (deliverables) + §4.1 (architecture: deliverable generators + customer templates) + §4.4 (per-customer template engine, deliverable export buttons). The pipeline-side write of `canonical.json` is explicitly deferred to a follow-up plan and called out. ✅
2. **Placeholder scan:** All test code is shown in full. All file paths are exact. No "TBD", "TODO", "implement later", or "similar to Task N". The one `YYYY-MM-DD` placeholder in Task 18's FEATURES.md entry is explicitly instructed to be replaced with the current date. ✅
3. **Type consistency:** `Generator.deliverable_type` / `file_format` as ClassVar[str] used consistently. `JobCanonical.entities` / `CanonicalEntity.entity_class` consistent. `REGISTRY.resolve(deliverable_type, file_format)` signature consistent. ✅
4. **Ambiguity check:** CSV fixture line-ending requirement called out (CRLF). `canonical_path_for_job` semantics tested for both org-scoped (jobs ≥ 40) and legacy (jobs ≤ 39) layouts. Generator behaviour on missing fields specified by `field_resolver` returning `""`. ✅

Plan is complete.
