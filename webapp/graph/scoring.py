"""Graph scoring vs a frozen ground truth — pure, DB-free, importable.

Aligns an extracted JobGraph (assembler on-disk shape) to a ground-truth
JobGraph by a cascade (entity_id -> tag -> spatial), then reports node/edge
precision-recall-F1, directed-edge agreement, a strict ``is_isomorphic`` gate,
and connectivity stats. Imported by the CLI and (later) the Phase 2 eval gate.

Determinism: no time calls; inputs iterated in list order; ties broken by id.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass
class NodeAlignment:
    mapping: Dict[str, str]            # extracted node id -> gt node id
    unmatched_extracted: List[str]
    unmatched_gt: List[str]


def _centroid(bbox: Optional[Sequence[float]]) -> Optional[Tuple[float, float]]:
    if not bbox or len(bbox) < 4:
        return None
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _iou(b1: Optional[Sequence[float]], b2: Optional[Sequence[float]]) -> float:
    if not b1 or not b2 or len(b1) < 4 or len(b2) < 4:
        return 0.0
    ax1, ay1, ax2, ay2 = min(b1[0], b1[2]), min(b1[1], b1[3]), max(b1[0], b1[2]), max(b1[1], b1[3])
    bx1, by1, bx2, by2 = min(b2[0], b2[2]), min(b2[1], b2[3]), max(b2[0], b2[2]), max(b2[1], b2[3])
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _dist(p: Tuple[float, float], q: Tuple[float, float]) -> float:
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def align_nodes(
    extracted_nodes: Sequence[Dict[str, Any]],
    gt_nodes: Sequence[Dict[str, Any]],
    *,
    iou_threshold: float = 0.5,
    centroid_px: float = 40.0,
) -> NodeAlignment:
    """Map extracted node ids -> gt node ids. Cascade, first match wins, each gt
    node matched at most once: entity_id exact -> tag exact (non-empty) ->
    spatial (best IoU >= iou_threshold, else nearest centroid <= centroid_px)."""
    mapping: Dict[str, str] = {}
    used_gt: set = set()

    def _gid(n: Dict[str, Any]) -> str:
        return str(n.get("id"))

    # Pass 1: entity_id exact.
    gt_by_entity: Dict[str, List[Dict[str, Any]]] = {}
    for g in gt_nodes:
        eid = g.get("entity_id")
        if eid:
            gt_by_entity.setdefault(str(eid), []).append(g)
    for e in extracted_nodes:
        eid = e.get("entity_id")
        if not eid:
            continue
        for g in gt_by_entity.get(str(eid), []):
            if _gid(g) not in used_gt:
                mapping[_gid(e)] = _gid(g)
                used_gt.add(_gid(g))
                break

    # Pass 2: tag exact (non-empty).
    gt_by_tag: Dict[str, List[Dict[str, Any]]] = {}
    for g in gt_nodes:
        tag = g.get("tag")
        if tag:
            gt_by_tag.setdefault(str(tag), []).append(g)
    for e in extracted_nodes:
        if _gid(e) in mapping:
            continue
        tag = e.get("tag")
        if not tag:
            continue
        for g in gt_by_tag.get(str(tag), []):
            if _gid(g) not in used_gt:
                mapping[_gid(e)] = _gid(g)
                used_gt.add(_gid(g))
                break

    # Pass 3: spatial — sub-pass A (best IoU >= threshold), else B (nearest centroid <= px).
    for e in extracted_nodes:
        if _gid(e) in mapping:
            continue
        ec = _centroid(e.get("bbox"))
        if ec is None:
            continue
        best_iou_g = None
        best_iou = 0.0
        best_dist_g = None
        best_dist = centroid_px   # must be within threshold to qualify
        for g in gt_nodes:
            if _gid(g) in used_gt:
                continue
            gc = _centroid(g.get("bbox"))
            if gc is None:
                continue
            iou = _iou(e.get("bbox"), g.get("bbox"))
            d = _dist(ec, gc)
            if iou >= iou_threshold and (best_iou_g is None or iou > best_iou):
                best_iou, best_iou_g = iou, g
            elif d <= centroid_px and d < best_dist:
                best_dist, best_dist_g = d, g
        chosen = best_iou_g if best_iou_g is not None else best_dist_g
        if chosen is not None:
            mapping[_gid(e)] = _gid(chosen)
            used_gt.add(_gid(chosen))

    unmatched_extracted = [str(e.get("id")) for e in extracted_nodes if str(e.get("id")) not in mapping]
    unmatched_gt = [str(g.get("id")) for g in gt_nodes if str(g.get("id")) not in used_gt]
    return NodeAlignment(mapping=mapping, unmatched_extracted=unmatched_extracted, unmatched_gt=unmatched_gt)


def _prf(tp: int, fp: int, fn: int) -> Tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def _label(node: Dict[str, Any]) -> str:
    return str(node.get("tag") or node.get("class") or "")


def _connectivity(nodes: Sequence[Dict[str, Any]], edges: Sequence[Dict[str, Any]]) -> Tuple[int, float]:
    """Component count + largest-component fraction via networkx."""
    import networkx as nx

    g = nx.Graph()
    for n in nodes:
        g.add_node(str(n.get("id")))
    for e in edges:
        g.add_edge(str(e.get("source")), str(e.get("target")))
    if g.number_of_nodes() == 0:
        return 0, 0.0
    comps = list(nx.connected_components(g))
    largest = max((len(c) for c in comps), default=0)
    return len(comps), largest / g.number_of_nodes()


def _is_isomorphic(
    ext_nodes, ext_edges, gt_nodes, gt_edges
) -> bool:
    """Strict label-aware isomorphism. Wrapped — returns False on any error."""
    import networkx as nx

    def build(nodes, edges):
        g = nx.Graph()
        for n in nodes:
            g.add_node(str(n.get("id")), k=_label(n))
        for e in edges:
            g.add_edge(str(e.get("source")), str(e.get("target")))
        return g

    try:
        ge = build(ext_nodes, ext_edges)
        gg = build(gt_nodes, gt_edges)
        return nx.is_isomorphic(ge, gg, node_match=lambda a, b: a.get("k") == b.get("k"))
    except Exception:  # noqa: BLE001 — never block the graded scores
        return False


@dataclass
class GraphScore:
    node_precision: float
    node_recall: float
    node_f1: float
    edge_precision: float
    edge_recall: float
    edge_f1: float
    directed_agreement: Optional[float]
    is_isomorphic: bool
    extracted_components: int
    gt_components: int
    extracted_largest_frac: float
    gt_largest_frac: float
    node_tp: int
    node_fp: int
    node_fn: int
    edge_tp: int
    edge_fp: int
    edge_fn: int
    missing_edges: List[Tuple[str, str]]
    extra_edges: List[Tuple[str, str]]

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        d["missing_edges"] = [list(p) for p in self.missing_edges]
        d["extra_edges"] = [list(p) for p in self.extra_edges]
        return d


def score_graph(extracted_graph: Dict[str, Any], gt_graph: Dict[str, Any]) -> GraphScore:
    ext_nodes = extracted_graph.get("nodes", []) or []
    gt_nodes = gt_graph.get("nodes", []) or []
    ext_edges = extracted_graph.get("edges", []) or []
    gt_edges = gt_graph.get("edges", []) or []

    align = align_nodes(ext_nodes, gt_nodes)

    # Node-level PRF.
    node_tp = len(align.mapping)
    node_fp = len(align.unmatched_extracted)
    node_fn = len(align.unmatched_gt)
    node_p, node_r, node_f1 = _prf(node_tp, node_fp, node_fn)

    # Map extracted edges into gt id-space; drop edges with unaligned endpoints.
    def _mapped_undirected(edges):
        out = set()
        for e in edges:
            s, t = align.mapping.get(str(e.get("source"))), align.mapping.get(str(e.get("target")))
            if s and t and s != t:
                out.add(frozenset((s, t)))
        return out

    gt_undirected = {frozenset((str(e.get("source")), str(e.get("target")))) for e in gt_edges
                     if str(e.get("source")) != str(e.get("target"))}
    ext_undirected = _mapped_undirected(ext_edges)

    edge_tp = len(ext_undirected & gt_undirected)
    edge_fp = len(ext_undirected - gt_undirected)
    edge_fn = len(gt_undirected - ext_undirected)
    edge_p, edge_r, edge_f1 = _prf(edge_tp, edge_fp, edge_fn)

    missing = sorted(tuple(sorted(fs)) for fs in (gt_undirected - ext_undirected))
    extra = sorted(tuple(sorted(fs)) for fs in (ext_undirected - gt_undirected))

    # Directed agreement over GT directed edges that are matched (TP).
    gt_directed = [e for e in gt_edges if e.get("directed")]
    ext_dir_lookup = {}
    for e in ext_edges:
        s, t = align.mapping.get(str(e.get("source"))), align.mapping.get(str(e.get("target")))
        if s and t and e.get("directed"):
            ext_dir_lookup[(s, t)] = True
    if gt_directed:
        matched = 0
        agree = 0
        for e in gt_directed:
            gs, gt_ = str(e.get("source")), str(e.get("target"))
            if frozenset((gs, gt_)) in ext_undirected:  # present as a connection
                matched += 1
                if ext_dir_lookup.get((gs, gt_)):
                    agree += 1
        directed_agreement = (agree / matched) if matched else 0.0
    else:
        directed_agreement = None

    ext_comp, ext_frac = _connectivity(ext_nodes, ext_edges)
    gt_comp, gt_frac = _connectivity(gt_nodes, gt_edges)
    iso = _is_isomorphic(ext_nodes, ext_edges, gt_nodes, gt_edges)

    return GraphScore(
        node_precision=node_p, node_recall=node_r, node_f1=node_f1,
        edge_precision=edge_p, edge_recall=edge_r, edge_f1=edge_f1,
        directed_agreement=directed_agreement, is_isomorphic=iso,
        extracted_components=ext_comp, gt_components=gt_comp,
        extracted_largest_frac=ext_frac, gt_largest_frac=gt_frac,
        node_tp=node_tp, node_fp=node_fp, node_fn=node_fn,
        edge_tp=edge_tp, edge_fp=edge_fp, edge_fn=edge_fn,
        missing_edges=missing, extra_edges=extra,
    )
