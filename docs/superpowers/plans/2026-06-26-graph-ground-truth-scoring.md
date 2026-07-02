# Graph Ground-Truth Anchor & Scoring Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a frozen ground-truth graph for job 43 plus a pure, importable scoring harness that reports node-aligned edge F1 and a strict `is_isomorphic` gate, so graph topology is measured rather than spot-checked.

**Architecture:** A DB-free module `webapp/graph/scoring.py` does node alignment (entity_id → tag → spatial cascade) and graph scoring; a thin CLI `webapp/scripts/score_graph.py` wraps it for humans; the ground truth is a frozen versioned JSON file (`tests/graph_ground_truth/job_43.json`) in the on-disk `JobGraph` shape. The scoring module is importable by the Phase 2 gated-retrain eval gate.

**Tech Stack:** Python 3.12 (server) / 3.9 (local), `networkx` (already in `requirements.txt`), `pytest`, `argparse`. No new dependencies.

## Global Constraints

- Python: use `Optional[X]` not `X | None`; use `python3` not `python`. (Server 3.12, local 3.9.)
- `webapp/graph/*` is **DB-free** — never import SQLAlchemy / `webapp.models` / `webapp.database` in `scoring.py`. Heavy deps (`networkx`) may be imported at module top (already used by `assembler.py`).
- On-disk `JobGraph` shape (from `assembler.assemble`): nodes have keys `id`, `entity_id`, `tag`, `class`, `bbox` (`[x1,y1,x2,y2]` or `None`), `tile`, `confidence`. Edges have keys `id`, `source`, `target`, `polyline`, `tile`, `method`, `confidence`, `directed` (bool). `source`/`target` reference node `id`s. The GT file uses this exact shape plus a `meta` block.
- Determinism: scoring must not call any time function; iterate inputs in list order; tie-break by `id` string. (Mirrors `assembler.py`'s determinism rule.)
- Tests run in the container: `docker run --rm -v $(pwd):/app qong_poc-web:latest python3 -m pytest tests/unit/test_graph_scoring.py -v`. Local host is Py3.9 and can't collect routers, but `webapp/graph/scoring.py` is pure and importable locally for quick checks if `networkx` is installed.
- Branch: `feat/graph-ground-truth-scoring` (already created off `dev`). No direct pushes to `dev`/`qa`/`main`; merge via PR with 2 approvals.
- Commit messages end with the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer.

---

## File Structure

- **Create** `webapp/graph/scoring.py` — alignment + scoring (pure, DB-free). Public: `NodeAlignment`, `GraphScore`, `align_nodes()`, `score_graph()`.
- **Create** `webapp/scripts/score_graph.py` — thin CLI (`python -m webapp.scripts.score_graph`).
- **Create** `tests/unit/test_graph_scoring.py` — unit tests for alignment + scoring.
- **Create** `tests/graph_ground_truth/job_43.json` — frozen GT (seeded from job 43, hand-corrected).
- **Modify** `FEATURES.md` — append one entry recording the metric definition + GT provenance.
- **Modify** `SESSION_STATE.md` — overwrite with the handoff at end of session.

---

## Task 1: Node alignment in `scoring.py`

**Files:**
- Create: `webapp/graph/scoring.py`
- Test: `tests/unit/test_graph_scoring.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces:
  - `@dataclass NodeAlignment` with fields `mapping: Dict[str, str]` (extracted id → gt id), `unmatched_extracted: List[str]`, `unmatched_gt: List[str]`.
  - `align_nodes(extracted_nodes: Sequence[Dict[str, Any]], gt_nodes: Sequence[Dict[str, Any]], *, iou_threshold: float = 0.5, centroid_px: float = 40.0) -> NodeAlignment`
  - Helpers used by Task 2: `_centroid(bbox) -> Optional[Tuple[float, float]]`, `_iou(b1, b2) -> float`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_graph_scoring.py`:

```python
"""Unit tests for webapp.graph.scoring (alignment + scoring). DB-free."""
from webapp.graph import scoring


def _node(id_, *, entity_id=None, tag=None, cls="valve", bbox=None):
    return {"id": id_, "entity_id": entity_id, "tag": tag, "class": cls, "bbox": bbox}


def test_align_by_entity_id_exact():
    ext = [_node("n_000", entity_id="E1"), _node("n_001", entity_id="E2")]
    gt = [_node("g_000", entity_id="E2"), _node("g_001", entity_id="E1")]
    a = scoring.align_nodes(ext, gt)
    assert a.mapping == {"n_000": "g_001", "n_001": "g_000"}
    assert a.unmatched_extracted == []
    assert a.unmatched_gt == []


def test_align_by_tag_when_no_entity_id():
    ext = [_node("n_000", tag="FT-101")]
    gt = [_node("g_000", tag="FT-101")]
    a = scoring.align_nodes(ext, gt)
    assert a.mapping == {"n_000": "g_000"}


def test_align_spatial_fallback_for_untagged():
    # No entity_id, no tag -> match by bbox overlap/centroid.
    ext = [_node("n_000", bbox=[10, 10, 20, 20])]
    gt = [_node("g_000", bbox=[11, 11, 21, 21])]
    a = scoring.align_nodes(ext, gt)
    assert a.mapping == {"n_000": "g_000"}


def test_align_spatial_beyond_threshold_unmatched():
    ext = [_node("n_000", bbox=[0, 0, 10, 10])]
    gt = [_node("g_000", bbox=[500, 500, 510, 510])]
    a = scoring.align_nodes(ext, gt)
    assert a.mapping == {}
    assert a.unmatched_extracted == ["n_000"]
    assert a.unmatched_gt == ["g_000"]


def test_align_each_gt_matched_once():
    # Two extracted nodes, one gt node: only the first (list order) wins.
    ext = [_node("n_000", tag="V-1"), _node("n_001", tag="V-1")]
    gt = [_node("g_000", tag="V-1")]
    a = scoring.align_nodes(ext, gt)
    assert a.mapping == {"n_000": "g_000"}
    assert a.unmatched_extracted == ["n_001"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker run --rm -v $(pwd):/app qong_poc-web:latest python3 -m pytest tests/unit/test_graph_scoring.py -v`
Expected: FAIL — `AttributeError: module 'webapp.graph.scoring' has no attribute ...` (module/functions don't exist).

- [ ] **Step 3: Write minimal implementation**

Create `webapp/graph/scoring.py`:

```python
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

    # Pass 3: spatial.
    for e in extracted_nodes:
        if _gid(e) in mapping:
            continue
        ec = _centroid(e.get("bbox"))
        if ec is None:
            continue
        best_g = None
        best_iou = 0.0
        best_dist = None
        for g in gt_nodes:
            if _gid(g) in used_gt:
                continue
            gc = _centroid(g.get("bbox"))
            if gc is None:
                continue
            iou = _iou(e.get("bbox"), g.get("bbox"))
            d = _dist(ec, gc)
            if iou > best_iou or (iou == best_iou and (best_dist is None or d < best_dist)):
                best_iou, best_dist, best_g = iou, d, g
        if best_g is None:
            continue
        if best_iou >= iou_threshold or (best_dist is not None and best_dist <= centroid_px):
            mapping[_gid(e)] = _gid(best_g)
            used_gt.add(_gid(best_g))

    unmatched_extracted = [str(e.get("id")) for e in extracted_nodes if str(e.get("id")) not in mapping]
    unmatched_gt = [str(g.get("id")) for g in gt_nodes if str(g.get("id")) not in used_gt]
    return NodeAlignment(mapping=mapping, unmatched_extracted=unmatched_extracted, unmatched_gt=unmatched_gt)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker run --rm -v $(pwd):/app qong_poc-web:latest python3 -m pytest tests/unit/test_graph_scoring.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add webapp/graph/scoring.py tests/unit/test_graph_scoring.py
git commit -m "feat(graph): node alignment for graph scoring (entity/tag/spatial cascade)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `score_graph()` in `scoring.py`

**Files:**
- Modify: `webapp/graph/scoring.py`
- Test: `tests/unit/test_graph_scoring.py`

**Interfaces:**
- Consumes: `align_nodes`, `NodeAlignment`, `_centroid`, `_iou` from Task 1.
- Produces:
  - `@dataclass GraphScore` with fields: `node_precision, node_recall, node_f1: float`; `edge_precision, edge_recall, edge_f1: float`; `directed_agreement: Optional[float]`; `is_isomorphic: bool`; `extracted_components, gt_components: int`; `extracted_largest_frac, gt_largest_frac: float`; `node_tp, node_fp, node_fn, edge_tp, edge_fp, edge_fn: int`; `missing_edges: List[Tuple[str, str]]`; `extra_edges: List[Tuple[str, str]]`. Plus `to_dict(self) -> Dict[str, Any]`.
  - `score_graph(extracted_graph: Dict[str, Any], gt_graph: Dict[str, Any]) -> GraphScore` — both args are JobGraph dicts (have `nodes` + `edges` lists).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_graph_scoring.py`:

```python
def _graph(nodes, edges):
    """edges: list of (source, target) or (source, target, directed)."""
    edge_dicts = []
    for i, e in enumerate(edges):
        src, tgt = e[0], e[1]
        directed = e[2] if len(e) > 2 else False
        edge_dicts.append({"id": f"e_{i:03d}", "source": src, "target": tgt, "directed": directed})
    return {"nodes": nodes, "edges": edge_dicts}


def test_score_perfect_copy():
    nodes = [_node("n_000", tag="A"), _node("n_001", tag="B"), _node("n_002", tag="C")]
    g = _graph(nodes, [("n_000", "n_001"), ("n_001", "n_002")])
    s = scoring.score_graph(g, g)
    assert s.node_f1 == 1.0
    assert s.edge_f1 == 1.0
    assert s.is_isomorphic is True


def test_score_one_missing_edge():
    nodes = [_node("n_000", tag="A"), _node("n_001", tag="B"), _node("n_002", tag="C")]
    gt = _graph(nodes, [("n_000", "n_001"), ("n_001", "n_002")])
    ext = _graph(nodes, [("n_000", "n_001")])  # missing n_001-n_002
    s = scoring.score_graph(ext, gt)
    assert s.edge_precision == 1.0
    assert s.edge_recall < 1.0
    assert len(s.missing_edges) == 1
    assert s.is_isomorphic is False


def test_score_one_extra_edge():
    nodes = [_node("n_000", tag="A"), _node("n_001", tag="B"), _node("n_002", tag="C")]
    gt = _graph(nodes, [("n_000", "n_001")])
    ext = _graph(nodes, [("n_000", "n_001"), ("n_001", "n_002")])  # extra
    s = scoring.score_graph(ext, gt)
    assert s.edge_recall == 1.0
    assert s.edge_precision < 1.0
    assert len(s.extra_edges) == 1


def test_score_reversed_direction_only_hits_directed_agreement():
    nodes = [_node("n_000", tag="A"), _node("n_001", tag="B")]
    gt = _graph(nodes, [("n_000", "n_001", True)])
    ext = _graph(nodes, [("n_001", "n_000", True)])  # reversed
    s = scoring.score_graph(ext, gt)
    assert s.edge_f1 == 1.0          # undirected connectivity unaffected
    assert s.directed_agreement == 0.0


def test_score_no_directed_edges_gives_none_agreement():
    nodes = [_node("n_000", tag="A"), _node("n_001", tag="B")]
    g = _graph(nodes, [("n_000", "n_001")])
    s = scoring.score_graph(g, g)
    assert s.directed_agreement is None


def test_score_empty_extracted_no_crash():
    nodes = [_node("n_000", tag="A"), _node("n_001", tag="B")]
    gt = _graph(nodes, [("n_000", "n_001")])
    ext = {"nodes": [], "edges": []}
    s = scoring.score_graph(ext, gt)
    assert s.node_recall == 0.0
    assert s.edge_recall == 0.0
    assert s.is_isomorphic is False


def test_score_to_dict_is_json_serializable():
    import json
    nodes = [_node("n_000", tag="A"), _node("n_001", tag="B")]
    g = _graph(nodes, [("n_000", "n_001")])
    s = scoring.score_graph(g, g)
    json.dumps(s.to_dict())  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker run --rm -v $(pwd):/app qong_poc-web:latest python3 -m pytest tests/unit/test_graph_scoring.py -v`
Expected: FAIL — `AttributeError: module 'webapp.graph.scoring' has no attribute 'score_graph'`.

- [ ] **Step 3: Write minimal implementation**

Append to `webapp/graph/scoring.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker run --rm -v $(pwd):/app qong_poc-web:latest python3 -m pytest tests/unit/test_graph_scoring.py -v`
Expected: PASS (12 tests total).

- [ ] **Step 5: Commit**

```bash
git add webapp/graph/scoring.py tests/unit/test_graph_scoring.py
git commit -m "feat(graph): score_graph — node-aligned edge F1 + is_isomorphic gate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: CLI `webapp/scripts/score_graph.py`

**Files:**
- Create: `webapp/scripts/score_graph.py`
- Test: `tests/unit/test_graph_scoring.py` (add a CLI resolution test)

**Interfaces:**
- Consumes: `scoring.score_graph`, `scoring.GraphScore` from Task 2.
- Produces:
  - `resolve_graph_path(job_id: int, explicit: Optional[str], root: str = "job_outputs") -> Optional[str]` — returns `explicit` if given, else the first match of `{root}/**/{job_id}/canonical_graph.json` (DB-free; handles flat ≤39 and org-scoped ≥40 layouts), else `None`.
  - `format_report(score: GraphScore, job_id: int) -> str` — human-readable multi-line report.
  - `main(argv: Optional[Sequence[str]] = None) -> int` — argparse entry; returns process exit code.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_graph_scoring.py`:

```python
def test_cli_resolve_graph_path_globs_job_dir(tmp_path):
    from webapp.scripts import score_graph as cli
    # org-scoped layout: job_outputs/<org>/43/canonical_graph.json
    d = tmp_path / "job_outputs" / "7" / "43"
    d.mkdir(parents=True)
    f = d / "canonical_graph.json"
    f.write_text("{}")
    found = cli.resolve_graph_path(43, None, root=str(tmp_path / "job_outputs"))
    assert found == str(f)


def test_cli_resolve_graph_path_explicit_wins(tmp_path):
    from webapp.scripts import score_graph as cli
    assert cli.resolve_graph_path(43, "/x/y.json", root=str(tmp_path)) == "/x/y.json"


def test_cli_format_report_contains_key_metrics():
    from webapp.scripts import score_graph as cli
    nodes = [_node("n_000", tag="A"), _node("n_001", tag="B")]
    g = _graph(nodes, [("n_000", "n_001")])
    s = scoring.score_graph(g, g)
    out = cli.format_report(s, 43)
    assert "edge_f1" in out.lower() or "edge f1" in out.lower()
    assert "is_isomorphic" in out.lower() or "isomorphic" in out.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker run --rm -v $(pwd):/app qong_poc-web:latest python3 -m pytest tests/unit/test_graph_scoring.py -k cli -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webapp.scripts.score_graph'`.

- [ ] **Step 3: Write minimal implementation**

Create `webapp/scripts/score_graph.py`:

```python
"""CLI: score a job's extracted graph against its frozen ground truth.

    python -m webapp.scripts.score_graph --job-id 43 [--graph PATH] [--gt PATH] [--json] [--seed]

Thin wrapper over webapp.graph.scoring. DB-free: the extracted graph is found
by globbing job_outputs (flat <=39 and org-scoped >=40 layouts), or passed
explicitly with --graph.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Optional, Sequence

from webapp.graph import scoring

DEFAULT_GT_DIR = os.path.join("tests", "graph_ground_truth")


def resolve_graph_path(job_id: int, explicit: Optional[str], root: str = "job_outputs") -> Optional[str]:
    if explicit:
        return explicit
    matches = sorted(glob.glob(os.path.join(root, "**", str(job_id), "canonical_graph.json"), recursive=True))
    flat = os.path.join(root, str(job_id), "canonical_graph.json")
    if flat in matches:
        return flat
    return matches[0] if matches else None


def resolve_gt_path(job_id: int, explicit: Optional[str]) -> str:
    return explicit or os.path.join(DEFAULT_GT_DIR, f"job_{job_id}.json")


def format_report(score: scoring.GraphScore, job_id: int) -> str:
    da = "n/a" if score.directed_agreement is None else f"{score.directed_agreement:.3f}"
    return "\n".join([
        f"Graph score — job {job_id}",
        f"  nodes: P={score.node_precision:.3f} R={score.node_recall:.3f} F1={score.node_f1:.3f} "
        f"(tp={score.node_tp} fp={score.node_fp} fn={score.node_fn})",
        f"  edges (undirected): P={score.edge_precision:.3f} R={score.edge_recall:.3f} F1={score.edge_f1:.3f} "
        f"(tp={score.edge_tp} fp={score.edge_fp} fn={score.edge_fn})",
        f"  directed_agreement: {da}",
        f"  is_isomorphic: {score.is_isomorphic}",
        f"  connectivity: extracted {score.extracted_components} comp / "
        f"largest {score.extracted_largest_frac:.2f}  |  gt {score.gt_components} comp / "
        f"largest {score.gt_largest_frac:.2f}",
        f"  missing_edges: {len(score.missing_edges)}   extra_edges: {len(score.extra_edges)}",
    ])


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Score a job graph against its ground truth.")
    ap.add_argument("--job-id", type=int, required=True)
    ap.add_argument("--graph", default=None, help="explicit path to extracted canonical_graph.json")
    ap.add_argument("--gt", default=None, help="explicit path to ground-truth json")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a text report")
    ap.add_argument("--seed", action="store_true", help="copy the extracted graph to the GT path and exit")
    args = ap.parse_args(argv)

    graph_path = resolve_graph_path(args.job_id, args.graph)
    if not graph_path or not os.path.exists(graph_path):
        print(f"error: extracted graph not found for job {args.job_id} "
              f"(looked at {graph_path or 'job_outputs/**/'+str(args.job_id)})", file=sys.stderr)
        return 2
    with open(graph_path, "r", encoding="utf-8") as f:
        extracted = json.load(f)

    gt_path = resolve_gt_path(args.job_id, args.gt)

    if args.seed:
        os.makedirs(os.path.dirname(gt_path), exist_ok=True)
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(extracted, f, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"seeded ground truth: {gt_path} (hand-correct it, then commit)")
        return 0

    if not os.path.exists(gt_path):
        print(f"error: ground truth not found: {gt_path} (run with --seed first)", file=sys.stderr)
        return 2
    with open(gt_path, "r", encoding="utf-8") as f:
        gt = json.load(f)

    score = scoring.score_graph(extracted, gt)
    if args.json:
        print(json.dumps(score.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_report(score, args.job_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker run --rm -v $(pwd):/app qong_poc-web:latest python3 -m pytest tests/unit/test_graph_scoring.py -v`
Expected: PASS (15 tests total).

- [ ] **Step 5: Commit**

```bash
git add webapp/scripts/score_graph.py tests/unit/test_graph_scoring.py
git commit -m "feat(graph): score_graph CLI — resolve job graph, report, --json, --seed

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Seed + freeze job 43 ground truth

**Files:**
- Create: `tests/graph_ground_truth/job_43.json`

**Interfaces:**
- Consumes: the `--seed` CLI from Task 3.
- Produces: a committed, hand-corrected GT file with a filled `meta` block.

> **NOTE — partly manual.** This task pulls job 43's current `canonical_graph.json` off the dev box, seeds the GT file, then a **human hand-corrects** the topology. The engineering steps below are mechanical; the correction is the human deliverable.

- [ ] **Step 1: Pull job 43's `canonical_graph.json` from the dev box**

Job 43 is ≤39-era flat layout: `/app/job_outputs/43/`. Read the exact path from the DB to be safe, then copy the file out via SSM. Run (from a shell authed for `tnbqong`):

```bash
# Confirm the on-disk path (avoid guessing the artifact dir):
aws ssm send-command --region ap-south-1 --profile tnbqong \
  --instance-ids i-0e7b89bd91b67a291 --document-name AWS-RunShellScript \
  --comment "find job43 graph" \
  --parameters 'commands=["sudo docker exec qong-web-1 sh -lc \"ls -la /app/job_outputs/43/canonical_graph.json && wc -c /app/job_outputs/43/canonical_graph.json\""]' \
  --query Command.CommandId --output text
# then: aws ssm get-command-invocation --region ap-south-1 --profile tnbqong --command-id <id> --instance-id i-0e7b89bd91b67a291 --query StandardOutputContent --output text
```

Copy the file to the host and down to local (graph JSON is small, well under the 50 MB IAP limit, so direct SSM copy is fine — no GCS hop needed):

```bash
# On the VM: stage a host copy the ubuntu user can read.
aws ssm send-command --region ap-south-1 --profile tnbqong \
  --instance-ids i-0e7b89bd91b67a291 --document-name AWS-RunShellScript \
  --comment "stage job43 graph" \
  --parameters 'commands=["sudo docker cp qong-web-1:/app/job_outputs/43/canonical_graph.json /tmp/job_43_graph.json && sudo chmod 644 /tmp/job_43_graph.json && base64 /tmp/job_43_graph.json | tr -d \"\\n\""]' \
  --query Command.CommandId --output text
# Fetch StandardOutputContent (base64), decode locally into the seed path:
#   aws ssm get-command-invocation ... --query StandardOutputContent --output text > /tmp/job43.b64
#   base64 -d /tmp/job43.b64 > /tmp/job_43_graph.json
```

(If the base64 output exceeds the ~24 KB `get-command-invocation` cap, write it to S3 from the VM — `aws s3 cp /tmp/job_43_graph.json s3://qong-pid-archive-2026-06-02/tmp/` — and pull it down with `aws s3 cp`.)

- [ ] **Step 2: Seed the GT file from the pulled graph**

```bash
python3 -m webapp.scripts.score_graph --job-id 43 --graph /tmp/job_43_graph.json --seed
# -> writes tests/graph_ground_truth/job_43.json
```

- [ ] **Step 3: Sanity-check the harness on the un-edited seed**

The seed equals the extraction, so scoring it against itself MUST be perfect — this validates the harness wiring before any edits:

```bash
python3 -m webapp.scripts.score_graph --job-id 43 --graph /tmp/job_43_graph.json --gt tests/graph_ground_truth/job_43.json
# Expected: node F1=1.000, edge F1=1.000, is_isomorphic: True
```

If it is NOT perfect, the harness is wrong — stop and fix scoring, do not proceed.

- [ ] **Step 4: Add the `meta` block and hand-correct (HUMAN)**

Edit `tests/graph_ground_truth/job_43.json`. Add a top-level `meta` object:

```json
"meta": {
  "source_job_id": 43,
  "source_commit": "<git rev-parse HEAD of the extraction>",
  "source_model": "v1-11 YOLO ONNX + gemini fallback",
  "authored_by": "<name>",
  "frozen_at": "2026-06-26T00:00:00Z",
  "notes": "Seeded from #66 extraction; hand-corrected edges/tags."
}
```

Then a human reviews against the source P&ID: add missing edges, delete wrong ones, fix node tags. Re-running the score after edits should show edge F1 < 1.0 by exactly the corrections — that delta is the measured error in the #66 extraction.

- [ ] **Step 5: Commit**

```bash
git add tests/graph_ground_truth/job_43.json
git commit -m "feat(graph): frozen ground-truth graph for job 43 (anchor for is_isomorphic metric)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: FEATURES.md entry + run full suite

**Files:**
- Modify: `FEATURES.md`
- Modify: `SESSION_STATE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: the required FEATURES.md journal entry + session handoff.

- [ ] **Step 1: Run the full unit suite to confirm no regressions**

Run: `docker run --rm -v $(pwd):/app qong_poc-web:latest python3 -m pytest tests/unit/ -q`
Expected: all pass except the known pre-existing `test_sheets_empty_when_no_tiles` (unrelated). Confirm the new `test_graph_scoring.py` (15) are green.

- [ ] **Step 2: Append a FEATURES.md entry**

Add a new top entry (do not edit past entries) recording: the metric definition (node-aligned undirected edge F1 + strict `is_isomorphic` gate + directed agreement secondary), the alignment cascade, the frozen GT provenance for job 43, and that cross-tile stitching is deferred pending the measured seam gap. Reference this plan + the spec.

- [ ] **Step 3: Overwrite SESSION_STATE.md**

Overwrite with: what shipped (scoring module + CLI + frozen GT), where it stopped, the measured job-43 edge F1 once the GT is hand-corrected, the next concrete step (measure seam gap → decide on stitch pass; or wire into Phase 2 eval gate), and the gotcha that the GT hand-correction is a human step.

- [ ] **Step 4: Commit**

```bash
git add FEATURES.md SESSION_STATE.md
git commit -m "docs(graph): FEATURES + session state — graph scoring harness & job-43 GT anchor

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- GT frozen file for job 43 → Task 4 ✅
- Pure importable `scoring.py` with `align_nodes` + `score_graph` → Tasks 1–2 ✅
- CLI with report/`--json`/`--seed` → Task 3 ✅
- Node-aligned graded edge F1 + strict `is_isomorphic` + directed agreement → Task 2 ✅
- Alignment cascade entity_id → tag → spatial → Task 1 ✅
- Connectivity + missing/extra edge lists → Task 2 ✅
- Error handling (missing/malformed files, wrapped isomorphism) → Task 2 (`_is_isomorphic` try/except), Task 3 (CLI exit codes) ✅
- Test plan cases (perfect, missing, extra, tag-rename→spatial, untagged threshold, reversed direction, empty) → Tasks 1–2 ✅
- networkx dependency check → Global Constraints + Task 5 Step 1 (suite runs in container) ✅
- FEATURES entry → Task 5 ✅
- Reusable by Phase 2 (DB-free module) → Global Constraints + module design ✅

**Placeholder scan:** No TBD/TODO in code steps. The one "HUMAN" step (Task 4 Step 4) is an inherent manual deliverable (hand-correcting ground truth), flagged in the spec's Non-Goals/decisions — not a plan gap.

**Type consistency:** `align_nodes`/`NodeAlignment`/`GraphScore`/`score_graph`/`to_dict` names match across Tasks 1–3. On-disk node key is `id` (not `node_id`) consistently in fixtures, `align_nodes`, and `score_graph`. Edge keys `source`/`target`/`directed` consistent. CLI functions `resolve_graph_path`/`format_report`/`main` match their tests.
