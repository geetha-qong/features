"""Process-graph read API (graph-extraction, 2026-06-13 design).

Serves the unified process graph for a job: the auto-extracted graph from the
on-disk ``canonical_graph.json`` (pipeline source of truth) merged with the
user-edit layer in ``graph_corrections`` (FEATURES #38, edges the user drew in
Studio).

Endpoint (mounted under prefix "/api/v1/jobs"):
  GET /{job_id}/graph   → 200 unified graph
                          404 {"error":"no_canonical"}      no canonical.json (pipeline never ran)
                          409 {"error":"canonical_required"} canonical present but graph not computed

Why merge at read time (not bake user edges into the file):
  Same contract as ``entity_overrides`` / ``canonical_entities`` — the file
  stays the pipeline's idempotent output, user edits live in a parallel DB
  layer, and the read path unions them. A pipeline re-run never clobbers user
  work.

Auth: same IDOR pattern as ``edges.py`` — 404 (not 403) for foreign jobs;
super_admin can read any job. Cookie-authed so the Studio ``<img>``-adjacent
fetch works same-origin.

v0 merge semantics (honest about limits):
  - Auto edges (method ``opencv`` / ``llm_fallback``) come from the file.
  - User edges (``graph_corrections``) are appended, tagged ``method`` from
    their ``source`` (``user`` → ``user_added``).
  - Rejecting an *auto* edge is NOT yet wired: auto edges are not stored in
    ``graph_corrections``, so there is no per-auto-edge reject key in v0. The
    merge is additive. Tracked for v0.5.
"""
from __future__ import annotations

import json
from html import escape as _he
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db
from webapp.graph.orphan_dedup import superseded_auto_ids

router = APIRouter(prefix="/api/v1/jobs", tags=["graph"])


def _page_dimensions(job_dir: Path) -> Tuple[Optional[int], Optional[int]]:
    """Read width/height from the full-page PNG when the graph file doesn't have them."""
    for candidate in (
        job_dir / "tmp" / "page_0_full.png",
        job_dir / "page_0_full.png",
    ):
        if candidate.exists():
            try:
                from PIL import Image
                with Image.open(str(candidate)) as img:
                    return img.size[0], img.size[1]
            except Exception:
                pass
    return None, None



def _load_job_or_404(
    job_id: int, db: Session, current_user: models.User
) -> models.Job:
    """404 (not 403) for foreign jobs — mirror of edges.py / entities.py."""
    job: Optional[models.Job] = db.get(models.Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    if job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job


def _job_dir(job: models.Job) -> Optional[Path]:
    if not job.output_csv_path:
        return None
    return Path(job.output_csv_path).parent


def _user_edge_to_dict(row: models.GraphCorrection) -> Dict[str, Any]:
    method = "user_added" if row.source == "user" else row.source
    # User edges are directed by construction (the user drew source→target).
    # A NULL `directed` column (legacy rows pre-migration) reads as True for
    # user edges — they were always directed; the column just didn't exist yet.
    directed = True if row.directed is None else bool(row.directed)
    return {
        "id": row.edge_id,
        "source": row.source_entity_id,
        "target": row.target_entity_id,
        "polyline": row.polyline,
        "tile": None,
        "method": method,
        "confidence": None,
        "directed": directed,
        "line_type": row.line_type,
        "status": row.status,
        "source_entity_id": row.source_entity_id,
        "target_entity_id": row.target_entity_id,
        "group_id": row.group_id,
    }


_REJECT_PREFIX = "reject__"

# Reserved EntityOverride.field_name flagging a user-removed (rejected) node.
# Mirrors webapp/deliverables/overrides.REJECTED_FIELD.
_REJECTED_FIELD = "__rejected__"

# UserAnnotation statuses that should surface as graph nodes (user-added marks
# and user-confirmed detections). Rejected/model-only statuses are excluded.
_ANNOTATION_NODE_STATUSES = frozenset({"user_added", "user_confirmed"})


def _annotation_to_node(a: "models.UserAnnotation", rejected: bool) -> Dict[str, Any]:
    """Map a UserAnnotation row to the graph node shape the canvas consumes."""
    return {
        "id": a.entity_id,
        "entity_id": a.entity_id,
        "tag": a.tag or a.placeholder_tag,
        "class": a.sub_class or a.entity_class,
        "bbox": a.bbox,
        "tile": "user",
        "confidence": 1.0,
        "source": "user",
        "rejected": rejected,
    }


def _rejected_entity_ids(job_id: int, db: Session) -> set:
    """entity_ids the user removed via a truthy `__rejected__` EntityOverride."""
    from webapp.deliverables.overrides import _truthy
    rows = (
        db.query(models.EntityOverride)
        .filter(
            models.EntityOverride.job_id == job_id,
            models.EntityOverride.field_name == _REJECTED_FIELD,
        )
        .all()
    )
    return {r.entity_id for r in rows if _truthy(r.new_value)}


def _annotation_nodes(job_id: int, db: Session, rejected_ids: set) -> List[Dict[str, Any]]:
    """UserAnnotation rows (user_added / user_confirmed) as source='user' nodes."""
    anns = (
        db.query(models.UserAnnotation)
        .filter(
            models.UserAnnotation.job_id == job_id,
            models.UserAnnotation.status.in_(_ANNOTATION_NODE_STATUSES),
        )
        .all()
    )
    return [
        _annotation_to_node(a, rejected=(a.entity_id in rejected_ids))
        for a in anns
    ]


@router.post("/{job_id}/graph/edges/{auto_edge_id}/reject", status_code=201)
def reject_auto_edge(
    job_id: int,
    auto_edge_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Mark an auto-extracted edge (opencv/llm_fallback) as rejected by the user.

    Stores a rejection record in graph_corrections. The get_job_graph endpoint
    filters out auto edges that have a corresponding rejection. Idempotent —
    calling again on an already-rejected edge is a no-op (returns 201 either way).
    """
    _load_job_or_404(job_id, db, current_user)
    rejection_edge_id = _REJECT_PREFIX + auto_edge_id
    existing = (
        db.query(models.GraphCorrection)
        .filter(
            models.GraphCorrection.job_id == job_id,
            models.GraphCorrection.edge_id == rejection_edge_id,
        )
        .first()
    )
    if not existing:
        row = models.GraphCorrection(
            job_id=job_id,
            edge_id=rejection_edge_id,
            user_id=current_user.id,
            source="auto_rejection",
            status="user_rejected",
            line_type="process_pipe",
            source_entity_id=auto_edge_id,
            target_entity_id="__auto_rejected__",
            polyline=[[0, 0], [0, 0]],
            sheet_number=1,
            directed=False,
        )
        db.add(row)
        db.commit()
    return {"rejected": auto_edge_id}


@router.delete("/{job_id}/graph/edges/{auto_edge_id}/reject", status_code=204, response_model=None)
def unreject_auto_edge(
    job_id: int,
    auto_edge_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Restore a previously-rejected auto edge (undo rejection)."""
    _load_job_or_404(job_id, db, current_user)
    rejection_edge_id = _REJECT_PREFIX + auto_edge_id
    row = (
        db.query(models.GraphCorrection)
        .filter(
            models.GraphCorrection.job_id == job_id,
            models.GraphCorrection.edge_id == rejection_edge_id,
        )
        .first()
    )
    if row:
        db.delete(row)
        db.commit()


@router.post("/{job_id}/nodes/{entity_id}/reject", status_code=200)
def reject_node(
    job_id: int,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Soft-remove a node (detected or user-added) from the graph + deliverables.

    Upserts an EntityOverride(field_name="__rejected__", new_value=True) keyed by
    entity_id. Idempotent — re-rejecting an already-rejected node returns 200 with
    no extra row (the UNIQUE constraint on (job_id, entity_id, field_name) keeps
    it to one). The override makes the node ghost in GET /graph and disappear from
    every deliverable (see overrides.load_canonical_with_overrides). Reversible via
    DELETE.
    """
    _load_job_or_404(job_id, db, current_user)
    existing = (
        db.query(models.EntityOverride)
        .filter(
            models.EntityOverride.job_id == job_id,
            models.EntityOverride.entity_id == entity_id,
            models.EntityOverride.field_name == _REJECTED_FIELD,
        )
        .first()
    )
    if existing:
        # Idempotent: ensure it's truthy, but don't duplicate.
        if existing.new_value is not True:
            existing.new_value = True
            db.commit()
    else:
        db.add(models.EntityOverride(
            job_id=job_id,
            entity_id=entity_id,
            field_name=_REJECTED_FIELD,
            new_value=True,
            edited_by=current_user.id,
        ))
        db.commit()
    return {"entity_id": entity_id, "rejected": True}


@router.delete("/{job_id}/nodes/{entity_id}/reject", status_code=204, response_model=None)
def unreject_node(
    job_id: int,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Undo a node rejection — deletes the `__rejected__` override row.

    404 if no rejection exists (frontend treats it as already-undone). Returns a
    bare 204 with no body.
    """
    from fastapi import Response
    _load_job_or_404(job_id, db, current_user)
    row = (
        db.query(models.EntityOverride)
        .filter(
            models.EntityOverride.job_id == job_id,
            models.EntityOverride.entity_id == entity_id,
            models.EntityOverride.field_name == _REJECTED_FIELD,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="node not rejected")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.get("/{job_id}/graph/twin", response_class=None)
def get_digital_twin(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Spatial digital twin visualization — nodes at real P&ID coordinates.

    Reads x/y/label/class from Neo4j (written by neo4j_writer._write_nodes).
    Returns a standalone HTML page with an SVG overlay scaled to the P&ID page.
    Falls back gracefully if Neo4j data is unavailable.
    """
    from fastapi.responses import HTMLResponse
    _load_job_or_404(job_id, db, current_user)

    try:
        from neo4j import GraphDatabase
        import os, json as _json
        _uri  = os.environ.get("NEO4J_URI",  "bolt://neo4j:7687")
        _user = os.environ.get("NEO4J_USER", "neo4j")
        _pwd  = os.environ.get("NEO4J_PASSWORD")
        driver = GraphDatabase.driver(_uri, auth=(_user, _pwd))
        jid = int(job_id)
        with driver.session() as s:
            meta_rec = s.run(
                "MATCH (m:Metadata {job_id:$jid}) RETURN m", jid=jid
            ).single()
            if not meta_rec:
                raise ValueError("no Neo4j data for this job — run the pipeline first")
            meta = dict(meta_rec["m"])
            page_w = float(meta.get("page_width") or 1)
            page_h = float(meta.get("page_height") or 1)

            raw_nodes = [
                dict(r["n"])
                for r in s.run(
                    "MATCH (n:Node {job_id:$jid,source:'auto'}) RETURN n", jid=jid
                )
            ]
            auto_edges = [
                {"src": r["src"], "tgt": r["tgt"], "method": "auto"}
                for r in s.run(
                    """MATCH (a:Node {job_id:$jid,source:'auto'})
                          -[e:PIPE {job_id:$jid,source:'auto'}]->
                       (b:Node {job_id:$jid,source:'auto'})
                       RETURN a.id AS src, b.id AS tgt""",
                    jid=jid,
                )
            ]
            user_edges = [
                {
                    "src": r["src"],
                    "tgt": r["tgt"],
                    "method": "user",
                    "line_type": r["lt"],
                }
                for r in s.run(
                    """MATCH (a)-[e:PIPE {job_id:$jid,source:'user_added'}]->(b)
                       WHERE e.status IS NULL OR NOT e.status = 'user_rejected'
                       RETURN
                         CASE WHEN 'FreePoint' IN labels(a) THEN a.id ELSE a.entity_id END AS src,
                         CASE WHEN 'FreePoint' IN labels(b) THEN b.id ELSE b.entity_id END AS tgt,
                         e.line_type AS lt""",
                    jid=jid,
                )
            ]
        driver.close()
    except Exception as exc:
        return HTMLResponse(
            f"<h2 style='font-family:sans-serif;color:red'>Digital twin not available</h2>"
            f"<p>{_he(str(exc))}</p>",
            status_code=200,
        )

    # Build node lookup by id and by entity_id
    nodes_by_id: Dict[str, Any] = {n["id"]: n for n in raw_nodes if n.get("id")}
    nodes_by_eid: Dict[str, Any] = {
        n["entity_id"]: n for n in raw_nodes if n.get("entity_id")
    }

    SVG_W = 4000
    SVG_H = int(SVG_W * page_h / page_w)

    def px(raw_x: float) -> float:
        return round(raw_x / page_w * SVG_W, 1)

    def py(raw_y: float) -> float:
        return round(raw_y / page_h * SVG_H, 1)

    CLASS_COLORS: Dict[str, str] = {
        "valve": "#ef4444", "instrument": "#8b5cf6",
        "equipment": "#10b981", "connector": "#f59e0b",
    }

    def node_color(cls: Optional[str]) -> str:
        if not cls:
            return "#94a3b8"
        for key, col in CLASS_COLORS.items():
            if key in (cls or "").lower():
                return col
        return "#94a3b8"

    # Build JSON data for JS — all positioning + edge adjacency in one blob
    import json as _json
    js_nodes = []
    for n in raw_nodes:
        if not n.get("x") or not n.get("y"):
            continue
        js_nodes.append({
            "id":        n.get("id") or "",
            "label":     (n.get("label") or n.get("tag") or n.get("class") or n.get("id") or "?")[:20],
            "cls":       n.get("class") or "",
            "tag":       n.get("tag") or "",
            "entity_id": (n.get("entity_id") or "")[:32],
            "conf":      round(n.get("confidence") or 0, 2),
            "x":         px(n["x"]),
            "y":         py(n["y"]),
            "color":     node_color(n.get("class")),
        })

    js_edges = []
    for e in auto_edges:
        n1 = nodes_by_id.get(e["src"])
        n2 = nodes_by_id.get(e["tgt"])
        if n1 and n2 and n1.get("x") and n2.get("x"):
            js_edges.append({"src": e["src"], "tgt": e["tgt"], "kind": "auto"})
    for e in user_edges:
        n1 = nodes_by_id.get(e["src"]) or nodes_by_eid.get(e["src"])
        n2 = nodes_by_id.get(e["tgt"]) or nodes_by_eid.get(e["tgt"])
        if n1 and n2 and n1.get("x") and n2.get("x"):
            js_edges.append({"src": e["src"], "tgt": e["tgt"], "kind": "user"})

    n_auto  = len([e for e in js_edges if e["kind"] == "auto"])
    n_user  = len([e for e in js_edges if e["kind"] == "user"])
    n_nodes = len(js_nodes)

    # Escape < and > so a value like "</script><script>..." can't break out of
    # the <script> block (json.dumps already escapes & as & by default).
    def _safe_json(obj: Any) -> str:
        return _json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e")

    nodes_json = _safe_json(js_nodes)
    edges_json = _safe_json(js_edges)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Digital Twin — Job {job_id}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #0f172a; font-family: sans-serif; display: flex; flex-direction: column;
       align-items: center; min-height: 100vh; padding: 16px; user-select: none; }}
h1 {{ color: #f1f5f9; font-size: 1rem; margin-bottom: 8px; letter-spacing: .05em; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 10px; }}
.legend-item {{ display: flex; align-items: center; gap: 6px; color: #94a3b8; font-size: .75rem; }}
.legend-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
.stats {{ color: #64748b; font-size: .7rem; margin-bottom: 10px; }}
.svg-wrap {{ background: #1e293b; border-radius: 8px; overflow: auto;
             border: 1px solid #334155; max-width: 100%; }}
.node-g {{ cursor: grab; }}
.node-g:active {{ cursor: grabbing; }}
#info-panel {{
  position: fixed; bottom: 20px; right: 20px; background: #1e293b;
  border: 1px solid #334155; border-radius: 8px; padding: 14px 16px;
  color: #f1f5f9; font-size: .78rem; min-width: 220px; max-width: 320px;
  display: none; box-shadow: 0 4px 24px rgba(0,0,0,.5); z-index: 100;
  font-family: monospace; line-height: 1.7;
}}
#info-panel h3 {{ font-size: .85rem; color: #e2e8f0; margin-bottom: 6px; }}
#info-panel .close-btn {{
  position: absolute; top: 8px; right: 10px; cursor: pointer;
  color: #64748b; font-size: 1rem;
}}
#info-panel .conn-list {{ margin-top: 8px; }}
#info-panel .conn-item {{ color: #94a3b8; }}
#info-panel .conn-item span {{ color: #60a5fa; }}
</style>
</head>
<body>
<h1>Digital Twin — Job {job_id} &nbsp;·&nbsp; P&amp;ID Graph (Neo4j)</h1>
<div class="legend">
  <div class="legend-item"><div class="legend-dot" style="background:#ef4444"></div>Valve</div>
  <div class="legend-item"><div class="legend-dot" style="background:#8b5cf6"></div>Instrument</div>
  <div class="legend-item"><div class="legend-dot" style="background:#10b981"></div>Equipment</div>
  <div class="legend-item"><div class="legend-dot" style="background:#94a3b8"></div>Other</div>
  <div class="legend-item"><div style="width:20px;height:2px;background:#60a5fa"></div>Auto pipe</div>
  <div class="legend-item"><div style="width:20px;height:2px;background:#f97316;border-top:2px dashed #f97316"></div>User pipe</div>
</div>
<div class="stats">{n_nodes} nodes &nbsp;|&nbsp; {n_auto} auto pipes &nbsp;|&nbsp; {n_user} user pipes
  &nbsp;|&nbsp; Page {int(page_w)}×{int(page_h)} px
  &nbsp;·&nbsp; <b style="color:#94a3b8">Drag</b> nodes &nbsp;·&nbsp; <b style="color:#94a3b8">Click</b> to see connections
</div>
<div class="svg-wrap">
  <svg id="twin-svg" width="{SVG_W}" height="{SVG_H}"
       viewBox="0 0 {SVG_W} {SVG_H}" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <marker id="arrow-user" markerWidth="8" markerHeight="8"
              refX="6" refY="3" orient="auto">
        <path d="M0,0 L0,6 L8,3 z" fill="#f97316"/>
      </marker>
      <marker id="arrow-user-hi" markerWidth="8" markerHeight="8"
              refX="6" refY="3" orient="auto">
        <path d="M0,0 L0,6 L8,3 z" fill="#fb923c"/>
      </marker>
    </defs>
    <rect width="{SVG_W}" height="{SVG_H}" fill="#0f172a"/>
    <g id="grid" opacity="0.06" stroke="#94a3b8" stroke-width="0.5">
      {"".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{SVG_H}"/>' for x in range(0, SVG_W, 100))}
      {"".join(f'<line x1="0" y1="{y}" x2="{SVG_W}" y2="{y}"/>' for y in range(0, SVG_H, 100))}
    </g>
    <g id="edges-layer"></g>
    <g id="nodes-layer"></g>
  </svg>
</div>

<div id="info-panel">
  <span class="close-btn" onclick="clearSelection()">✕</span>
  <h3 id="info-label"></h3>
  <div id="info-details"></div>
  <div class="conn-list" id="info-conns"></div>
</div>

<script>
const NODES = {nodes_json};
const EDGES = {edges_json};

const SVG_W = {SVG_W};
const SVG_H = {SVG_H};

// Escape HTML for safe innerHTML interpolation
function escHtml(s) {{
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}}

// ── State ────────────────────────────────────────────────────────────────────
const pos = {{}};  // id → {{x, y}}
NODES.forEach(n => {{ pos[n.id] = {{x: n.x, y: n.y}}; }});

const nodeMap = {{}};
NODES.forEach(n => {{ nodeMap[n.id] = n; }});

// Adjacency: id → [{{nid, kind}}]
const adj = {{}};
NODES.forEach(n => {{ adj[n.id] = []; }});
EDGES.forEach(e => {{
  if (adj[e.src]) adj[e.src].push({{nid: e.tgt, kind: e.kind}});
  if (adj[e.tgt]) adj[e.tgt].push({{nid: e.src, kind: e.kind}});
}});

// ── DOM refs ─────────────────────────────────────────────────────────────────
const svg       = document.getElementById('twin-svg');
const edgesLayer = document.getElementById('edges-layer');
const nodesLayer = document.getElementById('nodes-layer');
const infoPanel  = document.getElementById('info-panel');

// ── Build edge elements ───────────────────────────────────────────────────────
const edgeEls = {{}};  // "src|tgt" → {{el, kind}}
EDGES.forEach((e, i) => {{
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  const key = e.src + '|' + e.tgt;
  if (e.kind === 'auto') {{
    line.setAttribute('stroke', '#60a5fa');
    line.setAttribute('stroke-width', '1.2');
    line.setAttribute('stroke-opacity', '0.7');
  }} else {{
    line.setAttribute('stroke', '#f97316');
    line.setAttribute('stroke-width', '2');
    line.setAttribute('stroke-dasharray', '6,3');
    line.setAttribute('marker-end', 'url(#arrow-user)');
  }}
  line.dataset.src = e.src;
  line.dataset.tgt = e.tgt;
  line.dataset.kind = e.kind;
  edgesLayer.appendChild(line);
  edgeEls[key] = {{el: line, kind: e.kind}};
}});

// ── Build node elements ───────────────────────────────────────────────────────
const nodeEls = {{}};  // id → g element
NODES.forEach(n => {{
  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  g.setAttribute('class', 'node-g');
  g.dataset.id = n.id;

  const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  circle.setAttribute('r', '7');
  circle.setAttribute('fill', n.color);
  circle.setAttribute('stroke', 'white');
  circle.setAttribute('stroke-width', '1.5');
  circle.setAttribute('opacity', '0.9');

  const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  text.setAttribute('x', '9');
  text.setAttribute('y', '4');
  text.setAttribute('font-size', '8');
  text.setAttribute('fill', '#e2e8f0');
  text.setAttribute('font-family', 'monospace');
  text.setAttribute('paint-order', 'stroke');
  text.setAttribute('stroke', '#0f172a');
  text.setAttribute('stroke-width', '2');
  text.textContent = n.label;

  g.appendChild(circle);
  g.appendChild(text);
  nodesLayer.appendChild(g);
  nodeEls[n.id] = g;

  // ── Drag ──────────────────────────────────────────────────────────────────
  let dragging = false;
  let dragStartX, dragStartY, origX, origY;

  g.addEventListener('mousedown', ev => {{
    if (ev.button !== 0) return;
    dragging = true;
    dragStartX = ev.clientX;
    dragStartY = ev.clientY;
    origX = pos[n.id].x;
    origY = pos[n.id].y;
    ev.stopPropagation();
    ev.preventDefault();
  }});

  g.addEventListener('click', ev => {{
    if (Math.abs(ev.clientX - dragStartX) > 4 || Math.abs(ev.clientY - dragStartY) > 4) return;
    ev.stopPropagation();
    selectNode(n.id);
  }});
}});

// Global mouse handlers for drag
document.addEventListener('mousemove', ev => {{
  if (!Object.keys(nodeEls).some(id => nodeEls[id]._dragging)) return;
  Object.entries(nodeEls).forEach(([id, g]) => {{
    if (!g._dragging) return;
    const n = nodeMap[id];
    const svgRect = svg.getBoundingClientRect();
    const scaleX = SVG_W / svgRect.width;
    const scaleY = SVG_H / svgRect.height;
    const dx = (ev.clientX - g._dragStartX) * scaleX;
    const dy = (ev.clientY - g._dragStartY) * scaleY;
    pos[id].x = g._origX + dx;
    pos[id].y = g._origY + dy;
    renderPositions();
  }});
}});

document.addEventListener('mouseup', () => {{
  Object.values(nodeEls).forEach(g => {{ g._dragging = false; }});
}});

// Attach drag state to g elements
NODES.forEach(n => {{
  const g = nodeEls[n.id];
  g.addEventListener('mousedown', ev => {{
    if (ev.button !== 0) return;
    g._dragging = true;
    g._dragStartX = ev.clientX;
    g._dragStartY = ev.clientY;
    g._origX = pos[n.id].x;
    g._origY = pos[n.id].y;
  }});
}});

// ── Render positions ─────────────────────────────────────────────────────────
function renderPositions() {{
  // Move node groups
  NODES.forEach(n => {{
    nodeEls[n.id].setAttribute('transform', `translate(${{pos[n.id].x}},${{pos[n.id].y}})`);
  }});
  // Update edge endpoints
  Object.values(edgeEls).forEach(({{el}}) => {{
    const src = el.dataset.src;
    const tgt = el.dataset.tgt;
    if (pos[src] && pos[tgt]) {{
      el.setAttribute('x1', pos[src].x);
      el.setAttribute('y1', pos[src].y);
      el.setAttribute('x2', pos[tgt].x);
      el.setAttribute('y2', pos[tgt].y);
    }}
  }});
}}

// ── Selection / highlight ────────────────────────────────────────────────────
let selectedId = null;

function selectNode(id) {{
  selectedId = id;
  const neighbours = new Set(adj[id].map(a => a.nid));
  neighbours.add(id);

  // Dim all nodes and edges
  Object.entries(nodeEls).forEach(([nid, g]) => {{
    g.querySelector('circle').setAttribute('opacity', neighbours.has(nid) ? '1' : '0.15');
    g.querySelector('text').setAttribute('opacity', neighbours.has(nid) ? '1' : '0.1');
  }});

  Object.values(edgeEls).forEach(({{el, kind}}) => {{
    const connected = el.dataset.src === id || el.dataset.tgt === id;
    if (connected) {{
      el.setAttribute('stroke-opacity', '1');
      el.setAttribute('stroke-width', kind === 'auto' ? '2.5' : '3');
      if (kind === 'auto') el.setAttribute('stroke', '#93c5fd');
      else el.setAttribute('stroke', '#fb923c');
    }} else {{
      el.setAttribute('stroke-opacity', '0.05');
    }}
  }});

  // Info panel
  const n = nodeMap[id];
  document.getElementById('info-label').textContent = n.label;
  document.getElementById('info-details').innerHTML =
    `<div>Class: <b style="color:#8b5cf6">${{escHtml(n.cls)}}</b></div>` +
    `<div>Tag: <b style="color:#60a5fa">${{escHtml(n.tag || '—')}}</b></div>` +
    `<div>Confidence: ${{escHtml(n.conf)}}</div>` +
    `<div style="color:#64748b;font-size:.7rem">entity: ${{escHtml(n.entity_id || '—')}}</div>`;

  const connItems = adj[id].map(a => {{
    const nb = nodeMap[a.nid];
    const badge = a.kind === 'user'
      ? `<span style="color:#f97316;font-size:.65rem"> [user]</span>`
      : '';
    return `<div class="conn-item">→ <span>${{escHtml(nb ? nb.label : a.nid)}}</span>${{badge}}</div>`;
  }});
  document.getElementById('info-conns').innerHTML =
    `<div style="color:#64748b;font-size:.7rem;margin-top:4px">${{escHtml(adj[id].length)}} connection${{adj[id].length !== 1 ? 's' : ''}}</div>` +
    connItems.join('');

  infoPanel.style.display = 'block';
}}

function clearSelection() {{
  selectedId = null;
  Object.values(nodeEls).forEach(g => {{
    g.querySelector('circle').setAttribute('opacity', '0.9');
    g.querySelector('text').setAttribute('opacity', '1');
  }});
  Object.values(edgeEls).forEach(({{el, kind}}) => {{
    if (kind === 'auto') {{
      el.setAttribute('stroke', '#60a5fa');
      el.setAttribute('stroke-width', '1.2');
      el.setAttribute('stroke-opacity', '0.7');
    }} else {{
      el.setAttribute('stroke', '#f97316');
      el.setAttribute('stroke-width', '2');
      el.setAttribute('stroke-opacity', '1');
    }}
  }});
  infoPanel.style.display = 'none';
}}

// Click on SVG background clears selection
svg.addEventListener('click', ev => {{
  if (ev.target === svg || ev.target.tagName === 'rect') clearSelection();
}});

// ── Initial render ───────────────────────────────────────────────────────────
renderPositions();
</script>
</body>
</html>"""

    return HTMLResponse(content=html)


def _merge_tag_overrides(
    nodes: List[Dict[str, Any]], tag_by_eid: Dict[str, Any]
) -> None:
    """Overlay user `tag` edits onto graph nodes (in place), keyed by entity_id.

    The graph file (`canonical_graph.json`) carries the ORIGINAL OCR tag;
    `entity_overrides` is the canonical edit store. Without this merge the graph
    view reverts an edited tag on every refresh — while the deliverables (which
    already merge overrides) show the new value — so a user's tag edit silently
    "disappears" from the graph even though it is safely persisted.
    """
    if not tag_by_eid:
        return
    for node in nodes:
        eid = node.get("entity_id")
        if eid and eid in tag_by_eid:
            node["tag"] = tag_by_eid[eid]


@router.get(
    "/{job_id}/graph",
    responses={
        200: {"description": "Unified process graph (auto + user edges)"},
        404: {"description": "No canonical.json — pipeline has not run"},
        409: {"description": "canonical.json present but graph not yet computed"},
    },
)
def get_job_graph(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Dict[str, Any]:
    job = _load_job_or_404(job_id, db, current_user)
    job_dir = _job_dir(job)

    graph_path = (job_dir / "canonical_graph.json") if job_dir else None
    canonical_path = (job_dir / "canonical.json") if job_dir else None

    # Rejected entity_ids + user-annotation nodes are merged into every code path
    # below (and stand alone when there's no auto-graph file yet).
    rejected_ids = _rejected_entity_ids(job_id, db)
    annotation_nodes = _annotation_nodes(job_id, db, rejected_ids)

    if graph_path is None or not graph_path.exists():
        # No auto-graph on disk. A legacy job can still have user-added nodes —
        # return those (annotation-only) rather than erroring.
        if annotation_nodes:
            return {
                "job_id": job_id,
                "nodes": annotation_nodes,
                "edges": [],
                "stats": {
                    "nodes": len(annotation_nodes),
                    "edges": 0,
                    "auto_edges": 0,
                    "user_edges": 0,
                },
            }
        # Distinguish "pipeline never ran" from "ran but graph step hasn't been
        # computed for this (legacy) job".
        if canonical_path is not None and canonical_path.exists():
            raise HTTPException(
                status_code=409,
                detail={"error": "canonical_required",
                        "action": "run_pipeline_first"},
            )
        raise HTTPException(
            status_code=404,
            detail={"error": "no_canonical"},
        )

    try:
        graph: Dict[str, Any] = json.loads(graph_path.read_text(encoding="utf-8"))
    except Exception as e:  # corrupt file — treat as not-computed
        raise HTTPException(
            status_code=409,
            detail={"error": "graph_unreadable", "reason": str(e)},
        )

    graph.setdefault("job_id", job_id)

    # Enrich graph nodes with the pipe line number from their canonical entity.
    # Each valve entity stores fields.line (extracted by the Vision API); injecting
    # it here lets the frontend display the line label on edges without a second
    # API call.
    entity_line: Dict[str, str] = {}
    if canonical_path and canonical_path.exists():
        try:
            canonical_data = json.loads(canonical_path.read_text(encoding="utf-8"))
            for ent in canonical_data.get("entities", []):
                eid = ent.get("entity_id", "")
                line = (ent.get("fields") or {}).get("line", "")
                if eid and line:
                    entity_line[eid] = line
        except Exception:
            pass
    for node in graph.get("nodes", []):
        eid = node.get("entity_id") or ""
        if eid in entity_line:
            node["line"] = entity_line[eid]

    # Inject page dimensions when the graph file was assembled without them.
    # GraphLayer uses these to scale graph coords onto the canvas viewBox.
    if not graph.get("page_width") or not graph.get("page_height"):
        pw, ph = _page_dimensions(Path(job_dir))
        if pw:
            graph["page_width"] = pw
            graph["page_height"] = ph

    # Tag detected nodes source="auto" and flag rejected ones (returned, not
    # dropped, so the UI can ghost + restore them). Then merge user-annotation
    # nodes. entity_id is the cross-store spine.
    for node in graph.get("nodes", []):
        node["source"] = "user" if node.get("source") == "user" else "auto"
        node["rejected"] = (node.get("entity_id") or "") in rejected_ids
    # Merge user-annotation nodes, de-duplicated against canonical nodes that
    # already carry the same entity_id (a user may mark a symbol YOLO also found).
    _canonical_eids = {(n.get("entity_id") or "") for n in graph.get("nodes", [])}
    graph["nodes"] = list(graph.get("nodes", [])) + [
        a for a in annotation_nodes if a.get("entity_id") not in _canonical_eids
    ]

    # Drop orphan auto nodes (no entity_id) superseded by an adopted annotation
    # node at the same position, so the graph shows ONE node, not a duplicate.
    _superseded = superseded_auto_ids(
        [n for n in graph["nodes"] if n.get("source") == "auto"],
        [n for n in graph["nodes"] if n.get("source") == "user"],
    )
    if _superseded:
        graph["nodes"] = [n for n in graph["nodes"] if n.get("id") not in _superseded]

    # Merge user tag edits (entity_overrides field_name="tag") onto the final
    # node set so edited tags persist in the graph view on refresh. Applied
    # before any return path — both the Neo4j branch (via base_graph=graph) and
    # the JSON fallback read these merged nodes.
    _tag_overrides = {
        o.entity_id: o.new_value
        for o in db.query(models.EntityOverride).filter(
            models.EntityOverride.job_id == job_id,
            models.EntityOverride.field_name == "tag",
        )
    }
    _merge_tag_overrides(graph["nodes"], _tag_overrides)

    # Auto edges reference node ids (n_NNN), NOT entity_ids, so rejecting a
    # detected node must ALSO drop its edges by node id — else they dangle to a
    # ghosted node. `reject_keys` covers both id spaces for edge omission.
    rejected_node_ids = {
        n.get("id") for n in graph.get("nodes", [])
        if (n.get("entity_id") or "") in rejected_ids and n.get("id")
    }
    reject_keys = rejected_ids | rejected_node_ids | _superseded

    # Try Neo4j first — returns None if absent or on any error (non-fatal fallback).
    from webapp.graph.neo4j_writer import read_graph_from_neo4j
    neo4j_result = read_graph_from_neo4j(job_id, base_graph=graph)
    if neo4j_result is not None:
        # Apply the node-rejection edge omission to the Neo4j result too, so
        # removing a node consistently drops its dangling edges regardless of the
        # graph source (the merged nodes are already carried via base_graph).
        if reject_keys:
            neo4j_result["edges"] = [
                e for e in neo4j_result.get("edges", [])
                if not (
                    {
                        e.get("source_entity_id"), e.get("target_entity_id"),
                        e.get("source"), e.get("target"),
                    }
                    & reject_keys
                )
            ]
        return neo4j_result

    # ── Fallback: JSON + PostgreSQL merge (unchanged) ─────────────────────────
    auto_edges: List[Dict[str, Any]] = list(graph.get("edges", []))
    # Back-compat: legacy canonical_graph.json edges predate `directed`. A
    # missing key reads as False (undirected — renders as today).
    for e in auto_edges:
        e.setdefault("directed", False)

    # Load all graph_corrections for this job.
    all_corrections = (
        db.query(models.GraphCorrection)
        .filter(models.GraphCorrection.job_id == job_id)
        .all()
    )

    # Collect IDs of auto edges the user explicitly rejected.
    rejected_auto_ids = {
        r.source_entity_id
        for r in all_corrections
        if r.source == "auto_rejection"
    }
    auto_edges = [e for e in auto_edges if e.get("id") not in rejected_auto_ids]

    # User-drawn edges (source == "user"), excluding soft-deleted ones.
    user_edges = [
        _user_edge_to_dict(r)
        for r in all_corrections
        if r.source == "user" and r.status != "user_rejected"
    ]

    # Drop edges whose source/target entity_id was rejected (removing a node
    # also removes its dangling edges from the response).
    def _edge_touches_rejected(e: Dict[str, Any]) -> bool:
        endpoints = {
            e.get("source_entity_id"),
            e.get("target_entity_id"),
            e.get("source"),
            e.get("target"),
        }
        return bool(endpoints & reject_keys)

    if reject_keys:
        auto_edges = [e for e in auto_edges if not _edge_touches_rejected(e)]
        user_edges = [e for e in user_edges if not _edge_touches_rejected(e)]

    graph["edges"] = auto_edges + user_edges

    stats = dict(graph.get("stats", {}))
    stats["auto_edges"] = len(auto_edges)
    stats["user_edges"] = len(user_edges)
    stats["edges"] = len(graph["edges"])
    graph["stats"] = stats
    return graph
