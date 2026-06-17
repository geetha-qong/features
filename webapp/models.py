"""ORM models: User, Job, ValveRow, Feedback.

All `DateTime` columns use `timezone=True` (Postgres `timestamptz`). Defaults
use `datetime.now(timezone.utc)` so writes are timezone-aware UTC. SQLite
silently ignores `timezone=True` (column behaves like TEXT) which is fine
for local dev — only Postgres needs to enforce the TZ contract.
"""
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, Float, ForeignKey, Index, JSON, UniqueConstraint
from webapp.database import Base


def _utcnow():
    """Aware UTC `now()` — used as `default=_utcnow` on DateTime columns."""
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="user")       # "user" | "annotator" | "super_admin"
    is_active = Column(Boolean, default=True)   # super_admin can deactivate/approve users
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    credits_remaining = Column(Integer, default=10)
    tier = Column(String, default="trial")               # 'trial'|'starter'|'pro'|'enterprise'
    organization = Column(String, nullable=True)
    timezone = Column(String, nullable=True)             # IANA TZ name; NULL = use browser-detected (Intl.DateTimeFormat fallback)
    shortcuts = Column(JSON, nullable=True)              # Studio keymap: { "v": {"action":"select-class","entity_class":"valve","sub_class":"BV"}, ... }


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False)
    pid_no = Column(String, default="UNKNOWN")
    status = Column(String, default="pending")  # pending/processing/done/failed
    valve_count = Column(Integer, default=0)
    error_msg = Column(Text, nullable=True)
    output_csv_path = Column(String, nullable=True)
    include_control_valves = Column(Boolean, default=True)
    processing_time = Column(Float, nullable=True)   # seconds
    processing_log = Column(Text, nullable=True)     # captured stdout from pipeline
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    ls_project_id = Column(Integer, nullable=True)   # Label Studio project id
    ls_synced = Column(Boolean, default=False)        # True once tiles pushed to LS
    output_inst_index_path = Column(String, nullable=True)   # instrumentation_index.csv
    output_inst_datasheet_path = Column(String, nullable=True)  # instrument_datasheets.zip
    output_annotated_pdf_path = Column(String, nullable=True)   # annotated.pdf (numbered bounding boxes)
    gpu_detections = Column(Text, nullable=True)              # JSON list from GPU worker callback


class JobRun(Base):
    """One row per pipeline attempt for a Job (rerun => new row).

    Tracks heartbeat for staleness detection, stage progress for visibility,
    and the final outcome / killer. Decouples per-attempt observability from
    the Job row, which only tracks the latest state.
    """
    __tablename__ = "job_runs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    attempt_num = Column(Integer, nullable=False)
    rq_id = Column(String, nullable=True)
    started_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, default="running")        # running|done|failed|killed
    current_stage = Column(String, nullable=True)     # latest "Stage N: ..." line
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    error_msg = Column(Text, nullable=True)
    error_traceback = Column(Text, nullable=True)
    stage_timings = Column(Text, nullable=True)       # JSON: [{stage, started_at, ended_at}]
    killer = Column(String, nullable=True)            # heartbeat-watchdog|manual|sigterm


class ValveRow(Base):
    __tablename__ = "valve_rows"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)

    # 14 CSV columns
    pid_no = Column(String, default="")
    dynamic_code = Column(String, default="-")
    category = Column(String, default="")
    size = Column(String, default="NOT DEFINED")
    area_code = Column(String, default="-")
    serial_no = Column(String, default="")
    series_code = Column(String, default="-")
    fluid_code = Column(String, default="")
    piping_class = Column(String, default="")
    qty = Column(Integer, default=1)
    motor_actuator = Column(String, default="-")
    pneumatic_actuator = Column(String, default="-")
    solenoid = Column(String, default="-")
    line = Column(String, default="")


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    notes = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)            # user-defined label e.g. "production"
    key_prefix = Column(String(8), nullable=False)   # first 8 chars for display
    key_hash = Column(String, nullable=False)         # pbkdf2_sha256 hash of full key
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    delta = Column(Integer, nullable=False)              # signed: positive=grant, negative=consume
    balance_after = Column(Integer, nullable=False)      # snapshot for audit
    reason = Column(String, nullable=False)              # 'signup_grant'|'admin_grant'|'job_consumed'|'purchase'|'refund'
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    meta = Column(Text, nullable=True)                   # JSON string for extra context
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class BillingPlan(Base):
    __tablename__ = "billing_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)                # "Trial" | "Starter" | "Pro" | "Enterprise"
    credits = Column(Integer, nullable=False)
    price_usd_cents = Column(Integer, nullable=False)    # 0 for Trial
    is_active = Column(Boolean, default=True)
    stripe_price_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class EntityOverride(Base):
    """A user edit to a single field of a single entity within a job's canonical output.

    The deliverables subsystem is filesystem-first (`canonical.json` is the
    pipeline-produced source of truth). Overrides live in the DB so we get
    audit columns (edited_by, edited_at, prior_value) and concurrent-write
    safety without filesystem races. Generators merge overrides on top of
    `canonical.json` before emitting bytes — see
    `webapp/deliverables/job_loader.load_canonical_with_overrides()`.

    `field_name` uses dot notation matching `CanonicalEntity`'s shape:
      - "tag"                    → top-level scalar
      - "sub_class"              → top-level scalar
      - "fields.size"            → key inside the `fields` dict
      - "vendor_match.vendor_name" → key inside the `vendor_match` sub-model

    Read-only fields (entity_id, entity_class, pid_number, sheet_number,
    bbox) are rejected by the PATCH endpoint, not at the DB layer — the DB
    will accept anything, the API enforces the allowlist.

    The UNIQUE constraint gives "current value only" semantics: re-editing
    overwrites the row, capturing the latest prior_value. Full audit history
    (every prior value, not just one) is a future migration if needed —
    drop the UNIQUE and add a superseded_at column.
    """
    __tablename__ = "entity_overrides"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    entity_id = Column(String, nullable=False)     # UUID as string — SQLite has no native UUID
    field_name = Column(String, nullable=False)
    new_value = Column(JSON, nullable=False)
    prior_value = Column(JSON, nullable=True)
    edited_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    edited_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "entity_id", "field_name", name="uq_entity_overrides_jef"),
    )


class ModelCorrection(Base):
    """A user correction to a single YOLO detection on a job's canvas.

    FEATURES #28 — active-learning plumbing. Each row captures one editorial
    action on the bbox overlay (``Job.gpu_detections`` JSON list):

      - ``action="delete"``      → false-positive: this bbox should not exist.
      - ``action="reclassify"``  → wrong class: ``new_label`` is the correct one.
      - ``action="add"``         → false-negative: ``new_bbox`` (and usually
        ``new_label``) describe a symbol the model missed.

    ``detection_index`` refers to the index in the JSON list at edit time
    (``-1`` is the convention for new "add" rows that don't correspond to an
    existing detection). The bbox + class snapshot lives in the JSON column
    so we keep enough context to rebuild YOLO label files later — see the
    forthcoming ``webapp/scripts/export_corrections_for_training.py``.

    Audit columns deliberately mirror :class:`EntityOverride` (user + time).
    There is no UNIQUE constraint here: the same detection may be corrected
    multiple times (e.g. classified twice while the user is iterating), and
    each correction is a row. The export script picks the most recent per
    ``(job_id, detection_index)``.
    """
    __tablename__ = "model_corrections"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    detection_index = Column(Integer, nullable=False)         # -1 for "add" rows
    action = Column(String, nullable=False)                   # "delete"|"reclassify"|"add"
    new_label = Column(String, nullable=True)
    new_bbox = Column(JSON, nullable=True)                    # [x1, y1, x2, y2]
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class CustomerTemplateOverride(Base):
    """Per-customer-template column-label override (FEATURES #29).

    The canonical templates live as JSON files on disk
    (`webapp/deliverables/customer_templates/<slug>.json`) — they remain the
    fallback. Admin edits (label rename / hide / reorder) live here and merge
    on top of the JSON at load time via
    `webapp.deliverables.template_loader.merged_template_dict()`.

    `column_key` matches the `field` value in the JSON template (dot-notation
    path, e.g. "fields.size", "tag", "vendor_match.vendor_name"). One row per
    (slug, deliverable_type, column_key) — re-saving overwrites.

    `label_override`, `column_order` are nullable so a row can hide a column
    without forcing a new label/order; nulls fall back to the JSON's `header`
    and `order`.
    """
    __tablename__ = "customer_templates_overrides"

    id = Column(Integer, primary_key=True)
    customer_template_slug = Column(String, nullable=False, index=True)   # "default" | "ronesans" | "muk" | ...
    deliverable_type = Column(String, nullable=False)                     # "valve_list" | "instrument_index" | "datasheet" | "equipment_list"
    column_key = Column(String, nullable=False)                           # matches `field` in the JSON template
    label_override = Column(String, nullable=True)                        # null = use template default header
    column_order = Column(Integer, nullable=True)                         # null = use template default order
    hidden = Column(Boolean, default=False, nullable=False)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "customer_template_slug", "deliverable_type", "column_key",
            name="uq_template_override_sdc",
        ),
    )


class UserFeedback(Base):
    __tablename__ = "user_feedback"                      # distinct from "feedback" (job-level engineer notes)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)   # nullable = anon submissions ok
    category = Column(String, nullable=False)            # 'bug'|'feature'|'pricing'|'other'
    subject = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    page_url = Column(String, nullable=True)
    status = Column(String, default="new")               # 'new'|'in_progress'|'resolved'|'wontfix'
    admin_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class CanonicalEntityRow(Base):
    """DB index of canonical entities — mirrors `canonical.json` for cross-job
    SQL queries (admin dashboards, "all valves of size 8 across customer X's
    jobs", per-job aggregations) without N filesystem reads + JSON parses.

    **Source of truth remains the on-disk `canonical.json`** (FEATURES #26 /
    #33). This table is a denormalised read-index — populated by dual-write
    in `webapp.deliverables.pipeline_emitter.write_canonical_for_job()` when
    the pipeline emits a fresh file, and back-populated for legacy jobs via
    `webapp/scripts/index_canonical_to_db.py`. Deliverable generators still
    read the canonical file + merge `entity_overrides` at request time —
    this table doesn't change the read path.

    User edits are NOT applied here. `entity_overrides` is the edit store;
    a row in this table reflects what the pipeline emitted, not what the
    user has changed since. If you need "what the user sees", join through
    the deliverables API.

    Unique on (job_id, entity_id) — re-emit upserts. Indexed on
    (entity_class, tag) so the common "find all valves with tag X" query
    is cheap.
    """
    __tablename__ = "canonical_entities"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)          # UUID as string (SQLite has no UUID type)
    entity_class = Column(String, nullable=False, index=True)       # 'valve' | 'instrument' | 'equipment'
    sub_class = Column(String, nullable=True)                       # 'BV', 'BF', etc. for valves; None for instruments
    tag = Column(String, nullable=True, index=True)
    pid_number = Column(String, nullable=False)
    sheet_number = Column(Integer, nullable=False)
    bbox = Column(JSON, nullable=False)                             # [x1, y1, x2, y2] floats
    fields = Column(JSON, nullable=False, default=dict)             # entity-specific scalar map
    vendor_match = Column(JSON, nullable=True)                      # VendorMatch sub-model when present
    canonical_schema_version = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "entity_id", name="uq_canonical_entities_je"),
    )


class UserAnnotation(Base):
    """Workflow-state row for every symbol-level annotation event on a job.

    Companion to (NOT replacement for) `model_corrections`:
      - `model_corrections` captures bbox-level training signal (add / delete /
        reclassify) consumed by the YOLO export script.
      - `user_annotations` captures the higher-level workflow state — status
        lifecycle, placeholder tag → user-filled tag, fields, source attribution.

    When the user marks a previously-undetected entity, a row is inserted here
    AND in `model_corrections` (linked via `linked_correction_id`). When the
    user merely confirms an existing model detection, only a `user_annotations`
    row is created (no training-relevant correction).

    Status lifecycle:
      - `model_found`     → row implicitly exists per detection rendered (not always materialized)
      - `user_added`      → user drew/dropped a new bbox the model missed
      - `user_confirmed`  → user clicked an existing model detection, no class change
      - `user_rejected`   → user marked a model detection as wrong (false-positive)

    Source-of-truth note: the on-disk `canonical.json` is unchanged by this
    table. User-added marks become deliverable rows only after a separate
    "promote pending marks" workflow (Phase 6). Reads that need user state
    join through this table; reads that need pipeline state still go to
    `canonical_entities`.

    Unique on (job_id, entity_id) so each entity has at most one workflow row
    per job. Re-marking same entity_id = UPDATE, not duplicate INSERT.
    """
    __tablename__ = "user_annotations"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)        # UUID string — same id space as canonical_entities
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    source = Column(String, nullable=False)                       # 'model' | 'user'
    status = Column(String, nullable=False)                       # 'model_found'|'user_added'|'user_confirmed'|'user_rejected'
    entity_class = Column(String, nullable=False, index=True)     # 'valve'|'instrument'|'equipment'
    sub_class = Column(String, nullable=True)                     # 'BV'|'FT'|'CV'|...
    bbox = Column(JSON, nullable=False)                           # [x1,y1,x2,y2] page-pixel coords
    sheet_number = Column(Integer, nullable=False, default=1)
    placeholder_tag = Column(String, nullable=True)               # auto-assigned 'USER-VB-0042'
    tag = Column(String, nullable=True)                           # user-filled later
    fields_json = Column(JSON, nullable=True)                     # size, vendor, etc.
    linked_detection_index = Column(Integer, nullable=True)       # index in Job.gpu_detections; -1 for fresh user marks
    linked_correction_id = Column(Integer, ForeignKey("model_corrections.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "entity_id", name="uq_user_annotations_je"),
        Index("ix_user_annotations_status", "status"),
        Index("ix_user_annotations_source", "source"),
    )


class SheetApplyState(Base):
    """Persisted "Apply" state for a Studio sheet (design 2026-06-13, §1b).

    When a reviewer finishes marking a P&ID sheet they click "Apply · N".
    Previously this was UI-only per-session state (`appliedBySheet` in
    `Studio.tsx`); this table makes it survive a reload.

    One row per (job_id, sheet_number) — applying again upserts `applied_at` /
    `applied_by`; "re-arm" (the user added/removed marks and wants to re-apply)
    deletes the row. The presence of a row is the signal "this sheet is
    applied"; `applied_at` is surfaced to the frontend (Z-suffixed via
    `utc_iso`) so the picker can show when.

    Source-of-truth note: the underlying annotations live in
    `user_annotations`; this table only records the reviewer's "I'm done with
    this sheet" intent. It is not consumed by deliverable generators.
    """
    __tablename__ = "sheet_apply_state"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    sheet_number = Column(Integer, nullable=False)
    applied_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    applied_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "sheet_number", name="uq_sheet_apply_state"),
    )


class GraphCorrection(Base):
    """User-added or user-edited edges on a job's process graph.

    Companion to `canonical_graph.json` (file source of truth — produced by the
    graph-extraction pipeline; see `docs/superpowers/specs/2026-06-05-graph-extraction-design.md`).
    This DB table holds the user-edit layer:
      - Edges added by users (`source='user'`).
      - User confirmations of automatically-found edges (`status='user_confirmed'`).
      - User rejections of false-positive edges (`status='user_rejected'`).

    Extends the graph-extraction spec by supporting non-pipe line types:
      - `process_pipe`  — solid line (default; what graph-extraction v0 ships)
      - `instrument`    — instrument line (dashed)
      - `signal`        — DCS/control signal (long-dashed with marker)
      - `interlock`     — interlock line (dash-dot or labeled chain)

    `group_id` groups related edges into one logical relationship:
      - Control loops (FIC-101 → FT-101 + FIC-101 → FV-101) share a group_id.
      - Interlocks spanning N edges share a group_id.
      - Plain pipes leave it NULL.

    `metadata_json` holds line-type-specific extras (signal: 4-20mA, fail-safe
    direction; process pipe: pipe spec; instrument: tag of carried signal).
    Schemaless on purpose — different line types need different attributes.
    """
    __tablename__ = "graph_corrections"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    edge_id = Column(String, nullable=False, index=True)          # UUID string
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    source = Column(String, nullable=False)                       # 'opencv'|'llm_fallback'|'user'
    status = Column(String, nullable=False)                       # 'model_found'|'user_added'|'user_confirmed'|'user_rejected'
    line_type = Column(String, nullable=False, index=True)        # 'process_pipe'|'instrument'|'signal'|'interlock'
    relation_type = Column(String, nullable=True)                 # 'carries'|'measures'|'controls'|'interlocks_with'|'loops_to'
    source_entity_id = Column(String, nullable=False)             # FK-ish — joins to user_annotations.entity_id
    target_entity_id = Column(String, nullable=False)
    target_sheet_number = Column(Integer, nullable=True)          # set when target is on a different sheet (page-connector)
    polyline = Column(JSON, nullable=False)                       # [[x,y],[x,y],...] page-pixel
    sheet_number = Column(Integer, nullable=False, default=1)
    group_id = Column(String, nullable=True, index=True)          # all edges in a loop/interlock share this
    metadata_json = Column(JSON, nullable=True)
    # Flow direction flag (graph-directions, 2026-06-17). Nullable for back-compat:
    # rows that predate this column read as directed=True at the API layer (user
    # edges were always directed source→target). New user edges default True.
    directed = Column(Boolean, nullable=True, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    # NOTE: `line_type` + `group_id` indexes come from `index=True` on the columns
    # themselves. Don't add explicit Index() entries here for those columns —
    # SQLAlchemy auto-names them `ix_graph_corrections_<col>` and you'd hit a
    # duplicate-name DDL error on Base.metadata.create_all.
    __table_args__ = (
        UniqueConstraint("job_id", "edge_id", name="uq_graph_corrections_je"),
    )


class GraphNodeRow(Base):
    """DB read-index of auto-extracted graph nodes — mirrors the `nodes` array
    in `canonical_graph.json` (graph-extraction, 2026-06-13 design).

    **Source of truth is the on-disk `canonical_graph.json`.** This table is a
    denormalised read-cache for cross-job graph queries ("every node of class
    valve_bf across customer X's jobs", graph-size dashboards) without parsing N
    JSON files. Populated by `webapp.graph.graph_db_index.sync_graph_to_db()` as
    a dual-write after the pipeline emits the file, and back-populated for legacy
    jobs by `webapp/scripts/index_graph_to_db.py`.

    User edits are NOT applied here — `graph_corrections` is the edit store.
    This row reflects what the extractor emitted. Unique on (job_id, node_id).
    """
    __tablename__ = "graph_nodes"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    node_id = Column(String, nullable=False, index=True)          # 'n_001' (graph-local id)
    entity_id = Column(String, nullable=True, index=True)         # canonical_entities.entity_id; null when OCR/link failed
    tag = Column(String, nullable=True, index=True)
    node_class = Column(String, nullable=True, index=True)        # 'valve_bf', 'instrument', ...
    bbox = Column(JSON, nullable=True)                            # [x1,y1,x2,y2] page-pixel
    tile = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    sheet_number = Column(Integer, nullable=False, default=1)     # denormalised from graph 'page'
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "node_id", name="uq_graph_nodes_jn"),
    )


class GraphEdgeRow(Base):
    """DB read-index of auto-extracted graph edges — mirrors the `edges` array
    in `canonical_graph.json`.

    Same contract as `GraphNodeRow`: read-cache only, source of truth is the
    file, user edits live in `graph_corrections`. `method` ∈ {opencv,
    llm_fallback} (auto edges); user edges are NOT mirrored here — they already
    have their own table. Unique on (job_id, edge_id).
    """
    __tablename__ = "graph_edges"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    edge_id = Column(String, nullable=False, index=True)          # 'e_001'
    source_node = Column(String, nullable=False)                  # GraphNodeRow.node_id
    target_node = Column(String, nullable=False)
    method = Column(String, nullable=False, index=True)           # 'opencv' | 'llm_fallback'
    directed = Column(Boolean, nullable=True, default=False)      # flow direction known (source->target oriented by an arrow)
    confidence = Column(Float, nullable=True)
    polyline = Column(JSON, nullable=False)                       # [[x,y],...] page-pixel
    tile = Column(String, nullable=True)
    sheet_number = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "edge_id", name="uq_graph_edges_je"),
    )


class LabelTaxonomy(Base):
    """DB read-index of the P&ID symbol taxonomy — mirrors `webapp/taxonomy.json`.

    **Source of truth remains the on-disk `taxonomy.json`** (mirrors the
    `canonical_entities` contract — FEATURES #34). `webapp/taxonomy.py` is the
    in-process accessor every consumer reads; this table is a denormalised
    read-index so cross-cutting SQL/admin surfaces (palette config UI, triage
    assignment dropdowns, audits) can query the class list without parsing the
    JSON. Populated by `webapp.taxonomy_db.sync_taxonomy_to_db()` at startup
    and idempotent on (entity_class, sub_class).

    Never edit through this table — change `taxonomy.json` and re-sync. New
    labels discovered at runtime flow through `LabelTriage`, not direct writes
    here.
    """
    __tablename__ = "label_taxonomy"

    id = Column(Integer, primary_key=True, index=True)
    entity_class = Column(String, nullable=True, index=True)    # 'valve' | 'instrument' | 'equipment'; None for structural (arrow/connector) classes
    sub_class = Column(String, nullable=True)                   # 'BV', 'PT', ... ; None for unsubclassed classes
    display_name = Column(String, nullable=False)
    yolo_label = Column(String, nullable=True)                  # ONNX channel label; None for OCR-only canonical classes
    color = Column(String, nullable=False)                      # hex '#RRGGBB'
    glyph_kind = Column(String, nullable=False)
    isa_code = Column(String, nullable=True)
    order = Column("display_order", Integer, nullable=False, default=0)   # 'order' is a SQL reserved word -> safe column name
    active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("entity_class", "sub_class", name="uq_label_taxonomy_cs"),
    )


class LabelTriage(Base):
    """Queue of label values seen in the wild (Label Studio imports, raw
    detections) that aren't yet mapped into the taxonomy.

    A reviewer triages each `label_value` to an `(entity_class, sub_class,
    display_name, color, glyph_kind)` assignment (status 'approved') or marks
    it 'ignored'/'rejected'. Approved assignments are then promoted into
    `taxonomy.json` (the source of truth) by a separate step — this table is
    the staging/audit surface, not a live taxonomy override.

    Audit columns (`decided_by_user_id`, `decided_at`) mirror
    :class:`EntityOverride`. `label_value` is unique — the same raw label is
    one triage row, re-discovery doesn't duplicate it.
    """
    __tablename__ = "label_triage"

    id = Column(Integer, primary_key=True, index=True)
    label_value = Column(String, nullable=False, unique=True, index=True)
    source = Column(String, nullable=False)                     # 'ls' | 'detection'
    discovered_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending|approved|ignored|rejected
    assigned_entity_class = Column(String, nullable=True)
    assigned_sub_class = Column(String, nullable=True)
    assigned_display_name = Column(String, nullable=True)
    assigned_color = Column(String, nullable=True)
    assigned_glyph_kind = Column(String, nullable=True)
    decided_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
