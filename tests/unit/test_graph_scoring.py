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
    assert a.unmatched_extracted == []
    assert a.unmatched_gt == []


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


def test_align_spatial_prefers_nearest_centroid_when_iou_below_threshold():
    # G1: tiny IoU but below threshold; G2: zero IoU but much closer centroid.
    # Spec: with no candidate >= iou_threshold, the NEAREST centroid wins (G2).
    ext = [_node("n_000", bbox=[0, 0, 10, 10])]
    gt = [
        _node("g_000", bbox=[8, 8, 18, 18]),    # IoU ~0.05 (<0.5), centroid dist ~11.3
        _node("g_001", bbox=[2, 2, 12, 12]),    # IoU ~0.47 (<0.5), centroid dist ~2.8 -> nearest
    ]
    a = scoring.align_nodes(ext, gt)
    assert a.mapping == {"n_000": "g_001"}


def test_align_spatial_prefers_iou_match_over_nearer_centroid():
    # G1 meets IoU threshold; G2 is a hair closer in centroid but IoU=0.
    # Spec: an IoU>=threshold match takes precedence over the centroid fallback.
    ext = [_node("n_000", bbox=[0, 0, 10, 10])]
    gt = [
        _node("g_000", bbox=[1, 1, 11, 11]),       # IoU ~0.68 (>=0.5)
        _node("g_001", bbox=[-2, -2, 1, 1]),       # IoU 0, centroid dist ~4.2
    ]
    a = scoring.align_nodes(ext, gt)
    assert a.mapping == {"n_000": "g_000"}


def test_align_spatial_nearest_centroid_beats_farther_higher_iou_below_threshold():
    # Regression guard for the two-sub-pass fix. n_000 centroid (5,5).
    # g_000: zero IoU (disjoint) but NEAREST centroid (the correct match).
    # g_001: nonzero but below-threshold IoU, FARTHER centroid.
    # Old single-loop ranked by IoU first -> wrongly picked g_001.
    # New code: IoU sub-pass finds nothing >=0.5 -> centroid sub-pass picks nearest g_000.
    ext = [_node("n_000", bbox=[0, 0, 10, 10])]
    gt = [
        _node("g_000", bbox=[10, 4, 14, 6]),    # disjoint -> IoU 0; centroid (12,5) dist ~7
        _node("g_001", bbox=[4, 4, 20, 20]),    # IoU ~0.11 (<0.5); centroid (12,12) dist ~9.9
    ]
    a = scoring.align_nodes(ext, gt)
    assert a.mapping == {"n_000": "g_000"}


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


def test_cli_seed_with_bare_gt_filename(tmp_path, monkeypatch):
    from webapp.scripts import score_graph as cli
    # extracted graph to seed from
    src = tmp_path / "graph.json"
    src.write_text('{"nodes": [], "edges": []}')
    monkeypatch.chdir(tmp_path)  # so a bare GT filename resolves under tmp
    rc = cli.main(["--job-id", "99", "--graph", str(src), "--gt", "bare_gt.json", "--seed"])
    assert rc == 0
    assert (tmp_path / "bare_gt.json").exists()
