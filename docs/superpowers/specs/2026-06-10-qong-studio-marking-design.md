# Qong Studio Marking & Graph-Annotation System

**Date:** 2026-06-10
**Status:** Approved by user (direct build authorized); ship in phases on `dev`.
**Owner:** lead + Claude Code multi-agent track.
**Related specs:** `docs/superpowers/specs/2026-06-05-graph-extraction-design.md` (line tracing pipeline; this spec extends its data model for non-pipe line types).

## 0. Why

Today users see what the model found on a P&ID tile but cannot:

1. Mark symbols the model missed (false negatives).
2. Confirm or reject what the model did find (no per-detection signal for active-learning).
3. Connect symbols with pipes, signal lines, or interlocks (no graph annotation surface).
4. Define their own keyboard shortcuts for high-velocity marking.
5. See cross-tile lines as one continuous path (the canvas shows only a single tile at a time).

Without those, Qong Studio cannot be the single annotation surface that drives v1-11+ training AND ships deliverables. We need one prod-grade tool that captures every annotation event and feeds the training loop nightly.

## 1. Goal & Success Criteria

**Goal:** Build a unified annotation surface in Qong Studio where users mark symbols, draw lines (process pipe / instrument / signal / interlock), and confirm/reject the model — with every action persisted as training signal, and a continuous full-page canvas that ignores tile boundaries.

**Success (v1):**

- A user can mark a missed valve in under 5 seconds (palette drag OR shortcut + click).
- A user can draw a pipe connecting two existing entities in under 5 seconds (mode toggle + 2 clicks).
- 100% of user actions land in `user_annotations` or `graph_corrections` with full audit columns.
- Nightly export reproduces YOLO-format `.txt` labels for every confirmed `add` annotation.
- The "% of entities found by model vs added by user" delta is queryable per-job and over-time.
- Cross-tile pipes render as one polyline (no per-tile filter).

## 2. Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                          Qong Studio                                   │
│  ┌──────────────────────────────────────────────────────────────┐      │
│  │  PidCanvas (renders full-page PNG, NOT tile)                 │      │
│  │  ┌──────────────────────────────────────────────────────┐    │      │
│  │  │  Konva Stage (page-pixel coord space)                │    │      │
│  │  │   - Background: page_{p}_full.png                    │    │      │
│  │  │   - Layer 1: bboxes (from detections + user_annotations)│ │      │
│  │  │   - Layer 2: edges (from canonical_graph.json +      │    │      │
│  │  │              graph_corrections) — polylines          │    │      │
│  │  │   - Layer 3: drag-preview / draw-edge-preview        │    │      │
│  │  └──────────────────────────────────────────────────────┘    │      │
│  │                                                              │      │
│  │  Mode Toolbar: [Select] [Mark Symbol] [Draw Edge]            │      │
│  │  Palette (mode-dependent): hierarchical class → sub_class    │      │
│  │  Line-type sub-toolbar (Draw-Edge mode):                     │      │
│  │     [Process Pipe] [Instrument] [Signal] [Interlock]         │      │
│  └──────────────────────────────────────────────────────────────┘      │
│                                                                        │
│  Account → Shortcuts: per-user JSON keymap → class binding             │
└────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼  HTTPS
┌────────────────────────────────────────────────────────────────────────┐
│                          FastAPI Backend                               │
│                                                                        │
│  POST/GET/PATCH/DELETE /api/v1/jobs/{id}/annotations    (symbols)      │
│  POST/GET/PATCH/DELETE /api/v1/jobs/{id}/edges          (lines)        │
│  GET   /api/v1/jobs/{id}/page/{n}/full                  (image)        │
│  PATCH /api/v1/users/me/shortcuts                       (keymap)       │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼  SQLAlchemy
┌────────────────────────────────────────────────────────────────────────┐
│                              Postgres                                  │
│                                                                        │
│  user_annotations      (workflow state: status, tag, fields, source)   │
│  graph_corrections     (workflow state: line_type, relation, group)    │
│  model_corrections     (UNCHANGED — bbox-level YOLO training signal)   │
│  users.shortcuts       (NEW JSON column on existing users table)       │
└────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼  Nightly cron
┌────────────────────────────────────────────────────────────────────────┐
│                  Training Export Scripts                               │
│                                                                        │
│  webapp/scripts/export_annotations_for_yolo.py                         │
│      → datasets/pid_valves/labels/<job>/<tile>.txt                     │
│  webapp/scripts/export_graph_for_training.py                           │
│      → datasets/pid_graph/<job>/edges.jsonl                            │
└────────────────────────────────────────────────────────────────────────┘
```

## 3. Data Model

### 3.1 `user_annotations` (NEW)

Every symbol marking event (model_found, user_added, user_confirmed, user_rejected). Keyed by `(job_id, entity_id)` — same entity_id space as `canonical_entities` and `entity_overrides` (UUID stringified).

```python
class UserAnnotation(Base):
    __tablename__ = "user_annotations"

    id              = Column(Integer, primary_key=True)
    job_id          = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    entity_id       = Column(String, nullable=False)              # UUID string
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    source          = Column(String, nullable=False)              # 'model' | 'user'
    status          = Column(String, nullable=False)
        # 'model_found' | 'user_added' | 'user_confirmed' | 'user_rejected'
    entity_class    = Column(String, nullable=False)              # 'valve' | 'instrument' | 'equipment'
    sub_class       = Column(String, nullable=True)               # 'BV' | 'FT' | 'CV' | ...
    bbox            = Column(JSON, nullable=False)                # [x1,y1,x2,y2] page-pixel
    sheet_number    = Column(Integer, nullable=False, default=1)
    placeholder_tag = Column(String, nullable=True)               # 'USER-VB-0042'
    tag             = Column(String, nullable=True)               # user-filled later
    fields_json     = Column(JSON, nullable=True)                 # size, vendor, etc.
    linked_detection_index = Column(Integer, nullable=True)
        # index in Job.gpu_detections this annotation refers to; -1 for fresh user marks
    linked_correction_id   = Column(Integer, ForeignKey("model_corrections.id"), nullable=True)
        # 1:1 link when this annotation produced a YOLO-trainable correction row
    created_at      = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at      = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "entity_id", name="uq_user_annotations_je"),
        Index("ix_user_annotations_status", "status"),
        Index("ix_user_annotations_source", "source"),
    )
```

### 3.2 `graph_corrections` (NEW)

User-added or user-edited edges (process pipes + non-pipe line types).

```python
class GraphCorrection(Base):
    __tablename__ = "graph_corrections"

    id              = Column(Integer, primary_key=True)
    job_id          = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    edge_id         = Column(String, nullable=False)              # UUID string
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    source          = Column(String, nullable=False)              # 'opencv' | 'llm_fallback' | 'user'
    status          = Column(String, nullable=False)
        # 'model_found' | 'user_added' | 'user_confirmed' | 'user_rejected'
    line_type       = Column(String, nullable=False)
        # 'process_pipe' | 'instrument' | 'signal' | 'interlock'
    relation_type   = Column(String, nullable=True)
        # 'carries' | 'measures' | 'controls' | 'interlocks_with' | 'loops_to' | None
    source_entity_id = Column(String, nullable=False)             # FK-ish to user_annotations.entity_id
    target_entity_id = Column(String, nullable=False)
    target_sheet_number = Column(Integer, nullable=True)
        # Set when target lives on a different sheet (page connector)
    polyline        = Column(JSON, nullable=False)                # [[x,y],[x,y],...] page-pixel
    sheet_number    = Column(Integer, nullable=False, default=1)
    group_id        = Column(String, nullable=True)
        # All edges sharing a group_id form one logical loop / interlock
    metadata_json   = Column(JSON, nullable=True)
        # signal: 4-20mA, fail-safe, signal source, etc.
    created_at      = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at      = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "edge_id", name="uq_graph_corrections_je"),
        Index("ix_graph_corrections_line_type", "line_type"),
        Index("ix_graph_corrections_group_id", "group_id"),
    )
```

### 3.3 `users.shortcuts` (NEW JSON column)

Per-user keymap from physical key → entity sub_class (or special action). Loaded once at Studio mount.

```json
{
  "v": {"action": "select-class", "entity_class": "valve", "sub_class": "BV"},
  "b": {"action": "select-class", "entity_class": "valve", "sub_class": "GT"},
  "f": {"action": "select-class", "entity_class": "instrument", "sub_class": "FT"},
  "p": {"action": "select-class", "entity_class": "instrument", "sub_class": "PT"},
  "e": {"action": "mode", "mode": "draw-edge"},
  "s": {"action": "mode", "mode": "select"},
  "Escape": {"action": "cancel"},
  "Delete": {"action": "delete-selected"}
}
```

Defaults shipped centrally; user overrides merge over them. Stored as JSONB on Postgres.

### 3.4 Collision rule — mark on existing detection

When the user drops a mark on a tile region already covered by a model detection:

| Same class as detection? | Action |
|---|---|
| Yes | Create `user_annotations(status='user_confirmed', source='user', linked_detection_index=N)`. No `model_corrections` row. |
| No  | Create `user_annotations(status='user_added', source='user', linked_detection_index=N)` for the new class + `model_corrections(action='delete', detection_index=N)` to mark the model wrong. The model detection no longer renders. |

For empty regions: `user_annotations(status='user_added', source='user', linked_detection_index=-1)` + `model_corrections(action='add', new_bbox=bbox, new_label=class)`.

## 4. API Surface

All endpoints under `/api/v1/jobs/{job_id}/...` follow the same auth pattern as `entities.py` (owner or super_admin, 404 on foreign jobs).

### Annotations (symbols)

```
GET    /api/v1/jobs/{job_id}/annotations
       → {"annotations": [{entity_id, source, status, bbox, sheet_number,
                            entity_class, sub_class, tag, fields_json,
                            placeholder_tag, created_at, updated_at, ...}]}

POST   /api/v1/jobs/{job_id}/annotations
       body: {entity_class, sub_class, bbox: [x1,y1,x2,y2],
              sheet_number, linked_detection_index?: int}
       → 201 {entity_id, status, placeholder_tag, ...}
       (Auto-assigns placeholder_tag like 'USER-VB-0042'. Handles collision rule.)

PATCH  /api/v1/jobs/{job_id}/annotations/{entity_id}
       body: any subset of {status, tag, fields_json, sub_class}
       → 200 {entity_id, ...updated row}

DELETE /api/v1/jobs/{job_id}/annotations/{entity_id}
       → 204
       (Soft-rejects user_added ones; user_confirmed ones revert to model_found.)
```

### Edges (lines)

```
GET    /api/v1/jobs/{job_id}/edges
       → {"edges": [{edge_id, source, status, line_type, relation_type,
                     source_entity_id, target_entity_id, polyline,
                     sheet_number, group_id, metadata_json, ...}]}

POST   /api/v1/jobs/{job_id}/edges
       body: {line_type, source_entity_id, target_entity_id,
              polyline, sheet_number, relation_type?, group_id?,
              target_sheet_number?, metadata_json?}
       → 201 {edge_id, ...}

PATCH  /api/v1/jobs/{job_id}/edges/{edge_id}
       body: any subset of {status, line_type, relation_type, polyline,
                            group_id, metadata_json}

DELETE /api/v1/jobs/{job_id}/edges/{edge_id}
```

### Page render

```
GET    /api/v1/jobs/{job_id}/page/{page_index}/full
       → image/png (the page_{page_index}_full.png file)
       Headers: same CORS + Vary: Origin pattern as serve_tile.
```

### Shortcuts

```
GET    /api/v1/users/me/shortcuts          → {"shortcuts": {...}}
PATCH  /api/v1/users/me/shortcuts          body: {shortcuts: {...}}  (whole-object replace)
```

## 5. Frontend Components

```
webapp/frontend/src/studio/
├── PidCanvas.tsx              MODIFIED — full-page render; multi-layer Konva
├── PalettePanel.tsx           NEW — hierarchical class→sub_class picker
├── ModeToolbar.tsx            NEW — Select / Mark Symbol / Draw Edge
├── LineTypeToolbar.tsx        NEW — process_pipe / instrument / signal / interlock
├── ShortcutOverlay.tsx        NEW — toggleable HUD that lists active bindings
├── annotations/
│   ├── api.ts                 NEW — getAnnotations / createAnnotation / patch / delete
│   ├── useAnnotations.ts      NEW — React hook (cached + optimistic)
│   └── statusBadge.tsx        NEW — pill renderer for status states
├── edges/
│   ├── api.ts                 NEW
│   ├── useEdges.ts            NEW
│   └── lineStyles.ts          NEW — per-line-type stroke pattern + color
├── shortcuts/
│   ├── api.ts                 NEW
│   ├── useShortcuts.ts        NEW
│   └── keyboard.ts            NEW — global keydown listener
└── Studio.tsx                 MODIFIED — wire palette + toolbar + canvas + shortcuts

webapp/frontend/src/account/
└── Shortcuts.tsx              NEW — per-user shortcut editor
```

`PidCanvas` rewrite is the largest change — currently 552 lines, expected to land ~700 with the three Konva layers and mode-aware event handlers. Worth splitting layer renderers into separate files (`BboxLayer.tsx`, `EdgeLayer.tsx`, `PreviewLayer.tsx`) to keep each under 300 lines.

## 6. Phased Build Sequence

| Phase | Scope | Verification | Deploy |
|---|---|---|---|
| **1** | Schema (`user_annotations`, `graph_corrections`, `users.shortcuts`), API routes (`/annotations`, `/edges`, `/page/{n}/full`, `/users/me/shortcuts`), unit tests | `pytest tests/unit/test_annotations_api.py` | push → dev |
| **2** | `PidCanvas` swap to full-page render; drop tile filter; pan/zoom validation | Playwright load job 41 dev, full page visible, all bboxes on one canvas | push → dev |
| **3** | `PalettePanel` + drag-drop + status states + collision logic on POST | Playwright drag-place + click-on-existing flows | push → dev |
| **4** | `ModeToolbar` + edge drawing (all line types) + relation metadata + group_id | Playwright 2-click edge in each line_type | push → dev |
| **5** | Per-user shortcuts (User column + Account page + global listener) | Playwright keyboard sequence places a marked entity | push → dev |
| **6** | Nightly export scripts + admin metrics dashboard (model% vs user%) | pytest export roundtrip + dev cron manual run | push → dev |

Each phase ends with: pytest green, vitest green where applicable, Playwright happy path verified on dev, commit + push to dev (auto-deploy). FEATURES.md entry on every phase.

## 7. Testing Strategy

- **Backend unit tests** per router file, fixture DB via `sqlite:///:memory:` (existing pattern in `tests/unit/`).
- **State transition tests** — for each (current_status, action) pair, assert the resulting status; collision rule is one explicit test per branch.
- **Frontend unit tests** — vitest for `buildElements`-equivalent annotation derivation, status badge rendering, shortcut keymap merging.
- **Playwright smoke tests** — one per phase, on dev environment, hitting real Postgres. Browser closed after every run (project convention).
- **Idempotency tests** — POST same annotation twice = single row (uniqueness via `(job_id, entity_id)`), PATCH no-op tolerated.

## 8. Open Risks

| Risk | Mitigation |
|---|---|
| Full-page render PNG too large (>10 MB) for slow clients | Single fetch + cache; future PR to stream WebP or PDF.js |
| `gpu_detections` rendering all-on-one-canvas may visually overwhelm at 100% zoom | Default zoom-to-first-detection + click-through nav |
| Shortcut conflicts with browser/OS chords (Ctrl+S etc.) | Disallow modifier-chord bindings in v1; surface conflict warning on save |
| 1:1 link between `user_annotations` and `model_corrections` couples two stores | Foreign-key relationship is nullable + soft — code tolerates orphans |
| Group_id semantics ("loop") undefined for non-instrument line types | v1 uses group_id only for loops + interlocks; pipes leave it null |
| `users.shortcuts` JSON has no schema enforcement | Validate at API layer; reject unknown keys; log frontend parse errors |

## 9. Handover & FEATURES Trail

- One FEATURES.md entry per phase ship (`#38`, `#39`, ...).
- Spec stays put; superseding sections marked at the top of this doc.
- `SESSION_STATE.md` references the active phase across multi-session work.
- Graph-extraction spec (`2026-06-05`) gets a forward-reference note that `graph_corrections` now hosts user-added edges (was: planned `/graph/edges` corrections endpoint).
