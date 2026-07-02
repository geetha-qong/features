"""Orchestration — loader → linker → tracer → resolver → assembler → fallback.

``extract_graph`` is DB-free: the caller (the webapp integration glue, Stream 3)
fetches ``Job.gpu_detections`` and the job output directory, then calls this. It
writes ``canonical_graph.json`` into ``job_dir`` and returns the JobGraph dict.

``generated_at`` is a required keyword so callers control determinism (pass an
ISO-8601 ``Z``-suffixed string from ``webapp.datetime_utils.utc_iso`` in prod).
"""
from __future__ import annotations

import logging
import json
import os
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

from webapp.graph import assembler, fallback, linker, loader, orient, resolver
from webapp.graph.tracer import LineSegment, LineTracer, OpenCVLineTracer

GRAPH_FILENAME = "canonical_graph.json"

# IoU threshold for duplicate-detection suppression.  Two YOLO detections of
# the same class whose bboxes overlap more than this fraction are considered the
# same physical symbol; only the higher-confidence one is kept.
_NMS_IOU_THRESHOLD = 0.35


def _iou(b1: List[float], b2: List[float]) -> float:
    """Intersection-over-Union for two [x1,y1,x2,y2] bboxes."""
    ix1 = max(b1[0], b2[0])
    iy1 = max(b1[1], b2[1])
    ix2 = min(b1[2], b2[2])
    iy2 = min(b1[3], b2[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter == 0.0:
        return 0.0
    a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
    a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
    union = a1 + a2 - inter
    return inter / union if union > 0 else 0.0


def _dedup_detections(detections: List[Dict[str, Any]], iou_threshold: float = _NMS_IOU_THRESHOLD) -> List[Dict[str, Any]]:
    """Remove duplicate YOLO detections using greedy IoU-based NMS.

    Sort by confidence descending so the best detection for each symbol
    survives. Two detections are considered duplicates when their bboxes
    overlap more than ``iou_threshold`` (class-agnostic — same physical
    region regardless of label).
    """
    if not detections:
        return detections

    sorted_dets = sorted(
        detections,
        key=lambda d: float(d.get("confidence") or d.get("yolo_conf") or 0),
        reverse=True,
    )
    kept: List[Dict[str, Any]] = []
    suppressed: set = set()
    for i, det in enumerate(sorted_dets):
        if i in suppressed:
            continue
        kept.append(det)
        bi = det.get("bbox") or det.get("bbox_tile")
        if not bi or len(bi) < 4:
            continue
        for j in range(i + 1, len(sorted_dets)):
            if j in suppressed:
                continue
            bj = sorted_dets[j].get("bbox") or sorted_dets[j].get("bbox_tile")
            if not bj or len(bj) < 4:
                continue
            if _iou(bi, bj) > iou_threshold:
                suppressed.add(j)
    return kept


def _node_id(i: int) -> str:
    return f"n_{i:03d}"


def _bbox_area(bbox: Optional[Sequence[float]]) -> float:
    if not bbox:
        return 0.0
    return abs((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))


def dedupe_nodes_by_entity(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse nodes sharing an ``entity_id`` to one representative.

    Tile overlap makes the same physical instrument detected several times, so
    the linker emits multiple nodes per canonical entity (job 43: 79 redundant
    of 207). Keep the highest-confidence box per entity (tiebreak: largest
    bbox), so the graph has one node per component — correct for the topology
    metric and stops edges wiring an entity to its own duplicate detections.

    Nodes without an ``entity_id`` are kept individually (can't group them).
    First-appearance order is preserved.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for n in nodes:
        eid = n.get("entity_id")
        if eid:
            groups.setdefault(str(eid), []).append(n)
    reps = {
        eid: max(grp, key=lambda x: ((x.get("confidence") or 0.0), _bbox_area(x.get("bbox"))))
        for eid, grp in groups.items()
    }
    result: List[Dict[str, Any]] = []
    emitted: set = set()
    for n in nodes:
        eid = n.get("entity_id")
        if not eid:
            result.append(n)
        elif str(eid) not in emitted:
            emitted.add(str(eid))
            result.append(reps[str(eid)])
    return result


def _load_topology_segments(job_dir: str) -> Optional[List[LineSegment]]:
    """Load topology.json (produced by line_detector.py) as LineSegment objects.

    topology.json segments are in full-drawing page-pixel coordinates (all tile
    offsets already applied). Returns None if the file doesn't exist or is empty.
    Used by extract_graph() as the primary segment source for the BFS resolver —
    better coverage than OpenCVLineTracer (tile-based, lower min_length=15px).
    """
    topo_path = os.path.join(job_dir, "graph_outputs", "topology.json")
    if not os.path.exists(topo_path):
        return None
    try:
        with open(topo_path, encoding="utf-8") as f:
            topo = json.load(f)
    except Exception:
        return None
    lines = topo.get("lines", [])
    segments: List[LineSegment] = []
    for ln in lines:
        sx, sy = ln.get("startX"), ln.get("startY")
        ex, ey = ln.get("endX"), ln.get("endY")
        if None in (sx, sy, ex, ey):
            continue
        poly = [(int(sx), int(sy)), (int(ex), int(ey))]
        segments.append(LineSegment(polyline=poly, tile="topology", confidence=0.7))
    return segments if segments else None



def extract_graph(
    job_dir: str,
    detections: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    generated_at: str,
    job_id: Optional[int] = None,
    page: int = 1,
    tracer: Optional[LineTracer] = None,
    fallback_client: Any = None,
    write_file: bool = True,
    tile_local_detections: bool = False,
) -> Dict[str, Any]:
    """Build the per-job graph and (optionally) write ``canonical_graph.json``.

    Steps:
      1. loader — read canonical entities, full-page image, tile geometry.
      2. linker — one node per detection; OCR/fuzzy/class-prior to a canonical
         entity. OCR-empty/unmatched nodes still created (tag/entity_id None).
      3. tracer — OpenCV pipe tracing on the full page with bbox interiors masked.
      4. resolver — snap segment endpoints to nodes → edges + orphans.
      5. fallback — if edge density low, LLM connection pass (best-effort).
      6. assembler — MultiGraph → JobGraph dict in spec §3 shape.

    Returns the JobGraph dict. Non-crashing: every step degrades gracefully.
    """
    warnings: List[str] = []
    job_input = loader.load_job_input(
        job_dir, detections, page=page, tile_local_detections=tile_local_detections
    )

    # ── Step B.5: deduplicate overlapping detections (NMS) ──
    # YOLO can fire multiple times on the same physical symbol (overlapping
    # bboxes). Keep only the highest-confidence detection per overlapping group
    # so each symbol becomes exactly one node in the graph.
    before = len(job_input.detections)
    job_input = job_input._replace(detections=_dedup_detections(list(job_input.detections)))
    after = len(job_input.detections)
    if before != after:
        warnings.append(f"nms: removed {before - after} duplicate detections ({before} → {after})")

    # ── Step C: nodes via linker ──
    nodes: List[Dict[str, Any]] = []
    consumed: set = set()
    for i, det in enumerate(job_input.detections):
        bbox = det.get("bbox") or det.get("bbox_tile")
        label = det.get("label") or det.get("yolo_class")
        cls, _sub = linker.yolo_class_to_canonical(label)
        # Skip non-entity detections (direction arrows, connectors).
        if cls is None and (label and (label.startswith("arrow_") or label.startswith("connector_"))):
            continue
        try:
            entity_id, tag, _quality = linker.link_detection(
                job_input.full_page_image, det, job_input.canonical_entities, consumed
            )
        except Exception as _link_err:  # noqa: BLE001
            warnings.append(f"linker: detection {i} failed ({_link_err})")
            entity_id, tag = None, None
        nodes.append(
            {
                "node_id": _node_id(i),
                "entity_id": entity_id,
                "tag": tag,
                "class": label,
                "bbox": list(bbox) if bbox else None,
                "tile": det.get("tile"),
                "confidence": det.get("confidence") or det.get("yolo_conf"),
            }
        )

    # ── Step C.5: dedup duplicate detections of the same entity ──
    # Tile overlap yields multiple nodes per physical instrument; collapse them
    # so the graph is one-node-per-entity (topology) and edges don't wire an
    # entity to its own duplicate boxes. Runs before resolve/fallback so all
    # downstream edges reference the surviving representative node ids.
    pre_dedup = len(nodes)
    nodes = dedupe_nodes_by_entity(nodes)
    if len(nodes) != pre_dedup:
        warnings.append(f"node dedup: {pre_dedup} -> {len(nodes)} (collapsed same-entity detections)")

    # ── Step D: trace lines ──
    # Primary source: topology.json from line_detector.py (tile-based, better
    # coverage, min_length=15px vs OpenCVLineTracer's ~96px on full-page).
    # Fallback: OpenCVLineTracer on the full-page image when topology.json absent.
    topo_segments = _load_topology_segments(job_dir)

    segments = []
    if topo_segments:
        segments = topo_segments
        warnings.append(f"tracer: using topology.json ({len(segments)} segments)")
    elif job_input.full_page_image is not None and job_input.width and job_input.height:
        active_tracer = tracer or OpenCVLineTracer()
        bbox_mask = loader.build_bbox_mask(
            job_input.detections, job_input.width, job_input.height
        )
        try:
            segments = active_tracer.trace(job_input.full_page_image, bbox_mask)
        except Exception as _trace_err:  # noqa: BLE001
            warnings.append(f"tracer: failed ({_trace_err})")
            segments = []
    else:
        warnings.append("tracer: no full-page image and no topology.json; skipped")

    # ── Step E: resolve edges ──
    # Use BFS resolver when topology.json segments are available — it bridges
    # inter-segment gaps and traces multi-hop paths through the segment graph.
    # Fall back to single-endpoint snapping for OpenCVLineTracer output.
    if topo_segments:
        resolved = resolver.resolve_edges_bfs(segments, nodes)
    else:
        resolved = resolver.resolve_edges(segments, nodes)
    edges = list(resolved.edges)
    orphan_lines = list(resolved.orphan_lines)

    # Filter page-border artifacts: segments whose polyline is entirely within
    # BORDER_MARGIN px of a page edge are almost always frame/title-block lines
    # that OpenCV mistook for pipes — they have no valve/equipment endpoint.
    # This runs before the cap so the cap operates on real orphans only.
    BORDER_MARGIN = 400  # px
    if job_input.width and job_input.height:
        pw, ph = job_input.width, job_input.height
        def _is_border_artifact(o) -> bool:
            pts = o.polyline
            if not pts:
                return False
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            return (
                max(xs) < BORDER_MARGIN or
                min(xs) > pw - BORDER_MARGIN or
                max(ys) < BORDER_MARGIN or
                min(ys) > ph - BORDER_MARGIN
            )
        before = len(orphan_lines)
        orphan_lines = [o for o in orphan_lines if not _is_border_artifact(o)]
        filtered = before - len(orphan_lines)
        if filtered:
            warnings.append(f"border_filter: removed {filtered} frame/title-block artifacts")

    # Cap orphan lines: they are diagnostic-only (lines the resolver could not
    # attach to two nodes). On busy hi-DPI pages the tracer can emit thousands,
    # which bloats canonical_graph.json and makes the Studio "orphans" chip
    # meaningless. Keep the longest ORPHAN_CAP by polyline span; record the true
    # total in warnings so nothing is silently hidden.
    ORPHAN_CAP = 150
    if len(orphan_lines) > ORPHAN_CAP:
        def _span(o):
            pts = o.polyline
            if not pts:
                return 0
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            return max(max(xs) - min(xs), max(ys) - min(ys))
        total_orphans = len(orphan_lines)
        orphan_lines = sorted(orphan_lines, key=_span, reverse=True)[:ORPHAN_CAP]
        warnings.append(
            f"orphan_lines capped at {ORPHAN_CAP} of {total_orphans} (diagnostic only)"
        )

    # ── Step G: LLM fallback gate ──
    fallback_used = False
    if fallback.should_use_fallback(len(nodes), len(edges)):
        edges, fallback_used = fallback.run_fallback(
            nodes,
            edges,
            job_dir=job_dir,
            page_width=job_input.width,
            page_height=job_input.height,
            full_page_image_path=job_input.full_page_path,
            client=fallback_client,
            warnings=warnings,
        )

    # ── Step G.5: floating-node targeted pass ──
    # Nodes with zero connections after CV + density-gate fallback get a dedicated
    # LLM pass. The model receives only the unlinked symbols + the full image and
    # is asked explicitly to identify their pipe connections.
    connected_ids: set = set()
    for e in edges:
        connected_ids.add(e.source)
        connected_ids.add(e.target)
    floating_nodes = [
        n for n in nodes
        if (n.get("node_id") or n.get("id")) not in connected_ids
        and n.get("bbox")  # skip nodes with no spatial context
    ]
    if floating_nodes:
        edges, extra_fallback = fallback.run_floating_node_fallback(
            floating_nodes,
            nodes,
            edges,
            full_page_image_path=job_input.full_page_path,
            client=fallback_client,
            warnings=warnings,
        )
        fallback_used = fallback_used or extra_fallback

    # ── Step E.5: orient edges (flow direction) ──
    # Best-effort: use arrow_*/connector_in/out detections (skipped as nodes
    # above) to set per-edge direction. Never adds/drops edges — only the flag
    # and possible source/target swap change. No arrow nearby → undirected.
    oriented = orient.orient_edges(edges, job_input.detections, nodes)
    edges = [e for (e, _d) in oriented]
    directed_flags = [d for (_e, d) in oriented]

    # ── Step E.6: split edges at intermediate nodes ──
    # Any node B (not the declared source/target) whose bbox a polyline point
    # falls within 20px of is inserted as an intermediate, splitting A→C into
    # A→B + B→C.  The directed flag is replicated to every sub-edge.
    split_edges: List[Any] = []
    split_directed: List[bool] = []
    for edge, d in zip(edges, directed_flags):
        subs = resolver.split_edges_at_intermediates([edge], nodes)
        split_edges.extend(subs)
        split_directed.extend([d] * len(subs))
    edges = split_edges
    directed_flags = split_directed

    # ── Step E.7: drop degenerate edges ──
    # Edges where the pipe tracer could not find a valid path are stored with a
    # zero-length polyline (start == end).  Rendering them creates false visual
    # connections between symbols with no actual pipe in the drawing.
    # Filtered AFTER split_edges_at_intermediates so valid split sub-edges survive.
    def _polyline_length(pts: List) -> float:
        return sum(
            ((pts[i + 1][0] - pts[i][0]) ** 2 + (pts[i + 1][1] - pts[i][1]) ** 2) ** 0.5
            for i in range(len(pts) - 1)
        )

    good_mask = []
    for e in edges:
        pts = e.polyline
        if len(pts) < 2:
            good_mask.append(False)
        elif all(p == pts[0] for p in pts):
            good_mask.append(False)
        elif _polyline_length(pts) < 5.0:
            good_mask.append(False)
        else:
            good_mask.append(True)

    n_degenerate = good_mask.count(False)
    if n_degenerate:
        logger.info(
            "assembler: removed %d degenerate edges for job %s",
            n_degenerate, job_id,
        )
    edges = [e for e, ok in zip(edges, good_mask) if ok]
    directed_flags = [d for d, ok in zip(directed_flags, good_mask) if ok]

    # ── Step F: assemble ──
    graph = assembler.assemble(
        nodes,
        edges,
        orphan_lines,
        job_id=job_id,
        page=page,
        generated_at=generated_at,
        fallback_used=fallback_used,
        directed=directed_flags,
        page_width=job_input.width or None,
        page_height=job_input.height or None,
    )
    if warnings:
        graph["warnings"] = warnings

    if write_file:
        out_path = os.path.join(job_dir, GRAPH_FILENAME)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(assembler.to_json(graph))
        # Neo4j mirror — non-fatal, runs after JSON write.
        # Errors are logged but never propagate; the job always completes.
        from webapp.graph.neo4j_writer import write_graph_to_neo4j
        write_graph_to_neo4j(graph)

    return graph
