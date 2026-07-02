"""Step E — edge resolver.

Two resolvers are available:

``resolve_edges`` (original) — single-segment endpoint snapping.  Both segment
endpoints must independently land within ``proximity_px`` of a node bbox.  Fast
but misses connections where the pipe is fragmented into many short stubs.

``resolve_edges_bfs`` (Option A) — topology-graph BFS tracer.  Builds a
segment adjacency graph (endpoints within ``gap_px`` of each other are
"connected"), then BFS-traces from each node's attachment points through the
segment graph to discover all reachable nodes.  Handles fragmented topology.json
segments naturally — the BFS bridges the inter-segment gaps automatically.
Adjacent-symbol skip: if two node-bbox-centres are within ``adjacent_skip_px``,
the edge is omitted and left for the user to draw manually (the gap is so small
that the auto-detected segment is likely absent or ambiguous).

Pure-python, no cv2/network. ``Node`` is a lightweight dict produced by the
linker stage: ``{node_id, entity_id, tag, class, bbox, tile, confidence}``.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

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


# ── BFS resolver (Option A) ───────────────────────────────────────────────────

# Two segment endpoints are "adjacent" (part of the same pipe run) when their
# Euclidean distance is within this threshold. Bridges inter-tile / inter-stub gaps.
_BFS_GAP_PX: float = 30.0

# How close a segment endpoint must be to a node bbox edge to count as "attached".
# Pipe stubs are often cut short of the symbol bbox; 50px gives enough reach without
# snapping to the wrong nearby symbol.
_BFS_ATTACH_PX: float = 50.0

# If two node bbox-centres are closer than this, skip creating an automatic edge
# (symbols are probably directly adjacent with no visible pipe between them).
# Let the user draw the connection manually.
_BFS_ADJACENT_SKIP_PX: float = 120.0

# BFS depth cap — max number of segment hops in one path.  Prevents runaway
# traversal in densely connected topologies.
_BFS_MAX_DEPTH: int = 30


def _seg_endpoints(seg: LineSegment) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    return seg.polyline[0], seg.polyline[-1]


def _dist2(a: Tuple[int, int], b: Tuple[int, int]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _build_segment_adjacency(
    segments: Sequence[LineSegment],
    gap_px: float,
) -> Dict[Tuple[int, int], List[Tuple[int, int]]]:
    """For every (seg_idx, ep_idx=0/1), list adjacent (seg_idx, ep_idx) pairs.

    Two endpoint pairs are adjacent when their Euclidean distance ≤ gap_px.
    This is O(n²) — acceptable for topology.json sizes (~500-2000 segments).
    """
    gap2 = gap_px * gap_px
    n = len(segments)
    endpoints: List[Tuple[Tuple[int, int], Tuple[int, int]]] = [
        _seg_endpoints(s) for s in segments
    ]
    adj: Dict[Tuple[int, int], List[Tuple[int, int]]] = {
        (i, e): [] for i in range(n) for e in range(2)
    }
    for i in range(n):
        pi0, pi1 = endpoints[i]
        eps_i = [pi0, pi1]
        for j in range(i + 1, n):
            pj0, pj1 = endpoints[j]
            eps_j = [pj0, pj1]
            for ei, pi in enumerate(eps_i):
                for ej, pj in enumerate(eps_j):
                    if _dist2(pi, pj) <= gap2:
                        adj[(i, ei)].append((j, ej))
                        adj[(j, ej)].append((i, ei))
    return adj


def _build_node_attachments(
    segments: Sequence[LineSegment],
    nodes: Sequence[Any],
    attach_px: float,
) -> Dict[str, List[Tuple[int, int]]]:
    """Map node_id → [(seg_idx, ep_idx), ...] where endpoint is within attach_px of bbox."""
    attachments: Dict[str, List[Tuple[int, int]]] = {}
    for node in nodes:
        nid = _node_id(node)
        if nid:
            attachments[nid] = []

    for i, seg in enumerate(segments):
        p0, p1 = _seg_endpoints(seg)
        for ep_idx, pt in enumerate([p0, p1]):
            px, py = float(pt[0]), float(pt[1])
            for node in nodes:
                bbox = _node_bbox(node)
                nid = _node_id(node)
                if not bbox or not nid:
                    continue
                if _point_to_bbox_distance(px, py, bbox) <= attach_px:
                    attachments[nid].append((i, ep_idx))
    return attachments


def _build_path_polyline(
    segments: Sequence[LineSegment],
    path_segs: List[int],
    path_entry_eps: List[int],
) -> List[Tuple[int, int]]:
    """Concatenate segment polylines in traversal order into a single polyline."""
    result: List[Tuple[int, int]] = []
    for seg_idx, near_ep in zip(path_segs, path_entry_eps):
        poly = list(segments[seg_idx].polyline)
        if near_ep == 1:
            poly = poly[::-1]
        if result and result[-1] == poly[0]:
            poly = poly[1:]
        result.extend(poly)
    return result


def resolve_edges_bfs(
    segments: Sequence[LineSegment],
    nodes: Sequence[Any],
    *,
    attachment_px: float = _BFS_ATTACH_PX,
    gap_px: float = _BFS_GAP_PX,
    adjacent_skip_px: float = _BFS_ADJACENT_SKIP_PX,
    max_depth: int = _BFS_MAX_DEPTH,
    method: str = "opencv",
) -> ResolveResult:
    """BFS-based edge resolver — traces paths through the segment adjacency graph.

    Unlike ``resolve_edges`` (single-segment snapping), this resolver:
    1. Builds a segment-endpoint adjacency graph (endpoints within gap_px).
    2. For each node, marks segment endpoints within attachment_px as "attached".
    3. BFS from each node through the adjacency graph; stops when another node
       is reached → records an Edge with the full traversal polyline.
    4. Skips node pairs closer than adjacent_skip_px (directly adjacent symbols
       with no visible pipe between them — the user draws those manually).

    Segments that end up in no edge path become OrphanLines.
    """
    if not segments:
        return ResolveResult(edges=[], orphan_lines=[])

    adj = _build_segment_adjacency(segments, gap_px)
    attachments = _build_node_attachments(segments, nodes, attachment_px)

    # Build a reverse map: (seg_idx, ep_idx) → set of node_ids attached there.
    ep_to_nodes: Dict[Tuple[int, int], Set[str]] = {}
    for nid, eps in attachments.items():
        for ep in eps:
            ep_to_nodes.setdefault(ep, set()).add(nid)

    # Precompute node bbox centres for adjacent-skip distance check.
    node_centre: Dict[str, Tuple[float, float]] = {}
    for node in nodes:
        nid = _node_id(node)
        bbox = _node_bbox(node)
        if nid and bbox:
            node_centre[nid] = _bbox_center(bbox)

    edges: List[Edge] = []
    found_pairs: Set[Tuple[str, str]] = set()   # canonical (min,max) pairs already found
    segs_in_edges: Set[int] = set()

    for src_node in nodes:
        src_id = _node_id(src_node)
        if not src_id or not attachments.get(src_id):
            continue

        # BFS state: (seg_idx, far_ep_idx, path_seg_indices, path_entry_ep_indices)
        # We enter the segment at near_ep and exit at far_ep (1 - near_ep).
        queue: deque = deque()
        for (si, near_ei) in attachments[src_id]:
            if si in segs_in_edges:
                continue
            far_ei = 1 - near_ei
            queue.append((si, far_ei, [si], [near_ei]))

        visited: Set[Tuple[int, int]] = set()

        while queue:
            si, far_ei, path_segs, path_entry_eps = queue.popleft()
            state = (si, far_ei)
            if state in visited or si in segs_in_edges:
                continue
            visited.add(state)

            # Check if the far endpoint is attached to any target node.
            for tgt_id in ep_to_nodes.get((si, far_ei), set()):
                if tgt_id == src_id:
                    continue
                pair = (min(src_id, tgt_id), max(src_id, tgt_id))
                if pair in found_pairs:
                    continue

                # Skip directly-adjacent symbols (no visible pipe gap).
                sc = node_centre.get(src_id)
                tc = node_centre.get(tgt_id)
                if sc and tc:
                    d = math.sqrt((sc[0] - tc[0]) ** 2 + (sc[1] - tc[1]) ** 2)
                    if d < adjacent_skip_px:
                        continue

                found_pairs.add(pair)
                poly = _build_path_polyline(segments, path_segs, path_entry_eps)
                edges.append(
                    Edge(
                        source=src_id,
                        target=tgt_id,
                        polyline=poly,
                        tile="topology",
                        method=method,
                        confidence=0.75,
                    )
                )
                segs_in_edges.update(path_segs)

            # Expand: follow adjacency from the far endpoint.
            if len(path_segs) < max_depth:
                for (adj_si, adj_near_ei) in adj.get((si, far_ei), []):
                    adj_far_ei = 1 - adj_near_ei
                    new_state = (adj_si, adj_far_ei)
                    if new_state not in visited and adj_si not in segs_in_edges:
                        queue.append((
                            adj_si, adj_far_ei,
                            path_segs + [adj_si],
                            path_entry_eps + [adj_near_ei],
                        ))

    # Segments not used in any edge become orphan lines.
    orphans: List[OrphanLine] = [
        OrphanLine(
            polyline=list(segments[i].polyline),
            tile=segments[i].tile,
            reason="bfs_unmatched",
        )
        for i in range(len(segments))
        if i not in segs_in_edges
    ]

    return ResolveResult(edges=edges, orphan_lines=orphans)


# ── Intermediate-node splitter ────────────────────────────────────────────────

# How close any polyline point must be to a node bbox to count as
# "passing through".  Pipes run inside or just touching the symbol bbox,
# so a tight radius avoids false positives from nearby-but-unconnected nodes.
_SPLIT_PROXIMITY_PX: float = 20.0


def split_edges_at_intermediates(
    edges: Sequence[Edge],
    nodes: Sequence[Any],
    *,
    proximity_px: float = _SPLIT_PROXIMITY_PX,
) -> List[Edge]:
    """Split each edge at intermediate nodes the polyline passes through.

    For every edge A→C, any node B (not A, not C) whose bbox is touched by a
    polyline point within ``proximity_px`` is recorded as an intermediate node.
    Intermediates are sorted by their polyline-index position, and the edge is
    split into consecutive sub-edges A→B, B→C.  Each sub-edge inherits the
    parent's tile, method, and confidence.

    Only auto-detected edges are expected here (user-drawn edges are never
    passed through this function).  A polyline slice with < 2 distinct points
    is padded with the boundary points so every sub-edge is valid.
    """
    result: List[Edge] = []

    for edge in edges:
        poly = list(edge.polyline)
        if len(poly) < 2:
            result.append(edge)
            continue

        src_id = edge.source
        tgt_id = edge.target

        # Find intermediate nodes: closest polyline-point distance to bbox ≤ proximity_px,
        # for every node that is not the source or target of this edge.
        intermediates: List[Tuple[int, str]] = []  # (polyline_index, node_id)
        for node in nodes:
            nid = _node_id(node)
            if not nid or nid == src_id or nid == tgt_id:
                continue
            bbox = _node_bbox(node)
            if not bbox:
                continue
            best_dist = float("inf")
            best_idx = -1
            for idx, (px, py) in enumerate(poly):
                d = _point_to_bbox_distance(float(px), float(py), bbox)
                if d < best_dist:
                    best_dist = d
                    best_idx = idx
            if best_dist <= proximity_px:
                intermediates.append((best_idx, nid))

        if not intermediates:
            result.append(edge)
            continue

        # Sort by position along the polyline, then deduplicate same-index entries
        # (two nodes at the same polyline index → ambiguous split → keep neither).
        intermediates.sort(key=lambda x: x[0])
        deduped: List[Tuple[int, str]] = []
        last_idx = -1
        skip_idx = -1
        for idx, nid in intermediates:
            if idx == last_idx:
                # Collision: mark this index as ambiguous, remove previous entry.
                if deduped and deduped[-1][0] == idx:
                    deduped.pop()
                skip_idx = idx
            elif idx == skip_idx:
                continue
            else:
                deduped.append((idx, nid))
                last_idx = idx

        if not deduped:
            result.append(edge)
            continue

        # Build ordered node + split-index sequences
        ordered_nodes = [src_id] + [nid for _, nid in deduped] + [tgt_id]
        split_indices = [0] + [idx for idx, _ in deduped] + [len(poly) - 1]

        for i in range(len(ordered_nodes) - 1):
            sub_src = ordered_nodes[i]
            sub_tgt = ordered_nodes[i + 1]
            if sub_src == sub_tgt:
                continue
            start = split_indices[i]
            end = split_indices[i + 1]
            if start < end:
                sub_poly = poly[start: end + 1]
            else:
                sub_poly = [poly[start], poly[min(end, len(poly) - 1)]]
            if len(sub_poly) < 2:
                sub_poly = [poly[start], poly[min(end, len(poly) - 1)]]
            result.append(
                Edge(
                    source=sub_src,
                    target=sub_tgt,
                    polyline=sub_poly,
                    tile=edge.tile,
                    method=edge.method,
                    confidence=edge.confidence,
                )
            )

    return result
