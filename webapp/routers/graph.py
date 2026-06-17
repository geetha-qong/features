"""Process-graph read API (graph-extraction, 2026-06-13 design).

Serves the unified process graph for a job: the auto-extracted graph from the
on-disk ``canonical_graph.json`` (pipeline source of truth) merged with the
user-edit layer in ``graph_corrections`` (FEATURES #38, edges the user drew in
Studio).

Endpoint (mounted under prefix "/api/v1/jobs"):
  GET /{job_id}/graph   → 200 unified graph
                          404 {"error":"no_canonical"}      no canonical.json (pipeline never ran)
                          409 {"error":"canonical_required"} canonical present but graph not computed

Why merge at read time (not bake user edges into the file):
  Same contract as ``entity_overrides`` / ``canonical_entities`` — the file
  stays the pipeline's idempotent output, user edits live in a parallel DB
  layer, and the read path unions them. A pipeline re-run never clobbers user
  work.

Auth: same IDOR pattern as ``edges.py`` — 404 (not 403) for foreign jobs;
super_admin can read any job. Cookie-authed so the Studio ``<img>``-adjacent
fetch works same-origin.

v0 merge semantics (honest about limits):
  - Auto edges (method ``opencv`` / ``llm_fallback``) come from the file.
  - User edges (``graph_corrections``) are appended, tagged ``method`` from
    their ``source`` (``user`` → ``user_added``).
  - Rejecting an *auto* edge is NOT yet wired: auto edges are not stored in
    ``graph_corrections``, so there is no per-auto-edge reject key in v0. The
    merge is additive. Tracked for v0.5.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db

router = APIRouter(prefix="/api/v1/jobs", tags=["graph"])


def _load_job_or_404(
    job_id: int, db: Session, current_user: models.User
) -> models.Job:
    """404 (not 403) for foreign jobs — mirror of edges.py / entities.py."""
    job: Optional[models.Job] = db.get(models.Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    if job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job


def _job_dir(job: models.Job) -> Optional[Path]:
    if not job.output_csv_path:
        return None
    return Path(job.output_csv_path).parent


def _user_edge_to_dict(row: models.GraphCorrection) -> Dict[str, Any]:
    method = "user_added" if row.source == "user" else row.source
    # User edges are directed by construction (the user drew source→target).
    # A NULL `directed` column (legacy rows pre-migration) reads as True for
    # user edges — they were always directed; the column just didn't exist yet.
    directed = True if row.directed is None else bool(row.directed)
    return {
        "id": row.edge_id,
        "source": row.source_entity_id,
        "target": row.target_entity_id,
        "polyline": row.polyline,
        "tile": None,
        "method": method,
        "confidence": None,
        "directed": directed,
        "line_type": row.line_type,
        "status": row.status,
        "source_entity_id": row.source_entity_id,
        "target_entity_id": row.target_entity_id,
        "group_id": row.group_id,
    }


@router.get(
    "/{job_id}/graph",
    responses={
        200: {"description": "Unified process graph (auto + user edges)"},
        404: {"description": "No canonical.json — pipeline has not run"},
        409: {"description": "canonical.json present but graph not yet computed"},
    },
)
def get_job_graph(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Dict[str, Any]:
    job = _load_job_or_404(job_id, db, current_user)
    job_dir = _job_dir(job)

    graph_path = (job_dir / "canonical_graph.json") if job_dir else None
    canonical_path = (job_dir / "canonical.json") if job_dir else None

    if graph_path is None or not graph_path.exists():
        # No auto-graph on disk. Distinguish "pipeline never ran" from
        # "ran but graph step hasn't been computed for this (legacy) job".
        if canonical_path is not None and canonical_path.exists():
            raise HTTPException(
                status_code=409,
                detail={"error": "canonical_required",
                        "action": "run_pipeline_first"},
            )
        raise HTTPException(
            status_code=404,
            detail={"error": "no_canonical"},
        )

    try:
        graph: Dict[str, Any] = json.loads(graph_path.read_text(encoding="utf-8"))
    except Exception as e:  # corrupt file — treat as not-computed
        raise HTTPException(
            status_code=409,
            detail={"error": "graph_unreadable", "reason": str(e)},
        )

    graph.setdefault("job_id", job_id)
    auto_edges: List[Dict[str, Any]] = list(graph.get("edges", []))
    # Back-compat: legacy canonical_graph.json edges predate `directed`. A
    # missing key reads as False (undirected — renders as today).
    for e in auto_edges:
        e.setdefault("directed", False)

    # Overlay user-drawn edges from graph_corrections.
    user_rows = (
        db.query(models.GraphCorrection)
        .filter(models.GraphCorrection.job_id == job_id)
        .all()
    )
    user_edges = [
        _user_edge_to_dict(r)
        for r in user_rows
        if r.status != "user_rejected"
    ]

    graph["edges"] = auto_edges + user_edges
    stats = dict(graph.get("stats", {}))
    stats["auto_edges"] = len(auto_edges)
    stats["user_edges"] = len(user_edges)
    stats["edges"] = len(graph["edges"])
    graph["stats"] = stats
    return graph
