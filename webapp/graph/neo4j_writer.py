"""Write auto-detected graph data to Neo4j.

Called from graph/pipeline.py AFTER canonical_graph.json is written.
Non-fatal: any exception is logged but does NOT fail the pipeline job.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_NEO4J_URI      = os.environ.get("NEO4J_URI",  "bolt://neo4j:7687")
_NEO4J_USER     = os.environ.get("NEO4J_USER", "neo4j")
_NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")  # None → driver raises AuthError if unset


def _neo4j_enabled() -> bool:
    """Neo4j is opt-in. When NEO4J_PASSWORD is unset (the default since Neo4j was
    removed from the runtime, FEATURES #118), skip all Neo4j work WITHOUT creating
    a driver — otherwise every call attempts to resolve the absent ``neo4j`` host,
    and that DNS failure is slow (~30s) and saturates the worker pool, making every
    page slow (FEATURES #119). Read live from the env so it's test-overridable."""
    return bool(os.environ.get("NEO4J_PASSWORD"))


def write_graph_to_neo4j(graph: Dict[str, Any]) -> None:
    """Write auto-detected graph for one job into Neo4j.

    Step A — delete existing auto data (source='auto') for this job only.
             Never touches source='user_added', 'user_edited', or 'placeholder'.
    Step B — write fresh auto data (Metadata + Nodes + Edges) via MERGE.

    Both steps run inside a single session so a partial write after the
    delete is visible in logs but does not retry automatically — the next
    pipeline run restores the state.  Non-fatal: any exception is logged
    and never propagates.
    """
    if not _neo4j_enabled():
        return
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.warning("neo4j driver not installed; skipping Neo4j write")
        return

    _raw_job_id = graph.get("job_id")
    if not _raw_job_id or str(_raw_job_id) == "None":
        logger.warning("write_graph_to_neo4j: job_id missing; skipping")
        return
    job_id = int(_raw_job_id)

    try:
        driver = GraphDatabase.driver(_NEO4J_URI, auth=(_NEO4J_USER, _NEO4J_PASSWORD))
        with driver.session() as session:
            # ── Step A: delete stale auto data ──────────────────────────────
            _delete_auto_data(session, job_id)
            # ── Step B: write fresh auto data ───────────────────────────────
            _write_metadata(session, graph)
            _write_nodes(session, graph)
            _write_edges(session, graph)
        driver.close()
        logger.info(
            "neo4j: wrote job %s — %d nodes, %d edges",
            job_id, len(graph.get("nodes", [])), len(graph.get("edges", [])),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("neo4j write failed for job %s (non-fatal): %s", job_id, exc)


def _delete_auto_data(session: Any, job_id: str) -> None:
    """Delete all source='auto' relationships, nodes, and Metadata for one job.
    User-added / placeholder data is never touched."""
    session.run(
        "MATCH ()-[e:PIPE {job_id: $job_id, source: 'auto'}]->() DELETE e",
        job_id=job_id,
    )
    session.run(
        "MATCH (n:Node {job_id: $job_id, source: 'auto'}) DETACH DELETE n",
        job_id=job_id,
    )
    session.run(
        "MATCH (m:Metadata {job_id: $job_id}) DELETE m",
        job_id=job_id,
    )


def _write_metadata(session: Any, graph: Dict[str, Any]) -> None:
    session.run(
        """
        MERGE (m:Metadata {job_id: $job_id})
        SET m.page_width     = $page_width,
            m.page_height    = $page_height,
            m.version        = $version,
            m.schema_version = '2',
            m.created_at     = datetime()
        """,
        job_id=int(graph["job_id"]),
        page_width=graph.get("page_width"),
        page_height=graph.get("page_height"),
        version=graph.get("version", "0.1"),
    )


def _write_nodes(session: Any, graph: Dict[str, Any]) -> None:
    job_id = int(graph["job_id"])
    for node in graph.get("nodes", []):
        bbox = node.get("bbox")   # [x1, y1, x2, y2] page-pixel space
        cx = round((bbox[0] + bbox[2]) / 2.0, 2) if bbox else None
        cy = round((bbox[1] + bbox[3]) / 2.0, 2) if bbox else None
        # label: shown as node caption in Neo4j Browser (tag > class > id)
        label = node.get("tag") or node.get("class") or node["id"]
        session.run(
            """
            MERGE (n:Node {id: $id, job_id: $job_id})
            SET n.tag        = $tag,
                n.label      = $label,
                n.class      = $cls,
                n.bbox       = $bbox,
                n.x          = $x,
                n.y          = $y,
                n.confidence = $confidence,
                n.entity_id  = $entity_id,
                n.tile       = $tile,
                n.source     = 'auto'
            """,
            id=node["id"],
            job_id=job_id,
            tag=node.get("tag"),
            label=label,
            cls=node.get("class"),
            bbox=bbox,
            x=cx,    # page-pixel centre X — used for spatial queries / digital-twin viz
            y=cy,    # page-pixel centre Y
            confidence=node.get("confidence"),
            entity_id=node.get("entity_id"),
            tile=node.get("tile"),
        )


def _write_edges(session: Any, graph: Dict[str, Any]) -> None:
    job_id = int(graph["job_id"])
    for edge in graph.get("edges", []):
        # polyline is [[x,y],...] — Neo4j has no nested-list type;
        # store as JSON string so it round-trips exactly.
        polyline_str = json.dumps(edge.get("polyline", []))
        session.run(
            """
            MATCH (src:Node {id: $source, job_id: $job_id})
            MATCH (tgt:Node {id: $target, job_id: $job_id})
            MERGE (src)-[e:PIPE {id: $edge_id, job_id: $job_id}]->(tgt)
            SET e.line_type  = 'pipe',
                e.polyline   = $polyline,
                e.directed   = $directed,
                e.confidence = $confidence,
                e.method     = $method,
                e.tile       = $tile,
                e.source     = 'auto'
            """,
            source=edge["source"],
            target=edge["target"],
            edge_id=edge["id"],
            job_id=job_id,
            polyline=polyline_str,
            directed=edge.get("directed", False),
            confidence=edge.get("confidence"),
            method=edge.get("method"),
            tile=edge.get("tile"),
        )


# ── User-drawn edge writer ────────────────────────────────────────────────────

def delete_user_edge_from_neo4j(job_id: int, edge_id: str) -> None:
    """Delete a user-drawn PIPE from Neo4j by edge_id. Non-fatal."""
    if not _neo4j_enabled():
        return
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return

    job_id_int = int(job_id)
    try:
        driver = GraphDatabase.driver(_NEO4J_URI, auth=(_NEO4J_USER, _NEO4J_PASSWORD))
        with driver.session() as session:
            session.run(
                "MATCH ()-[e:PIPE {id: $edge_id, job_id: $job_id}]->() DELETE e",
                edge_id=edge_id,
                job_id=job_id_int,
            )
        driver.close()
        logger.info("neo4j: deleted user edge %s for job %s", edge_id, job_id_int)
    except Exception as exc:  # noqa: BLE001
        logger.warning("neo4j delete-edge failed for job %s (non-fatal): %s", job_id_int, exc)


def write_user_edge_to_neo4j(
    job_id: int,
    edge_id: str,
    source_entity_id: str,
    target_entity_id: str,
    line_type: str,
    polyline: list,
    directed: bool,
    status: str = "user_added",
    group_id: Optional[str] = None,
) -> None:
    """Write one user-drawn PIPE relationship into Neo4j with source='user_added'.

    Freepoint endpoints ("freepoint:x,y") get a (:FreePoint) node.
    Normal entity IDs are MERGEd against existing (:Node) nodes by entity_id;
    if the node is not yet in Neo4j (user annotation not yet in pipeline graph)
    a placeholder is created and enriched on the next pipeline run.

    Non-fatal: any exception is logged; the API request always succeeds.
    """
    if not _neo4j_enabled():
        return
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.warning("neo4j driver not installed; skipping user-edge write")
        return

    job_id_int = int(job_id)
    try:
        driver = GraphDatabase.driver(_NEO4J_URI, auth=(_NEO4J_USER, _NEO4J_PASSWORD))
        with driver.session() as session:
            _ensure_endpoint(session, source_entity_id, job_id_int)
            _ensure_endpoint(session, target_entity_id, job_id_int)
            _merge_user_pipe(
                session,
                src_id=source_entity_id,
                tgt_id=target_entity_id,
                job_id=job_id_int,
                edge_id=edge_id,
                line_type=line_type,
                polyline_str=json.dumps(polyline),
                directed=directed,
                status=status,
                group_id=group_id,
            )
        driver.close()
        logger.info("neo4j: user edge %s written for job %s", edge_id, job_id_int)
    except Exception as exc:  # noqa: BLE001
        logger.warning("neo4j user-edge write failed for job %s (non-fatal): %s", job_id_int, exc)


def _ensure_endpoint(session: Any, entity_id: str, job_id: int) -> None:
    """MERGE the node for this endpoint. Freepoints get :FreePoint; others :Node."""
    if entity_id.startswith("freepoint:"):
        session.run(
            "MERGE (:FreePoint {id: $id, job_id: $job_id})",
            id=entity_id, job_id=job_id,
        )
    else:
        session.run(
            """
            MERGE (n:Node {entity_id: $entity_id, job_id: $job_id})
            ON CREATE SET n.source = 'placeholder'
            """,
            entity_id=entity_id, job_id=job_id,
        )


def _pipe_cypher(src_fp: bool, tgt_fp: bool) -> str:
    """Build MERGE Cypher for a PIPE between two endpoints of known label types.
    Only hardcoded strings are interpolated — no user input reaches this."""
    sl = "FreePoint" if src_fp else "Node"
    sk = "id"        if src_fp else "entity_id"
    tl = "FreePoint" if tgt_fp else "Node"
    tk = "id"        if tgt_fp else "entity_id"
    return f"""
        MATCH (src:{sl} {{{sk}: $src_id, job_id: $job_id}})
        MATCH (tgt:{tl} {{{tk}: $tgt_id, job_id: $job_id}})
        MERGE (src)-[e:PIPE {{id: $edge_id, job_id: $job_id}}]->(tgt)
        SET e.line_type  = $line_type,
            e.polyline   = $polyline,
            e.directed   = $directed,
            e.status     = $status,
            e.group_id   = $group_id,
            e.source     = 'user_added'
    """


def _merge_user_pipe(
    session: Any,
    src_id: str, tgt_id: str, job_id: int,
    edge_id: str, line_type: str, polyline_str: str, directed: bool,
    status: str = "user_added", group_id: Optional[str] = None,
) -> None:
    session.run(
        _pipe_cypher(src_id.startswith("freepoint:"), tgt_id.startswith("freepoint:")),
        src_id=src_id, tgt_id=tgt_id,
        job_id=job_id, edge_id=edge_id,
        line_type=line_type, polyline=polyline_str, directed=directed,
        status=status, group_id=group_id,
    )


# ── Graph reader ─────────────────────────────────────────────────────────────

def read_graph_from_neo4j(
    job_id: int,
    base_graph: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Read nodes + edges from Neo4j and return a response dict with the
    identical shape as the current JSON+PG merge in graph.py.

    base_graph (loaded from canonical_graph.json) supplies:
      orphan_lines, warnings, generated_at, page — not stored in Neo4j.

    Returns None on any failure so the router falls back transparently.
    """
    if not _neo4j_enabled():
        return None
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return None

    job_id_int = int(job_id)
    try:
        driver = GraphDatabase.driver(_NEO4J_URI, auth=(_NEO4J_USER, _NEO4J_PASSWORD))
        with driver.session() as session:
            # 1. Metadata — gates whether this job is in Neo4j at all.
            meta_rec = session.run(
                "MATCH (m:Metadata {job_id: $job_id}) RETURN m",
                job_id=job_id_int,
            ).single()
            if meta_rec is None:
                driver.close()
                return None

            meta = dict(meta_rec["m"])

            # 2. Auto nodes.
            raw_nodes = [
                dict(rec["n"])
                for rec in session.run(
                    "MATCH (n:Node {job_id: $job_id, source: 'auto'}) RETURN n",
                    job_id=job_id_int,
                )
            ]

            if not raw_nodes:
                driver.close()
                return None

            # Old-format data (written before schema_version="2") is missing
            # entity_id/tile on nodes and method/tile on edges → fall back.
            if meta.get("schema_version") != "2":
                logger.info(
                    "neo4j: job %s pre-dates schema_version 2; falling back to JSON",
                    job_id_int,
                )
                driver.close()
                return None

            # 3. Auto edges.
            auto_edges = []
            for rec in session.run(
                """
                MATCH (src:Node {job_id: $job_id, source: 'auto'})
                      -[e:PIPE {job_id: $job_id, source: 'auto'}]->
                      (tgt:Node {job_id: $job_id, source: 'auto'})
                RETURN src.id AS src_id, tgt.id AS tgt_id, e
                """,
                job_id=job_id_int,
            ):
                e = dict(rec["e"])
                auto_edges.append({
                    "id": e.get("id"),
                    "source": rec["src_id"],
                    "target": rec["tgt_id"],
                    "polyline": json.loads(e.get("polyline", "[]")),
                    "tile": e.get("tile"),
                    "method": e.get("method", "opencv"),
                    "confidence": e.get("confidence"),
                    "directed": bool(e.get("directed", False)),
                })

            # 4. User edges — mirror the PG filter (exclude user_rejected).
            user_edges = []
            for rec in session.run(
                """
                MATCH (src)-[e:PIPE {job_id: $job_id, source: 'user_added'}]->(tgt)
                WHERE e.status IS NULL OR NOT e.status = 'user_rejected'
                RETURN
                  CASE WHEN 'FreePoint' IN labels(src) THEN src.id
                       ELSE src.entity_id END AS src_ep,
                  CASE WHEN 'FreePoint' IN labels(tgt) THEN tgt.id
                       ELSE tgt.entity_id END AS tgt_ep,
                  e
                """,
                job_id=job_id_int,
            ):
                e = dict(rec["e"])
                src_ep = rec["src_ep"]
                tgt_ep = rec["tgt_ep"]
                user_edges.append({
                    "id": e.get("id"),
                    "source": src_ep,
                    "target": tgt_ep,
                    "polyline": json.loads(e.get("polyline", "[]")),
                    "tile": None,
                    "method": "user_added",
                    "confidence": None,
                    "directed": bool(e.get("directed", True)),
                    "line_type": e.get("line_type"),
                    "status": e.get("status", "user_added"),
                    "source_entity_id": src_ep,
                    "target_entity_id": tgt_ep,
                    "group_id": e.get("group_id"),
                })

        driver.close()

    except Exception as exc:  # noqa: BLE001
        logger.warning("neo4j read failed for job %s (falling back): %s", job_id_int, exc)
        return None

    # Normalise to canonical_graph.json node shape.
    nodes = [
        {
            "id": n.get("id"),
            "entity_id": n.get("entity_id"),
            "tag": n.get("tag"),
            "class": n.get("class"),
            "bbox": n.get("bbox"),
            "tile": n.get("tile"),
            "confidence": n.get("confidence"),
        }
        for n in raw_nodes
    ]

    # floating_nodes = nodes not incident to any auto edge.
    connected = {e["source"] for e in auto_edges} | {e["target"] for e in auto_edges}
    floating_nodes = [n["id"] for n in nodes if n["id"] not in connected]

    all_edges = auto_edges + user_edges
    return {
        "version": base_graph.get("version", "0.1"),
        "job_id": job_id,
        "page": base_graph.get("page", 1),
        "page_width": meta.get("page_width") or base_graph.get("page_width"),
        "page_height": meta.get("page_height") or base_graph.get("page_height"),
        "generated_at": base_graph.get("generated_at", ""),
        "stats": {
            "nodes": len(nodes),
            "edges": len(all_edges),
            "fallback_used": base_graph.get("stats", {}).get("fallback_used", False),
            "auto_edges": len(auto_edges),
            "user_edges": len(user_edges),
        },
        "nodes": nodes,
        "edges": all_edges,
        "floating_nodes": floating_nodes,
        "orphan_lines": base_graph.get("orphan_lines", []),
        "warnings": base_graph.get("warnings", []),
    }
