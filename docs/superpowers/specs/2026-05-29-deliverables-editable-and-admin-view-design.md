# Deliverables Editable + Admin Dashboard View — Design Spec

> **Subsystem A of 2** (paired with `2026-05-29-aws-qa-environment-design.md`). Independent — can ship without the AWS work, and vice versa.

**Date:** 2026-05-29
**Branch:** `feature/digital-twin`
**Author:** Claude (controller) for tarun

---

## Goal

Make the three primary deliverables in QONG Studio — **Valve List**, **Instrument Index**, **Instrument Datasheet** — visible and editable in-app. Today they exist only as on-disk CSVs/ZIPs; the React Studio shows demo data. Pair this with admin-side visibility (super_admin sees all users' projects with owner labels) and the cleanup of a misleading static label.

## Why

- Customers can't validate or correct extracted data without downloading CSV and round-tripping. That breaks the human-in-the-loop premise the digital-twin platform is built on (FEATURES.md #01).
- Engineering can't see customer projects on the dashboard. Today admin shares the same query as users; debugging requires SQL. The previous Jinja dashboard had owner labels for admins — that capability regressed in the React port.
- Canvas footer reads "16 valves on this sheet" on every sheet, which is misleading. The number is whole-job, not per-sheet. Users have asked twice what it means.

## Non-Goals

- **Per-sheet valve counts.** User explicitly out of scope — sheet-scoped counts add no real engineering value and aren't worth a schema migration just for a footer.
- **Project/Job rename.** User-facing rename to "projects" is queued for a separate small PR (no DB changes); not part of this spec.
- **Multi-tenant `Organization` model.** Bigger conversation; deferred to a future spec.
- **Impersonation (login-as-customer).** Owner-label visibility gives 95% of debug value at none of the audit/security cost. Revisit if a customer asks.

---

## Architecture

Three independent, parallel-shippable feature slices, plus one micro-fix and one infra change:

```
┌─ DB Migration ────────────────────────────────────────────────────┐
│  - Add instrument_rows table (mirror of valve_rows shape)         │
│  - Add bbox JSON + sheet_index int on valve_rows & instrument_rows│
│  - Add instrument_datasheets table (56-field structured schema)   │
│  - Backfill from existing CSV files on disk                       │
└───────────────────────────────────────────────────────────────────┘
              │
              ▼
┌─ Slice 1: Valve List editable ────────────────────────────────────┐
│  GET    /api/v1/jobs/{id}/valves                                  │
│  PATCH  /api/v1/valves/{row_id}                                   │
│  POST   /api/v1/jobs/{id}/valves                                  │
│  DELETE /api/v1/valves/{row_id}                                   │
│  Frontend: studio/bulk-review/BulkReviewScreen wired to API       │
└───────────────────────────────────────────────────────────────────┘

┌─ Slice 2: Instrument Index editable ──────────────────────────────┐
│  GET    /api/v1/jobs/{id}/instruments                             │
│  PATCH  /api/v1/instruments/{row_id}                              │
│  POST   /api/v1/jobs/{id}/instruments                             │
│  DELETE /api/v1/instruments/{row_id}                              │
│  Frontend: same Bulk Review screen, different deliverable picker  │
└───────────────────────────────────────────────────────────────────┘

┌─ Slice 3: Instrument Datasheet editable ──────────────────────────┐
│  GET   /api/v1/instruments/{id}/datasheet  → 56-field record      │
│  PATCH /api/v1/instruments/{id}/datasheet  → save edits           │
│  Frontend: DatasheetDrawer wired to backend (not seed defaults)   │
└───────────────────────────────────────────────────────────────────┘

┌─ Slice 4: Admin dashboard owner labels ───────────────────────────┐
│  /api/v1/jobs already returns owner_username                      │
│  Frontend: ProjectCard/ProjectRow render owner badge when         │
│             current user.role === "super_admin"                   │
└───────────────────────────────────────────────────────────────────┘

┌─ Slice 5: Remove static "N valves on this sheet" text ────────────┐
│  studio/PidCanvas.tsx:390-407 — delete the useReal && (<div>) blk │
└───────────────────────────────────────────────────────────────────┘
```

---

## Component Designs

### DB Migration

**New tables:**

```python
class InstrumentRow(Base):
    """Mirror of ValveRow shape, but for instruments (PT/FT/LT/TT/PI/...).
    Backed by what the API pipeline writes to instrumentation_index.csv today."""
    __tablename__ = "instrument_rows"
    id           = Column(Integer, primary_key=True, index=True)
    job_id       = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    tag          = Column(String, nullable=False)        # e.g. "PT-101"
    service      = Column(String, default="")             # e.g. "Reactor inlet pressure"
    pid_no       = Column(String, default="")
    sheet_index  = Column(Integer, nullable=True)         # which tile this came from (0-based)
    bbox         = Column(JSON, nullable=True)             # [x1, y1, x2, y2] in tile pixel space
    instrument_type = Column(String, default="")          # "transmitter" | "indicator" | "switch"
    measured_variable = Column(String, default="")        # "pressure" | "flow" | ...
    line         = Column(String, default="")
    notes        = Column(Text, default="")
    extra        = Column(JSON, nullable=True)             # any field the parser found but we didn't model

class InstrumentDatasheet(Base):
    """Per-instrument 56-field datasheet record.
    Schema mirrors studio/datasheet/schemas.ts index schema."""
    __tablename__ = "instrument_datasheets"
    id              = Column(Integer, primary_key=True, index=True)
    instrument_id   = Column(Integer, ForeignKey("instrument_rows.id"), nullable=False, unique=True, index=True)
    # 56 fields stored as a single JSON blob keyed by schema field name.
    # Why JSON not 56 columns: schema evolves with customer templates; per-customer field sets
    # already exist in webapp/deliverables/customer_templates/. JSON keeps migrations cheap.
    fields          = Column(JSON, nullable=False, default=dict)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by      = Column(Integer, ForeignKey("users.id"), nullable=True)
```

**Column adds to `valve_rows`:**

```python
sheet_index = Column(Integer, nullable=True)
bbox        = Column(JSON, nullable=True)
```

**Backfill strategy:**
- Migration creates tables empty.
- A separate `scripts/backfill_deliverables.py` walks `job_outputs/{job_id}/instrumentation_index.csv` and `*.csv` per-tag datasheet files (if any), populating `instrument_rows` and `instrument_datasheets`.
- Backfill is idempotent: `(job_id, tag)` uniqueness; re-running won't dupe.
- Bbox + sheet_index left NULL for old data — we don't have that info historically. New jobs populate them via pipeline changes (out of scope; tracked separately).

**Alembic migration file:** `alembic/versions/2026_05_29_add_instrument_rows_and_bbox.py` (or equivalent if not using Alembic — see existing pattern in `webapp/database.py`).

### Slice 1 — Valve List API + UI

**Endpoints** (all under `webapp/routers/api_v1.py`):

| Method | Path | Auth | Behavior |
|---|---|---|---|
| GET | `/api/v1/jobs/{id}/valves` | own job OR super_admin | returns `{valves: [{id, pid_no, category, size, ...}], count: int}` |
| PATCH | `/api/v1/valves/{row_id}` | own job OR super_admin | body: partial dict of editable fields; returns updated row |
| POST | `/api/v1/jobs/{id}/valves` | own job OR super_admin | body: full row; returns created row with new id |
| DELETE | `/api/v1/valves/{row_id}` | own job OR super_admin | hard delete; returns 204 |

**Authorization helper** (extract once, reuse across slices):
```python
def _assert_can_edit_job(job: models.Job, user: models.User):
    if user.role != "super_admin" and job.user_id != user.id:
        raise HTTPException(403, "Not your job")
```

**Frontend wiring:**
- `studio/bulk-review/BulkReviewScreen.tsx` — replace `buildRows.ts` demo data with `useQuery("/api/v1/jobs/:id/valves")`.
- New `studio/bulk-review/EditableCell.tsx` — wraps a cell, click to edit, blur or Enter saves via PATCH, Esc cancels, optimistic update with rollback on error.
- New "+" row at table bottom → POST.
- Per-row trash icon → DELETE with confirm dialog.

**Editable fields:** all 14 valve_rows columns (`pid_no`, `category`, `size`, `serial_no`, `line`, `qty`, etc.). `id` and `job_id` are read-only.

### Slice 2 — Instrument Index API + UI

Identical to Slice 1 shape, swap `ValveRow` → `InstrumentRow`. Editable fields: `tag`, `service`, `pid_no`, `instrument_type`, `measured_variable`, `line`, `notes`. `sheet_index` and `bbox` are read-only (they come from the detector).

Bulk Review screen already has a deliverable picker (`schemas.ts` reorder from last week). Selecting "Instrument Index" swaps the table to use `/api/v1/jobs/:id/instruments` and a different column schema. No new screen needed.

### Slice 3 — Instrument Datasheet API + UI

**Endpoints:**

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/v1/instruments/{id}/datasheet` | returns `{fields: {...}, updated_at, updated_by}` |
| PATCH | `/api/v1/instruments/{id}/datasheet` | body: partial `fields` dict; merges into existing JSON; returns updated record |

**Frontend wiring:**
- `studio/datasheet/DatasheetDrawer.tsx` — when an instrument is selected and drawer opens, fetch `/api/v1/instruments/{selectedId}/datasheet`.
- If record doesn't exist yet (404), fall back to `defaultValues()` from `schemas.ts` as a draft.
- `DSField.tsx` already has the locked/editable toggle. On unlock + save, PATCH the field.
- Conflict policy: last-write-wins for now. We're 1 user per drawer; multi-user concurrent edit is a future problem.

### Slice 4 — Admin dashboard owner labels

Backend already does the work: `/api/v1/jobs` returns `owner_username` in each row (verified at `api_v1.py:204`).

**Frontend changes:**
- `dashboard/types.ts` — add `ownerUsername?: string` to `ProjectTile`.
- `dashboard/types.ts:toProjectTile` — copy `owner_username` from API response.
- `dashboard/ProjectCard.tsx` and `ProjectRow.tsx` — render a small owner badge (avatar circle + username) ONLY when `user?.role === "super_admin"`. Reuse the existing `BrandRow` / avatar component if reasonable; otherwise inline 24px circle with first-letter monogram.
- Sort: keep created_at desc; consider adding a "Filter by owner" chip later (out of scope this PR).

**Visual treatment:** small monochrome chip with username; not a tier badge, not colored. Goal is information, not decoration.

### Slice 5 — Remove static valve count text

Delete `webapp/frontend/src/studio/PidCanvas.tsx:390-407`. Remove the `valveCount` / `valveCountTotal` props from PidCanvas if they have no other consumer after deletion. Remove their pass-through in `Studio.tsx:184-185`.

---

## Data Flow

**Editing a valve in Bulk Review:**

```
User clicks cell → EditableCell enters edit mode →
User types new value, blurs cell →
Frontend: optimistic update local state →
Frontend: PATCH /api/v1/valves/{row_id} {field: newValue} →
Backend: _assert_can_edit_job(job, user) →
Backend: SQLAlchemy update + commit →
Backend: 200 with updated row →
Frontend: reconcile (no-op if optimistic was correct) OR rollback on error
```

**Opening a datasheet for an instrument:**

```
User clicks instrument bbox on PidCanvas →
Studio sets selectedId →
DatasheetDrawer opens →
GET /api/v1/instruments/{id}/datasheet →
  200 → render fields from response
  404 → render defaultValues() as draft (no PATCH until user actually edits)
User edits a field, unlocks, types new value, blurs →
PATCH /api/v1/instruments/{id}/datasheet {fields: {fieldName: newValue}} →
Backend: merge into existing JSON, commit, return →
Frontend: update local cache
```

---

## Error Handling

| Failure | API response | UI behavior |
|---|---|---|
| Not your job, not admin | 403 | Toast: "You don't have permission to edit this." Roll back optimistic update. |
| Job not found | 404 | Toast: "Job no longer exists." Navigate to /dashboard. |
| Row not found (deleted by another session) | 404 | Toast: "This row was deleted." Refresh table. |
| Validation fail (e.g. qty not int) | 422 | Inline cell error, keep edit mode open. |
| Network error | n/a | Toast with retry button. Optimistic update kept locally until retry. |
| Backfill encounters malformed CSV row | log + skip | Backfill report at end: "X rows backfilled, Y skipped, paths: …" |

---

## Testing

**Backend (pytest):**
- `tests/unit/test_api_v1_valves.py` — CRUD endpoints, auth boundaries (own job ✓, other user ✗, super_admin ✓), validation.
- `tests/unit/test_api_v1_instruments.py` — same shape.
- `tests/unit/test_api_v1_datasheet.py` — GET 404 vs 200, PATCH merge semantics, JSON field validation.
- `tests/unit/test_migration_backfill.py` — fixture CSV in `tests/unit/deliverables/fixtures/` → run backfill → assert rows + idempotency.

**Frontend (vitest + React Testing Library):**
- `BulkReviewScreen.test.tsx` — renders rows from mocked API, edit-cell-save cycle, delete with confirm, add row.
- `DatasheetDrawer.test.tsx` — 404 fallback to defaults, PATCH merge, optimistic update rollback.
- `ProjectCard.test.tsx` — owner badge shown only when user.role === super_admin.

**Manual smoke (Playwright after deploy to QA):**
1. Log in as admin → dashboard shows all 8 jobs with owner badges.
2. Open job 2 → Bulk Review → 28 valves visible (not 14 demo rows).
3. Edit a valve `size` field → reload → value persists.
4. Open instrument PT-101 datasheet → edit `manufacturer` field → reload → persists.
5. Canvas footer no longer shows "16 valves on this sheet".

---

## Migration Risk + Rollback

**Risk:** the migration adds NOT-NULL-able columns (`bbox`, `sheet_index`) — both nullable, so it's a clean ALTER TABLE on SQLite and Postgres. No data backfill blocking the migration; existing rows get NULL.

**Rollback:** if backfill produces bad data, truncate `instrument_rows` and `instrument_datasheets` and re-run. The old CSVs on disk are untouched and remain the source of truth until app reads start hitting the new tables. We can ship the migration + backfill BEFORE flipping app reads (feature flag `READ_INSTRUMENTS_FROM_DB`) for safety.

**Production data:** dev DB has 8 jobs. Backfill is cheap. Postgres prod (when QA migrates) will run the same migration; same backfill script.

---

## Open Questions Resolved Inline

- **Should we use Alembic or hand-rolled migration?** Check `webapp/database.py` for the current pattern. If Alembic not yet wired, just add the columns/tables in code and use a one-off script. Don't introduce Alembic in this PR.
- **JSON vs 56 columns for datasheet fields?** JSON. Per-customer field sets already vary (see `webapp/deliverables/customer_templates/*.json`); 56 columns would be the wrong shape for an extensible product.
- **Per-row authz check on PATCH?** Yes — fetch the parent Job, check ownership. Reuse `_assert_can_edit_job` helper.

---

## Implementation Order (estimated)

1. Migration + backfill — 0.5 day
2. Slice 1 (valves) backend + frontend + tests — 1 day
3. Slice 2 (instruments) backend + frontend + tests — 1 day
4. Slice 3 (datasheet) backend + frontend + tests — 1.5 days
5. Slice 4 (admin labels) — 0.25 day
6. Slice 5 (remove static text) — 0.05 day

**Total: ~4 days of focused work, shippable in slices.**

---

## Out of Scope (Tracked Elsewhere)

- Adding `Organization` model and `org_id` FK to Job — separate spec.
- Adding `Project` model (one project = many P&ID revisions) — separate spec; tied to digital-twin Sprint 2.
- Populating `bbox` and `sheet_index` from the existing OpenRouter API pipeline — separate spec; needs prompt engineering changes.
- User-facing "job → project" rename — separate small PR.
- Login-as-customer impersonation — deferred; revisit when a customer asks.
