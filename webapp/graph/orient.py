"""Step E.5 — edge orientation (flow direction), best-effort, model path.

The tracer + resolver (steps D/E) produce **undirected** edges: a polyline with
``source``/``target`` node ids assigned in tracing order, which carries no flow
semantics. This module adds direction using the detector's *direction* classes
that the linker/pipeline deliberately skip as nodes:

  - ``arrow_up`` / ``arrow_down`` / ``arrow_left`` / ``arrow_right`` — a flow
    arrow glyph whose orientation is the local flow direction.
  - ``connector_in`` / ``connector_out`` — page/line connectors marking the
    upstream (in) / downstream (out) end of a run.

For each traced edge we look for a direction detection whose centroid lies
within ``ARROW_PROXIMITY_PX`` of the edge polyline. If one is found we orient
``source → target`` along the flow and set ``directed = True``. No direction
detection nearby → the edge stays undirected (``directed = False``), exactly as
today. Orientation NEVER adds or drops an edge — it only (a) sets the flag and
(b) may swap an edge's source/target. Edge count is invariant.

Pure-python (no cv2/networkx) so it imports cheaply and is trivially testable.
``arrow_*`` detection bboxes are page-pixel, matching the resolver's node bboxes
and the tracer's polyline coordinates.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from webapp.graph.resolver import Edge

# Max page-pixel distance from an arrow/connector centroid to the edge polyline
# for the arrow to be considered "on" that edge. Sized like the resolver's
# node-snap proximity (30px) — a flow arrow sits on the pipe it annotates, so a
# generous-but-bounded band catches it without grabbing arrows on parallel runs.
ARROW_PROXIMITY_PX: float = 30.0

# Unit flow vectors per arrow class, in image coordinates (x right, y DOWN).
_ARROW_VECTORS: Dict[str, Tuple[float, float]] = {
    "arrow_right": (1.0, 0.0),
    "arrow_left": (-1.0, 0.0),
    "arrow_down": (0.0, 1.0),
    "arrow_up": (0.0, -1.0),
}


def _label(det: Dict[str, Any]) -> Optional[str]:
    return det.get("label") or det.get("yolo_class")


def _bbox(det: Dict[str, Any]) -> Optional[Sequence[float]]:
    return det.get("bbox") or det.get("bbox_tile")


def _centroid(bbox: Sequence[float]) -> Tuple[float, float]:
    x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _point_to_segment_dist(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Euclidean distance from point P to segment A-B."""
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))
    projx = ax + t * dx
    projy = ay + t * dy
    return ((px - projx) ** 2 + (py - projy) ** 2) ** 0.5


def _safe_polyline(polyline: Any) -> List[Tuple[float, float]]:
    """Coerce a polyline to a list of (float, float), dropping malformed points.

    Upstream extraction data is not always clean — a point may have the wrong
    arity or a non-numeric coordinate. Rather than 500 the whole graph step we
    skip the bad point; if fewer than 2 valid points remain the caller treats
    the edge as undirected (degenerate-polyline contract)."""
    out: List[Tuple[float, float]] = []
    if not polyline:
        return out
    for pt in polyline:
        try:
            x, y = pt  # arity check
            out.append((float(x), float(y)))
        except (TypeError, ValueError):
            continue
    return out


def _point_to_polyline_dist(
    px: float, py: float, polyline: Sequence[Tuple[float, float]]
) -> float:
    """Min distance from a point to any segment of the polyline."""
    if not polyline:
        return float("inf")
    if len(polyline) == 1:
        (ax, ay) = polyline[0]
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    best = float("inf")
    for (ax, ay), (bx, by) in zip(polyline, polyline[1:]):
        d = _point_to_segment_dist(px, py, float(ax), float(ay), float(bx), float(by))
        if d < best:
            best = d
    return best


def split_direction_detections(
    detections: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Partition detections into (arrow_dets, connector_dets) with valid bboxes.

    These are exactly the labels the linker/pipeline skip when building nodes —
    we recover them here for orientation only. Anything without a usable bbox is
    dropped (it can't be matched to a polyline).
    """
    arrows: List[Dict[str, Any]] = []
    connectors: List[Dict[str, Any]] = []
    for det in detections:
        label = _label(det)
        bbox = _bbox(det)
        if not label or not bbox or len(bbox) < 4:
            continue
        if label in _ARROW_VECTORS:
            arrows.append(det)
        elif label in ("connector_in", "connector_out"):
            connectors.append(det)
    return arrows, connectors


def orient_edges(
    edges: Sequence[Edge],
    detections: Sequence[Dict[str, Any]],
    nodes: Sequence[Dict[str, Any]],
    *,
    proximity_px: float = ARROW_PROXIMITY_PX,
) -> List[Tuple[Edge, bool]]:
    """Return ``[(edge, directed), ...]`` — same edges, same count, in order.

    Orientation rules (per spec):
      1. **Arrow:** the nearest ``arrow_*`` detection within ``proximity_px`` of
         the edge polyline gives the flow vector. If the edge's current
         ``source → target`` vector disagrees with the flow (dot product < 0)
         the edge is swapped so ``source`` is upstream. ``directed = True``.
      2. **Connector (fallback when no arrow):** if a ``connector_in`` sits near
         one endpoint and/or ``connector_out`` near the other, orient
         ``connector_in``-side → ``connector_out``-side. ``directed = True``.
      3. **Neither:** edge unchanged, ``directed = False``.

    Edges with a degenerate polyline (<2 points) or zero direction vector are
    left undirected. Never adds or removes edges.
    """
    arrows, connectors = split_direction_detections(detections)
    nodes_by_id: Dict[str, Sequence[float]] = {
        str(n.get("node_id")): n.get("bbox")
        for n in nodes
        if n.get("bbox") is not None and n.get("node_id") is not None
    }

    out: List[Tuple[Edge, bool]] = []
    for edge in edges:
        # Defensive parse: a malformed point (wrong arity or non-numeric coord)
        # from upstream extraction must not 500 the whole graph step — that edge
        # just stays undirected, consistent with the degenerate-polyline contract.
        poly = _safe_polyline(edge.polyline)
        if len(poly) < 2:
            out.append((edge, False))
            continue
        ev = (poly[-1][0] - poly[0][0], poly[-1][1] - poly[0][1])
        if ev[0] == 0.0 and ev[1] == 0.0:
            out.append((edge, False))
            continue

        # ── Rule 1: nearest in-range arrow ──
        best_arrow: Optional[Tuple[float, Tuple[float, float]]] = None
        for det in arrows:
            cx, cy = _centroid(_bbox(det))  # type: ignore[arg-type]
            dist = _point_to_polyline_dist(cx, cy, poly)
            if dist <= proximity_px and (best_arrow is None or dist < best_arrow[0]):
                best_arrow = (dist, _ARROW_VECTORS[_label(det)])  # type: ignore[index]

        if best_arrow is not None:
            fvx, fvy = best_arrow[1]
            # Agree with flow? dot(edge_vector, flow_vector). If negative the
            # tracer assigned source/target opposite to flow — swap them.
            dot = ev[0] * fvx + ev[1] * fvy
            if dot < 0:
                out.append((_swap(edge), True))
            else:
                out.append((edge, True))
            continue

        # ── Rule 2: connectors (only if no arrow matched) ──
        oriented = _orient_by_connectors(edge, poly, connectors, nodes_by_id, proximity_px)
        if oriented is not None:
            out.append((oriented, True))
            continue

        # ── Rule 3: undirected ──
        out.append((edge, False))

    return out


def _swap(edge: Edge) -> Edge:
    """source↔target swap. Polyline is reversed so endpoint-0 stays the source.

    Keeps the invariant that ``polyline[0]`` is near ``source`` and
    ``polyline[-1]`` near ``target`` (relied on by downstream renderers and the
    connector heuristic)."""
    return Edge(
        source=edge.target,
        target=edge.source,
        polyline=list(reversed(edge.polyline)),
        tile=edge.tile,
        method=edge.method,
        confidence=edge.confidence,
    )


def _endpoint_for_node(
    nodes_by_id: Dict[str, Sequence[float]], node_id: str
) -> Optional[Tuple[float, float]]:
    bbox = nodes_by_id.get(node_id)
    if not bbox or len(bbox) < 4:
        return None
    return _centroid(bbox)


def _orient_by_connectors(
    edge: Edge,
    poly: List[Tuple[float, float]],
    connectors: Sequence[Dict[str, Any]],
    nodes_by_id: Dict[str, Sequence[float]],
    proximity_px: float,
) -> Optional[Edge]:
    """Orient by connector_in (upstream) / connector_out (downstream) glyphs.

    A connector sits at an endpoint of the run. We measure each connector's
    centroid distance to the two polyline endpoints; ``connector_in`` near an
    endpoint marks that endpoint as the *source* side, ``connector_out`` marks
    the *target* side. If they imply the opposite of the current orientation we
    swap. Returns the (possibly swapped) edge, or None when no connector is
    close enough to disambiguate.
    """
    if not connectors:
        return None
    start = poly[0]
    end = poly[-1]

    def _near_which_end(cx: float, cy: float) -> Optional[int]:
        ds = ((cx - start[0]) ** 2 + (cy - start[1]) ** 2) ** 0.5
        de = ((cx - end[0]) ** 2 + (cy - end[1]) ** 2) ** 0.5
        nearest = 0 if ds <= de else 1
        if min(ds, de) > proximity_px:
            return None
        return nearest

    in_end: Optional[int] = None    # which polyline endpoint the source sits at
    out_end: Optional[int] = None
    for det in connectors:
        cx, cy = _centroid(_bbox(det))  # type: ignore[arg-type]
        which = _near_which_end(cx, cy)
        if which is None:
            continue
        if _label(det) == "connector_in" and in_end is None:
            in_end = which
        elif _label(det) == "connector_out" and out_end is None:
            out_end = which

    # Decide upstream endpoint index (0 = current source side, 1 = current target side).
    upstream: Optional[int] = None
    if in_end is not None:
        upstream = in_end
    elif out_end is not None:
        upstream = 1 - out_end  # source is the opposite end from connector_out
    if upstream is None:
        return None

    # upstream==0 → polyline[0] is the source → orientation already correct.
    # upstream==1 → flip.
    return edge if upstream == 0 else _swap(edge)
