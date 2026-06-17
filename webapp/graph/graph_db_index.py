"""Dual-write index of an extracted graph into the `graph_nodes` / `graph_edges`
DB tables (graph-extraction, 2026-06-13 design).

`webapp.graph.pipeline.extract_graph()` stays DB-free (it writes
`canonical_graph.json` and returns the JobGraph dict). This module composes the
dual-write, mirroring `webapp.deliverables.canonical_db_index.sync_canonical_to_db`:

    graph = extract_graph(job_dir, detections, generated_at=utc_iso(...), job_id=...)
    sync_graph_to_db(graph, db)   # idempotent upsert of nodes + edges

**Source of truth remains the on-disk `canonical_graph.json`.** These tables are
a read-cache for cross-job graph queries — never the edit target. User edits
live in `graph_corrections` and are merged at read time by the graph API.

Idempotency: unique on (job_id, node_id) and (job_id, edge_id). Re-emit
overwrites matching rows and deletes rows absent from the latest graph, so the
function is safe to call N times.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from sqlalchemy.orm import Session

from webapp import models


def sync_graph_to_db(graph: Dict[str, Any], db: Session) -> Tuple[int, int]:
    """Upsert every node + edge from a JobGraph dict into the index tables.

    Returns (nodes_synced, edges_synced) where each count is inserts + updates.
    Rows present from a prior emit but absent from this graph are deleted.
    """
    job_id = graph.get("job_id")
    if job_id is None:
        raise ValueError("graph dict missing job_id; cannot index")
    sheet_number = int(graph.get("page") or 1)

    nodes_synced = _sync_nodes(graph.get("nodes", []), job_id, sheet_number, db)
    edges_synced = _sync_edges(graph.get("edges", []), job_id, sheet_number, db)

    db.commit()
    return nodes_synced, edges_synced


def _sync_nodes(nodes, job_id: int, sheet_number: int, db: Session) -> int:
    existing = {
        row.node_id: row
        for row in db.query(models.GraphNodeRow).filter(
            models.GraphNodeRow.job_id == job_id
        )
    }
    synced = 0
    seen: set[str] = set()
    for node in nodes:
        nid = str(node["id"])
        seen.add(nid)
        payload = {
            "entity_id": node.get("entity_id"),
            "tag": node.get("tag"),
            "node_class": node.get("class"),
            "bbox": list(node["bbox"]) if node.get("bbox") is not None else None,
            "tile": node.get("tile"),
            "confidence": node.get("confidence"),
            "sheet_number": sheet_number,
        }
        row = existing.get(nid)
        if row is None:
            db.add(models.GraphNodeRow(job_id=job_id, node_id=nid, **payload))
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        synced += 1

    stale = [nid for nid in existing if nid not in seen]
    if stale:
        db.query(models.GraphNodeRow).filter(
            models.GraphNodeRow.job_id == job_id,
            models.GraphNodeRow.node_id.in_(stale),
        ).delete(synchronize_session=False)
    return synced


def _sync_edges(edges, job_id: int, sheet_number: int, db: Session) -> int:
    existing = {
        row.edge_id: row
        for row in db.query(models.GraphEdgeRow).filter(
            models.GraphEdgeRow.job_id == job_id
        )
    }
    synced = 0
    seen: set[str] = set()
    for edge in edges:
        eid = str(edge["id"])
        seen.add(eid)
        payload = {
            "source_node": str(edge["source"]),
            "target_node": str(edge["target"]),
            "method": edge.get("method") or "opencv",
            "directed": bool(edge.get("directed", False)),
            "polyline": [list(p) for p in edge.get("polyline", [])],
            "confidence": edge.get("confidence"),
            "tile": edge.get("tile"),
            "sheet_number": sheet_number,
        }
        row = existing.get(eid)
        if row is None:
            db.add(models.GraphEdgeRow(job_id=job_id, edge_id=eid, **payload))
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        synced += 1

    stale = [eid for eid in existing if eid not in seen]
    if stale:
        db.query(models.GraphEdgeRow).filter(
            models.GraphEdgeRow.job_id == job_id,
            models.GraphEdgeRow.edge_id.in_(stale),
        ).delete(synchronize_session=False)
    return synced
