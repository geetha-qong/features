"""Step F — graph assembler.

Build a ``networkx.MultiGraph`` (undirected — flow direction is a v1 problem)
from resolved nodes + edges, and serialise to the ``canonical_graph.json`` shape
defined in the predecessor spec §3. ``to_json``/``from_json`` are round-trip
identity for the dict form.

Determinism: this module never calls a time function. ``generated_at`` is passed
in by the caller (an ISO-8601 string) so tests are reproducible.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import networkx as nx

from webapp.graph.resolver import Edge, OrphanLine

GRAPH_VERSION = "0.1"


def _edge_id(i: int) -> str:
    return f"e_{i:03d}"


def build_multigraph(
    nodes: Sequence[Dict[str, Any]],
    edges: Sequence[Edge],
) -> nx.MultiGraph:
    """Assemble a NetworkX MultiGraph. Node attrs carry the full node dict;
    edge attrs carry method/polyline/tile/confidence."""
    g = nx.MultiGraph()
    for node in nodes:
        nid = str(node["node_id"])
        attrs = {k: v for k, v in node.items() if k != "node_id"}
        g.add_node(nid, **attrs)
    for i, e in enumerate(edges):
        g.add_edge(
            e.source,
            e.target,
            key=_edge_id(i),
            polyline=[list(p) for p in e.polyline],
            tile=e.tile,
            method=e.method,
            confidence=e.confidence,
        )
    return g


def assemble(
    nodes: Sequence[Dict[str, Any]],
    edges: Sequence[Edge],
    orphan_lines: Sequence[OrphanLine],
    *,
    job_id: Optional[int],
    page: int,
    generated_at: str,
    fallback_used: bool = False,
) -> Dict[str, Any]:
    """Build the ``canonical_graph.json`` dict (the JobGraph).

    Node order is preserved from input. ``floating_nodes`` are node_ids that
    appear in no edge. The shape matches predecessor spec §3 exactly.
    """
    node_dicts: List[Dict[str, Any]] = []
    connected: set = set()

    edge_dicts: List[Dict[str, Any]] = []
    for i, e in enumerate(edges):
        connected.add(e.source)
        connected.add(e.target)
        edge_dicts.append(
            {
                "id": _edge_id(i),
                "source": e.source,
                "target": e.target,
                "polyline": [list(p) for p in e.polyline],
                "tile": e.tile,
                "method": e.method,
                "confidence": e.confidence,
            }
        )

    floating: List[str] = []
    for node in nodes:
        nid = str(node["node_id"])
        node_dicts.append(
            {
                "id": nid,
                "entity_id": node.get("entity_id"),
                "tag": node.get("tag"),
                "class": node.get("class"),
                "bbox": list(node["bbox"]) if node.get("bbox") is not None else None,
                "tile": node.get("tile"),
                "confidence": node.get("confidence"),
            }
        )
        if nid not in connected:
            floating.append(nid)

    orphan_dicts = [
        {"polyline": [list(p) for p in o.polyline], "tile": o.tile, "reason": o.reason}
        for o in orphan_lines
    ]

    return {
        "version": GRAPH_VERSION,
        "job_id": job_id,
        "page": page,
        "generated_at": generated_at,
        "stats": {
            "nodes": len(node_dicts),
            "edges": len(edge_dicts),
            "fallback_used": fallback_used,
        },
        "nodes": node_dicts,
        "edges": edge_dicts,
        "floating_nodes": floating,
        "orphan_lines": orphan_dicts,
    }


def to_json(graph: Dict[str, Any]) -> str:
    """Serialise a JobGraph dict to a canonical JSON string (sorted keys for
    deterministic output)."""
    import json

    return json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True)


def from_json(text: str) -> Dict[str, Any]:
    """Parse a JobGraph JSON string back into a dict. Round-trips with
    ``to_json`` for value identity (tuples become lists, which is the on-disk
    contract)."""
    import json

    return json.loads(text)
