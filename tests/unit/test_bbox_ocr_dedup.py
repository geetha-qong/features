"""Tests for page_dims_for_job (webapp.graph.page_geometry).

TDD: test_page_dims_reads_canonical_graph and test_page_dims_missing_returns_none
are the RED tests; they fail until page_geometry.py is created.
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from webapp.graph.page_geometry import page_dims_for_job


class _Job:
    def __init__(self, p): self.output_csv_path = p


def test_page_dims_reads_canonical_graph(tmp_path):
    (tmp_path / "canonical_graph.json").write_text(json.dumps({"page_width": 900, "page_height": 700}))
    j = _Job(str(tmp_path / "output.csv"))
    assert page_dims_for_job(j) == (900, 700)


def test_page_dims_missing_returns_none(tmp_path):
    j = _Job(str(tmp_path / "output.csv"))
    assert page_dims_for_job(j) is None
