# Unified Symbol Taxonomy + Label Triage — Design

**Date:** 2026-06-16
**Status:** Draft for review
**Track:** team (`dev`-line feature; build on a local branch first per current testing policy)

## Problem

The same set of P&ID symbol classes is currently defined in **seven** independent
places, with no single source of truth and no path for a newly-annotated Label
Studio (LS) label to flow back into the app:

| # | List | File | Shape |
|---|------|------|-------|
| 1 | YOLO classes (23) | `webapp/inference.py:65-92` | ordered Python list (index = model channel) |
| 2 | LS label config (23) | `scripts/ls_label_config.xml` | XML `<RectangleLabels>` + colors |
| 3 | Palette swatches (26) | `webapp/frontend/src/studio/paletteColors.ts:28-61` | `entity_class → [{sub, color}]` |
| 4 | Glyph kinds (34) | `webapp/frontend/src/studio/PidSymbol.tsx:86-410` | `subClassToSymKind()` switch |
| 5 | Display names | `webapp/frontend/src/studio/labelMap.ts:31-115` | `MODEL_LABEL_NAMES` + `SUB_CLASS_NAMES` |
| 6 | Instrument type codes (150+) | `instrument_parser.py:18-182` | `TYPE_MAP` (ISA 5.1) |
| 7 | YOLO→entity routing | `webapp/routers/api_v1.py:_yolo_class_to_canonical()` | prefix rules → `(entity_class, sub_class)` |

**Consequences:**
- Adding a class means editing 4–7 files by hand and keeping them in lock-step.
- A new label drawn in LS is **silently dropped** at training-export time
  (`export_ls_dataset.py` keeps only labels present in the Python `CLASS_NAMES`),
  and never appears in the palette, glyphs, display names, or routing.
- There is **no backward LS→code sync** and **no triage surface** for unknown labels.

## Goal

1. **One source of truth** for the symbol taxonomy that every consumer reads.
2. **Triage workflow**: unknown labels (discovered in LS or in `gpu_detections`)
   surface to an admin, who classifies them (valve / instrument / equipment /
   ignore) and assigns sub_class + display name + color + glyph. On approval the
   label is promoted into the taxonomy and auto-propagated.
3. **Zero behavior change** for the existing 23 classes (byte-for-byte routing,
   colors, glyphs, display names preserved).

## Non-goals (YAGNI)

- No live re-training trigger. Promotion updates the taxonomy + LS config; the
  next training run picks up new labels through the existing export path.
- No frontend live-fetch refactor in v1. Frontend keeps a **static import** of a
  generated taxonomy module (decision from brainstorming) — avoids a boot-time
  network dependency and keeps the SPA build hermetic. A later version may switch
  to an API fetch if the taxonomy starts changing at runtime frequently.
- We do **not** unify `instrument_parser.TYPE_MAP` (150+ ISA codes) into the
  taxonomy in v1 — it is a CSV-description lookup, orthogonal to symbol classes.
  It stays where it is; the taxonomy references instrument *sub_classes* only.

## Architecture

### Source of truth: `taxonomy.json` (file-first, DB read-index)

Mirrors the proven `canonical.json` + `canonical_entities` pattern (FEATURES #34):
the file is authoritative; a DB table is a denormalized read-index for queries
and the admin UI.

- **File:** `webapp/config/taxonomy.json` — version-controlled, the canonical
  definition. One entry per `(entity_class, sub_class)` plus the YOLO routing rules.
- **DB table `label_taxonomy`** — synced from the file on startup (idempotent
  upsert keyed on `(entity_class, sub_class)`), queried by the admin UI + triage.
- **DB table `label_triage`** — pending/decided unknown labels (the workflow store).

```jsonc
// taxonomy.json (excerpt)
{
  "schema_version": 1,
  "classes": [
    { "entity_class": "valve", "sub_class": "BV",
      "display_name": "Ball Valve", "yolo_label": "valve_bv",
      "color": "#86D8C4", "glyph_kind": "valve_bv" },
    { "entity_class": "instrument", "sub_class": "FT",
      "display_name": "Flow Transmitter", "yolo_label": "inst_field",
      "color": "#E5CBA0", "glyph_kind": "inst_field", "isa_code": "FT" }
    // ... seeded from the current 7 lists, verified equal to today's values
  ],
  "yolo_routing": [
    { "match": "prefix", "value": "valve_", "entity_class": "valve",
      "sub_class": "suffix_upper" },
    { "match": "prefix", "value": "inst_",  "entity_class": "instrument",
      "sub_class": null },
    { "match": "exact",  "value": "interlock", "entity_class": "instrument" },
    { "match": "exact",  "value": "SIS-R",     "entity_class": "instrument" },
    { "match": "exact",  "value": "Motor",          "entity_class": "equipment" },
    { "match": "exact",  "value": "Pump/Dwg Pump",  "entity_class": "equipment" },
    { "match": "prefix", "value": "arrow_",     "entity_class": null },
    { "match": "prefix", "value": "connector_", "entity_class": null }
  ]
}
```

### Backend module: `webapp/taxonomy.py`

Single import surface for Python consumers:
- `load_taxonomy() -> Taxonomy` (cached; reads the file once).
- `yolo_to_canonical(label) -> (entity_class | None, sub_class | None)` — replaces
  the hard-coded `_yolo_class_to_canonical()`. Driven by `yolo_routing` rules.
- `class_names() -> list[str]` — ordered YOLO labels for `inference.py` (order
  preserved via an explicit `order` index in the file so the ONNX channel map
  never shifts).
- `display_name(entity_class, sub_class)` / `color(...)` / `glyph_kind(...)`.

`inference.py` `CLASS_NAMES` becomes `class_names()` (asserted equal to today's 23
in a test so a bad edit can't silently break the model head mapping).

### Frontend: generated module

A small build step (or a checked-in generated file regenerated by a script)
emits `webapp/frontend/src/studio/taxonomy.generated.ts` from `taxonomy.json`.
`paletteColors.ts`, `labelMap.ts`, and `PidSymbol.subClassToSymKind` consume it.
Static import — no runtime fetch (brainstorming decision).

### LS auto-sync

`scripts/ls_label_config.xml` becomes **generated** from `taxonomy.json`
(`scripts/ls_sync_labels.py --from-taxonomy`). On promotion of a triaged label,
the sync runs (or is one click in the admin UI) and PATCHes all LS projects.

### Triage workflow

```
unknown label discovered ──► label_triage row (status=pending)
   sources: LS webhook (new label in config) | gpu_detections label not in taxonomy
                          │
            admin opens /admin/label-triage
                          │
        classify: entity_class + sub_class + display_name + color + glyph
                          │
      approve ─► append to taxonomy.json ─► upsert label_taxonomy
               ─► regenerate frontend module + LS XML ─► (optional) sync LS
      ignore  ─► status=ignored (won't resurface)
      reject  ─► status=rejected
```

**Discovery hooks (non-fatal, additive):**
- `webapp/routers/api_v1.py:api_job_detections()` — when a detection label has no
  taxonomy match, record it in `label_triage` (dedup on label value).
- LS tasks/labels webhook — when LS reports a label not in the taxonomy.

## Data model

```python
class LabelTaxonomy(Base):          # read-index, synced from taxonomy.json
    id; entity_class; sub_class; display_name; yolo_label
    color; glyph_kind; isa_code (nullable); order (int); active (bool)
    # unique (entity_class, sub_class)

class LabelTriage(Base):            # workflow store
    id; label_value (unique); source ("ls"|"detection")
    discovered_at; status ("pending"|"approved"|"ignored"|"rejected")
    assigned_entity_class; assigned_sub_class; assigned_display_name
    assigned_color; assigned_glyph_kind
    decided_by_user_id; decided_at; notes
```

Both created via `Base.metadata.create_all` (no Alembic, per CLAUDE.md). The
file→`label_taxonomy` sync follows the `sync_canonical_to_db` pattern.

## API surface (all `require_super_admin`)

- `GET  /api/v1/admin/taxonomy` — full taxonomy (for the admin UI + a future FE fetch).
- `GET  /api/v1/admin/label-triage?status=pending` — triage queue.
- `POST /api/v1/admin/label-triage/{id}/classify` — body: decision; performs
  promote/ignore/reject + regenerate + (optional) LS sync.

## Migration / seeding (the critical safety step)

1. Author `taxonomy.json` by **extracting** the current 7 lists.
2. A test asserts the generated values **exactly equal** today's hard-coded ones:
   - `class_names()` == current `CLASS_NAMES` (same order).
   - `yolo_to_canonical(x)` == `_yolo_class_to_canonical(x)` for every current label
     **and** a set of unknown/arrow/connector labels.
   - palette colors + glyph kinds + display names unchanged for all 23/26/34 entries.
3. Only after parity is green do we switch consumers to read the taxonomy.

## Testing

- **Parity tests** (above) — gate the whole change.
- `webapp/taxonomy.py` unit tests: routing rules, ordering, unknown-label handling.
- Triage tests: discovery dedup, classify→promote appends + upserts, ignore won't
  resurface, reject path, non-admin 403.
- Frontend: generated module matches `paletteColors`/`labelMap` snapshots; palette
  still renders; no hotkey regressions (existing `paletteColors.test.ts`).
- E2E (local): draw an annotation with a class, confirm palette/glyph/color; admin
  triage a synthetic unknown label and see it appear in the palette after promote.

## Rollout

- Build on a **local branch** (not `dev`) per current testing policy.
- Phase 1: taxonomy file + `webapp/taxonomy.py` + parity tests (no consumer switch).
- Phase 2: switch backend consumers (`inference.py`, `api_v1` routing).
- Phase 3: frontend generated module + switch FE consumers.
- Phase 4: triage DB + API + admin UI + discovery hooks + LS generation.
- FEATURES.md entry per phase.

## Open questions for review

1. **Frontend delivery**: generated checked-in `.ts` (simplest, reviewable diffs)
   vs a Vite build plugin that reads the JSON. Recommendation: **checked-in
   generated file + a regen script** — diffs are visible, no build-time JSON IO.
2. **Discovery aggressiveness**: auto-create triage rows from `gpu_detections`
   on every job, or only via an explicit "scan for unknown labels" admin action?
   Recommendation: explicit scan + LS webhook (avoids noisy rows from arrows).
3. **Instrument sub_class granularity**: YOLO emits only `inst_field`/`inst_bpcs`/
   etc., not ISA codes (PT/FT/…). Sub_class for instruments comes from OCR/parsing,
   not the model. Confirm the taxonomy keys instruments by the *canonical* sub_class
   (PT, FT, …) for palette/colors while routing keys on the YOLO label — i.e. a
   one-to-many YOLO→sub_class relation for instruments. (This matches today.)
