# Deliverables subsystem

The `webapp/deliverables/` package generates customer-facing files (Valve
List CSV/XLSX, Instrument Index CSV/XLSX, Equipment List XLSX, Instrument
Datasheet XLSX) from the pipeline's internal canonical JSON.

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

`POST /api/v1/jobs/{job_id}/export/{deliverable_type}/{file_format}` →
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
