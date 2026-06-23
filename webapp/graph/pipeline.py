"""Orchestration — loader → linker → tracer → resolver → assembler → fallback.

``extract_graph`` is DB-free: the caller (the webapp integration glue, Stream 3)
fetches ``Job.gpu_detections`` and the job output directory, then calls this. It
writes ``canonical_graph.json`` into ``job_dir`` and returns the JobGraph dict.

``generated_at`` is a required keyword so callers control determinism (pass an
ISO-8601 ``Z``-suffixed string from ``webapp.datetime_utils.utc_iso`` in prod).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

from webapp.graph import assembler, fallback, linker, loader, orient, resolver
from webapp.graph.tracer import LineTracer, OpenCVLineTracer

GRAPH_FILENAME = "canonical_graph.json"


def _node_id(i: int) -> str:
    return f"n_{i:03d}"


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

    # ── Step D: trace lines ──
    segments = []
    if job_input.full_page_image is not None and job_input.width and job_input.height:
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
        warnings.append("tracer: no full-page image; skipped CV tracing")

    # ── Step E: resolve edges ──
    resolved = resolver.resolve_edges(segments, nodes)
    edges = list(resolved.edges)
    orphan_lines = list(resolved.orphan_lines)

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
            full_page_image_path=job_input.full_page_path,
            client=fallback_client,
            warnings=warnings,
        )

    # ── Step E.5: orient edges (flow direction) ──
    # Best-effort: use arrow_*/connector_in/out detections (skipped as nodes
    # above) to set per-edge direction. Never adds/drops edges — only the flag
    # and possible source/target swap change. No arrow nearby → undirected.
    oriented = orient.orient_edges(edges, job_input.detections, nodes)
    edges = [e for (e, _d) in oriented]
    directed_flags = [d for (_e, d) in oriented]

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

    return graph
