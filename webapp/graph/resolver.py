"""Step E — edge resolver.

For each traced ``LineSegment``, snap its two endpoints to the nearest node
bbox (within a proximity threshold, page-pixel). Both endpoints resolved → an
``Edge``; exactly one → an orphan line; neither → discarded.

Pure-python, no cv2/network. ``Node`` is a lightweight dict produced by the
linker stage: ``{node_id, entity_id, tag, class, bbox, tile, confidence}``.
"""
from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from webapp.graph.tracer import LineSegment


class Edge(NamedTuple):
    source: str          # node_id
    target: str          # node_id
    polyline: List[Tuple[int, int]]
    tile: str
    method: str
    confidence: float


class OrphanLine(NamedTuple):
    polyline: List[Tuple[int, int]]
    tile: str
    reason: str


class ResolveResult(NamedTuple):
    edges: List[Edge]
    orphan_lines: List[OrphanLine]


def _bbox_center(bbox: Sequence[float]) -> Tuple[float, float]:
    x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _point_to_bbox_distance(px: float, py: float, bbox: Sequence[float]) -> float:
    """Euclidean distance from a point to the nearest edge of a bbox.

    0 when the point is inside the bbox. This is more forgiving than
    centre-distance for large equipment symbols where a pipe lands on the rim.
    """
    x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    dx = max(x1 - px, 0.0, px - x2)
    dy = max(y1 - py, 0.0, py - y2)
    return (dx * dx + dy * dy) ** 0.5


def _node_id(node: Any) -> Optional[str]:
    nid = node.get("node_id") if isinstance(node, dict) else getattr(node, "node_id", None)
    return str(nid) if nid is not None else None


def _node_bbox(node: Any) -> Optional[Sequence[float]]:
    return node.get("bbox") if isinstance(node, dict) else getattr(node, "bbox", None)


def _nearest_node(
    px: float, py: float, nodes: Sequence[Any], proximity_px: float
) -> Optional[str]:
    best_id = None
    best_dist = None
    for node in nodes:
        bbox = _node_bbox(node)
        if not bbox:
            continue
        dist = _point_to_bbox_distance(px, py, bbox)
        if dist <= proximity_px and (best_dist is None or dist < best_dist):
            best_dist = dist
            best_id = _node_id(node)
    return best_id


def resolve_edges(
    segments: Sequence[LineSegment],
    nodes: Sequence[Any],
    *,
    proximity_px: float = 30.0,
    method: str = "opencv",
) -> ResolveResult:
    """Resolve traced segments against node bboxes into edges + orphans.

    Both endpoints snap to a node (and not the *same* node) → ``Edge``.
    Exactly one endpoint snaps → ``OrphanLine`` (reason ``one_endpoint_unmatched``).
    Neither snaps → discarded (reason ``no_bbox_within_proximity`` orphan).

    A segment whose two endpoints snap to the *same* node is treated as a
    no-op (discarded as a self-loop orphan) — v0 is undirected and a self-edge
    on a single symbol carries no connectivity info.
    """
    edges: List[Edge] = []
    orphans: List[OrphanLine] = []

    for seg in segments:
        poly = seg.polyline
        if not poly or len(poly) < 2:
            continue
        (sx, sy) = poly[0]
        (ex, ey) = poly[-1]

        src = _nearest_node(float(sx), float(sy), nodes, proximity_px)
        tgt = _nearest_node(float(ex), float(ey), nodes, proximity_px)

        if src is not None and tgt is not None:
            if src == tgt:
                orphans.append(
                    OrphanLine(polyline=list(poly), tile=seg.tile, reason="self_loop")
                )
                continue
            edges.append(
                Edge(
                    source=src,
                    target=tgt,
                    polyline=list(poly),
                    tile=seg.tile,
                    method=method,
                    confidence=seg.confidence,
                )
            )
        elif src is not None or tgt is not None:
            orphans.append(
                OrphanLine(
                    polyline=list(poly),
                    tile=seg.tile,
                    reason="one_endpoint_unmatched",
                )
            )
        else:
            orphans.append(
                OrphanLine(
                    polyline=list(poly),
                    tile=seg.tile,
                    reason="no_bbox_within_proximity",
                )
            )

    return ResolveResult(edges=edges, orphan_lines=orphans)
