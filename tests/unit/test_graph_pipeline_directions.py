"""End-to-end pipeline integration for edge orientation (graph-directions
spec 2026-06-17, Step E.5).

The orient unit tests (test_graph_orient.py) exercise ``orient_edges`` in
isolation. These tests drive the *real* ``webapp.graph.pipeline.extract_graph``
orchestration and assert that the per-edge ``directed`` flag actually lands on
the assembled ``canonical_graph.json`` edges — i.e. Step E.5 is wired, the flag
flows through ``assembler.assemble`` to the on-disk shape, and the edge-count
invariant holds *through the whole pipeline* (not just the unit).

Strategy: avoid cv2 image processing by injecting a stub ``LineTracer`` (the
``tracer=`` kwarg) that emits one fixed page-pixel segment between two nodes.
The arrow/connector detections ride in via ``detections`` (page-pixel, so
``tile_local_detections`` stays False). The linker skips ``arrow_*`` /
``connector_*`` as nodes (pipeline.py lines 63-64) but orient.py recovers them.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.graph import pipeline  # noqa: E402
from webapp.graph.tracer import LineSegment  # noqa: E402

GEN_AT = "2026-06-17T00:00:00Z"


def _write_full_page(job_dir, w=200, h=200):
    """The pipeline only invokes the tracer when a full-page image is on disk
    (pipeline.py guards CV tracing on ``full_page_image is not None``). Write a
    blank white page so our stub tracer runs and load_job_input sizes the page;
    the stub ignores the pixels, so the content is irrelevant."""
    import cv2

    os.makedirs(os.path.join(job_dir, "tmp"), exist_ok=True)
    img = np.full((h, w), 255, dtype=np.uint8)
    cv2.imwrite(os.path.join(job_dir, "tmp", "page_0_full.png"), img)


class _StubTracer:
    """A LineTracer that returns a fixed set of page-pixel segments, ignoring
    the image/mask. Lets us exercise the real resolver+orient+assembler chain
    without skimage/cv2 skeletonisation."""

    def __init__(self, segments):
        self._segments = segments

    def trace(self, image, bbox_mask=None):
        return list(self._segments)


# Two valve detections on a horizontal run. Node n_000 at the LEFT, n_001 RIGHT.
# (Page-pixel; the linker creates one node per detection, in order.)
def _valve(bbox):
    return {"label": "valve_BV", "bbox": bbox, "tile": "page", "confidence": 0.9}


def _arrow(label, bbox):
    return {"label": label, "bbox": bbox, "tile": "page", "confidence": 0.8}


# A → B, left → right. Valve A centred ~ (10,10); valve B centred ~ (110,10).
LEFT_VALVE = _valve([0, 0, 20, 20])
RIGHT_VALVE = _valve([100, 0, 120, 20])
# Traced segment whose endpoints snap to the two valve bboxes (within 30px).
RUN_SEGMENT = LineSegment(polyline=[(15, 10), (105, 10)], tile="page", confidence=0.8)


def _run(detections, *, write_dir):
    """Drive extract_graph with the stub tracer and our detections."""
    os.makedirs(write_dir, exist_ok=True)
    _write_full_page(write_dir)
    return pipeline.extract_graph(
        write_dir,
        detections,
        generated_at=GEN_AT,
        job_id=99,
        page=1,
        tracer=_StubTracer([RUN_SEGMENT]),
        write_file=True,
    )


def _the_edge(graph):
    """The single auto edge the pipeline should have resolved + oriented."""
    edges = graph["edges"]
    assert len(edges) == 1, f"expected exactly one resolved edge, got {edges}"
    return edges[0]


# ── arrow present → directed=True, source→target matches the arrow ────────────

def test_pipeline_arrow_on_edge_yields_directed_true(tmp_path):
    # arrow_right sits on the run (centroid (60,10), on the polyline). Flow is
    # left→right, which agrees with the tracer's source(n_000,left)→target(n_001).
    dets = [
        LEFT_VALVE,
        RIGHT_VALVE,
        _arrow("arrow_right", [55, 5, 65, 15]),
    ]
    graph = _run(dets, write_dir=str(tmp_path))
    edge = _the_edge(graph)
    assert edge["directed"] is True
    # source is the LEFT node (upstream), target the RIGHT node (downstream).
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    src_bbox = nodes_by_id[edge["source"]]["bbox"]
    tgt_bbox = nodes_by_id[edge["target"]]["bbox"]
    src_cx = (src_bbox[0] + src_bbox[2]) / 2
    tgt_cx = (tgt_bbox[0] + tgt_bbox[2]) / 2
    assert src_cx < tgt_cx, "arrow_right must orient source(left)→target(right)"


def test_pipeline_arrow_left_swaps_source_target(tmp_path):
    # Same geometry, but the flow arrow points LEFT. The pipeline must swap so
    # the RIGHT node is the source (upstream) and the LEFT node the target.
    dets = [
        LEFT_VALVE,
        RIGHT_VALVE,
        _arrow("arrow_left", [55, 5, 65, 15]),
    ]
    graph = _run(dets, write_dir=str(tmp_path))
    edge = _the_edge(graph)
    assert edge["directed"] is True
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    src_cx = sum(nodes_by_id[edge["source"]]["bbox"][0::2]) / 2
    tgt_cx = sum(nodes_by_id[edge["target"]]["bbox"][0::2]) / 2
    assert src_cx > tgt_cx, "arrow_left must orient source(right)→target(left)"


# ── no arrow → directed=False, SAME edge count as the arrow case ──────────────

def test_pipeline_no_arrow_yields_directed_false_same_edge_count(tmp_path):
    with_arrow = _run(
        [LEFT_VALVE, RIGHT_VALVE, _arrow("arrow_right", [55, 5, 65, 15])],
        write_dir=str(tmp_path / "with"),
    )
    no_arrow = _run([LEFT_VALVE, RIGHT_VALVE], write_dir=str(tmp_path / "without"))

    # The invariant the spec demands: orientation never adds/drops edges.
    assert len(no_arrow["edges"]) == len(with_arrow["edges"]) == 1
    assert no_arrow["edges"][0]["directed"] is False
    assert with_arrow["edges"][0]["directed"] is True
    # Node count identical too — only the flag/orientation differs.
    assert len(no_arrow["nodes"]) == len(with_arrow["nodes"])


# ── the flag actually persists to canonical_graph.json on disk ────────────────

def test_pipeline_directed_persists_to_canonical_graph_json(tmp_path):
    _run([LEFT_VALVE, RIGHT_VALVE, _arrow("arrow_right", [55, 5, 65, 15])],
         write_dir=str(tmp_path))
    on_disk = json.loads(
        (tmp_path / pipeline.GRAPH_FILENAME).read_text(encoding="utf-8")
    )
    assert on_disk["edges"][0]["directed"] is True
    # And every edge carries the key (back-compat reader relies on its presence
    # being optional, but the emitter must always write it).
    assert all("directed" in e for e in on_disk["edges"])


def test_pipeline_arrow_does_not_become_a_node(tmp_path):
    # Sanity: the arrow detection is consumed by orientation, NOT linked as a
    # graph node. 2 valves in → 2 nodes out (the arrow is skipped at link time).
    graph = _run(
        [LEFT_VALVE, RIGHT_VALVE, _arrow("arrow_right", [55, 5, 65, 15])],
        write_dir=str(tmp_path),
    )
    assert len(graph["nodes"]) == 2
    classes = sorted(n["class"] for n in graph["nodes"])
    assert classes == ["valve_BV", "valve_BV"]
    assert not any(str(n["class"]).startswith("arrow_") for n in graph["nodes"])
