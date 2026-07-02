"""Graph-edge CRUD API (Studio marking, FEATURES #38).

Backs the Studio canvas line-drawing tool. The user draws a polyline between
two entities (valve → instrument, instrument → DCS, etc.); the frontend POSTs
the path here and we persist it in `graph_corrections`.

Why a write-ahead store (not direct edits to canonical_graph.json):
  - The on-disk `canonical_graph.json` is the pipeline source-of-truth (graph-
    extraction spec, 2026-06-05). User edits live in a parallel DB layer that
    deliverable generators merge at read time — same pattern as
    `entity_overrides` for entity fields. Keeps re-runs of the pipeline idempotent.
  - Auditing: every user edge has user_id + created_at; deletions are hard but
    the audit lives in the change history surface (out of scope here).

Endpoints (mounted under prefix "/api/v1/jobs"):
  GET    /{job_id}/edges                    list all GraphCorrection rows for job
  POST   /{job_id}/edges                    create a new user edge (status='user_added')
  PATCH  /{job_id}/edges/{edge_id}          partial update (re-classify / re-route)
  DELETE /{job_id}/edges/{edge_id}          hard delete

Auth: same IDOR pattern as `entities.py` / `exports.py` — 404 (not 403) for
foreign jobs to avoid leaking other users' job IDs. Super_admin can read/write
any job.

Entity-id reference policy (intentional, not a bug):
  `source_entity_id` and `target_entity_id` are stored as plain strings with
  NO foreign-key enforcement. They may legitimately point at either a
  `user_annotations.entity_id` (a user-added entity) OR a
  `canonical_entities.entity_id` (a model detection from the pipeline).
  Validating the FK at write time would force one or the other and break the
  write-ahead model. The frontend is responsible for surfacing dangling refs
  to the user.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, conlist
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db

router = APIRouter(prefix="/api/v1/jobs", tags=["edges"])


# Line types accepted on create. Mirrors the GraphCorrection model docstring.
VALID_LINE_TYPES = {"plain_pipe", "process_pipe", "instrument", "signal", "interlock"}
# Allowed values for the other free-text-ish columns (mirror the model comments).
# Validated so a typo can't silently change graph-merge visibility (graph.py
# filters edges by status) or corrupt the relation taxonomy.
VALID_RELATION_TYPES = {"carries", "measures", "controls", "interlocks_with", "loops_to"}
VALID_STATUSES = {"model_found", "user_added", "user_confirmed", "user_rejected"}


# --- pydantic models ---

# A single (x, y) page-pixel coordinate.
PolylinePoint = conlist(float, min_length=2, max_length=2)
# A polyline must have at least 2 points (a line). We don't cap the upper bound
# — complex routes around equipment can need 10+ segments.
# Cap polyline length: a real pipe run is a handful of segments; 500 points is
# far beyond any legitimate edge and bounds the JSON stored per row + re-served
# on every /edges and /graph read (security: unbounded-row / DoS guard).
Polyline = conlist(PolylinePoint, min_length=2, max_length=500)


class EdgeCreate(BaseModel):
    line_type: str
    source_entity_id: str
    target_entity_id: str
    polyline: Polyline  # type: ignore[valid-type]
    sheet_number: int = 1
    relation_type: Optional[str] = None
    group_id: Optional[str] = None
    target_sheet_number: Optional[int] = None
    metadata_json: Optional[Dict[str, Any]] = None
    # User-drawn edges are directed source→target by construction (the user
    # asserted the flow direction by click order). Defaults True; a caller may
    # pass False to record an explicitly-undirected edge.
    directed: bool = True


class EdgePatch(BaseModel):
    """All fields optional. Only those present in the payload are updated.

    Mirrors PATCH semantics — omitted fields are left untouched, explicit
    `null` is a clear (set the column to NULL). Use case for clear: removing
    a group_id when an edge is reclassified out of a control loop.
    """
    status: Optional[str] = None
    line_type: Optional[str] = None
    relation_type: Optional[str] = None
    polyline: Optional[Polyline] = None  # type: ignore[valid-type]
    group_id: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    directed: Optional[bool] = None


class EdgeRow(BaseModel):
    edge_id: str
    job_id: int
    user_id: int
    source: str
    status: str
    line_type: str
    relation_type: Optional[str] = None
    source_entity_id: str
    target_entity_id: str
    target_sheet_number: Optional[int] = None
    polyline: List[List[float]]
    sheet_number: int
    group_id: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    directed: bool = True


class EdgesResponse(BaseModel):
    edges: List[EdgeRow]


# --- helpers ---


def _load_job_or_404(
    job_id: int, db: Session, current_user: models.User
) -> models.Job:
    """Mirror of entities.py auth pattern. 404 (not 403) for foreign jobs.

    Difference from entities.py: we do NOT require `job.output_csv_path` to be
    set. The user can draw edges on a job whose CSV deliverable hasn't been
    emitted yet (e.g. during initial marking). This is the intended workflow
    — marking edges is a precursor to graph-extraction running.
    """
    job: Optional[models.Job] = db.get(models.Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    if job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job


def _row_to_response(row: models.GraphCorrection) -> EdgeRow:
    return EdgeRow(
        edge_id=row.edge_id,
        job_id=row.job_id,
        user_id=row.user_id,
        source=row.source,
        status=row.status,
        line_type=row.line_type,
        relation_type=row.relation_type,
        source_entity_id=row.source_entity_id,
        target_entity_id=row.target_entity_id,
        target_sheet_number=row.target_sheet_number,
        polyline=row.polyline,
        sheet_number=row.sheet_number,
        group_id=row.group_id,
        metadata_json=row.metadata_json,
        # NULL (legacy rows pre-migration) → True: user edges were always directed.
        directed=True if row.directed is None else bool(row.directed),
    )


# --- endpoints ---


@router.get(
    "/{job_id}/edges",
    response_model=EdgesResponse,
    responses={
        200: {"description": "All graph_corrections rows for the given job"},
        404: {"description": "Job not found / not owned by caller"},
    },
)
def list_edges(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> EdgesResponse:
    _load_job_or_404(job_id, db, current_user)
    rows = (
        db.query(models.GraphCorrection)
        .filter(models.GraphCorrection.job_id == job_id)
        .order_by(models.GraphCorrection.id.asc())
        .all()
    )
    return EdgesResponse(edges=[_row_to_response(r) for r in rows])


@router.post(
    "/{job_id}/edges",
    response_model=EdgeRow,
    status_code=201,
    responses={
        201: {"description": "Edge created"},
        400: {"description": "Invalid line_type, polyline, or self-loop"},
        404: {"description": "Job not found / not owned by caller"},
    },
)
def create_edge(
    job_id: int,
    payload: EdgeCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> EdgeRow:
    job = _load_job_or_404(job_id, db, current_user)

    if payload.line_type not in VALID_LINE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid line_type '{payload.line_type}'. "
                f"Must be one of: {sorted(VALID_LINE_TYPES)}"
            ),
        )
    if payload.relation_type is not None and payload.relation_type not in VALID_RELATION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid relation_type '{payload.relation_type}'. "
                f"Must be one of: {sorted(VALID_RELATION_TYPES)}"
            ),
        )
    if payload.source_entity_id == payload.target_entity_id:
        # Self-loops aren't a real P&ID construct and complicate the graph
        # consumers (NetworkX is_isomorphic, BOM joins). Disallowed v1.
        raise HTTPException(
            status_code=400,
            detail="source_entity_id and target_entity_id must differ (self-loops disallowed)",
        )

    edge_id = uuid.uuid4().hex
    row = models.GraphCorrection(
        job_id=job.id,
        edge_id=edge_id,
        user_id=current_user.id,
        source="user",
        status="user_added",
        line_type=payload.line_type,
        relation_type=payload.relation_type,
        source_entity_id=payload.source_entity_id,
        target_entity_id=payload.target_entity_id,
        target_sheet_number=payload.target_sheet_number,
        polyline=payload.polyline,
        sheet_number=payload.sheet_number,
        group_id=payload.group_id,
        metadata_json=payload.metadata_json,
        directed=payload.directed,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    # Neo4j mirror — non-fatal, runs after PostgreSQL commit.
    from webapp.graph.neo4j_writer import write_user_edge_to_neo4j
    write_user_edge_to_neo4j(
        job_id=job.id,
        edge_id=edge_id,
        source_entity_id=payload.source_entity_id,
        target_entity_id=payload.target_entity_id,
        line_type=payload.line_type,
        polyline=[list(p) for p in payload.polyline],
        directed=payload.directed,
        status="user_added",
        group_id=payload.group_id,
    )
    return _row_to_response(row)


@router.patch(
    "/{job_id}/edges/{edge_id}",
    response_model=EdgeRow,
    responses={
        200: {"description": "Edge updated"},
        400: {"description": "Invalid line_type or polyline"},
        404: {"description": "Job or edge not found / not owned by caller"},
    },
)
def patch_edge(
    job_id: int,
    edge_id: str,
    payload: EdgePatch,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> EdgeRow:
    _load_job_or_404(job_id, db, current_user)

    row: Optional[models.GraphCorrection] = (
        db.query(models.GraphCorrection)
        .filter(
            models.GraphCorrection.job_id == job_id,
            models.GraphCorrection.edge_id == edge_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"edge {edge_id} not in job {job_id}",
        )

    # Validate before mutating so a bad payload is atomic — caller gets a 400
    # with the original row untouched.
    update_data = payload.model_dump(exclude_unset=True)
    if "line_type" in update_data and update_data["line_type"] not in VALID_LINE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid line_type '{update_data['line_type']}'. "
                f"Must be one of: {sorted(VALID_LINE_TYPES)}"
            ),
        )
    if (
        update_data.get("relation_type") is not None
        and update_data["relation_type"] not in VALID_RELATION_TYPES
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid relation_type '{update_data['relation_type']}'. "
                f"Must be one of: {sorted(VALID_RELATION_TYPES)}"
            ),
        )
    if (
        update_data.get("status") is not None
        and update_data["status"] not in VALID_STATUSES
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid status '{update_data['status']}'. "
                f"Must be one of: {sorted(VALID_STATUSES)}"
            ),
        )

    for field, value in update_data.items():
        setattr(row, field, value)

    db.commit()
    db.refresh(row)
    return _row_to_response(row)


@router.delete(
    "/{job_id}/edges/{edge_id}",
    status_code=204,
    # Don't add `responses={204: ...}` — newer FastAPI asserts no body is
    # allowed for 204 at route-registration time when a response is declared.
    responses={
        404: {"description": "Job or edge not found / not owned by caller"},
    },
)
def delete_edge(
    job_id: int,
    edge_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Response:
    _load_job_or_404(job_id, db, current_user)

    row: Optional[models.GraphCorrection] = (
        db.query(models.GraphCorrection)
        .filter(
            models.GraphCorrection.job_id == job_id,
            models.GraphCorrection.edge_id == edge_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"edge {edge_id} not in job {job_id}",
        )
    db.delete(row)
    db.commit()
    # Neo4j mirror — non-fatal, runs after PostgreSQL commit.
    from webapp.graph.neo4j_writer import delete_user_edge_from_neo4j
    delete_user_edge_from_neo4j(job_id=job_id, edge_id=edge_id)
    return Response(status_code=204)
