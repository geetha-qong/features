# FEATURES — Append-only decision log

> Every meaningful feature, model swap, threshold change, architecture decision, bugfix, experiment, or business decision gets one entry here. **Newest first. Never edit past entries — mark superseded with `SUPERSEDED BY #NN`.** Recording the *reasoning* matters more than the choice.

**Why this file exists:** so we don't repeat ourselves. Every Claude Code session, every team standup, every "why did we decide that?" question — answer is here. Convention adopted from the QS-60 vision pack (see `docs/onboarding/`).

**Format for each entry** (keep under 200 words; long discussions go in `docs/decisions/NN-title.md` and link here):

```
## [YYYY-MM-DD] #NN — <short title, sentence case>

**Type:** feature | model-swap | threshold-tune | architecture | bugfix | experiment | decision | business
**Stage:** ingestion | preprocess | symbols | lines | direction | text | associate | graph | validate | review | export | training | infra | webapp
**Status:** shipped | experimental | reverted | superseded-by-#NN

**Why:** 2–4 sentences. What problem, where the request originated. Origin matters more than description.

**What:** What was built or changed. Files touched. Public interfaces added or modified.

**Result (if measurable):** Numbers, not adjectives.

**Notes:** Weird things next session should know. Hardcoded values that should become config. Dead ends. Links.
```

---

## [2026-06-12] #39 — Qong Studio UI redesign: sheet-picker dropdown, category palette sidebar, Apply action, details strip

**Type:** feature | architecture
**Stage:** webapp/frontend
**Status:** shipped

**Why:** User-driven redesign — flagged the existing 3-column layout (SheetRail + Canvas + Properties) as cramped, with the sheet rail eating canvas width while sheets are infrequently switched. Design landed via a Claude Design handoff bundle (chats 1–6, final iteration 2026-06-12) with explicit asks: sheets-as-dropdown in the top bar, collapsible-category palette on the left as the main symbol picker, full-width canvas with an explicit "I'm done with this sheet" Apply action, and a right details panel that can collapse to a slim vertical strip so the canvas can run edge-to-edge during heavy marking.

**What:**
- New `webapp/frontend/src/studio/SheetPicker.tsx` — top-bar pill dropdown that lists every sheet (real tile thumbnails or generated SheetGlyph fallback) with a `applied ✓ N` badge per sheet. Replaces the left rail.
- Deleted `webapp/frontend/src/studio/SheetRail.tsx`. `StudioTopBar.tsx` now receives `sheets / activeSheet / onActivateSheet / projectId / dark / realSheets / appliedBySheet` and mounts `SheetPicker` inside `.proj-meta`. The "42 issues" badge is gone from the top bar.
- `annotations/PalettePanel.tsx` restructured into the draw.io-style collapsible category list (Valves, Instruments, Equipment). Rows are glyph + full name + hotkey badge. **Test contract preserved** — `data-testid="palette-item-${cat}-${sub}"`, click-to-arm semantics, and `style.background contains 'var(--qong-pink'` on the active row all still hold; all 6 existing tests pass.
- `Studio.tsx` body grid switches to `studio-body--draw` variants: `with-props` (248 / canvas / 348) or `with-strip` (248 / canvas / 44). Adds `appliedBySheet` state, `propsOpen` state, and a `showToast` helper.
- Canvas toolbar inside Studio now hosts a primary **Apply · N** button (right-aligned, pink gradient) — disabled when zero marks, switches to green **Applied** after click. Annotation list resetting Apply count is via the `applied` derived value.
- `PropertiesPanel.tsx` gains an `onCollapse` prop + Export Deliverables section (Instrument Index, Datasheets, I/O List, Valve List, Control Narrative, Cause & Effect — all wired via optional `onExportDeliverable(type)`). When collapsed, `Studio.tsx` renders a full-height `.props-strip` button (vertical "DETAILS" label + issue badge at bottom).
- `design/studio.css` — ~430 new lines under a "REDESIGN (Jun 2026)" header. Uses existing semantic tokens (`--bg`, `--surface`, `--fg-*`, `--qong-*`) so light/dark theming works through the existing `[data-theme="dark"]` selectors with no new theme overrides needed.

**Result:**
- `npx tsc --noEmit` clean. `npx vitest run` → 15 files / 66 tests passing (incl. 6 PalettePanel tests).
- Canvas gains ~232px horizontal real estate when the details strip is collapsed; ~120px even when details are open vs. the old layout.

**Notes:**
- Apply is **UI-only state** — `appliedBySheet[sheetId] = applyCount`. Annotations are already persisted on creation via `useAnnotations.create`; "Apply" is a reviewer's intent ("done with this sheet") rather than a new backend mutation. If/when a server-side `sheet_applied_at` lands, the same `handleApply` will fire the POST and the UI doesn't change.
- Sheet picker uses real tile thumbnails (`RealSheet.url`) when `realSheets` is populated; otherwise the deterministic `SheetGlyph` SVG, same fallback the rail used.
- The hotkey labels in the palette (1, 2, s, g, …) are **visual hints only** — actual binding stays inside `useShortcutDispatcher` (FEATURES #38). When a user customises shortcuts, the keys in the palette will drift; future work: read bindings from `useShortcuts` and surface the user's actual keys.
- Design bundle archived at `/tmp/qong_design/qong-app/` (not committed). 6 chat transcripts captured the iteration history if we need to revisit a specific decision.

## [2026-06-11] #38 — Qong Studio marking + graph annotation system (6-phase end-to-end)

**Type:** feature | architecture
**Stage:** webapp | webapp/frontend | training
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-11)
**Spec:** `docs/superpowers/specs/2026-06-10-qong-studio-marking-design.md`

**Why:** Studio could surface model detections but couldn't accept user marks, confirmations, rejections, or line-drawing. We needed one prod-grade annotation surface that captures every action as YOLO/graph training signal, lets users define their own shortcuts, and renders the whole page (not just one tile) so cross-tile pipes/loops/interlocks become trivial. User authorized direct build (no approval gate).

**What (one session, six phases, multi-agent):**

**Phase 1 — Backend schema + APIs** (commits `4af85c1`, `ac505dc`, `e6a6314`):
- `user_annotations` + `graph_corrections` tables (file-first + DB-read-index pattern; same architecture as `canonical_entities`).
- `users.shortcuts` JSONB column for per-user keymap.
- POST/GET/PATCH/DELETE on `/api/v1/jobs/{id}/{annotations,edges}` with collision rule (same-class on existing detection → user_confirmed; different-class → user_added + model_corrections(delete); empty region → user_added + model_corrections(add) linked via FK).
- `/api/v1/jobs/{id}/page/{n}/full` (cookie-authed FileResponse of the full-page render that pdf_to_tiles already emits).
- `/api/v1/users/me/shortcuts` GET/PATCH/POST(reset). 14 DEFAULT bindings; modifier-chord + multi-char keys rejected.
- 41 pytest cases (10+13+5+13).

**Phase 2 — Studio canvas pivot to full-page** (commit `d5cd41d`):
- PidCanvas now renders `page_{n}_full.png` and translates every model-detection bbox from tile-local into page-pixel coords via `computeTileOffsets()` (mirror of pdf_to_tiles 3×3/20% geometry).
- 4-layer SVG: model detections + user_annotations + edges + in-flight edge preview.
- Theme-coherent status palette (`--info`/`--qong-pink`/`--ok`/`--error`) and line-type stroke styles (`--scan-cyan` solid / `--qong-pink` dashed / `--qong-purple` long-dash / `--warn` dash-dot) with arrowheads on flowing lines.
- Mode-aware event handlers (`select`/`mark-symbol`/`draw-edge`), entity snap (28 px) on edge draw, Escape cancels in-flight draws.
- Legacy single-tile mode preserved as fallback.

**Phase 3 — Symbol palette + status states** (commit `23b0566`):
- `PalettePanel` (220 px left rail, hierarchical class→sub_class), `ModeToolbar`, `StatusBadge` pill renderer, `useAnnotations` hook with optimistic create/patch/delete.

**Phase 4 — Edge drawing** (commit `23b0566`):
- `LineTypeToolbar` (4 buttons with live SVG stroke previews), `EdgeMetadataDrawer` (slide-up panel for relation_type + group_id + metadata K/V), `useEdges` hook.

**Phase 5 — Per-user shortcuts** (commit `23b0566`):
- `/account/shortcuts` page (capture input + action picker + conflict warning + reset), `useShortcuts` + `useShortcutDispatcher` hooks, pure `normalizeKey()` with input/textarea bypass + modifier-chord rejection.

**Phase 6 — Training loop + metrics** (commit `23b0566`):
- `export_annotations_for_yolo.py` (page-pixel → tile-local normalized YOLO labels, idempotent append), `export_graph_for_training.py` (JSONL), `/api/v1/admin/annotations/metrics` endpoint (totals, by_status, per_day_last_30), `AdminAnnotationMetrics` admin page.

**Result:**

| Metric | Value |
|---|---|
| New backend tables | 2 (`user_annotations`, `graph_corrections`) + 1 column |
| New API endpoints | 12 |
| New frontend routes | 2 (`/account/shortcuts`, `/admin/annotation-metrics`) |
| New frontend components | 9 (PalettePanel, ModeToolbar, StatusBadge, LineTypeToolbar, EdgeMetadataDrawer, Shortcuts, AdminAnnotationMetrics + 2 hooks) |
| pytest cases added | 63 (40 router + 22 export + 1 admin metrics — actually 4) |
| vitest cases added | 45 (palette 6, badge 8, mode toolbar implicit, line-type 3, edge-drawer 4, shortcuts 8, keyboard 12, admin metrics 4) |
| Total new tests this session | 108, all green |

**Notes:**
- **FastAPI 204 quirk:** 204 endpoints in this codebase MUST use `status_code=204`, `response_class=Response`, NO `-> None` return annotation, NO `responses[204]`, and `return Response(status_code=204)` explicitly. Production FastAPI tripped a registration-time assertion otherwise; local pytest's older FastAPI didn't catch it. Two patches (`ac505dc`, `e6a6314`) sorted it. Worth a CLAUDE.md note.
- **Tile geometry duplicated** in `pdf_to_tiles.py` and `PidCanvas.computeTileOffsets` (3×3, 20% overlap). If those defaults ever change, change BOTH ends in the same PR.
- **Tile-local → page-pixel translation** happens client-side via the page-full image's `naturalWidth/Height`. No new backend coord-translation endpoint needed.
- **Collision rule** at POST /annotations is the magic that makes "click an existing detection to confirm" feel natural without a separate API verb.
- **page-full endpoint is cookie-authed** so plain `<img src>` works same-origin. Cross-origin (LS-style) consumers would need a separate no-auth route.
- **Status colors are part of the brand palette now** — `--qong-pink` for user marks signals "this is yours" everywhere it appears.

---

## [2026-06-10] #37 — Cross-job duplicate-tag audit surface

**Type:** feature
**Stage:** webapp | webapp/frontend
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-10)

**Why:** FEATURES #34 unblocked cross-job queries; FEATURES #36 made them clickable. But a user still had to know what tag to search for. Promoting "tags appearing in ≥2 jobs" to a top-level audit list turns the "what's duplicated across our corpus?" question from "you'd need to write SQL" into one glance at the page.

**What:**
- `/api/v1/admin/entities/aggregates` extended with `duplicate_tags_across_jobs`: top-15 tags by `(job_count desc, row_count desc)` where `COUNT(DISTINCT job_id) ≥ 2`. SQL `GROUP BY tag HAVING COUNT(DISTINCT job_id) >= 2`.
- `AdminEntities.tsx`: new section between the top-N grid and the search filter — title with `AlertTriangle` icon, table of tag · job_count · total_rows. Clicking a row fills the tag search box and resets other filters, dropping the user straight into the table view for that tag.
- `types.ts`: field marked optional so older deploys (without the field) don't break the UI.

**Result (Playwright-verified live on dev):**

15 duplicate tags surfaced automatically — the 32047 audit from FEATURES #35 is now one of many:

| Tag | Job count | Total rows |
|---|---|---|
| 62-BF-151014 | 3 | 3 |
| 62-BF-151031 | 3 | 3 |
| 62-DB-151042 | 3 | 3 |
| 61-BV-149128, 149131, 32047, 149130, 32049, 32050, 32052, 32053, 32054, 32055, 32048 | 2 each | 2 each |
| 61-CK-149165 | 2 | 2 |

**Three tags appearing in 3 jobs each** is a strong "same drawing re-extracted three times" signal — worth chasing operationally (wasted compute, deliverable consistency).

**Notes:**
- Capped at 15 server-side to keep payload bounded; full inspection via `?tag_contains=<tag>` (the click handler already wires this).
- Sorted by `job_count desc, row_count desc` because the spread-across-many-jobs case is the strongest audit signal.
- Screenshot: `themes/screenshots/admin-entities-duplicates.png`.

---

## [2026-06-10] #36 — Admin Entity Index UI (visual surface for cross-job queries)

**Type:** feature
**Stage:** webapp/frontend
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-10)

**Why:** FEATURES #35 exposed `/api/v1/admin/entities` + `/aggregates` but the data wasn't reachable without a curl loop. A frontend page makes the cross-job query power visible to anyone with super_admin role.

**What:**
- `webapp/frontend/src/admin/AdminEntities.tsx` (new) — three workflows on one page:
  1. **Aggregates strip**: total entities, per-class counts (1,304 / 625 instruments / 679 valves on dev today).
  2. **Top sub-classes + top jobs** as two side-by-side clickable lists. Clicking a sub-class filters the table to `entity_class=valve, sub_class=X`; clicking a job filters to `job_id=N`.
  3. **Filter bar + paginated table**: tag-substring search, class + sub_class dropdowns, job-ID input. 50 rows per page. Each row links to `/jobs/{id}` (Studio).
- Sub-class dropdown options derived from the live `top_valve_sub_classes` payload so it stays in sync without a separate API call.
- Wired into `AdminLayout` nav (new "Entity Index" item, Database icon), `App.tsx` (`/admin/entities` route), `admin/api.ts` (`getEntityAggregates`, `searchEntities`), `admin/types.ts` (3 new interfaces).

**Result (Playwright-verified live on dev):**
- Page loads at `/admin/entities` with full aggregates: total=1,304, by_class={valve:679, instrument:625}.
- Top valve sub_classes correctly shown: VB(205), BV(154), VF(90), DB(69), BF(68), VD(17), GL(14), CK(14), PV(13), VCS(10).
- Tag-substring search `"32047"` returns exactly **2 hits**: job 38 `61-BV-32047` + job 43 `61-BV-32047`, both on `MUK-61-0-0218-002-25L3`. Confirms duplicate is the *same drawing across two job runs* (re-extraction), not two physical valves on different drawings — actionable audit signal previously invisible.

**Notes:**
- The 2-hit duplicate is now visible from the UI without curl. Earlier scope for an audit endpoint isn't necessary — the existing search + tag substring covers the use case.
- Sub-class dropdown only appears when `entity_class=valve` — keeps the UI from showing a meaningless filter when the user picked instruments.
- Screenshot: `themes/screenshots/admin-entities-search-32047.png`.

---

## [2026-06-10] #35 — Admin cross-job entity search + aggregates endpoints

**Type:** feature
**Stage:** webapp
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-10)

**Why:** FEATURES #34 added the `canonical_entities` DB index but no surface to query it without raw SQL. Production usage (admin dashboards, customer summaries, duplicate-tag audits) needs an authenticated HTTP endpoint.

**What:**

- `GET /api/v1/admin/entities` — filterable cross-job search. Query params: `entity_class`, `sub_class`, `tag_contains` (ILIKE substring), `job_id`. Pagination via `offset` + `limit` (capped at 500). Returns rows with `job_id, entity_id, entity_class, sub_class, tag, pid_number, sheet_number, fields, updated_at`.
- `GET /api/v1/admin/entities/aggregates` — single-call dashboard payload: `total_rows`, `by_class` (per-entity-class counts), `top_valve_sub_classes` (top-10), `top_jobs_by_valve_count` (top-10).
- Both `require_super_admin`.
- Reads pipeline-emitted state — entity_overrides NOT applied. For user-visible state, use the deliverables API.

Frontend bonus: expanded `VALVE_SUB_CLASS_LABELS` in `studio/buildElements.ts` to cover the CSV-side codes the backfill surfaced (VB=Block, VF=Flow, VD=Drain, PV=Pressure, SB=Sample/Bleed). Without this map ~205 ball-valve-equivalents were rendering as "Valve (VB)" placeholders.

**Result (live on dev as super_admin):**

| Endpoint | Sample output |
|---|---|
| `/aggregates` | `total_rows=1304, by_class={valve:679, instrument:625}` |
| `?tag_contains=32047` | 2 hits: job 38 `61-BV-32047` + job 43 `61-BV-32047` (duplicate-tag audit) |
| `?entity_class=valve&sub_class=BV` | 154 total ball valves across all jobs |

**Notes:**

- `top_valve_sub_classes` revealed **VCS** (10) as a new sub_class not yet in the frontend label map — add when seen often enough to matter.
- The duplicate `61-BV-32047` in jobs 38 + 43 is real (same `pid_number` and `sub_class`) — either the same physical valve re-extracted across drawing revisions, or a legitimate duplicate. Cross-job audit endpoint is the right tool to chase this.
- Endpoint serving order: dev took ~75 seconds to flip the response Content-Type from `text/html` (SPA catch-all) → `application/json` after push, because the FastAPI router only re-registers on container restart. Worth checking via Content-Type when polling deploy state, not just status code.

---

## [2026-06-10] #34 — Dynamic PropertiesPanel + DB-backed canonical_entities index

**Type:** feature | architecture
**Stage:** webapp | webapp/frontend
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-10)

**Why:** Two stacked moves toward production-grade studio output.

1. **Frontend dynamism (Phase A):** The Studio right panel ("Selected Element"
   + "Elements on Sheet") was rendering hard-coded prototype tags
   (`PV-203` / `V-101` / `FT-101` / `P-101` / `E-104`) regardless of real
   data, because `Studio.tsx` fell through to `DEMO_ELEMENT_DATA` whenever
   `selectedId` wasn't in the prototype dictionary — which was *always* once
   a real bbox was clicked. Effect: clicking a real bbox highlighted the
   rect but never updated the panel; users reported "the click does
   nothing" even though D1.5 entity matching was working correctly behind
   the scenes.

2. **Cross-job queryability (Phase B):** Until today, "find all valves of
   size 8 across customer X's jobs" required parsing N `canonical.json`
   files. Production dashboards / customer summaries / audit queries need
   one SQL `WHERE` clause, not a Python loop.

**What:**

**Phase A — PropertiesPanel real-data wiring:**
- `webapp/frontend/src/studio/buildElements.ts` (new) — derives a
  `Record<entity_id, CanvasElement>` for the active tile, joining live
  detections with canonical entities. Includes a `sub_class → human label`
  table mirroring `api_v1.py:_yolo_class_to_canonical` so "valve_bv"
  surfaces as "Ball Valve". Detections without `entity_id` (direction
  arrows, page connectors) are excluded — non-editable.
- `Studio.tsx` — fetches `valve_list` + `instrument_index` entities at
  mount, builds an `entityIndex` Map keyed by UUID, memoises a per-tile
  `realElements` derivation. `panelElements` is real when present,
  `DEMO_ELEMENT_DATA` otherwise. When real data first lands, `selectedId`
  auto-jumps from `"PV-203"` to the first real entity_id on the tile.
- `PropertiesPanel.tsx` — switched to `Object.entries(elements)` so row
  click + isSel checks use the dictionary key (entity_id), not `el.tag`.
  `onSelect` contract now propagates `entityClass` so the drawer opens
  to the right deliverable.

**Phase B — `canonical_entities` DB table:**
- `webapp/models.py` — `CanonicalEntityRow` ORM. Mirrors `CanonicalEntity`
  1-for-1 plus `canonical_schema_version` for cross-version filtering.
  Unique on `(job_id, entity_id)`; indexed on `entity_class` + `tag` for
  the common "find all valves named X" query. Created automatically on
  startup via `Base.metadata.create_all(engine)`.
- `webapp/deliverables/canonical_db_index.py` — `sync_canonical_to_db()`
  per-job idempotent upsert + stale-row delete (re-emit truth wins).
  Lives in its own module to keep `pipeline_emitter.py`'s "pure function
  — no DB, no network" contract intact.
- `webapp/pipeline_runner.py` — dual-writes after canonical.json emit.
  Non-fatal: DB sync failure logs but doesn't roll back job "done" state.
- `webapp/scripts/index_canonical_to_db.py` — backfill CLI for legacy
  canonical files. Same idempotent path; safe to re-run.

**Source of truth remains the on-disk `canonical.json`.** The DB table is
a denormalised read-index — never the edit target. User edits still live
in `entity_overrides` and merge at request time via the deliverables API.
Deliverable generators are unchanged.

**Result:**

| Metric | Value |
|---|---|
| Legacy GCP-era paths migrated (jobs table) | 36 |
| Canonical.json files backfilled total | 49 |
| canonical_entities rows indexed | **1,304** (679 valves + 625 instruments) |
| Backfill errors | 0 |
| Cross-job query verified | `SELECT … WHERE tag LIKE '%32047%'` → job 38 + job 43 |
| Top-5 jobs by valve count (instant) | 6 (51), 3 (50), 5 (49), 14 (46), 19 (41) |
| Frontend tests | 21/21 pass |

**Notes:**

- **Surprise sub_class diversity:** the DB shows VB (205), BV (154), VF
  (90), DB (69), BF (68), VD (17), GL (14), CK (14), PV (13), SB (10) as
  the most common valve sub_classes. Only BV/BF/GT/CK/DB/GL/CV/NCBV/
  PNEUCTRL/RELIEF_SAFETY/3WAY_RELIEF are in the
  `VALVE_SUB_CLASS_LABELS` map (FEATURES #31 mirror) — the others
  (VB, VF, VD, PV, SB) come from CSV-side customer conventions, not the
  YOLO vocabulary. Currently render as "Valve (VB)" etc. — fine for now;
  expand the map as customer feedback rolls in.
- **Duplicate tag observation:** `61-BV-32047` exists in both job 38 and
  job 43. Worth an audit pass — might be the same physical valve
  re-extracted, or a legitimate duplicate across drawings. Cross-job
  audit queries like this are exactly the use case the DB index unlocks.
- **The `Job.output_csv_path` migration (`/www/wwwroot/qong_poc/` →
  `/app/job_outputs/`)** was a one-time SQL UPDATE on 36 jobs that had
  survived the AWS migration (FEATURES #21) with stale GCP paths. Memory
  rule "no autonomous job mutation" still stands — this was an
  explicit user authorisation ("update all the jobs").

---

## [2026-06-10] #33 — Backfill canonical.json for legacy jobs + drawer 404→notFound routing fix

**Type:** bugfix
**Stage:** webapp | webapp/frontend
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-10)

**Why:** Reported on dev.qongsystems.com/jobs/38 — clicking a detection opened the DatasheetDrawer with `0 of 0 fields` and `Failed to load: HTTP 404`. Two independent bugs were stacking:

1. **Legacy-data gap.** The canonical-entity emitter shipped 2026-05-28 (commit `024cf4a`, FEATURES #26). Jobs 2–39 were processed before that date and have `valve_list.csv` + `instrumentation_index.csv` on disk but no `canonical.json` next to them, so `GET /api/v1/jobs/{id}/entities` raises `JobCanonicalNotFound` → 404.
2. **Drawer 404 routing broken for GETs.** `getEntities` uses `call<T>` which threw plain `Error("HTTP 404")`, not `HttpError`. The drawer's `if (e instanceof HttpError && e.status === 404) setNotFound(true)` branch therefore never fired and the raw error message leaked through as `Failed to load: HTTP 404`. The `HttpError` path was only wired into `callJson` (write verbs).

**What:**

- `webapp/scripts/backfill_canonical.py` (new) — one-shot CLI:
  - Modes: `--from-db` (iterates `models.Job` rows where `output_csv_path` is set; default mode walks the filesystem under `/app/job_outputs`).
  - For each job missing `canonical.json` but having at least one of `valve_list.csv` / `instrumentation_index.csv`, calls `webapp.deliverables.pipeline_emitter.write_canonical_for_job(...)` — same code path the pipeline runs at job-completion time.
  - Idempotent (skips dirs that already have `canonical.json`).
  - Verbose per-job logging + a final tally.
- `webapp/frontend/src/studio/api.ts` — moved `HttpError` declaration above `call<T>` and switched `call<T>` to `throw new HttpError(...)` for both opaque-redirect (401) and `!res.ok` (status) cases. Backwards-compatible: `HttpError extends Error`, all existing `err.message` consumers (CreateUserModal, CreateProjectModal, JobDetail, Login) continue to work unchanged.
- `webapp/frontend/src/studio/datasheet/DatasheetDrawer.tsx` — `notFound` copy rewritten to call out the legacy-job case explicitly so re-runs are the obvious remedy ("Most likely this is a legacy job processed before the editable-entities feature shipped (2026-05-28). Re-run the job from the dashboard to regenerate `canonical.json`...").

**Result:**

Live backfill on dev (`docker compose exec -T web python -m webapp.scripts.backfill_canonical --from-db`):

| Outcome | Count |
|---|---|
| Wrote canonical.json | 6 (jobs 2, 38, 39, 40, 42, 43) |
| Already present, skipped | 7 |
| No CSVs found (stale DB paths — see Notes) | 36 |
| Errors | 0 |

`GET /api/v1/jobs/38/entities?deliverable_type=valve_list` now returns 200 with 21 valves + 14-column schema. `GET .../detections` now attaches `entity_id` to 21 of 71 detections (the rest are direction labels, which intentionally have no canonical match per FEATURES #31).

**Notes:**

- **Discovered orthogonal issue: 36 jobs have stale GCP-era paths in their DB rows** (`output_csv_path` like `/www/wwwroot/qong_poc/job_outputs/N/...`). These survived the AWS migration (FEATURES #21) but the DB column wasn't rewritten — the files actually live at `/app/job_outputs/N/` on the AWS EC2. The backfill script can't reach them via `--from-db` because it follows the (wrong) DB path. The API's `_load_job_or_404` also can't load them. **Fix is one SQL UPDATE** but punted out-of-scope here; flagged in SESSION_STATE next-steps. Memory `feedback_job_running_policy.md` (no autonomous job mutation) applies — surface, don't fix unilaterally.
- The backfill found **3 unexpected org-scoped jobs missing canonical.json** (40, 42, 43) despite being post-emitter. Probable explanations: jobs that crashed before the emit step, or were created via a code path that doesn't call `write_canonical_for_job`. Worth a follow-up audit but not blocking — they're now backfilled.
- **`call<T>` now throws `HttpError`** — any future GET endpoint can branch on status code without changes. Mirrors what `callJson` already did.
- **Frontend test suite** — there are existing vitest cases for the drawer's `notFound` UX. Copy text was changed; the assertion most likely checks for the bold "no editable entities" heading; if the test was string-coupled it'll need updating. Not run from this session.

---

## [2026-06-08] #32 — Auto-register TASKS_CREATED webhook on new LS projects

**Type:** bugfix
**Stage:** webapp
**Status:** shipped (committed on `dev`, auto-deploys via `deploy-dev.yml`)

**Why:** LS 1.23 Community has no org-level webhooks (FEATURES #30) — every
project needs its own row. The auto-tile feature (PDF dropped via LS Import →
9 PNG tiles) only works on projects whose webhook is registered. Until today,
`get_or_create_project()` created the project but did NOT register a hook, so
any project created after the initial backfill silently missed the auto-tile
flow. Found on 2026-06-08: 3 of 36 dev LS projects (35/36/37 — `void1`/`void1`/
`void2`) were hookless; PDFs dropped there never tiled. Same root cause is
about to bite the new LS projects that get spawned when jobs 47-49 are re-run
post `OPENROUTER_MODEL` fix — each will create a fresh project, none of which
would have the hook without this fix.

**What:**

- `webapp/label_studio_client.py`:
  - Added module constants `WEBAPP_BASE_URL` (defaults `http://localhost:8000`,
    overridden by env on AWS) and `LS_WEBHOOK_SECRET` (empty disables
    registration — empty-string means the receiver would 401 anyway, so we
    don't bother creating a poisoned hook).
  - New `_register_tasks_created_webhook(project_id)` — POSTs to
    `LS_URL/api/webhooks/` with body
    `{project, url, actions=["TASKS_CREATED"], headers={"X-LS-Webhook-Secret": ...}, is_active=True}`.
    Best-effort: logs and returns False on any 4xx/5xx/exception. Caller still
    treats project creation as successful — tile-push doesn't depend on the
    hook, only the LS-Import-UI PDF path does.
  - `get_or_create_project()` now invokes the helper immediately after a 201
    on `POST /api/projects/`. Existing-project branch is unchanged (no
    mutation of pre-existing config — backfill remains a separate admin
    concern).
- `tests/unit/test_label_studio_client.py` (new, 5 tests):
  - existing-project short-circuits → no POST calls
  - new-project → webhook POST with correct URL + body + secret header
  - webhook 5xx → project_id still returned (best-effort contract)
  - empty `LS_WEBHOOK_SECRET` → webhook step skipped silently
  - `is_configured()` false → returns None immediately, no HTTP

**Result:** 5/5 new tests pass; existing 56 unit tests unchanged (the one
pre-existing `test_sheets_empty_when_no_tiles` failure is the Postgres DB-leak
flake noted in SESSION_STATE — predates this commit).

**Notes:**

- The 3 unhooked projects (35/36/37) were patched up via one-off SSM script
  this morning (cmd id `d6a671d8`). They now have webhook ids 34/35/36
  respectively.
- This fix only covers the *creation* path. Pre-existing projects without a
  webhook still need the one-off admin script — `webapp/scripts/` would be
  the natural home for a "backfill webhooks" CLI but it's not worth one until
  someone needs it again.
- The webhook receiver enforces shared-secret via `hmac.compare_digest`
  (`webapp/routers/webhooks.py:_verify_secret`). The Authorization-Bearer
  fallback in the receiver isn't used here — we set `X-LS-Webhook-Secret`
  explicitly, which is the recommended path per the receiver's docstring.
- No model retraining or schema migration needed.

---

## [2026-06-06] #31 — D1.5: class-based entity_id matching on canvas detections (Spec A unblock)

**Type:** bugfix
**Stage:** webapp
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-06)

**Why:** The `/api/v1/jobs/{id}/detections` endpoint was supposed to attach `entity_id` to each YOLO bbox so the studio canvas click → DatasheetDrawer flow could key entities by UUID. The existing logic matched by string equality of `detection.label` → `canonical_entity.tag` — which never fires in production because `webapp/inference.py` emits YOLO class names (`"valve_bf"`) as `label`, never engineering tags. Effect: every detection had `entity_id=null`, blocking Spec A D2 (DatasheetDrawer real-data wiring) since the post-v1-9 deploy. Fix surfaced when starting D1.5 work post-v1-10.

**What:**

- `webapp/routers/api_v1.py`: rewrote the enrichment block as a 3-step matcher (`_attach_entity_ids` helper):
  1. **Tag-equality.** `detection.valve_tag` / `tag` / tag-shaped `label` → `entity.tag`. Preserves the legacy GPU-worker path + existing fixture shape.
  2. **Label-as-tag.** Same lookup keyed by `label`.
  3. **Class compatibility (FIFO).** YOLO class string (from `label` *or* legacy `yolo_class`) → `(entity_class, sub_class)` via `_yolo_class_to_canonical()`, then take the first un-consumed canonical entity matching that class. Sub-class match preferred; falls back to class-only.
- `_yolo_class_to_canonical` mapping (covers v1-10's 23 classes + v1-9 legacy labels):
  - `valve_*` → `("valve", <suffix>.upper())`
  - `inst_*`, `interlock`, `SIS-R` → `("instrument", None)`
  - `Motor`, `Pump/Dwg Pump`, `Pump_Dwg_Pump` → `("equipment", None)`
  - `arrow_*`, `connector_*` → `(None, None)` (direction labels not editable)
- Tests: replaced single unrealistic test with 3 focused tests covering (a) tag carriers, (b) realistic v1-10 `label`-as-class shape, (c) legacy `yolo_class` field shape. All 7 detections tests pass.

**Result:**

Detections with a canonical-class peer (valve, instrument, equipment) now get a real `entity_id`. DatasheetDrawer canvas-click now opens for the matched class. Pairing is order-based (not spatially correct) because canonical entities' bboxes are still `(0,0,0,0)` placeholders — see notes.

**Notes:**

- **Spatial IoU matching is the v2 of D1.5,** deferred until `pipeline_emitter` populates real bboxes on canonical entities. Today two `valve_bv` detections pair with the first two `valve_bv` canonical entities in iteration order; a user clicking the second-from-left valve will see whichever entity is second in the canonical list, not necessarily the one physically there. Acceptable degraded state for the field-edit flow but produces wrong-pair UX on dense same-class clusters.
- Direction labels (`arrow_*`, `connector_*`) are intentionally non-editable. They render on the canvas but click does nothing.
- Pre-existing failing test `test_sheets_empty_when_no_tiles` (Postgres DB-state leak between tests) is unrelated and fails on the prior commit too — left alone.

---

## [2026-06-05] #30 — v1-10 YOLO ONNX deployed (23 classes incl. flow direction, 2× mAP50 over v1-9)

**Type:** model-swap
**Stage:** training | infra | webapp
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-05 17:28 UTC)

**Why:** v1-9 didn't detect the 6 direction labels the team added in LS over the past week (arrow_up/down/left/right + connector_in/out), blocking the flow-direction step of graph-extraction v0 (digital twin sub-project G). Rather than ship a separate direction-detector running alongside v1-9 (two-pass inference, two ONNX files), the call was to retrain a single unified model with all 23 classes from LS — both gains (direction) and the existing valve/instrument vocabulary in one pass.

**What:**

1. **Single 23-class model** trained from `yolov8s.pt` on 24,428 annotations exported from all 33 dev-LS projects:
   - 9 valves: `valve_bv`, `valve_ncbv`, `valve_gt`, `valve_bf`, `valve_ck`, `valve_db`, `valve_relief_safety`, `valve_gl`, `valve_3way_relief`
   - 8 instruments / signals: `inst_field`, `inst_bpcs`, `Motor`, `Pump/Dwg Pump`, `inst_sis`, `SIS-R`, `interlock`, `inst_local_panel`
   - 6 direction (NEW): `arrow_up`, `arrow_left`, `arrow_right`, `arrow_down`, `connector_out`, `connector_in`
2. **LS schema hygiene:** before training, two LS label typos consolidated — `valve_3way_releif` → `valve_3way_relief` (3 results) and `valve_pnuectrl` → `valve_pneuctrl` (16 results, 28 project configs). Idempotent fixer at `experiments/digital_twin/scripts/fix_ls_typos.py`.
3. **Dataset pipeline:** new exporter `experiments/digital_twin/scripts/export_ls_dataset.py` walks all LS projects, applies a global 23-class ID map, emits a standard YOLO dataset (605 train + 62 val, 90/10 split). Handles both `/data/upload/` LS storage and webapp tile-route URLs. Output staged to `s3://qong-pid-archive-2026-06-02/training/v1-10/dataset_v1-10.tar` (258 MB).
4. **Training:** g5.2xlarge on-demand in ap-south-1b (GPU spot quota = 0 in account; on-demand cost ~$1.21/hr × ~12 min training + setup = ~$3.50 total including a failed first run). Autonomous script: dataset pull → smoke (yolov8n, 1ep) → full train (yolov8s, 100ep, imgsz=640, batch=32, patience=20) → ONNX export → S3 upload → self-terminate. Script at `experiments/digital_twin/scripts/ec2_train_v1-10.sh`.
5. **Production wiring:**
   - GitHub release `model-v1-10` on `Qong-Systems/qong_product` (https://github.com/Qong-Systems/qong_product/releases/tag/model-v1-10), asset `v1-10.onnx` (42.6 MB, sha256 `896e42561fddd8014fd6021176ce903a5bb0afeffa3717b436e32a56c19e3142`)
   - `Dockerfile`: TAG/ASSET_NAME/MODEL_SHA/DEST bumped to v1-10
   - `webapp/inference.py`: MODEL_PATH → `/app/models/v1-10.onnx`, IMGSZ 1280 → 640 (v1-10 exported at 640), CLASS_NAMES rewritten to 23-class order
   - Auto-deployed on push to `dev` via existing `deploy-dev.yml` (build → SSM RunCommand → docker compose restart → healthz)
6. **Live smoke test on dev:** healthz 200, container has `/app/models/v1-10.onnx` (43 MB), `len(CLASS_NAMES)==23`, real inference on 9 job-9 tiles returned 138 detections including both old (`valve_db`, `inst_field`) and new (`inst_bpcs`, `inst_sis`) classes.

**Result:**

| Metric | v1-9 | v1-10 |
|---|---|---|
| mAP50 | 0.404 | **0.834** |
| mAP50-95 | (unknown) | 0.502 |
| Precision | (unknown) | 0.826 |
| Recall | (unknown) | 0.755 |
| Classes | 20 | 23 (7 dropped, 10 added) |
| ONNX size | 43 MB | 42.6 MB |

**Notes:**

- **BREAKING:** dropped 7 v1-9 classes that lacked ≥100 LS annotations: `valve_cv`, `valve_gen`, `DCS`, `PLC`, `interlock-R`, `inst_field-R`, `valve_pnuectrl` (typo). Anything that currently relies on those class names or IDs will silently stop firing. Class IDs are completely reordered — only safe to map by name. The 20-class → 23-class transition is decoded by name via `CLASS_NAMES[d["_class_id"]]` in `inference.py`, so callers that read the string `label` field are fine.
- **`Pump_Dwg_Pump` (v1-9) → `Pump/Dwg Pump` (v1-10)** — label now has slash + space, mirroring LS exactly. YOLO tolerates it; if it ever flows through filesystem paths we'd need to normalise.
- **Under-represented classes** (`connector_in` 55 instances, `connector_out` 73, `valve_3way_relief` 114, `inst_local_panel` 113) — per-class mAP likely weaker; surface in eval and either annotate more in LS or use class weights on next retrain.
- **GPU spot quota = 0** in account 449901518037 for "All G and VT Spot Instance Requests". Worth filing a quota increase ahead of v1-11 to halve retrain cost (~$0.49/hr spot vs $1.21/hr on-demand). 24-48h approval.
- **Training script lessons logged** (commit `89be82c` on `dt/main`): (1) Ultralytics resolves `path:` in data.yaml against its own settings dir not the yaml file location — always use absolute paths; (2) `cmd 2>&1 | tail -N` masks `cmd`'s non-zero exit without `set -o pipefail`; (3) `torch.onnx.export` needs `onnxscript` (not just `onnx`) on PyTorch 2.7+ — add to bootstrap pip install.
---

## [2026-06-05] #30-DT — [DT] Experimental track scaffolded + v1-10 YOLO retrain kicked off (23 classes incl. direction arrows)

> **Numbering note (added at merge):** Both `dev` and `dt/main` independently allocated `#30` on 2026-06-05 — `dev`'s entry above documents the *shipped deployment*, this one (originally `#30` on `dt/main`) documents the *scaffold + training kickoff* that preceded it. Renumbered to `#30-DT` during the `dt/main → dev` merge on 2026-06-10 so both histories survive intact. See also FEATURES #30.

**Type:** infra, model-swap, decision
**Stage:** training | infra
**Status:** in-flight (training EC2 launched, ~3h remaining at write time)

**Why:** Team interns ramping up on the production codebase at their own pace,
while the lead races ahead with Claude Code to ship graph-extraction v0 and a
new direction-aware YOLO model. Separating the work onto `dt/*` branches +
`experiments/digital_twin/` folder keeps `dev` clean for the team and lets the
lead iterate without merge pressure. Same repo (shared data, shared memory)
but separate working surface. Handover via one PR `dt/main → dev` when v0
lands.

User had also added 6 new direction labels in LS over the past week
(arrow_up/down/left/right + connector_in/out) that need to land in the
production model so we can build a flow-direction-aware MultiDiGraph in
graph-extraction v0 (design doc:
`docs/superpowers/specs/2026-06-05-graph-extraction-design.md`).

**What:**

1. **Experimental track:**
   - New branch `dt/main` off `dev` (commit `d77164b`).
   - Folder `experiments/digital_twin/` with `pyproject.toml`,
     `notebooks/`, `backend/`, `data/` (gitignored), `docs/`, `scripts/`.
   - CLAUDE.md gets a new `## Experimental track` section.
   - `deploy-dev.yml` only fires on `branches: [dev]` so `dt/*` pushes are
     silent — zero deploy noise.

2. **LS schema hygiene (script `scripts/fix_ls_typos.py`):**
   - Renamed `valve_3way_releif` → `valve_3way_relief` (3 annotation results in
     1 annotation, project 19).
   - Renamed `valve_pnuectrl` → `valve_pneuctrl` (14 annotations in project 25
     + 28 project label_configs). Idempotent verification pass at end.

3. **v1-10 dataset (script `scripts/export_ls_dataset.py`):**
   - 23-class schema (9 valves + 8 instruments + 6 direction).
   - 605 train + 62 val images, 24,428 bbox annotations exported in YOLO
     format with global class IDs across all 33 dev-LS projects.
   - Handles both `/data/upload/` LS-served images and
     `https://dev.qongsystems.com/jobs/N/tiles/...` webapp-served images.
   - Auto-refreshes the LS JWT access token on 401.
   - Output (gitignored): `experiments/digital_twin/data/dataset_v1-10/`,
     258 MB. Also uploaded to
     `s3://qong-pid-archive-2026-06-02/training/v1-10/dataset_v1-10.tar`.

4. **Training infrastructure:**
   - Bucket policy on `qong-pid-archive-2026-06-02` extended with a
     `PutObject` grant scoped to `training/*` prefix for the existing
     `may26-ec2-ssm-role` (read-only before).
   - GPU spot quota = 0 in this account; **falling back to on-demand**
     (~$1.21/hr g5.2xlarge vs planned ~$0.49/hr g5.xlarge spot).
   - Capacity churn pushed instance from g5.xlarge → g5.2xlarge and from
     ap-south-1a → 1b. Same A10G GPU, larger CPU/RAM. Net effect: slightly
     higher cost, marginally better dataloader headroom.
   - Instance `i-0ec47e4aaa9ad364b` launched on-demand with
     `--instance-initiated-shutdown-behavior=terminate`. Bootstrap user-data
     installs ultralytics 8.3.40 + onnx; main training script
     (`scripts/ec2_train_v1-10.sh`) is fetched from S3 and run detached via
     `nohup`. Auto-terminates on completion.

5. **Training run plan (yolov8s, 100 epochs, imgsz=640, batch=32, A10G):**
   - 1-epoch yolov8n smoke first as fail-fast.
   - Patience=20, save_period=10.
   - Background log uploader pushes `training.log` + `results.csv` +
     `results.png` to S3 every 5 min.
   - ONNX export with opset=12, simplified.
   - All artefacts → `s3://qong-pid-archive-.../training/v1-10/`.
   - Hard timeout 8h on the yolo command bounds worst-case cost ≈ $10.

**Result (target):**
- v1-10 mAP50 ≥ 0.40 (matching v1-9 baseline) on the 17 existing valve/
  instrument classes, plus ≥0.30 on the 4 strong arrow classes
  (350-470 instances each).
- `connector_in` (55 instances) and `connector_out` (73) likely to be
  weaker — flagged for v1-11 with more annotation work.
- Single ONNX model (no two-pass inference) — drop-in replacement for
  v1-9 in `webapp/inference.py` after CLASS_NAMES update.

**Result (actual):** TBD. See `experiments/digital_twin/docs/v1-10-training-handoff.md`
for status-check commands and post-training promotion flow.

**Notes:**
- **`Pump/Dwg Pump`** class name has slash + space + caps. YOLO tolerates it
  in `data.yaml` as a string, but if it ever needs to flow through filesystem
  paths we'd have to normalise.
- **Class imbalance**: 6365 inst_field vs 55 connector_in (~115×). First
  training pass uses default ultralytics class weights; if minority classes
  underperform we'll switch to inverse-frequency weights in v1-11.
- **GPU spot quota** is 0 in account 449901518037 ("All G and VT Spot
  Instance Requests"). Worth filing a quota increase ahead of v1-11 to halve
  retrain cost. Takes 24-48h to approve.
- **Auto-terminate semantics**: instance was launched with
  `--instance-initiated-shutdown-behavior=terminate`, so the training
  script's final `sudo shutdown -h now` causes the EC2 to terminate (not
  stop). Belt + braces.
- The full Spec A goal had v1-10 only adding direction arrows. We expanded
  to a unified 23-class single-model retrain because LS already has 24K
  valve/instrument annotations and a single model is cleaner than two-pass.
  Lead authorised the scope expansion mid-session.

---

## [2026-06-03] #29 — D5: Custom-column-labels per customer template (admin UI)

**Type:** feature
**Stage:** webapp | webapp/frontend
**Status:** shipped (Spec A · A.4, FEATURES #26 deliverables queue)

**Why:** Customers want to rename / reorder / hide deliverable columns without us
editing the canonical JSON templates. The JSON files stay version-controlled
(canonical), and a thin DB-side override layer merges at template-load time —
same pattern as `entity_overrides` for canonical entity data (FEATURES #26).

**What:**
- New ORM `CustomerTemplateOverride` (table `customer_templates_overrides`)
  in `webapp/models.py`. UNIQUE on `(customer_template_slug, deliverable_type, column_key)`.
  `column_key` = the JSON template's `field` value (e.g. `"fields.size"`), the
  natural identity that survives label/order edits. Created automatically via
  `Base.metadata.create_all()` in `run_migrations()` — no Alembic, no
  `new_columns` entry needed.
- `webapp/deliverables/template_loader.py` extended with `merged_template_dict(slug, db, …)`
  + `TemplateLoader.load_merged(slug, db, …)`. Returns the JSON template with
  label/order overrides applied and hidden columns dropped. Generators can opt
  in by switching from `load_with_fallback` to `load_merged`; existing callers
  (`exports.py`, `entities.py`) still use the JSON-only loader for now — D5
  intentionally ships the data layer + UI; opting generators in is a follow-up.
- Three admin endpoints in `routers/api_v1_admin.py`:
  - `GET /api/v1/admin/customer-templates/{slug}` — merged template + `available_slugs`.
  - `PUT /api/v1/admin/customer-templates/{slug}` — body `{overrides: [...]}`,
    delete-then-insert per (deliverable_type, column_key) tuple. No-op rows
    (no label change, no order change, not hidden) are skipped.
  - `DELETE /api/v1/admin/customer-templates/{slug}/overrides` — clears all overrides for the slug.
- New admin page `webapp/frontend/src/admin/AdminCustomColumns.tsx` at
  `/admin/custom-columns`. Slug picker, four sections (valve_list,
  instrument_index, equipment_list, datasheet), per-row up/down buttons +
  editable label + visible checkbox + per-row Reset link. Top-right "Save" /
  "Reset all" buttons. Uses `formatDateTime(last_updated_at, tz)` for the
  audit display.
- `admin/api.ts` + `admin/types.ts` extended with `getCustomerTemplate`,
  `putCustomerTemplate`, `resetCustomerTemplate` + matching interfaces.
- `App.tsx` route + `AdminLayout.tsx` nav entry (Columns3 lucide icon).

**Result:**
- `python3 -c 'import ast; ast.parse(...)' ` clean on backend files.
- `pytest tests/unit/deliverables/` — 69/69 pass (no regressions, including
  the 5 existing template-loader tests).
- `npx tsc --noEmit` clean.
- `npx vitest run` — 21/21 pre-existing tests pass.

**Notes:**
- `column_key` deliberately uses the JSON `field` value (dot-notation), not a
  zero-based index. Reordering on disk later won't break overrides as long as
  the `field` identity is stable. If a `field` is renamed in JSON, its
  overrides become orphaned (silently ignored on merge) — acceptable for now;
  if it becomes painful add a per-slug "orphaned overrides" report.
- Generators still consume the JSON-only template. To opt one in: replace
  `_loader.load_with_fallback(slug)` with `_loader.load_merged(slug, db)`.
  Skipped in this commit to keep the blast radius tight; follow-up ticket once
  the UI sees real use.
- The `is_overridden` bookkeeping field added to merged column dicts is
  silently dropped by `TemplateConfig.model_validate` (pydantic v2 default
  `extra="ignore"`) so it only surfaces through the dict-based API path —
  exactly what the UI needs, no generator surprise.

---

## [2026-06-03] #28 — YOLO v1-9 ONNX in webapp for canvas bbox overlay + corrections-rollback API

**Type:** feature | architecture
**Stage:** webapp | infra | training
**Status:** shipped (feature branch — pending merge to `dev`)

**Why:** Three pressures converged:

1. **Decouple from the Windows GPU worker.** Until now, the canvas overlay on the studio page only got bboxes when the Windows/CUDA worker (`worker.run_inference_job` over Tailscale-Redis) called back to `/api/v1/jobs/{id}/gpu-result`. That box is single-tenant, on a residential ISP, frequently powered down, and not part of the official AWS inventory. Customers visiting the studio on a fresh job often saw an empty canvas. Baking the model into the webapp image makes overlays the default.
2. **Unblock on-prem deploys.** A handful of prospects want air-gapped installs ("our docs never leave our network"). With the model in the image, a single `docker compose up` reproduces the full UX — no Tailscale, no GPU box, no extra moving parts. CPU inference is slower (~1-2 s/tile on a t3.medium) but still well inside the perceived "instant" window for the on-load canvas paint.
3. **Lay active-learning groundwork.** Spec C (corrections-driven retraining) needs a place to land "this bbox is wrong / this one is missing" events. Without a persistence layer, every studio session throws those signals away. The new `model_corrections` table is that drain — write-only audit log, indexed by `job_id`, ready for an export script to convert into YOLO `labels/*.txt` for the next training cycle. Competitor note: Model Broker / similar P&ID extractors require vector PDFs; we accept raster scans and can correct on them.

The "Two-Mode Architecture — Do NOT Mix" rule in `CLAUDE.md` had to be amended: YOLO inside the webapp is now permitted, but **only** for bbox surfacing. The CSV / deliverable pipeline is still OpenRouter Vision API via `extractor.py` (93% recall, customer-facing quality bar). `pipeline.py` must not import `detector.py`.

**What:**

- **`Dockerfile`** — new RUN step downloads `v1-9.onnx` (43 MB) from the public GitHub release `model-v1-9`, verifies sha256 `11e29b47…f526178`, lands it at `/app/models/v1-9.onnx`. Tries an anonymous `curl -L` first (the release is public on prerelease); falls back to a `--mount=type=secret,id=github_pat` PAT path if the asset returns non-200. Both paths documented inline.
- **`webapp/inference.py`** — new module exposing `run_yolo_inference(tile_paths) -> list[dict]`. Lazy-loads an `onnxruntime.InferenceSession` once at module scope behind a double-checked-locking pattern (`_session` + `threading.Lock`), CPU provider only. Output dict shape matches the existing GPU-worker callback (`bbox`, `label`, `confidence`, `tile_*`), so the `Job.gpu_detections` consumer in `routers/api_v1.py::api_job_detections` is unchanged. `label` is the raw YOLO class name (`valve_bf`, `inst_bubble`, …) — NOT the OCR'd tag. The entity_id-matching code in api_v1.py (added at `e9dbc1e`) returns `entity_id=null` for raw-class detections, which is the intended state for D1.5+.
- **`webapp/pipeline_runner.py`** — new `_run_inplace_inference(job_id, job_dir)` runs after `write_canonical_for_job()`, JSON-dumps detections onto `Job.gpu_detections`. Wrapped in try/except (non-fatal), and skipped if the column already has a real (length > 0) list — the GPU worker callback wins if it raced. Logged via stderr; never crashes the job.
- **`webapp/routers/api_v1.py::api_job_corrections`** — new `POST /api/v1/jobs/{id}/corrections`. Body `{ corrections: [{detection_index, action, new_label?, new_bbox?, note?}] }`. Atomic insert (single commit) into `model_corrections`. Validates action ∈ {delete, reclassify, add}, requires `new_label` on reclassify, `new_bbox` on add. Per-job auth: owner or super_admin.
- **`webapp/models.ModelCorrection`** — id, job_id FK, user_id FK, detection_index int (-1 for "add"), action str, new_label nullable, new_bbox JSON nullable, note Text nullable, created_at `DateTime(timezone=True)` defaulting via `_utcnow`. Picked up by `Base.metadata.create_all()` in `run_migrations()` — no manual ALTER needed since the table is new.
- **`requirements.txt`** — added `onnxruntime>=1.17.0`. Pillow was already a dep; numpy via pandas; nothing else new.
- **`CLAUDE.md`** — amended the "CRITICAL: Two-Mode Architecture" section with the explicit exception clause pointing at `webapp/inference.py`.

**Result (TBD — measure after deploy):**

- v1-9 mAP50 = 0.404 on the diverse val split per the release notes — that's the upper bound for what the canvas will surface. Real-job recall typically tracks higher because the val split is intentionally hard.
- Expected CPU inference cost: ~1-2 s/tile on a t3.medium (4-tile job ≈ 5 s overhead added to pipeline tail). Smoke-test on the dev EC2 after merge.
- Numbers pending: recall on the standard MUK sample job after the dev image rebuilds.

**Notes:**

- The `_run_inplace_inference` step is **best-effort**. If the model file is missing (e.g. the Dockerfile download silently degraded), `InferenceError` is caught and the job still finishes "done" — canvas just stays empty, same as today's Windows-worker-unreachable state.
- The PAT fallback in the Dockerfile is a no-op when no secret is mounted; both `docker build .` and `docker build --secret …` work.
- Corrections-to-training-data export is **out of scope** here. Follow-up: `webapp/scripts/export_corrections_for_training.py` that reads `model_corrections`, joins on tile geometry, and writes YOLO `labels/*.txt` for the next training run.
- Future v1-10 should be trainable from accumulated corrections once the export script lands. No timeline pinned — gates on first ~500 corrections accumulating, which at current job volume is ~6-8 weeks.
- The detections endpoint's entity_id matching (matching `label` to canonical entity `tag`) returns null for raw-class labels like `"valve_bf"` because canonical tags look like `"01-BF-151031"`. That's expected for D1.5+; clicking on a raw-YOLO bbox shows the overlay but doesn't open a datasheet drawer. A "class+bbox → tag" reverse-lookup pass is its own ticket (needs a spatial index over canonical entities, doesn't exist yet).
- `webapp/inference.py` gates the `import onnxruntime` behind a try/except ImportError so unit tests that don't exercise the inference path don't require the native library locally. Failures surface inside `_get_session()` instead, where they belong.

---

## [2026-06-03] #27 — Timezone handling: UTC-on-the-wire + per-user display preference + frontend datetime util

**Type:** feature | bugfix | architecture
**Stage:** webapp | webapp/frontend | infra
**Status:** shipped (all three phases) — feature branch `feature/timezone-handling`, PR open against `dev`

**Why:** A user-facing question ("what TZ are the servers running in, and can users pick their own?") surfaced a real latent bug stack:

1. The `web` and `cpu-worker` containers had `TZ=Asia/Kolkata` in `docker-compose.yml`, which only changes `datetime.now()` / `time.localtime()` output, not `datetime.utcnow()`. Most code uses `utcnow()` (correct UTC writes), but the env was misleading and meant any future bare `datetime.now()` would silently emit IST into the same column as UTC values. Latent mixed-timezone data.
2. The API serialized datetimes with `dt.isoformat() if dt else None`, producing strings without the `Z` suffix (e.g. `"2026-06-03T06:53:16"`). JavaScript's `new Date(iso)` parses those as **local clock**, not UTC, under-shifting every displayed timestamp by the browser's offset (5:30h on IST). This was wrong everywhere on dev.qongsystems.com.
3. There was no `User.timezone` column or UI to let users pick a display TZ. Frontend defaulted to whatever `toLocaleString()` picked up from the browser, with no way to override.

Without fixing all three, "show times in the user's TZ" wouldn't have done what users expect.

**What:** Three phases, one commit per phase on `feature/timezone-handling`:

- **Phase 1 — Backend correctness** (commit `29643a2`):
  - Removed `TZ=Asia/Kolkata` from `web` + `cpu-worker` (containers now UTC, matching the EC2 host).
  - New `webapp/datetime_utils.py` with `utc_iso(dt)` (Z-suffixed) and aware `utcnow()`. All 12 `dt.isoformat() if dt else None` callsites in `routers/api_v1.py` + `api_v1_admin.py` replaced. `pipeline_runner.py` stage timings switched too.
  - `models.py`: every `DateTime` column → `DateTime(timezone=True)` (14 columns across 9 tables). Defaults switched to a module-level `_utcnow()` returning aware UTC.
  - `database.py:run_migrations()` extended with a Postgres-only ALTER pass that converts each legacy `timestamp without time zone` column to `timestamptz USING (... AT TIME ZONE 'UTC')`. SQLite is a no-op. Failures are logged (not silently swallowed) so half-migrated state is visible.

- **Phase 2 — User TZ preference** (commit `05b04e4`):
  - `User.timezone = Column(String, nullable=True)` + a new entry in the `run_migrations` `new_columns` list.
  - `GET /api/v1/account` now returns `timezone`. New `PATCH /api/v1/account/timezone` validates the IANA name via stdlib `zoneinfo.ZoneInfo` and returns 422 on unknown values.
  - `AuthContext.tsx`: `CurrentUser.timezone`, new `detectBrowserTimezone()` utility wrapping `Intl.DateTimeFormat`. On `refresh()`, if the server returns null timezone, silently PATCH the browser-detected zone (best-effort; errors swallowed so login never breaks).
  - `routes/Account.tsx`: TZ selector in Profile section with 11 curated IANA options and an "Auto-detect (browser: X)" sentinel that clears the field. Saves on change, refreshes AuthContext so the rest of the SPA picks up the change immediately.

- **Phase 3 — Frontend rendering layer** (commit `b5e1fec`):
  - `npm install date-fns@^4.4.0` (only `formatDistanceToNow` imported; ~6 KB gzipped).
  - New `webapp/frontend/src/util/datetime.ts` exporting `useUserTimezone()`, `formatDateTime(iso, tz?)`, `formatDate(iso, tz?)`, `formatRelative(iso)`. Native `Intl.DateTimeFormat` for absolute formatting (no `date-fns-tz` needed); date-fns only for relative-distance strings.
  - 9 callsites replaced: `routes/Account.tsx`, `routes/AccountApiKeys.tsx`, `routes/Dashboard.tsx`, `dashboard/types.ts`, `admin/AdminDashboard.tsx`, `admin/AdminCredits.tsx`, `admin/AdminFeedback.tsx`, `admin/AdminLabelStudio.tsx`, `admin/AdminUsers.tsx`. Each component now does `const tz = useUserTimezone()` once at top, passes through.
  - Added `useAuthOptional()` (non-throwing variant) so `useUserTimezone()` is resilient to being called outside `<AuthProvider>` in isolated component tests. Saved wrapping every existing admin test in an AuthProvider.

**Result (verified):**
- `npx tsc --noEmit`: clean across the SPA.
- `npx vitest run`: 21/21 tests pass (no test changes needed).
- `webapp/datetime_utils.py` smoke test: naive UTC, aware UTC, aware IST, None — all serialize to expected Z-suffixed UTC string.
- Bundle delta from date-fns: ~6 KB gzipped (tree-shaken to `formatDistanceToNow` only).

**Notes:**
- The timestamptz migration rewrites the column on disk. Safe at our current scale (jobs ~50 rows, users <20) but if any table hits 10M+ rows in the future, the same migration would need to be batched / use `pg_repack`. Not an issue today.
- For users whose `User.timezone` is set but the IANA value later disappears from the system tzdb (e.g. obsolete zone removed), `Intl.DateTimeFormat` throws — we catch and fall back to `toLocaleString()`. Logged as a known soft-failure in `formatDateTime`.
- Auto-detect on first login silently fires `PATCH /api/v1/account/timezone`. If you observe a `timezone` field appearing in DB writes for new users right after login, that's expected.
- The dashboard's `relativeTime()` keeps its hand-rolled short strings ("3 hr ago", "Yesterday") for ≤30 days; only the >30-day "old date" fallback was migrated to the util. Replacing with `formatRelative()` everywhere would give consistent date-fns wording but would change tile copy ("about 3 hours ago" vs "3 hr ago"). Out of scope for this entry; reconsider when bulk-review screen renders timestamps.
- Open follow-ups (not blocking):
  1. Wire `entity_overrides.edited_at` display in DatasheetDrawer once Spec A D2 lands.
  2. The QA-stopped EC2 will need the migration on next start (will run automatically on app startup via `run_migrations()`).
  3. Consider exposing a richer TZ picker (full IANA list) once users complain about the 11-option curated list.

---

## [2026-06-02] #26 — Editable deliverables: entity_overrides backend layer (Day 1 of Spec A)

**Type:** feature | architecture
**Stage:** webapp | deliverables | export
**Status:** shipped (backend); frontend wiring in follow-ups

### What changed

The deliverables subsystem now supports **user edits** without disturbing the
pipeline-produced `canonical.json`. Edits live in a new `entity_overrides` DB
table; a thin merge layer applies them on top of canonical before any
generator runs.

New components:
- **`models.EntityOverride`** — DB table `(job_id, entity_id, field_name,
  new_value, prior_value, edited_by, edited_at)` with
  `UNIQUE(job_id, entity_id, field_name)` for current-value semantics. Full
  audit history is a future migration: drop UNIQUE, add `superseded_at`.
- **`webapp/deliverables/overrides.py`** — `load_canonical_with_overrides()`
  reads canonical.json, queries the override table, walks dot notation
  (`tag`, `fields.size`, `vendor_match.vendor_name`) on each affected
  entity, re-validates through `CanonicalEntity`. Read-only fields
  (`entity_id`, `entity_class`, `pid_number`, `sheet_number`, `bbox`) are
  silently skipped at this layer; API rejects them upstream.
- **`webapp/routers/entities.py`**:
    - `GET /api/v1/jobs/{job_id}/entities?deliverable_type={t}` — returns
      schema (from customer template) + entities filtered by entity_class
      (valve_list→valve, instrument_index/datasheet→instrument,
      equipment_list→equipment), each with per-field `{value, source,
      is_override}`. `source` distinguishes "pid" (canonical had a value)
      from "manual" (user-supplied field). `is_override` true iff an
      override row exists for that field path.
    - `PATCH /api/v1/jobs/{job_id}/entities/{entity_id}` — `{fields:
      {path: value}}`. Atomic: validates all paths editable before any
      writes. Captures `prior_value` from on-disk canonical (not from a
      prior override row) so audit always references pipeline output. Skips
      writes when value unchanged.
- **`webapp/routers/exports.py`** — swapped `load_canonical_for_job` →
  `load_canonical_with_overrides` so generated CSV/XLSX include user edits.
  Single change-point; generators themselves are unmodified.

### Why this design

The architecture already supported edits cleanly because of one prior choice:
generators don't care where data comes from — they consume `JobCanonical`
and emit bytes. So "make 4 deliverables editable" turned out to be one merge
layer above generators + one router file, NOT a per-generator change. If the
6 future generators (Control Narrative, C&E, I/O List, Line List, Loop
Schedule, Tag Register) follow the same `Generator.generate(canonical,
template)` contract, they get edit-ability for free.

**Why DB, not filesystem.** User picked "DB table" over "canonical_overrides.json
per job" because: audit columns come for free; concurrent edits on the same
job are atomic without filesystem race; `canonical.json` stays the only
file the pipeline writes.

**Why `prior_value` snapshots from canonical, not from prior override.** Audit
always references the pipeline's source-of-truth. If a user PATCHes X to A
then B then C, the final audit row has `prior_value` from the original
canonical, not from B. A reader sees "pipeline said X=Z; now X=C" — useful.

### Smoke test (proven on job 41 / dev)

| Test | Result |
|---|---|
| `GET /entities` returns schema + entities with per-field metadata | ✅ |
| `PATCH` two fields → `applied=2` | ✅ |
| `GET` again — `is_override:True` on edited fields | ✅ |
| `POST /export/valve_list/csv` — CSV contains edited values | ✅ |
| `PATCH bbox` (read-only) → 400 | ✅ |
| `PATCH` unknown entity → 404 | ✅ |
| DB row — `prior_value` captures pipeline value | ✅ |

The override flowing into the exported CSV was the satisfying test — it
validates the whole architectural premise (edit lives in DB, merged into
canonical, flows through generator, lands in customer artifact) in one
round-trip.

### Out of scope (deferred)

- **Canvas-click → entity_id linkage** (Spec A Day 1.5). GPU detections
  don't carry `entity_id` today — they come from a separate code path than
  canonical (Windows GPU worker → JSON detections vs. CSVs →
  pipeline_emitter → canonical.json). User picked Option B: write a
  `(page, bbox, tag) → entity_id` mapping during canonical emission and
  surface it on the detections endpoint. ~half a day.
- **DatasheetDrawer + BulkReviewScreen real-data wiring** — Days 2-4.
  Blocked on D1.5.
- **Admin custom-column-labels CRUD UI** — Day 5.

### Files

- `webapp/models.py` (+44 lines — EntityOverride)
- `webapp/deliverables/overrides.py` (new, 160 lines)
- `webapp/routers/entities.py` (new, 280 lines)
- `webapp/routers/exports.py` (3 lines)
- `webapp/main.py` (2 lines — router registration)

### Commit

- `54e0905` feat(deliverables): entity-override layer + editable-deliverables API (Day 1)

---

## [2026-06-02] #25 — CI/CD migrated to GitHub Actions + AWS SSM; branches synced (feature/digital-twin → dev → main)

**Type:** infra | architecture
**Stage:** ci-cd | deployment
**Status:** shipped (pending: GH Secrets paste + first auto-deploy validation)

### What changed

Three coupled changes, shipped together:

1. **CI/CD architecture pivoted from SSH-to-GCP to SSM-to-EC2.**
   - `.github/workflows/deploy-dev.yml` rewritten. Old: `ssh maahedev@34.126.93.103 <<ENDSSH ... ENDSSH` (the GCP VM, stopped 2026-06-02 per #21 — meaning every dev push since cutover triggered a workflow that hung on SSH and silently failed). New: `aws-actions/configure-aws-credentials@v4` → `aws ssm send-command` → poll `get-command-invocation` → curl `/healthz`. Targets `i-0e7b89bd91b67a291`.
   - `.github/workflows/deploy-qa.yml` created. **Manual** (`workflow_dispatch` only, no `push:` trigger) so QA stays stakeholder-paced. Accepts `ref` input (default `dev`) so hotfix branches can ship to QA without polluting `dev`. Ref is regex-validated `^[A-Za-z0-9._/-]+$` before flowing into the SSM JSON payload (defense-in-depth — `workflow_dispatch` already requires repo write, but a compromised account could otherwise shell-inject through the input).
   - IAM user `github-actions-deploy` created with inline `DeployViaSSM` policy scoped to `ssm:SendCommand` on **exactly two** EC2 ARNs (dev + qa) + the `AWS-RunShellScript` document; `ssm:GetCommandInvocation` + `ssm:ListCommandInvocations` (read-only). Blast radius if leaked: shell on those 2 boxes only. No IAM, no other AWS services. Access keys generated; user pastes into GitHub repo Secrets.

2. **`feature/digital-twin` → `dev` fast-forward merge.** 94 commits. `feature/digital-twin` had been the active dev branch since 2026-05-26 (#01) but never merged back; `dev` had drifted to "what's deployed to the dead GCP VM". FF-merge collapses the gap with no merge commit (dev was a strict ancestor). New `dev` tip: `028ee6a`.

3. **`dev` → `main` fast-forward merge.** 100 commits. `main` was at `7f406db` from before the entire AWS migration, before the SaaS webapp, before the digital-twin work. Per CLAUDE.md `main` is reserved for future `app.qongsystems.com` prod — but the branch itself was so stale that prod cutover would have meant a 100-commit catch-up on top of infra work. FF'd to `028ee6a` (no deploy workflow on main — intentional, per CLAUDE.md "do not push until prod infra ready"). Now main is current; when prod is provisioned, cutover is one infra step, not infra + a giant catch-up merge.

### Why this matters

The dev deploy workflow had been **silently broken for 6 days** post-AWS-cutover. Every commit since 2026-05-27 was hand-deployed via SSM. The team had unknowingly traded "automated CI/CD" for "manual SSM commands hidden in conversation transcripts" — no audit trail in GitHub, no health check after deploy, no notifications on failure, easy to forget a step. This entry restores the CI/CD invariant: push to `dev` → deploy happens → health-checked → reported in GitHub.

Also: the deploy workflow had been pointing at a dead host for 6 days and nobody noticed because no one looked at GitHub Actions during the AWS migration. The new workflows include a `/healthz` curl step that fails loudly if the deploy didn't actually take effect — so future "looks deployed but didn't" bugs surface immediately.

### Why GH Actions + SSM over CodeDeploy / Jenkins / OIDC-on-day-one

User explicitly evaluated:
- **CodeDeploy + CodePipeline** — better fit at ≥3 envs or for blue/green, but ~3-4 hr setup (agent on each EC2, deployment groups, lifecycle hooks, S3 revision bucket). For 2 EC2s it's strictly more plumbing for marginal gain.
- **Jenkins** — right at 20+ services across multiple teams; wrong at this scale. Would cost more in maintenance ops than the deploys save.
- **ArgoCD/Flux** — only relevant if we move to EKS.
- **GH Actions + OIDC from day one** — better security posture (no long-lived keys), but adds ~45 min to set up the GitHub OIDC provider in IAM + role trust policy. User picked "long-lived keys now, OIDC later" to ship faster. OIDC migration tracked as a follow-up.

Rule of thumb encoded: **the right CI/CD tool scales with team size and deploy frequency, not project ambition.** Move to CodeDeploy when env count outgrows GH Actions; don't move to Jenkins ever (operational burden too high for our scale).

### Files changed

- `.github/workflows/deploy-dev.yml` (rewritten)
- `.github/workflows/deploy-qa.yml` (new)
- IAM resources (AWS, account `449901518037`):
  - User `github-actions-deploy` (programmatic only, tagged `Purpose=ci-cd`)
  - Inline policy `DeployViaSSM`
  - Access key (surfaced to user once; he pastes into GH Secrets)

### Commit

- `028ee6a` ci(deploy): SSM-based deploy workflows for dev + qa

### Branch state after this entry

| Branch | Tip | Deployed to |
|---|---|---|
| `feature/digital-twin` | `0769c2d` (1 behind dev, no longer load-bearing) | nothing |
| `dev` | `028ee6a` | dev.qongsystems.com (manual SSM this round; auto-deploy after secrets are pasted) |
| `main` | `028ee6a` | nothing (no deploy wired — intentional) |

QA EC2 (`i-04be6af1fb7929a0c`) switched from `feature/digital-twin` to tracking `dev`. Future QA deploys are manual via `workflow_dispatch` in the Actions UI.

### Follow-ups

1. **User**: paste `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` into Qong-Systems/qong_product → Settings → Secrets → Actions.
2. **Verify**: re-run the deploy-dev workflow (workflow_dispatch) to confirm credentials work. The push of `028ee6a` will have already triggered the workflow once and failed (no secrets yet) — that red ✗ in Actions history is expected, ignore it.
3. **Migrate to OIDC** (queued separately): replace long-lived access keys with GitHub OIDC trust → IAM role. ~1 hr.
4. **deploy-prod.yml** when `app.qongsystems.com` infra is up — same SSM mechanism, gated by GitHub Environments with required-reviewer approval. Manual approval gate before any prod deploy fires.

---

## [2026-06-02] #23 — Label Studio exposed on ls-dev.qongsystems.com; all GCP LS data preserved

**Type:** feature | infra
**Stage:** infra | webapp
**Status:** shipped

**Why:** After the AWS cutover (FEATURES #21), Label Studio was running on dev (docker container `qong-label-studio-1` healthy, bound to `127.0.0.1:8080`) but not externally reachable — the dev nginx config copied from QA only proxies `/healthz` + `/` to the FastAPI webapp, with no `/ls/` location. User asked: "we should have label studio hosted on dev, is it removed?". Answer: no, just unrouted. This entry sets up a clean subdomain `ls-dev.qongsystems.com` rather than path-mounting at `/ls/` on the main hostname (which would conflict with FastAPI's own `/api/*` routes — the local-dev docker nginx config handles this with multiple proxy_pass blocks but it's brittle).

**What:**

1. **New nginx vhost `qong-dev-ls`** at `/etc/nginx/sites-available/qong-dev-ls` on EC2 `i-0e7b89bd91b67a291`. Mirrors the main `qong-dev` site's posture (CF Origin Cert + CF IP allowlist + 600s read timeout for long-running label-stream uploads) but proxies `/` to `http://127.0.0.1:8080` (the LS container). Symlink in `/etc/nginx/sites-enabled/`. `client_max_body_size 500M` for LS's image/video uploads.

2. **Cloudflare DNS:** User added an `A` record `ls-dev.qongsystems.com → 13.204.52.248` (proxied / orange-cloud). CF Origin Cert (`*.qongsystems.com` SAN) covers the subdomain — no new cert work needed.

3. **`docker-compose.override.dev.yml` now committed to the repo** (was previously only generated on the EC2 during bootstrap). Adds the `label-studio.environment.LABEL_STUDIO_HOST` override to `https://ls-dev.qongsystems.com`. The base compose ships `LABEL_STUDIO_HOST=https://dev.qongsystems.com/ls` (a path-based local-dev artifact); on AWS dev that value causes LS to generate `/ls/user/login` redirects that 404 because the dev nginx doesn't proxy `/ls/`.

4. **Label Studio data fully preserved from GCP.** The PostgreSQL dump restored in Phase 2 (FEATURES #21) included the `label_studio` database — all 6 users (`tnb@qongsystems.com`, `admin@qong.com`, plus 4 team members), 28 projects, 819 tasks, 826 annotations were present on dev as soon as LS started. LS uses Django's PBKDF2-hashed passwords stored in `htx_user.password`; passwords carried over verbatim so the team logs in with their original GCP credentials.

**Result (if measurable):**
- `https://ls-dev.qongsystems.com/` returns `302 Location: /user/login/` then `200` on the login page (LS's normal anonymous flow). Playwright snapshot shows the LS branding, "Log in" form, and "Brought to you by Human Signal" footer. No 404, no path-prefix weirdness.
- `https://ls-dev.qongsystems.com/health/` returns `200`.
- `label_studio` DB row counts on dev: **6 users, 28 projects, 819 tasks, 826 annotations** — identical to the source GCP DB.
- LS container env after the recreate: `LABEL_STUDIO_HOST=https://ls-dev.qongsystems.com` (no `/ls/`).
- Both the main `dev.qongsystems.com` and the new `ls-dev.qongsystems.com` are CF-IP-allowlisted at nginx — direct IP access still gets 403, and bare-IP redirects (FEATURES #22) still apply.

**Notes:**
- *QA does NOT get this treatment.* User explicitly said "we dont this on QA. only for Dev instance." If QA needs LS exposed later, mirror this exact pattern with `ls-qa.qongsystems.com` (cert + nginx vhost + override.qa.yml env + CF DNS).
- *LS expects to own its entire hostname.* No path rewrites needed because the subdomain owns the whole URL space. If anyone ever tries path-based hosting (`/ls/` on the main domain), expect to ALSO proxy `/api/`, `/static/`, `/websocket/`, `/react-app/` to LS — which collides with the FastAPI app's `/api/v1/*`. Avoid.
- *No fresh admin account was created on dev's LS.* The existing GCP-era admin (`tnb@qongsystems.com` with `is_staff=true`, or `admin@qong.com` with `is_staff=true`) logs in normally. If the original LS password is forgotten, reset via Django shell in the container: `docker compose exec label-studio python3 -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.label_studio'); django.setup(); from users.models import User; u=User.objects.get(email='tnb@qongsystems.com'); u.set_password('newpass'); u.save()"`.
- *Bootstrap script gap:* `docker-compose.override.dev.yml` is now in the repo, but `bootstrap_1.sh` (which the EC2 ran during provisioning) wrote the file inline via `tee` instead of `cp` from the repo. If we ever re-provision, prefer reading from the repo so the LS override and any future changes flow into the new EC2 automatically. Tracked as a follow-up improvement.
- *LS's `LS_EXTERNAL_URL=https://ls-dev.qongsystems.com`* was also added to `.env.dev` for the webapp (the webapp uses this env var to build links to LS in the annotator UI). Different env var, different consumer than `LABEL_STUDIO_HOST`.

---

## [2026-06-02] #22 — SPA marketing pages removed; IP-direct access redirects; GCP VMs stopped

**Type:** feature | infra | decision
**Stage:** webapp | infra
**Status:** shipped

**Why:** Three threads converged in the tail end of the AWS-migration session. (1) User wanted `dev.qongsystems.com` to be engineering-app-only — "we don't need any UI like home, about, contact pages on this instance … we will have first page as login page and then our studio will start. website is already hosted on diff server". (2) User noticed origins are reachable by bare-IP and asked to "check and redirect but don't allow IP opening directly in browser". (3) With the AWS cutover live (FEATURES #21), the GCP VMs were burning ~$60/mo for nothing — user asked to stop them. None of these are dramatic in isolation but each tightened the production posture and saved real money.

**What:**

1. **Marketing pages deleted from the SPA** (commit `9fb2692`):
   - DELETE `webapp/frontend/src/marketing/` (7 files: `Drive.tsx`, `Footer.tsx`, `Hero.tsx`, `MarketingNav.tsx`, `Sections.tsx`, `Social.tsx`, `marketing.css`)
   - DELETE `webapp/frontend/src/routes/Home.tsx` (was the marketing landing — Hero + Sections + Footer composition)
   - NEW `webapp/frontend/src/routes/RootRedirect.tsx`: calls `useAuth()`, waits for the loading flag to settle, then `<Navigate replace>` to `/dashboard` if there's a session or `/signin` if anon
   - `App.tsx`: `<Route index>` swapped from `<Home />` → `<RootRedirect />`
   - `Layout.tsx`: dropped `/` from `FULL_BLEED_EXACT` since the root now renders nothing (the redirect fires immediately after auth resolves)
   - `Login.tsx`: "Request access" CTA changed from `<Link to="/">` (which would now bounce visitors back to /signin in a feels-like-loop) to `<a href="https://qongsystems.com" target="_blank">` — points at the external marketing site
   - `RequireAuth.tsx` docstring no longer references "marketing /"
   - Unused `Link` import dropped from `Login.tsx`

2. **IP-direct access redirects to the canonical hostname** (nginx-only, no code in repo):
   - Both dev and QA `nginx` `default_server` blocks rewritten on the EC2 hosts (idempotent overwrite, after a first-attempt regex-strip left duplicate `default_server` lines and broke `nginx -t`).
   - New behaviour: any request hitting the bare EIP (or with a wrong/empty Host header) returns `301 Location: https://{dev|qa}.qongsystems.com$request_uri`. Replaces the prior `return 444` silent connection drop.
   - Cert presented for HTTPS-via-IP is `*.qongsystems.com` (the CF Origin Cert from `/etc/ssl/qong-{env}/origin.crt`); browsers show a name-mismatch warning before the redirect, which is acceptable friction since CF-fronted access is the supported path.
   - Verified externally from a non-CF IP (my mac): `http://13.204.52.248/` → 301, `https://13.204.52.248/` → 301, both pointing at `https://dev.qongsystems.com/`. QA HTTP-via-IP is also closed at the SG level (port 80 not open on QA's `sg-0ece96660d8ee00bc`), so it times out instead of redirecting — defense in depth.

3. **GCP VMs stopped** (no code; gcloud state change):
   - `gcloud compute instances stop qong-dev-server qong-intake-server --zone=asia-southeast1-c`
   - Both VMs in TERMINATED state. Disks persist (~$2.40/mo for the 50 GB dev disk + ~$1/mo for the 20 GB intake disk). Daily snapshots continue. GCS buckets `qong-backups` + `qong-intake-data` untouched.
   - GCP ephemeral external IPs released on stop — if VMs restart, new IPs will be assigned. The Cloudflare A-record currently points at the AWS EIP `13.204.52.248`, so the GCP IPs being different on restart is irrelevant for rollback (we'd just update CF to whatever the new IP is).

4. **Dev super_admin password reset** (post-`pg_dumpall`-restore housekeeping):
   - The dev Postgres was restored from the GCP dump on 2026-06-02 (FEATURES #21 Phase 2). The `users` table preserved the GCP-era bcrypt hashes for all 8 users including `admin`, but the GCP `admin` password was unknown to me (it had been set on the old dev VM before this session began).
   - Reset via `docker compose exec web python3` calling `webapp.auth.hash_password(...)`. Saved as `reference_dev_admin_password.md` in user auto-memory.

**Result (if measurable):**
- Live SPA bundle on both dev and QA: `index-COLjBvIo.js`, **0 occurrences of "About" / marketing strings** (verified via `curl + grep`). Previous QA bundle `index-ChMrWMB0.js` had 4× "About".
- Playwright on `https://dev.qongsystems.com/`: anonymous visit redirects to `/signin` (full-bleed, no app header), `hasMarketingNav: false`, "Request access" link points at `https://qongsystems.com`, `window.__QONG_BUILD__ === "9fb2692"`.
- Origin redirect verified from my mac (non-CF IP):
  - `http://13.204.52.248/` → `301 https://dev.qongsystems.com/`
  - `https://13.204.52.248/` (k) → `301 https://dev.qongsystems.com/`
  - `https://43.205.96.86/` (k) → `301 https://qa.qongsystems.com/`
  - `http://43.205.96.86/` → timeout (SG closed on 80 for QA)
- Cost delta: **−$60/mo** (GCP compute → $0, disks/snapshots stay at ~$2.50/mo). Net total monthly run-rate: ~$74/mo (was ~$102/mo at session start, +$36/mo for the new AWS dev EC2 since session start, −$63/mo from stopping GCP).
- Dev admin auth verified end-to-end through Cloudflare: `POST /login` → 303 → `/dashboard`, then `GET /api/v1/account` returns `{id: 1, username: "admin", role: "super_admin", credits_remaining: 999, tier: "enterprise"}` (data exactly as it was on GCP).

**Notes:**
- *Login page's left brand panel is still there.* `Login.tsx` renders a two-pane screen — sign-in form on the right, brand panel on the left with the "Read your P&ID. Generate the rest." headline + a `Live Extraction · Demo` tile (FT-201 / PT-101 / etc.) + version chip. The user hasn't asked for that to go (yet); if they do, the left `<aside class="login-brand">` block is the surgical removal target. Tracked as a future option in SESSION_STATE.
- *nginx configs live on the EC2 hosts, NOT in this repo.* If we ever rebuild from scratch we'll need to recreate them from the `docs/superpowers/specs/2026-05-29-aws-qa-environment-design.md` notes or extract from the running hosts via SSM. Worth a future refactor: ship the canonical configs at `deploy/nginx/qong-{env}.conf` and have the EC2 user-data script `cp` them at boot.
- *The first nginx-rewrite attempt left duplicate `default_server` lines.* The Python script used a regex that matched `# Block bare-IP` comment headers; dev's nginx config had the bare blocks WITHOUT the comment, so the strip-and-replace became append-only. nginx -t failed, `systemctl reload` was rejected, and the old `return 444` config kept serving traffic — masking the fact that nothing had changed until the external curl test surfaced it. **Lesson:** for nginx config edits, prefer idempotent full-file rewrites over regex-stitching.
- *GCP rollback path is still open* and explicitly tested in this session's exit notes. To roll back: `gcloud compute instances start qong-dev-server qong-intake-server` (new ephemeral IPs), then update the Cloudflare A-record for `dev.qongsystems.com` from `13.204.52.248` to the new GCP IP. The AWS dev box can be left running as a warm secondary or stopped to save costs while GCP is primary.
- *Memory file added for dev admin* — `reference_dev_admin_password.md` joins the local + QA admin reference files. The MEMORY.md index lists all three.
- *Phase 4 (GCP decommission) deliberately deferred.* The 7-day soak window is conservative; we could shorten if we trust the rollback path won't be needed. The GCP daily snapshots will keep accumulating until Phase 4 deletes them.

---

## [2026-06-02] #21 — AWS migration Phases 1-3: dev moved from GCP to AWS; DNS cut over

**Type:** infra
**Stage:** infra
**Status:** shipped

**Why:** Continuation of FEATURES #20 (Phase 0 backup). User authorised "if we got the dev backup, go and finish all phases and validate on aws. give me new IP, i will change on cloudflare and we will mark this migration as complete". Since dev has no real customers and the QA pattern was already proven over the prior 2 days, this was an autonomous straight-line build + cutover.

**What:** dev.qongsystems.com now runs on AWS, mirroring the QA pattern in ap-south-1.

**Phase 1 — Provision AWS dev:**
- Security Group `sg-0ad6bfa98b1e06969` (`qong-dev-web`): tcp/443 + tcp/80 from 0.0.0.0/0 (CF allowlist enforced at nginx, not SG).
- Elastic IP `13.204.52.248` allocated + associated → stable IP for Cloudflare A-record across EC2 restarts. Free while attached.
- EC2 `i-0e7b89bd91b67a291` (`qong-dev-server`): t3.medium, AMI `ami-0c54f8b78468b2ba2` (same as QA), `subnet-0eecf25001fad5cc9` in `ap-south-1a`, IAM `may26-ec2-ssm-role`, no key pair (SSM-only access), IMDSv2 required.
- 30 GB encrypted gp3 root + 50 GB encrypted gp3 data EBS (`vol-00152abd9fa8f1bf8`) attached as `/dev/sdf`, formatted ext4, mounted at `/mnt/qong-data` via UUID-pinned fstab entry.
- 7 SSM SecureString params under `/may26aws/qong-dev/`: `openrouter-api-key` (reuses the QA value), `secret-key`, `ls-api-key`, `postgres-password`, `redis-password`, `minio-root-user`, `minio-root-password`. All freshly generated with `openssl rand -hex` — guaranteed alphanumeric only, so no shell-special-char surprises like the `$wrv` SECRET_KEY corruption that FEATURES #19 documented for QA.

**Phase 1B — VM bootstrap (via SSM RunCommand):**
- apt installed docker.io, docker-compose-v2, git, jq, python3-boto3, unzip, curl
- AWS CLI v2 installed via the official `awscli-exe-linux-x86_64.zip` (Ubuntu 24.04 dropped `awscli` from apt — fix added)
- Reused QA's `qong-deploy` SSH key + ssh config via SSM-fetch from QA, base64-piped to dev. Both EC2s now share the same GitHub deploy key (acceptable for dev/QA scope; dev-only or QA-only rotation is a future option).
- Repo cloned at `c7a8928` (`feature/digital-twin`) to `/opt/qong` (owned by ubuntu).
- `git config --system --add safe.directory /opt/qong` so SSM RunCommand (running as root) can operate on the repo without "dubious ownership" errors.
- `.env.dev` rendered from SSM via a Python script that fetches all 7 params with `boto3.client("ssm").get_parameters_by_path`, then escapes `$` → `$$` for Compose interpolation safety. The full file is written to `/opt/qong/.env.dev` with mode 600.
- `docker-compose.override.dev.yml` written: web binds to `127.0.0.1:8000` (not host 80), data volumes point at `/mnt/qong-data/{uploads,job_outputs,postgres,minio}`, disables `nginx`/`label-studio-mcp`/`trainer` services with `profiles: [disabled]`.

**Phase 2 — Storage cutover (GCS → S3, restore from archive):**
- The dev EC2 role couldn't read the new archive bucket out of the box; added a bucket policy on `qong-pid-archive-2026-06-02` granting `s3:GetObject` + `s3:ListBucket` to `arn:aws:iam::449901518037:role/may26-ec2-ssm-role`. Identity-policy-on-shared-IAM-role left untouched.
- Restore sequence on the new EC2:
  1. `docker compose build web` with `BUILD_ID=$(git rev-parse --short HEAD)` baked into `__QONG_BUILD__` via the Vite define (FEATURES #19 queue-item B mechanism).
  2. `up -d postgres redis`, wait for `pg_isready`.
  3. `aws s3 cp s3://.../db-dumps/qong-dev-postgres-2026-06-02.sql` → `psql -U qong -d postgres -v ON_ERROR_STOP=0 < dump.sql`. Errors about pre-existing `qong` role and `qong` database are expected and ignored; data tables load into the qong DB. Verified: **8 users, 43 jobs, 706 valve_rows** — exact match with the GCP source.
  4. `aws s3 cp s3://.../vm-tarballs/qong-vm-data-2026-06-02.tar.gz` → `tar xzf -C /mnt/qong-data`. Verified: **44 PDFs in /mnt/qong-data/uploads** (matches the freshest VM-disk count, +4 over GCS qong-backups).
  5. `up -d --no-build web minio label-studio cpu-worker`.
- **Bug surfaced + fixed:** After the pg_dumpall restore, the `qong` role's password was reset to the **GCP value** (from the dump's `ALTER ROLE ... WITH ENCRYPTED PASSWORD ...` line), which no longer matched the freshly-generated SSM password in `.env.dev`. Web crashed in a loop with `psycopg2.OperationalError: password authentication failed for user "qong"`. Fixed: `ALTER ROLE qong WITH PASSWORD '<ssm-value>'` from a `psql -U qong` connection. Web recovered immediately on restart. **Lesson: pg_dumpall's ALTER ROLE statements overwrite role passwords on the target — restore order matters when the new env has fresh credentials. Either restore *before* changing the password, or run an ALTER ROLE re-sync after.**

**Phase 3 — TLS + DNS cutover:**
- Host nginx 1.24 installed on dev EC2. Cloudflare Origin Certificate + private key + `cloudflare-ips.conf` copied verbatim from QA via SSM (cert covers `*.qongsystems.com` so it works for both subdomains). nginx site `qong-dev` configured identically to QA's `qong-qa` (TLS termination on 443, CF IP allowlist via `include` + `deny all`, `proxy_pass http://127.0.0.1:8000`, `client_max_body_size 100M`, websocket + long-poll headers, 600s read timeout for PDF endpoints).
- docker `web` rebound from `0.0.0.0:80:8000` → `127.0.0.1:8000:8000` (host nginx now fronts it).
- User updated the Cloudflare A-record for `dev.qongsystems.com` → `13.204.52.248`.
- Validation: `curl https://dev.qongsystems.com/healthz` → **HTTP 200** through CF edge → CF Full (Strict) → origin TLS (CF Origin Cert) → nginx → docker web → FastAPI. Direct origin probe with non-CF IP returns 403 (nginx allowlist working).

**Result:**
- dev.qongsystems.com live on AWS with same security posture as QA (CF Full Strict, allowlist, AES256 SSM secrets, no SSH ingress).
- GCP `qong-dev-server` still running but unused for traffic. 7-day soak begins; decommission tracked as Phase 4 (FEATURES TBD).
- Cost: ~$36/mo running (t3.medium + 30 GB root + 50 GB data + EIP free while attached) + the ~$0.06/mo archive bucket from #20. QA continues at its own ~$36/mo. Total: ~$72/mo AWS + decaying GCP cost until #20 Phase 4.

**Notes:**
- *Many small footguns surfaced and were fixed in-line.* In rough order: SG description rejected unicode em-dash; bash `set -e` didn't trigger on a failed run-instances captured into `EC2=$(...)`; the wrong instance ID was looked up via a stray `Reservations[0]` query (turned out to be `may26-ollama`, harmlessly); `awscli` no longer in apt on 24.04; `lsblk` awk column counting was wrong for empty MOUNTPOINT; `git` refused root operations on ubuntu-owned `/opt/qong`; SSM RunCommand stdout truncates at ~24KB (lost the tail of the long bootstrap output); `may26-ec2-ssm-role` lacked S3 perms for the new archive bucket; pg_dumpall ALTER ROLE overwrote password; CF Full Strict needs origin TLS not HTTP. All resolved within this session.
- *Repo deploy key shared with QA.* Both EC2s use the same `qong-deploy` private key for `git@qong-product:Qong-Systems/qong_product.git`. Acceptable for dev+QA scope. Rotation would require regenerating + adding both as separate GitHub deploy keys, or moving to a deploy token; deferred.
- *cpu-worker reported "already exists" image conflict* during `up -d` but the container is running fine. Investigated only briefly — likely a docker buildx parallel-build noise that doesn't affect runtime. Tracked as a low-priority follow-up.
- *Port 80 still open in the SG* — used during bootstrap before nginx took 443; should be closed before any real users. Tracked in queue items.
- *GCP rollback path intact:* the original `qong-dev-server` VM is still running on GCP. To roll back: change Cloudflare A-record back to `34.126.93.103` (the GCP IP). The dump-restore on AWS doesn't mutate GCP at all. The 7-day soak window is conservative; could shorten if comfortable.

---

## [2026-06-02] #20 — AWS migration Phase 0: full GCP PID-doc backup to S3 (3-way redundancy)

**Type:** infra | decision
**Stage:** infra
**Status:** shipped

**Why:** User asked to move the `dev` environment from GCP to AWS (consolidating to the same `tnbqong` AWS account that already hosts QA), plus migrate GCP Cloud Storage to S3. Explicit prerequisite: "before that make sure, we have save all our PID docs. so we can begin with those PID on new AWS server." This entry covers Phase 0 only — the pre-migration safety backup. Phases 1-4 (provision AWS dev, migrate storage, cutover DNS, decommission GCP) are tracked in SESSION_STATE queue items and will get their own FEATURES entries when shipped.

**What:** Inventoried the GCP env, then created a 3-way-redundant backup of every PID-related byte before touching anything on the source.

GCP source state at backup time:
- VM `qong-dev-server` (e2-standard-2 + 50 GB disk, asia-southeast1-c) serving https://dev.qongsystems.com — Postgres `qong` DB has **8 users, 43 jobs, 706 valve rows**.
- VM `qong-intake-server` (e2-small + 20 GB) — separate intake service.
- GCS `gs://qong-backups/` — 502 MB across `uploads/` (40 PDFs, 34 MB), `job_outputs/` (2,892 files, 423 MB), `models/` (45 MB), `postgres/` (59 KB legacy dump).
- GCS `gs://qong-intake-data/` — 37 MB, 3 PDFs from the intake server.
- AWS S3 in `449901518037` had **zero buckets** — clean slate.

**Important finding during inventory:** the VM's `/app/qong_poc/uploads/` (44 PDFs, 39 MB) and `/app/qong_poc/job_outputs/` (3,089 files, 837 MB) **contain more data than the GCS qong-backups bucket** (+4 PDFs, +197 files, ~+414 MB). The GCS bucket is a partial historical archive, not a complete mirror. Without the VM tarball below, those newest files would only exist on the VM disk (and the daily disk snapshots).

3-way redundancy achieved:

1. **Fresh GCP disk snapshot** — `qong-dev-server-pre-aws-cutover-20260602-151219` (50 GB logical, 28.9 GB storage). Captures the entire `/app/qong_poc/` tree plus docker volumes (postgres, minio, label_studio) at the moment of the migration kickoff. Restore path: create a new disk from this snapshot, mount, extract whatever's needed.

2. **GCS unchanged** — both buckets left intact for now; will be deleted in Phase 4 only after the AWS dev environment has been validated for 7+ days.

3. **New S3 archive** — `s3://qong-pid-archive-2026-06-02` in `ap-south-1`, AES256 (SSE-S3), versioning enabled, public access blocked. Contents:
   - `MANIFEST.json` — full inventory with SHA256s, sizes, restore instructions
   - `db-dumps/qong-dev-postgres-2026-06-02.sql` — 10.5 MB `pg_dumpall` (databases: `qong`, `label_studio`, `postgres`; source user `qong`); SHA256 `6f3027b5b37b3519792a3807f0b6a7347a5d1ae3ee12fd7e52065daa521d28aa`
   - `vm-tarballs/qong-vm-data-2026-06-02.tar.gz` — 531 MB gzipped tar of `uploads/` + `job_outputs/` (3,225 entries); SHA256 `f3e0bb39ccab17dcc8a063f0e3d2758e5ffa7119f7fbf7f35d5301a633cc9f30`
   - `gcs-qong-backups/` — verbatim copy of `gs://qong-backups/` (2,935 objects, 502,091,044 bytes exact byte match)
   - `gcs-qong-intake-data/` — verbatim copy of `gs://qong-intake-data/` (3 objects, 37,539,001 bytes exact byte match)
   - **Total:** 2,941 objects, 1.08 GB

**Result:**
- Spot-check verification: 5 random PDFs from `gcs-qong-backups/uploads/` — MD5 from GCS source matches base64-decoded S3 ETag for all 5. **0 mismatches across 5 random samples**.
- Cost: <$0.10 one-time egress, ~$0.06/mo recurring (S3 storage + snapshot incremental).
- Time: ~25 min wall clock from `aws s3api create-bucket` to verified manifest, including the SCP-via-IAP false-start (see Notes).

**Notes:**
- **EC2 deploy-key gotcha is also live for the dev VM via a different mechanism**: the new dev VM (Phase 1) will need the same `qong-product` SSH alias setup that QA needed (FEATURES #19 Part 4). Document during Phase 1.
- **Don't use `gcloud compute scp` for files > ~50 MB through IAP**. Threw the IAP tunnel at ~0.3 MB/s and stalled at 8% (42 MB of 531 MB). Killed it after ~2 minutes; rerouted via GCS: `gcloud storage cp` from VM to GCS ran at **128 MB/s** (literally 400× faster), then GCS → local at 16 MB/s, then local → S3 at ~30 MB/s. **Lesson: IAP tunnels are for `ssh` and small transfers; large transfers should go via GCS or direct EC2-side `aws s3 cp` when the VM has credentials.** Added to gotchas.
- **The `qong-intake-server` VM was NOT backed up** beyond the GCS `qong-intake-data` bucket. If that server holds state beyond the 3 PDFs in the bucket, capture before Phase 4 decommission.
- **Postgres dump captured `qong` + `label_studio` + globals** via `pg_dumpall`. Restore on the new AWS Postgres: `psql -U <new_user> < qong-dev-postgres-2026-06-02.sql`. The `\restrict` line at the top is a PostgreSQL 17 dump-format token; should restore cleanly on PG ≥ 16.
- **Pre-existing daily disk snapshots** (5/20 onwards) remain in GCP and will be kept until Phase 4. They are NOT in the new S3 archive — they're disk-level, not file-level, so cost more to keep around. The new snapshot taken this session is the canonical "pre-cutover" rollback point.
- The user picked the "Yes, execute Phase 0 as above" option from a 4-way menu (default plan; not the smaller "skip intake-data" variant). All scope kept.

---

## [2026-06-02] #19 — Jinja → SPA consistency sweep; public signup removed; 4 surfaces ported

**Type:** architecture | feature | bugfix
**Stage:** webapp
**Status:** shipped

**Why:** Two user asks converged: (a) "we don't need public signup — remove the /register URL", and (b) "remove any pending jinja form from our app … make new in SPA, to have consistent app". The pre-existing Jinja surface had drifted into a hybrid state — the React SPA covered /dashboard, /projects, /jobs, /admin/*, but user-facing /account, /account/api-keys, /account/billing, and /feedback were still Jinja form-POSTs against `webapp/templates/*`. Clicking "Account" in the SPA's AccountMenu navigated to a Jinja-rendered page, which is a UX inconsistency and a maintenance trap (two divergent UI stacks for a single product surface). Public /register was also still exposed at the HTTP layer despite the React Admin UI's `CreateUserModal` shipping in Phase 3 — meaning the same admin-creates-user flow existed twice (Jinja form-POST and the SPA's POST /api/v1/admin/users), with the public arm an unwanted attack surface.

**What:** Three-stage sweep on `feature/digital-twin`, two commits (`e84ccb6`, `0e846d3`):

1. **Public signup + Jinja /login removed** (`e84ccb6`):
   - DELETE `webapp/routers/auth.py` @router.get/post('/register')
   - DELETE `webapp/templates/{register,login}.html`
   - GET /login → 303 redirect to /signin (legacy bookmark compat only)
   - POST /login: error path returns JSON `{detail: ...}` (was Jinja-rendered HTML); SPA's `AuthContext.tsx` updated to parse JSON instead of regex-scraping `class="error-box"`
   - GET /logout: redirects to /signin (was /login)
   - `webapp/auth.py`: unauth-middleware 303 Location header /login → /signin (4 callsites)
   - `webapp/templates/base.html`: navbar "Login" link /login → /signin
   - `tests/e2e/test_admin_api.py` assertion updated to /signin
   - First-user bootstrap on a fresh DB is now a one-off SSM-direct SQLAlchemy script (template kept in 2026-06-02 session memory; pattern used to create QA's super_admin `tarun` after deleting the smoke user `qa-smoke-2026-06-01` via cascade-delete on `credit_transactions`).

2. **Account, API Keys, Billing, Feedback ported to SPA** (`0e846d3`):
   - Backend (`webapp/routers/api_v1.py`):
     - GET `/api/v1/account/transactions` — recent credit txns for current user
     - GET `/api/v1/account/api-keys` — list non-revoked keys (never exposes full value)
     - POST `/api/v1/account/api-keys` — create with one-time plaintext reveal in JSON body
     - DELETE `/api/v1/account/api-keys/{id}` — revoke (204; user-scoped, 404 on other-user-key)
     - GET `/api/v1/account/billing` — balance + tier + active plans
     - POST `/api/v1/feedback` — anon-allowed; same javascript:/data:/vbscript: page_url scrub as the pre-existing Jinja handler
   - Frontend:
     - `webapp/frontend/src/account/{api,types}.ts` — typed call helpers mirroring `admin/api.ts`
     - `webapp/frontend/src/routes/Account.tsx` — profile + transactions + billing combined
     - `webapp/frontend/src/routes/AccountApiKeys.tsx` — list + create-with-reveal + revoke (with copy-to-clipboard, dismiss-acknowledgement, and a "this is the only time" warning)
     - `webapp/frontend/src/routes/Feedback.tsx` — bug/feature/pricing/other form
     - `App.tsx`: 3 new authed routes mounted
     - `AccountMenu.tsx`: replaced "Shortcuts" + "Notifications" placeholders with real "API Keys" + "Send feedback" links
     - `dashboard/CreateProjectModal.tsx`: error-hint copy `/account/billing` → `/account`
   - Deleted: `webapp/routers/account.py` (entire file); `webapp/templates/account/{index,api_keys,billing}.html`; `webapp/templates/feedback.html`. `webapp/main.py` no longer imports `account_router`.
   - Security tests migrated:
     - `tests/unit/test_feedback_url_xss.py` ports the 9 hostile-URL parametrised cases (javascript:, data:, vbscript:, file:, ftp:, protocol-relative, JS-with-fake-netloc) to POST /api/v1/feedback. Status 200 → 201.
     - `tests/unit/test_account_api_keys.py` rewritten for JSON endpoints; **added two new security tests**: (1) GET /account/api-keys list response never contains the full key (only the 8-char prefix), and (2) DELETE another user's key returns 404 (not 403), matching the user-scoped query in `api_v1.py` — 403 would leak existence.
   - Lingering Jinja: only `annotate.html` + `base.html` (its host layout). Intentional per `webapp/routers/annotate.py:5` — "React SPA covers only customer-facing + super_admin surfaces; annotators get the legacy Jinja page". Confirmed kept by the user during the inventory pass.

3. **EC2 deploy-path latent bug fixed** during the QA deploy: `/opt/qong/.git/config` had `origin = git@github.com:Qong-Systems/qong_product.git` (bare GitHub host), but the deploy key was registered against the `qong-product` SSH alias in `~ubuntu/.ssh/config`. `git pull` had been silently failing with "Permission denied (publickey)" — the prior FEATURES #17 / #18 deploys appear to have relied on host-side `npm run build` + bind-mount rather than a real git-pull. Fixed once with `git remote set-url origin git@qong-product:Qong-Systems/qong_product.git`. Future deploys via SSM RunCommand → `sudo -i -u ubuntu git pull` now work without intervention.

**Result (if measurable):** Playwright-verified on `https://qa.qongsystems.com` end-to-end:
- `GET /register` → SPA "404 - This page doesn't exist." (no Jinja form anywhere)
- `GET /login` → 303 → `/signin` (SPA login renders)
- `POST /login` with bad creds → `400 application/json` `{"detail":"Invalid username or password"}` parsed by SPA AuthContext
- Login `tarun / CzlYN5pah7z5Dvbr` → 303 → `/dashboard`
- `GET /logout` → 303 → `/signin`, cookie cleared, subsequent `/api/v1/account` → 401
- `/account` SPA: shows profile + 1 txn row (`initial_admin_grant +10 → 20`) + 3 plans (Trial $0, Starter $19, Pro $149)
- `/account/api-keys` SPA: created `playwright-qa-smoke` → revealed `qk_24a9e2515760a01684c07034fb5fff3c` (32 hex, correct shape) → Bearer-authed against `/api/v1/account` returning `{"username":"tarun","role":"super_admin"}` → revoked → cookie-isolated Bearer retry returned 401 (revocation effective at auth layer, not just UI)
- `/feedback` SPA: submitted pricing-category form → 201 → "Thanks for your feedback!" banner. Hostile `page_url=javascript:alert(1)` curl-tested via SSM RunCommand on EC2 → DB row stored with `page_url=None` (security scrub holds across the port).
- AccountMenu popover items: `["Account", "API Keys", "Send feedback", "Sign out"]` — no more Shortcuts/Notifications placeholders.

**Notes:**
- *base.html still in tree* — only referenced by `annotate.html`. Becomes orphan-deletable the day the annotator surface gets ported to SPA (no current plan; out of SPA scope by design).
- *Pre-existing "20 credits on signup" bug surfaced* — the User model column default of 10 + `credits.grant(10, reason="signup_grant")` both fire at user creation, so the audit row's intent (just record the existing 10) ends up adding another 10. Not introduced by this work, just observed. Tracked as a follow-up; either drop the default-10 or stop double-granting.
- *`wrv` compose warning still benign* — surfaced again during this deploy. The compose interpolation `${wrv}` is somewhere in the docker-compose chain; harmless empty-string default. Low-priority cleanup.
- *RouterAuth tests not updated* — `webapp/frontend/src/auth/RequireAuth.test.tsx` already covered /signin redirection; no changes needed there. New SPA routes (Account, AccountApiKeys, Feedback) have NO unit tests yet — they rely on Playwright-on-QA verification documented above. Worth adding component tests if test parity with admin/*.test.tsx becomes a priority.
- *Admin-side feedback UI not retested* — the new Playwright feedback row should now appear in `/admin/feedback`. Eyeball check skipped for time; defer to next admin-feedback session.
- *AccountMenu no longer has Shortcuts / Notifications* — these were placeholders. If product wants them back, restore the buttons but route them somewhere real.

---

## [2026-06-01] #18 — QA SPA bootstrap fixed (Playwright caught what curl missed); 4 root-causes addressed

**Type:** bugfix
**Stage:** infra | webapp
**Status:** shipped

**Why:** After FEATURES #17 declared QA "live" (all HTTP smoke checks green), Playwright revealed the SPA was actually broken in real browsers: `/assets/index-Ck0HogSN.js` returned `text/html` instead of JavaScript, breaking the strict-MIME ES-module bootstrap. Four overlapping root-causes had to be unwound to fully fix it.

**What:**

1. **Import-time SPA mount gate (`webapp/main.py:148`)** — `if (_SPA_DIST/"assets").exists()` ran at module import. When web container started before `npm run build`, the mount was never registered, so the catch-all served `index.html` for every `/assets/*` URL. Fixed by mounting unconditionally with `StaticFiles(..., check_dir=False)` — missing files now return real 404s, not HTML-as-JS.

2. **Dockerfile didn't bake the SPA** — `webapp/frontend/dist/` is gitignored, Dockerfile had no node stage. Every deploy required a host-side `npm ci && npm run build` before `docker compose up`, easy to forget. Fixed with a multi-stage Dockerfile (`node:20-alpine AS frontend` builds dist, copied into the python runtime stage via `COPY --from=frontend`).

3. **Compose volume merge silently shadowed the baked dist** — Docker Compose CONCATENATES volume lists between base and override files (it does NOT replace them). Base `docker-compose.yml` had `./webapp:/app/webapp` for local-dev hot-reload; the QA override couldn't suppress it. Result: host `/opt/qong/webapp/frontend/dist` (empty) shadowed the baked dist from step #2. Fixed by moving dev bind-mounts out of base into a new `docker-compose.override.yml` (auto-loaded only when `docker compose up` is invoked without `-f`; explicit-`-f` QA stack skips it). Removed `docker-compose.override.yml` from `.gitignore` since it's now the canonical dev override; per-developer customization moves to `docker-compose.local.yml` (still gitignored).

4. **Cloudflare cached the broken text/html response under the JS asset URL** — CF auto-caches common static-asset extensions regardless of `Content-Type`. After fixing the origin, the cached HIT for `/assets/index-Ck0HogSN.js` continued serving the bad response. Fixed by adding a small `window.__QONG_BUILD__ = "2026-06-01T12:20Z"` side-effect in `webapp/frontend/src/main.tsx` — survives Vite minification (it's an assignment, not a comment), changes bundle bytes, produces a new content hash (`index-C_wqiXGd.js`), new asset URL, new CF cache key, MISS. Bump the date string in this line on any future incident where CF caches a wrong response under a hash we need to retire. Long-term, wire `BUILD_ID` via a vite `define` from a CI env var (deferred — see Notes).

Also **added `tests/smoke/qa_smoke.mjs`** — standalone Node ESM script using Playwright. Launches headless Chromium, asserts no unexpected console errors, no bad MIME types on `.js`/`.css` requests, no failed network requests, non-empty DOM. Filters the expected `/api/v1/account` 401 anonymous check. Header docs invocation in a future `deploy-qa.yml` workflow. Would have caught this entire bug class on the first deploy.

**Result (if measurable):** `https://qa.qongsystems.com/` loads cleanly in browser — `window.__QONG_BUILD__` reads `"2026-06-01T12:20Z"` (confirms users see the THIS-deploy bundle), React mounts, all asset MIME types correct, only the expected 401 in console.

**Notes:**
- The bind-mount-vs-baked-dist conflict is a one-time setup issue, not a runtime one — but the consequence is total SPA failure with no clear error in HTTP-level checks. The takeaway: any future post-deploy smoke MUST be browser-based, not curl-based. `tests/smoke/qa_smoke.mjs` enforces this.
- **`BUILD_ID` via CI env var** — proper long-term solution. Edit `vite.config.ts` to add `define: { __BUILD_ID__: JSON.stringify(process.env.BUILD_ID || "dev") }`. Reference it from `main.tsx`. CI passes `BUILD_ID=$GITHUB_SHA` per deploy → unique hash per commit, predictable per-source-state. Until that lands, the date-string in `main.tsx` is bumped by hand on demand.
- **Removed `docker-compose.override.yml` from .gitignore** — used to be per-developer local file; now it IS the canonical dev override (with the bind-mounts). Per-developer overrides go in `docker-compose.local.yml` (still gitignored).
- **Compose volume merge rule** is one of the gnarlier foot-guns. There's no documented way to suppress a base-defined volume from an override; the only workaround is structural (base = production-minimal, env-specific overrides add what each env needs). Future schema/refactor work should keep this invariant.

---

## [2026-06-01] #17 — AWS QA app live at qa.qongsystems.com; local stack switched from SQLite → Postgres

**Type:** infra
**Stage:** infra | webapp
**Status:** shipped

**Why:** Two threads converged this session. First, local was still on SQLite while production (`dev.qongsystems.com`) and QA (`qa.qongsystems.com`) both target Postgres — that mismatch meant Postgres-only bugs surfaced in QA after passing locally. Second, the AWS QA bring-up (FEATURES #16) was stuck on a placeholder OpenRouter SSM key. User set a real QA key, unblocking PHASE 2.

**What:**
- *Local stack:* `.env` populated with 9 missing keys (POSTGRES/REDIS/MINIO/STORAGE/GPU_CALLBACK), `DATABASE_URL=postgresql://qong:...@postgres:5432/qong`. New `postgres/init/01-create-label-studio-db.sql` runs on first Postgres boot to create the `label_studio` DB that Label Studio expects (compose's `POSTGRES_DB=qong` would otherwise leave it missing). `web` now has `depends_on: postgres (healthy) + redis (started)` so `run_migrations()` can't race. Tailscale port lines on web:8000 and redis:6379 commented out in base compose (no Tailscale on local Mac or AWS) — when this branch merges to `dev`, these need to come back for the GCP VM that talks to the Windows GPU box. Commits `4dd9d3e` and `b9e8def`.
- *QA bring-up:* OpenRouter SSM param replaced (Version 2). New `docker-compose.override.qa.yml` binds `/mnt/qong-data/{postgres,minio,uploads,job_outputs}` to the EBS data volume so QA data survives EC2 replacement, and disables `nginx` / `label-studio-mcp` / `trainer` services that conflict with host nginx or aren't needed in QA. `.env.qa` rendered on EC2 by SSM-driven script reading 7 SecureString params (added `/may26aws/qong-qa/redis-password` — spec missed it). AWS CLI v2 installed on EC2 (PHASE 1 bootstrap missed it). SPA built in-place via `npm ci && npm run build` (Dockerfile doesn't include a frontend build step — see Notes). nginx `qong-qa` site swapped from 503 placeholder to `proxy_pass http://127.0.0.1:8000` with `X-Forwarded-*` headers, WS upgrade headers, and 600s read timeout for long-running PDF endpoints.

**Result (if measurable):**
- `https://qa.qongsystems.com/healthz` → 200, `/` → 200 (SPA serving), `/api/v1/account` → 401 (auth gating works)
- Public registration round-trip succeeded; user landed in QA Postgres with `id=1, role=super_admin` (first-user auto-promotion in `webapp/routers/auth.py:107`)
- Build time on t3.medium: ~4 min docker compose build + ~50s npm install + 5s vite build = under 6 min total
- Marginal cost of this bring-up: <$0.10 (EC2 was already running)

**Notes:**
- *Dockerfile gap:* SPA build is not part of the image. Today it works because the bind-mount `./webapp:/app/webapp` exposes the host-built `dist/` to the container. Long-term fix: add a multi-stage Dockerfile that runs `npm ci && npm run build` in a node stage, then copies `dist/` into the python stage. Until then, every deploy must rebuild the SPA on-host before `docker compose up`.
- *Tailscale binding regression risk:* base `docker-compose.yml` no longer binds `100.127.190.88:*`. When merging `feature/digital-twin` → `dev`, restore those two `ports:` lines (or move them into a `docker-compose.override.dev.yml`) so the Windows GPU worker can still reach the GCP web container.
- *Smoke-test user `qa-smoke-2026-06-01`:* created as first user → got auto-promoted to super_admin. Real first human user on QA will NOT get admin — manually demote/delete the smoke user before onboarding real users.
- *Cloudflare Origin Cert rotation still pending* (private key was pasted in chat 2026-05-29). Limited blast radius (CF↔origin only, not public CA trust) but rotate when convenient.
- *Local admin password:* `admin` / `6GvVUz9HqaMeO1Bq` on `http://localhost:8000`. Saved in user auto-memory at `memory/reference_local_admin_password.md`. Local Postgres ≠ QA Postgres ≠ GCP dev Postgres — three independent DBs.

---

## [2026-05-30] #16 — AWS QA environment provisioned at qa.qongsystems.com (TLS live, app bring-up paused)

**Type:** infra
**Stage:** infra
**Status:** experimental — TLS live, docker compose not yet running

**Why:** `feature/digital-twin` is 14 commits ahead of `dev` (Phase 1–4 SPA cutover, deliverable reorder, admin port, %PDF- magic byte, two design specs). Deploying directly to `dev.qongsystems.com` on GCP risks current customers who use it for valve list extraction. Need a parallel URL to validate the branch end-to-end before promoting. AWS chosen because the team is migrating off GCP — QA also doubles as the AWS-learning lab. Cloud-agnostic shape (no RDS/ECS/ALB) so the pattern transfers cleanly to dev/prod later.

**What:** Single `t3.medium` EC2 (`i-04be6af1fb7929a0c`) in `ap-south-1`, IMDSv2-required, IAM role `may26-ec2-ssm-role`, public IP `43.205.96.86`, 30 GB encrypted root + 50 GB gp3 data EBS (`vol-06bdf1fab12bd2971`) at `/mnt/qong-data`. nginx 1.24 terminates TLS using a Cloudflare Origin Certificate (SAN `qa.qongsystems.com` + `*.qongsystems.com`, valid until 2041). Cloudflare proxy ON, SSL mode Full (strict), nginx allowlist restricts ingress to CF IP ranges only. SG `sg-0ece96660d8ee00bc` opens 443 from anywhere; no public 22 (SSM only). Reuses shared VPC `vpc-0c9453aafa64f6e40` and the existing `may26-ec2-ssm-role` instance profile. SSM Parameter Store namespace `/may26aws/qong-qa/*` for secrets (6 SecureString params, 5 of 6 populated). Specs at `docs/superpowers/specs/2026-05-29-aws-qa-environment-design.md`.

**Result (if measurable):** `https://qa.qongsystems.com/healthz` returns `200 ok` through the full Cloudflare→nginx stack. `/` returns 503 placeholder (docker compose not yet up). Monthly cost: ~$36/mo running, ~$6/mo if stopped.

**Notes:** Bring-up paused mid-session. ONE blocker before docker compose can come up: `/may26aws/qong-qa/openrouter-api-key` still holds the placeholder value `PLACEHOLDER_REPLACE_VIA_CONSOLE`. Once set, PHASE 2 (clone + override compose + render `.env.qa` from SSM + `docker compose up` + swap nginx 503 for `proxy_pass http://127.0.0.1:8000`) runs in ~15 min. EC2 deploy key SHA256 fingerprint `g49BJAfltEoDkdnpokihv7Bt31X6sWF2vsSEfH72rvA` added to `Qong-Systems/qong_product` deploy keys by user. **Origin Certificate private key was pasted in chat — rotate the cert** after end-to-end test passes; blast radius is limited (CF-edge↔origin only, no public CA trust) but best practice is to rotate. AWS account `449901518037` is treated as production per `../../../may26aws/CLAUDE.md` PROD RULES; every mutation in future sessions still needs same-turn user approval. Resource inventory should be appended to `may26aws/CLAUDE.md` once bring-up succeeds so the account-wide registry stays accurate. Full handoff in `SESSION_STATE.md`.

---

## [2026-05-28] #15 — Phase 3: Admin features ported to React with full test coverage

**Type:** feature
**Stage:** webapp
**Status:** shipped (React UI lives alongside legacy Jinja; Jinja deletion deferred to a follow-up after prod SPA deployment)

**Why:** User asked: *"on our main branch, we had created admin login with feature to add new users and approve and give them role. is that converted into new react ui?"* — answer was no, only customer-facing surfaces were ported in Phase 1+2. They then said: *"spin up phase 3, and port with testing and make sure we don't miss old users or projects."* So Phase 3 ports the 6 admin surfaces from Jinja to React, with full E2E + component-test coverage, and verified data continuity (every existing User/Job/Plan/Feedback row surfaces in the new UI).

**What — backend:**
- **`webapp/routers/api_v1_admin.py`** (NEW, 19 endpoints) — JSON API mirroring the legacy Jinja /admin/* forms. Cookie auth via existing `require_super_admin` dep. Endpoints: users CRUD + role/tier/activate/deactivate/grant-credits, dashboard KPIs, credits ledger, feedback list+update, plans list+create+toggle, label-studio list+sync-labels+sync-job. Same SQLAlchemy queries — zero schema changes.
- **`webapp/routers/api_v1.py`** — `/api/v1/account` now returns `id`, `email`, and `role` (was only username/credits/tier). Fixed a real bug surfaced by Playwright A/B test: AuthContext fell back to `data.tier` when `data.role` was missing, treating super_admin as "trial" and 403-ing the admin out of /admin/*. SECURITY: role must come from the server explicitly — never derived from tier or any other client-readable field.
- **`webapp/main.py`** — registers the new api_v1_admin router.

**What — frontend:**
- **`webapp/frontend/src/admin/types.ts`** — TS interfaces for all admin resources.
- **`webapp/frontend/src/admin/api.ts`** — typed fetch helpers for every endpoint. `HttpError` class, opaque-redirect detection for 401 handling, cookie credentials.
- **`webapp/frontend/src/admin/AdminLayout.tsx`** — left rail with 6 admin nav links + role gate (renders 403 page if `user.role !== "super_admin"`).
- **6 surface components:**
  - `AdminUsers.tsx` + `CreateUserModal.tsx` + `EditUserModal.tsx` — list, create, edit (role/tier/activate/deactivate/grant-credits/delete with self-deletion blocked).
  - `AdminDashboard.tsx` — KPI stat-strip (8 cards) + recent transactions table.
  - `AdminFeedback.tsx` — status-filter chips + items list + per-item status dropdown + admin notes. Reuses the iter-2 security fix: only renders an `<a href>` when page_url starts with http(s).
  - `AdminCredits.tsx` — read-only ledger with username search + sign filter (granted/consumed/all).
  - `AdminPlans.tsx` + inline `CreatePlanModal` — list/create/toggle.
  - `AdminLabelStudio.tsx` — completed-jobs table with LS-stats column + sync-job action + global sync-labels action. Banner when LS not configured.
- **`webapp/frontend/src/auth/AuthContext.tsx`** — role now read strictly from `data.role` (never tier).
- **`webapp/frontend/src/routes/Layout.tsx`** — Shield icon in nav for super_admin only, links to /admin.
- **`webapp/frontend/src/App.tsx`** — `/admin/*` nested routes under AdminLayout.

**Tests:**
- **`tests/e2e/test_admin_api.py`** (NEW, 43 tests) — every endpoint × {super_admin success, regular user 403, no auth 303}; business rules (cannot demote/deactivate/delete self, invalid role/tier/amount rejected, feedback filter validation, plan toggle round-trip, LS configured/unconfigured paths). All 43 pass.
- **`tests/unit/test_api_v1.py`** — existing 7 tests still pass (account endpoint shape change is backwards-compatible).
- **Vitest + React Testing Library wired** in `vite.config.ts` (`test:` block) + `src/test/setup.ts` (RTL cleanup + jest-dom). Added devDeps: `vitest`, `@testing-library/{react,jest-dom,user-event}`, `jsdom`.
- **6 component test files** (`src/admin/Admin*.test.tsx`) — 17 tests total covering: table renders, search/filter behaviour, modal opens, API calls fire with correct arguments, error banners, defense-in-depth (`javascript:` page_url not rendered as href).
- Total: 157 backend tests pass, 18 frontend component tests pass (smoke + 6 admin surfaces).

**Result (if measurable):**
- TypeScript build: 0 errors.
- Vite production bundle: 402 KB JS / 79 KB CSS (gzip 115 / 14 KB). +37 KB JS vs Phase 2 (the admin surfaces + lucide icons + Vitest infra in dev).
- A/B verified against legacy Jinja: both admin and seeded alice appear in /admin/users with identical data (role, tier, credits, status); seeded feedback appears with the safe https URL link.

**Notes:**
- **Legacy Jinja /admin/* routes NOT deleted in this commit.** User chose "Delete Jinja routes + templates after the React port is verified" — but verification is currently dev-only. The SPA isn't wired into prod yet (prod still serves Jinja at dev.qongsystems.com). Deleting Jinja now would 404 prod admin access. Plan: prod-deploy the SPA, A/B verify once more, then a separate small commit drops the 6 Jinja templates + the legacy route handlers from `webapp/routers/admin.py`.
- **The `/annotate` route stays** — it's annotator-role (not super_admin) and the Phase 3 port covers only super_admin surfaces. Annotators continue to use the Jinja landing.
- **The role-bug fix in `/api/v1/account`** is *also* relevant for the future deactivate-doesn't-revoke-session security finding noted in the security review. When that fix lands, `get_current_user` will need to check `is_active`; this endpoint's response will then accurately reflect it.
- **Dependency continuity check:** existing `webapp/credits.py:grant()` is reused by the grant-credits endpoint (same ledger row creation as the legacy Jinja). Existing `webapp/label_studio_client.py` helpers (is_configured, get_or_create_project, push_tiles, delete_all_tasks, sync_all_label_configs, get_project_stats) all reused unchanged.
- **Files touched/created:** ~25 files. New: 1 backend router, 1 backend E2E test file, 6 admin React components + 3 modal components, 6 component test files, 1 Vitest setup file, 1 admin scaffolding (types + api + AdminLayout). Modified: `webapp/main.py`, `webapp/routers/api_v1.py`, `webapp/frontend/src/App.tsx`, `webapp/frontend/src/auth/AuthContext.tsx`, `webapp/frontend/src/routes/Layout.tsx`, `webapp/frontend/vite.config.ts`, `webapp/frontend/package.json` (+ lock).

---

## [2026-05-28] #14 — QONG Studio Phase 2b+2c: DatasheetDrawer + BulkReviewScreen

**Type:** feature
**Stage:** webapp
**Status:** shipped

**Why:** Phase 2a (#13) shipped the Studio visual shell with stub buttons for Open Datasheet and Bulk Review. This commit lands the two real surfaces those buttons open, completing the full design loop the user committed to in chat2.md (Studio → drawer → bulk-review → back to studio with element selected + drawer reopened).

**What:**
- **DatasheetDrawer** (`webapp/frontend/src/studio/datasheet/`):
  - `schemas.ts` — 10 per-doc-type field schemas (datasheet, index, narrative, cande, io, valves, lines, equip, loop, tags); `defaultValues()` returns per-element + per-doc-type seed data. `FieldDef` with `w` hint (xs/sm/md/full = 1/2/3/4 grid cols), `extracted` + `conf` for confidence pills.
  - `DocTypeIcon.tsx` — maps icon names (`file-text`, `list-checks`, `scroll-text`, `git-merge`, etc.) to lucide-react components.
  - `DSField.tsx` — single field with locked-vs-input modes, P&ID badge for extracted fields, confidence pill, pencil to unlock for manual override, "Manual" hint for non-extracted empty fields.
  - `DatasheetDrawer.tsx` — full drawer: doc-type picker (swaps schema), Bulk Review pill (count badge), close (Esc + outside-click), title + completion progress, **vertical accordion** sections (sections 0+1 open by default per chat2.md decision to replace horizontal scroll), Save Draft + Export footer. Backdrop blocks the studio behind.
- **BulkReviewScreen** (`webapp/frontend/src/studio/bulk-review/`):
  - `deliverables.ts` — `DELIVERABLES` list (10 docs with done/total counts), `COLUMNS` per-deliverable table column schemas, `DETAIL_GROUPS` per-deliverable right-panel field groups.
  - `buildRows.ts` — 14 demo instruments (PV-203, FT-101, V-101, PT-201, TT-301, LT-401, FV-101, PSV-022, XV-501, P-101, E-104, FT-202, PT-301, TV-204), enriched per-deliverable.
  - `BulkReviewScreen.tsx` — workbench top bar (Back to Studio, breadcrumb, search, Filter, Export, toggleable panel-right), left deliverables nav with completion bars, center table with grid-template-columns reshaping per deliverable + stat strip (Total/Complete/Review/Missing), right detail panel with Open in Studio action.
- **Studio.tsx wiring**:
  - Real `DatasheetDrawer` mounted (no more alert stub).
  - `mode: "studio" | "bulk"` state. When `bulk`, renders `BulkReviewScreen` full-screen.
  - `onBulkReview` closes the drawer and switches to bulk mode (triggered by both the studio top-bar "Bulk Review" button and the drawer's BULK REVIEW pill).
  - `onOpenInStudio(id)` callback from bulk-review: sets `selectedId` to the picked tag, returns to studio mode, and reopens the drawer — matches v3 design behavior verbatim.

**Result (if measurable):**
- TypeScript build clean. Vite bundle 366 KB JS / 79 KB CSS (gzipped 108/14 KB), up from 2a's 331/78 KB.
- Verified the full loop end-to-end with Playwright + a seeded job (Block-18-Crude-Train-2.pdf): Studio → click Open Datasheet → drawer shows Control Valve PV-203 with 14/21 fields (67%) → click BULK REVIEW pill → workbench shows 14 instruments with PV-203 row pre-selected → click FT-101 row → right panel updates → click Open in Studio → studio reopens with FT-101 selected + drawer reopened with Flow Transmitter schema and per-element defaults (Reflux header flow, Differential Pressure 4-20mA HART, P-12-102-CS150 line).

**Notes:**
- **`1fr` column compression on narrow viewport.** In Bulk Review, the "Type" column uses `w: "1fr"` in the datasheet schema but ends up compressed to ~30px on a 1200px viewport because the parent grid's free-space calculation doesn't expand 1fr when other fixed cols sum near the container width. Minor visual bug — not breaking. Likely the bundle's CSS expects a wider viewport (1600+). Easy follow-up: switch `.br-table-wrap` to `overflow-x: auto` and let the table extend; or tighten fixed widths.
- **All bulk-review demo data is canonical to the design** — same 14 base rows from `bulk-review.jsx`, including the `sel: true` flag on PV-203 (selects it on initial load) and `missing: true` flags on LT-401, E-104, PT-301 (which makes Missing count = 3 in the stat strip).
- **DatasheetDrawer uses `useMemo` for defaults** — when element OR docType changes, defaults recompute, then `useEffect([defaults])` resets the form. This is the v3 design's pattern and it works correctly.
- **Backdrop click-to-close + Esc** both wired on the drawer. Bulk Review doesn't have a backdrop (it's a full-screen replacement).
- **`display: contents` on bulk-review rows** — each `.br-row` uses `display: contents` so its children become direct grid items of the parent `.br-table`. That's why selection styling has to be applied to individual cells (via inline style `color: var(--qong-magenta)`) rather than the row container.
- **No backend changes** — both surfaces are pure UI on top of the existing /api/v1/jobs/{job_id} endpoint. Real wiring to per-instrument data (instead of the 14-row demo set) is a separate piece of work (call it Phase 2d) — would need a `/api/v1/jobs/{id}/instruments` endpoint and the pipeline_runner to write canonical.json with per-instrument entries (we already have a `canonical.py` model from Plan A).
- **Files modified vs Phase 2a:** `webapp/frontend/src/studio/Studio.tsx` (drawer + bulk-review wiring) and 6 new files under `studio/datasheet/` + `studio/bulk-review/`. The studio.css from 2a already contains all the styles for the drawer + bulk-review (was the v3 superset).

---

## [2026-05-28] #13 — QONG Studio design bundle Phase 2a: Studio visual shell

**Type:** feature
**Stage:** webapp
**Status:** shipped

**Why:** Phase 1 (#12) shipped Dashboard + Login + theme. User then exported an updated design bundle (`design/qong-studio-v3/`) with the Studio screen polished: "Bulk Review" button added before "Save" in the top bar, "Save & continue" renamed to "Save", Issues panel replaced with "Elements on Sheet" (lists all detected elements with bidirectional canvas-list selection), and the prior horizontal datasheet tabs replaced with a vertical accordion. v3 also adds two new surfaces (DatasheetDrawer rewrite + BulkReviewScreen) but those are Phase 2b/2c. Phase 2a is the Studio visual shell on its own — clicking a tile on the Dashboard opens this Studio.

**What:**
- **Studio component split** under `webapp/frontend/src/studio/`:
  - `types.ts` — Sheet, CanvasElement, SessionEvent, ProjectLike interfaces.
  - `buildSheets.ts` — deterministic sheet generator (8–28 per project, status distribution).
  - `SheetGlyph.tsx` — small SVG glyph for sheet rail thumbnails (theme-aware grid).
  - `PidCanvas.tsx` — center canvas: prototype V-101/FT-101/P-101/PV-203/E-104 elements with edges; pan via mouse drag (3px threshold to distinguish click vs pan), wheel zoom (0.3×–4×), `.canvas-inner.animated` for smooth button-driven transitions; theme-aware colors for fill/stroke/text/grid.
  - `SheetRail.tsx` — left rail: head (Sheets count), search, All/Issues/Pending tabs, sheet-tile list with status badges.
  - `StudioTopBar.tsx` — back btn, QONG mark, project + sheet meta + reviewer slug, issue badge, **Bulk Review** secondary btn (new), **Save** primary btn (was "Save & continue"), `SettingsMenu variant="dark-chrome"`, more-menu (Export I/O / Share / Settings / Exit).
  - `PropertiesPanel.tsx` — Selected Element card (tag, type, confidence bar, inflow/outflow, Confirm/Edit, Open Datasheet) + **Elements on Sheet** list (replaces Issues; bidirectional select with canvas) + This Session activity.
  - `StudioFoot.tsx` — keyboard shortcut bar + auto-save indicator.
  - `Studio.tsx` — orchestrator. Reads `theme` from ThemeContext, locks body scroll while mounted, manages selection/zoom/pan state, stubs Open Datasheet + Bulk Review with alert (Phase 2b/2c).
- **Route wiring** — `routes/JobDetail.tsx` rewritten to fetch `GET /api/v1/jobs/{job_id}` and render Studio. `routes/ReviewCanvas.tsx` collapses to a thin alias re-exporting JobDetail (legacy URL preserved). Old JobDetail placeholder (deliverable download grid) removed — those URLs are still reachable directly via `/api/v1/jobs/{id}/export/{type}/{fmt}` from Plan A.
- **Layout full-bleed routes** — `routes/Layout.tsx` now matches `/jobs/:jobId(/review)?` via regex so the Studio's own header replaces the app-nav. Existing `/` and `/signin` exact matches still apply.
- **Studio CSS** — `webapp/frontend/src/design/studio.css` updated to v3 (2016 → 2507 lines): adds `.element-row`, accordion `.ds-section`, `.bulk-review`, `.studio-top` polish, dark-scope override under `.studio` (drawer shows in dark even when theme is light, per user "in A, background is darkmode, drawer shud also show in dark mode").

**Result (if measurable):**
- TypeScript build clean. Vite bundle 331 KB JS / 78 KB CSS (gzip 99 KB / 14 KB) — up from Phase 1's 309/68 KB.
- Verified visually with a seeded job (Block-18-Crude-Train-2.pdf): three-pane layout, theme-aware studio chrome, sheet rail with 8 mock tiles, pan/zoom canvas with bidirectional selection, properties panel rendering all 5 detected elements with confidence pills.

**Notes:**
- **Phase 2b** (next session): port `datasheet.jsx` (459 LOC, +140 vs v2). Drawer widened to 720px, 4-col grid (`grid-auto-flow: dense`), vertical accordion sections (01 + 02 open by default, rest collapsed), 10 distinct deliverable schemas (each doc-type swaps the field set), Bulk Review pill in drawer header, dark-mode override.
- **Phase 2c** (next session): port `bulk-review.jsx` (466 LOC, new). Full-screen workbench: deliverables nav (10 docs), instrument table with per-deliverable column schema, toggleable right detail panel (default open, `panel-right` button in top bar), "Open in Studio" returns with element selected + drawer reopened.
- **Studio canvas elements are prototype** — V-101, FT-101, P-101, PV-203, E-104 are hardcoded in `PidCanvas.tsx` (DEMO_ELEMENTS export). Real wiring to job detections is a separate piece of work (Phase 2b or later); requires either parsing the existing valve-list CSV or storing detection JSON on Job.
- **Body scroll lock** added in `Studio.tsx` useEffect — Studio is a single-viewport surface, prevents the page from scrolling behind the studio chrome.
- **Datasheet types** that get an "Open Datasheet" button: Control Valve, Flow Transmitter, Block Valve, Centrifugal Pump (set in Studio.tsx). Exchangers and pumps without the magic types don't show the button — matches the design's behavior.
- **`Datasheet Explorations.html`** in v3 bundle (uses `design-canvas.jsx` + `explorations.jsx`) is a SEPARATE bundle — NOT in QONG Studio.html scope. Skipped from Phase 2 entirely; treated as research/mockup material.
- **lucide icons added** vs Phase 1: `arrow-left`, `arrow-up-right`, `chevron-down`, `chevron-up`, `download`, `git-pull-request`, `info`, `layout-grid`, `log-in`, `log-out`, `maximize`, `panel-right`, `pencil`, `radio`, `scan-search`, `settings-2`, `boxes`, `circle-dot`, `filter`, `share-2`, `keyboard`. All present in lucide-react 1.17.0.
- **Production-continuity rule confirmed:** `/jobs/:jobId` (React SPA) now renders Studio. The legacy FastAPI Jinja `/jobs/{id}` HTML route in `webapp/routers/jobs.py:111` is untouched — direct URL access outside the SPA (legacy customers, email links, the dashboard route in `webapp/routers/dashboard.py`) continues to render the old Jinja template. When a user navigates from the new Dashboard tile click, the SPA's `/jobs/:jobId` wins (BrowserRouter handles it before the FastAPI server responds).
- **Files modified:** `webapp/frontend/src/design/studio.css` (v2→v3), `webapp/frontend/src/routes/{JobDetail,ReviewCanvas,Layout}.tsx`, plus new files under `webapp/frontend/src/studio/`. No backend changes (existing `GET /api/v1/jobs/{job_id}` already provided what Studio needs).

---

## [2026-05-28] #12 — QONG Studio design bundle Phase 1: Dashboard + Login + theme system

**Type:** feature
**Stage:** webapp
**Status:** shipped

**Why:** User exported a fresh design bundle from Claude Design (`design/qong-studio-v2/`) covering 4 surfaces (Login, Projects/Dashboard, Studio, Datasheet drawer) plus a Settings popover with light/dark theming. Previous Dashboard.tsx was an "Awaiting design" placeholder. User explicitly asked for projects-as-tiles dashboard now, full design later. Phase 1 ships Dashboard + Login refresh + theming infrastructure; Studio + Datasheet deferred to Phase 2.

**What:**
- **Design tokens unchanged** — existing `webapp/frontend/src/design/tokens.css` was already identical to the bundle's `colors_and_type.css` (full semantic layer for `--fg`, `--surface`, `--border`, both light + dark themes). Only fix: `global.css` no longer hardcodes body bg/color so theme attribute wins.
- **Studio CSS imported** — copied bundle's `app.css` (2016 lines) verbatim to `webapp/frontend/src/design/studio.css`; imported from `global.css`.
- **Theme system** — new `webapp/frontend/src/theme/ThemeContext.tsx` with localStorage persistence (key `qong.theme`), prefers-color-scheme fallback. `App.tsx` wraps router with `<ThemeProvider>`. SettingsMenu in nav lets user toggle.
- **Shared components** — `components/BrandRow.tsx`, `components/SettingsMenu.tsx` (gear icon + iOS-style toggle popover), `components/PidThumb.tsx` (generative SVG P&ID thumbnail per seed).
- **New backend endpoint** — `GET /api/v1/jobs` in `webapp/routers/api_v1.py` returns `{jobs: [{id, name, pid_no, status, valve_count, created_at, owner_username}]}` for the current user (or all jobs for super_admin). Joins User for owner_username — no ORM relationship existed.
- **Dashboard rebuilt** — `routes/Dashboard.tsx` replaces placeholder with full ProjectsPage: stats strip, search + filter chips, sidebar OR grid OR list (layout persisted to localStorage `qong.dashboard.layout`), `ProjectCard`/`ProjectRow` components, empty state, loading state. Wired to `/api/v1/jobs`.
- **CreateProjectModal** — `dashboard/CreateProjectModal.tsx` with name/client/discipline + drag-drop PDF dropzone; uploads via existing `POST /api/v1/jobs` (one job per file, sequentially); ESC closes.
- **Login refreshed** — `routes/Login.tsx` rewritten to use bundle's `.login-screen`/`.login-brand`/`.login-card`/`.extract-viz`/`.airgap-chip` classes instead of inline styles. Keeps existing auth wiring (`useAuth().login()` POST `/login`). Variant A (Split) only; Variant B deferred.
- **Layout nav** — `routes/Layout.tsx` rebuilt to use bundle's `.app-nav`/`.breadcrumbs`/`.icon-btn`/`.nav-actions` classes; includes `<SettingsMenu />` so users can flip theme from any page.

**Result (if measurable):**
- TypeScript build: 0 errors. Bundle: 309 KB JS / 68 KB CSS (gzipped 94 KB JS / 12 KB CSS).
- Curl verification: `GET /api/v1/jobs` returns 200 with `{"jobs": []}` for admin (no jobs in dev DB); `POST /login` → 303; Vite proxy forwards `/api/v1/jobs` correctly.
- 4 of 7 designed surfaces remain placeholders: Studio (Phase 2), Datasheet drawer (Phase 2), Projects route (delegates to Dashboard), Login Variant B (Cinematic — Phase 2 maybe).

**Notes:**
- **Design bundle staged** at `design/qong-studio-v2/` (extracted from gzip tarball at `/tmp/qong-design-bundle/`). Source files: `project/{app.jsx,screens.jsx,studio.jsx,datasheet.jsx,app.css}` + `design-system/`. Keep this folder around — Phase 2 needs `studio.jsx` and `datasheet.jsx`.
- **lucide-react 1.16.0 → 1.17.0** — bumped to get modern icon names (`chevron-right`, `panel-left`, `git-branch`, `cpu`, `zap`, `arrow-up-right`). 1.17.0 is the actual latest on npm (3924 icons) despite the suspicious version number.
- **Vite binds to IPv6 only by default** (`::1`, not `127.0.0.1`). Curl tests must use `http://localhost:5173` (IPv6 resolver hits) or `http://[::1]:5173`. Bit me during smoke test.
- **One Job = one tile** in the Dashboard — no `projects` table added (user confirmed in scoping). When agency MVP needs multi-PID-per-project, that's a separate plan (FK migration, endpoint changes).
- **Body of CreateProjectModal uploads files sequentially**, not in parallel. Simpler error handling; can parallelize when we hit volume.
- **Owner_username via outer join** — Job model has no SQLAlchemy `relationship("User")` defined, so `job.user.username` would NameError. The dashboard endpoint does `db.query(Job, User.username).outerjoin(User)` instead. Worth adding a real relationship if more endpoints need it.
- **Project name maps to original_filename** with `.pdf` stripped; client maps to owner_username. When the projects-table refactor happens, both get proper fields.
- **Files modified:** `webapp/routers/api_v1.py` (+30 lines), `webapp/frontend/src/{design/global.css,design/studio.css (new),theme/ThemeContext.tsx (new),components/{BrandRow,SettingsMenu,PidThumb}.tsx (new),dashboard/{types.ts,ProjectCard,ProjectRow,CreateProjectModal}.tsx (new),routes/{Dashboard,Login,Layout}.tsx,App.tsx}`. Two files inflated (Login from inline-styles to design classes, Dashboard from 15 → 290 LOC); rest are net-new.

---

## [2026-05-28] #11 — Marketing landing page ported into React SPA (Plan B Phase 1 Task 6)

**Type:** feature
**Stage:** webapp
**Status:** shipped

**Why:** Plan B Phase 1 final task. The Home route was a placeholder; the team needed a full marketing-site composition in the SPA so sales/demo links (`/`) show the real brand. Also needed to prove the JSX design-system UI kit (in `design/QONG Design System/ui_kits/marketing-site/`) ports cleanly to TypeScript.

**What:** Created `webapp/frontend/src/marketing/` with 7 files: `Drive.tsx`, `Social.tsx`, `Hero.tsx`, `Sections.tsx` (About, Features, Problems, Process, CoreEngine, Advantages, Sectors, FAQ, CTAStrip), `Footer.tsx`, `MarketingNav.tsx`, `marketing.css`. Replaced `routes/Home.tsx` entirely. Added `/` to `FULL_BLEED_ROUTES` in `Layout.tsx` so the marketing page is edge-to-edge. Commit `41db788`.

**Result (if measurable):** tsc + vite build clean. Bundle size 283 KB JS / 18 KB CSS (grew ~18 KB from marketing components). "Beyond Plant", "Oil & Gas", "Instrument Index" present in the JS bundle.

**Notes:** Drive mockup animates via a `setInterval` — functional, not a real product. CTA buttons link to `/signin` or `mailto:hello@qongsystems.com`. Nav links for About/Careers/Contact do in-page anchor scroll only (not separate routes — those are post-Phase-1 surfaces).

---

## [2026-05-28] #10 — Deliverables subsystem shipped (Valve List / Instrument Index / Equipment List / Datasheet generators + per-customer templates)

**Type:** feature
**Stage:** webapp, export
**Status:** shipped

**Why:** Per `docs/decisions/01-qong-studio-mvp-design.md` Plan A. The MVP
customer experience hinges on four deliverables in per-EPC templates;
this subsystem is the production path for all four.

**What:** `webapp/deliverables/` package — Pydantic canonical schema
(v1.0.0), per-customer JSON template format, generator registry, six
concrete generators (Valve List CSV+XLSX, Instrument Index CSV+XLSX,
Equipment List XLSX, Datasheet XLSX with 11-section IDS structure) and
the `POST /api/v1/jobs/{id}/export/{type}/{format}` endpoint. Three
customer templates landed: default (matches production columns +
TNB-style Instrument Index), ronesans (sheet-name + font overrides),
muk (subsetted columns). Pipeline-side `canonical.json` writing is
intentionally out of scope for this plan — a follow-up plan will wire
the extraction pipeline to emit canonical.json next to valve_list.csv.

**Result:** End-to-end test passes: given a hand-crafted canonical.json
fixture, the endpoint returns valid CSV/XLSX in the expected template
(matching the customer reference files `parser.py:to_csv_dict`,
`TNB-26E009A001_Instrument index R0.pdf`, `23E065AJ01_ASV_IDS.xlsx`).
~56 unit tests + 5 E2E tests, all green.

**Notes:** The customer_template_slug "default" is the fallback; jobs
whose project sets no template still produce a usable deliverable.
Companion entry to #09 (ValveListCSVGenerator) — #10 covers the
remaining 5 generators + the API endpoint + the registry wiring.

---

## [2026-05-28] #09 — ValveListCSVGenerator: stdlib csv.writer, CRLF fixture, self-registers in REGISTRY

**Type:** feature
**Stage:** export
**Status:** shipped

**Why:** Plan `2026-05-27-deliverables-template-engine.md` Task 9 — first concrete deliverable generator to exercise the Generator/REGISTRY/TemplateLoader/field_resolver stack end-to-end. Needed to prove byte-exact output before XLSX variant is added.

**What:** New file `webapp/deliverables/valve_list.py` — `ValveListCSVGenerator(Generator)` filters entities to `entity_class == "valve"`, orders columns by `ColumnDef.order`, writes CRLF CSV via `csv.writer`, self-registers in `REGISTRY` at import time. Fixture `tests/unit/deliverables/fixtures/expected_valve_list_default.csv` (315 bytes, 3 CRLF lines) pinned via Python csv.writer for byte-exact comparison. `.gitattributes` added so git checks out the fixture with `eol=crlf` on all platforms.

**Result:** 4 pytest tests pass: byte-equality fixture, filter-to-valves-only (instrument/equipment rows excluded), trailing-space header preservation, class attrs. Commit `ac2cde8`.

**Notes:** `.gitattributes` `eol=crlf` rule is critical — without it a fresh clone on Linux/Mac would check out LF and the byte-equality test would fail. The `"8""-G-62151004-AC-PP"` double-double-quote is csv-module standard escaping; do not hand-edit that fixture.

---

## [2026-05-27] #08 — Qong Studio MVP scope locked: agency beachhead, 4 deliverables, Aug '26, Level-2 vendor inclusion via separate Laravel portal

**Type:** decision, architecture
**Stage:** infra, webapp
**Status:** shipped (design doc); implementation plan to follow

**Why:** The 9-month phased plan in `docs/onboarding/ARCHITECTURE.md` §5 was written before the MVP shape was sharpened around a beachhead persona and the marketplace revenue model. Brainstorm session 2026-05-27 surfaced: (a) the customer is P&ID-digitization **agencies**, not big-oil or individual engineers; (b) the Datasheet deliverable specifically needs vendor data to be a complete product, which means at least Level-2 vendor inclusion is required for MVP; (c) Omprakash is the team capacity bottleneck — the only way to fit Level-2 in 14 weeks is for Tarunkumar to own the vendor portal as a separate Laravel app, freeing Omprakash to focus on Qong Studio canvas + templates + deliverable generators. Without this scoping, the team would spend 6 months building a maximalist version of what only needs to be focused.

**What:** Wrote `docs/decisions/01-qong-studio-mvp-design.md` — the authoritative MVP spec. Locks four deliverables (Valve List, Instrument Index, Datasheet, Equipment List), per-customer template engine (3-5 hardcoded JSON templates), Qong Studio React/Konva canvas, free-for-design-partners MVP with manual invoicing on paid signups, separate Laravel vendor portal owned by Tarunkumar, vendor data living in Qong's Postgres as single source of truth with Laravel calling Qong's REST API. Explicit deferral list: Line List + topology + Cable Schedule + JB Schedule + Manuals + Cause & Effect + Control Narrative → FLEDGE Oct '27; Stripe + in-house quote management + customer-editable template editor + collaborative review → v1.5 (Q4 '26 / Q1 '27); SSO + on-prem + DGX Spark → post-MVP. Sprint 1 work in QS-48/50/52/54/56/60/62/64/65/66/68 continues unchanged; this design doc tells subsequent sprints what they're building toward.

**Result:** Per-person FTE-week budget now balances: Omprakash 14/14, Geetha 13/14, Swaraj 9/14, Tarunkumar partial-FT. Capacity gap that the brainstorm started with (32 weeks of work on Omprakash) is closed without slipping the Aug '26 target.

**Notes:** Reversible only by formal supersession with a new `docs/decisions/NN-...md` entry — not by drift. Several items intentionally left as open questions in the design doc §8 to resolve in the implementation-plan step (seed vendor list, Laravel build-or-contract call, hosting topology, org-role schema, PaddleOCR upgrade scope, design-partner agency list). FEATURES.md entries #04 (no DEXPI), #03 (Konva), #06 (no GPU queue) all remain load-bearing for this design.

---

## [2026-05-27] #07 — QS-60 vision pack lands in `docs/onboarding/`; root discipline files stay canonical

**Type:** decision, architecture
**Stage:** infra
**Status:** shipped

**Why:** QS-60 (Omprakash onboarding) produced a 10-file "full-project-guide" pack — `PROJECT_VISION.md`, `ARCHITECTURE.md`, `REVIEW_UI_SPEC.md`, `ACTIVE_LEARNING_SPEC.md`, `DATASETS.md`, `REFERENCES.md`, `README.md`, plus its own copies of `CLAUDE.md` / `FEATURES.md` / `SESSION_STATE.md`. Sitting at repo root as `full-project-guide/`, the latter three would silently shadow the live root discipline files during any `Read CLAUDE.md` lookup. Risk: a future session reads the pack's template SESSION_STATE.md (dated 2026-05-25 "initial seed") instead of the real one and wipes the actual handoff. The pack is reference material, not active state.

**What:** Moved 7 vision/spec files from `full-project-guide/` to `docs/onboarding/`. Deleted the 3 conflicting duplicates. Removed empty `full-project-guide/`. Patched `docs/onboarding/README.md` to point new joiners at the live root `CLAUDE.md` instead of its (deleted) sibling. Also: deleted loose root one-offs `intern_jd.html`, `intern_offer_letter.html`, `readfirst.txt`. Committed `ref/` (5.4 MB customer PDFs for the Ronesans/Ebara instrument-index investigation), `patent.md`, and `Dockerfile.{mcp,trainer}` (already wired into `docker-compose.yml`; fresh clones could not build without them). `.gitignore` extended for `/*.pt`, `datasets/**/*.cache`, `annotate/exports/*.zip`.

**Result:** N/A (docs reorg). Repo size unchanged on disk; no large binaries now tracked.

**Notes:** `data_room/` additions (investor HTML pack) left untracked for now — owned by Vrushab, not core eng. `yolov8s.pt` (22 MB base weights) and `annotate/exports/*.zip` (24 MB LS export) intentionally ignored — regenerable. The vision pack still describes the *future* monorepo layout (`pipeline/`, `api/`, `web/`, etc.) which doesn't match today's flat layout — that's expected, it's the north-star doc.

---

## [2026-05-26] #06 — No backend GPU job queue; shared IAM role + per-user IAM users + runs.jsonl

**Type:** architecture, decision
**Stage:** training, infra
**Status:** shipped (rollout in Sprint 1 via QS-48 + QS-52)

**Why:** Training cadence is 1-3 runs/week (manual ad-hoc) growing to weekly automated by Sprint 4. Building a backend queue (REST endpoint + UI + status polling) is ~1-2 weeks of work for no benefit at this volume — there's no real concurrency to coordinate, and AWS spot/on-demand instances don't care about parallel launches.

**What:**
- One shared IAM role `qong-trainer-burst` with EC2 + S3 + SSM permissions
- Four IAM users (`tarunkumar`, `geetha`, `swaraj`, `omprakash`) — each with MFA — assume the shared role
- `s3://qong-training-artifacts/runs.jsonl` is the team-visible log of every training run: `aws_train_burst.sh` appends one line at start (status=running) and one at end (status=success/failed + cost + model artifact). Anyone reads with `aws s3 cp s3://.../runs.jsonl - | jq`.
- CloudTrail provides full per-user audit for free.
- Instance type: **on-demand** g5.xlarge for now (~$1/hr, no termination risk). Switch to spot in Sprint 4 when checkpointing is added.

**Result:** ~3 hours of additional work in Sprint 1 (folded into QS-48 + QS-52 — no new tickets) vs ~1-2 weeks for a real queue. Equivalent visibility for the team via the runs.jsonl log.

**Notes:** Revisit if/when training runs exceed ~5/day AND coordination problems appear (e.g., same experiment launched twice). Probably never at team size 4. The Sprint 4 active-learning loop will use the same shared role + runs.jsonl, so we're not building this twice.

---

## [2026-05-26] #05 — Project Jira (SCRUM) + Confluence wired; Sprint 1 ready

**Type:** infra
**Stage:** infra
**Status:** shipped

**Why:** Need a single board the whole team (lead + 3 interns + CEO as customer-tester) coordinates from. Pure-doc planning doesn't survive a multi-month project.

**What:** Created 8 Jira epics in SCRUM project (project name "QS-Customers"; key will be renamed SCRUM→QS via admin UI), 11 Sprint 1 stories balanced 3/2/3/3 across Tarunkumar/Omprakash/Geetha/Swaraj. Two Confluence pages: full technical plan (SD space) + customer-flow exec summary (Q space).

**Result:** Sprint 1 stories visible at https://qongsystems.atlassian.net/browse/SCRUM-48 ... SCRUM-68. All assignees set with Atlassian account IDs.

**Notes:** Project rename SCRUM→QS pending — admin must do via Project Settings → Details → Key. Old issue links auto-redirect after rename. Vrushab (CEO) is *not* in Jira as a developer; he's the customer-tester from Sprint 3 onwards.

---

## [2026-05-26] #04 — No DEXPI XML export — proprietary deliverables only

**Type:** business decision
**Stage:** export
**Status:** shipped

**Why:** The earlier architecture spec (`full-project-guide/`) treated DEXPI 2.0 as the canonical output format. Strategic reversal: providing a clean industry-standard exit format makes it easy for customers to migrate off our platform. We want lock-in.

**What:** All customer deliverables stay in proprietary CSV / PDF / XLSX. The graph data model + queryable graph stay internal. No `pydexpi` integration. Sprint 15-16 deliverables (BOM, equipment list, loop trace) are derived from the graph but exported in our formats only.

**Notes:** Reversible later if a paying customer specifically demands DEXPI for procurement integration. Document any such request and weigh per-customer.

---

## [2026-05-26] #03 — Frontend stack locked: React 19 + Vite + react-konva + Zustand + TanStack Query

**Type:** architecture
**Stage:** review (UI)
**Status:** shipped

**Why:** Review UI is the product wedge. Spec targets `<800ms first paint, 60fps pan/zoom` on 4K P&IDs — needs a real SPA, not server-rendered templates. Konva chosen over PixiJS because real P&IDs peak at 5K–10K elements (well within Konva's smooth range); PixiJS only wins above 10K and costs 6–8 weeks WebGL ramp-up.

**What:** New directory `webapp/frontend/` will contain the React app. Mounted at `/jobs/{id}/review` via FastAPI static-files. Pydantic-derived TS types from `webapp/schemas/`. Vitest unit tests + Playwright E2E. Stack lifted directly from `full-project-guide/REVIEW_UI_SPEC.md` + decision #03 in `full-project-guide/FEATURES.md`.

**Notes:** Omprakash (sole web dev) owns the entire frontend. Risk: 8-10 week MVP slips to 12 weeks if React learning curve hits hard. Lead pair-programs with him 2hr/week to mitigate + learn alongside.

---

## [2026-05-26] #02 — AWS burst-mode EC2 replaces Windows GPU + Tailscale for training

**Type:** infra
**Stage:** training
**Status:** shipped (rollout in Sprint 1)

**Why:** Windows GPU + Tailscale is a single point of failure with a fragile connection. After v1-9 training run today (multiple hours of Tailscale debugging), the cost-of-fragility is unacceptable for a team that will retrain weekly via active learning.

**What:** AWS account + IAM role `qong-trainer-burst` + S3 bucket `qong-training-artifacts` (ap-south-1 / Mumbai) + EC2 launch template `qong-train-burst` (g5.xlarge spot, ~$0.30/hr, NVIDIA A10G 24GB VRAM, Ubuntu 22.04 + CUDA 12 AMI). New `scripts/aws_train_burst.sh` does spin-up → SCP dataset → SSM-run train_gpu.py → SCP model back → terminate. SSM (not SSH) for instance access — no key management.

**Result (target):** v1-10 retraining completes in 60-90 min for $5-15 per run. Documented in Sprint 1 SCRUM-52.

**Notes:** Windows GPU stays as fallback for 30 days then decommissioned. Tailscale link removed once decommissioning is confirmed.

---

## [2026-05-26] #01 — Digital twin platform project kicked off — human-in-the-loop wedge

**Type:** architecture, business decision
**Stage:** webapp, review, training
**Status:** shipped (planning + Sprint 1 ready)

**Why:** Customer feedback: the current valve-list extraction is good but customers do the work twice — they get a CSV, then manually fix what's missing. They want all deliverables in one sitting: valve list + instrument index + datasheets + future BOM / loop trace / equipment list. End-state: ship as on-premises **Qong Box** appliance once models are good enough.

**What:** Single-product trajectory in same repo. New branch `feature/digital-twin` from `dev`. Existing valve-list flow keeps running for paying customers throughout. 8-10 week MVP across Sprints 1-5 = shadow graph + review UI + active learning loop. Post-MVP Months 3-6 = multi-page + cross-page, pipe tracing + flow direction, new deliverables (BOM, equipment list, loop trace), production switchover from API to graph-derived outputs.

Plan: `/Users/maahedev/.claude/plans/async-soaring-puppy.md` (also in Confluence SD space).

**Notes:** **Auto-improving model loop** is built in Sprint 4 (Weeks 7-8), not Sprint 1. Sprint 1 lands the *plumbing* (ReviewEvent + TrainingEvent schemas + LS migration). Until Sprint 4 ships, model retraining stays manual. Headline metric is graph isomorphism (`networkx.is_isomorphic`) not symbol mAP.
