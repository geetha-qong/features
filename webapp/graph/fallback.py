"""Step G — LLM fallback (graceful degradation).

Gate: when the CV tracer produces too few edges (``len(edges) < 0.3 * len(nodes)``),
ask an OpenRouter vision model to read the drawing and return pipe connections as
JSON pairs of node ids. Merged edges are tagged ``method="llm_fallback"``.

Design choices for testability:
  - The OpenRouter client is *injected* (``client`` arg). Default loader lazily
    imports the repo-root ``extractor`` module so this file imports cleanly
    without ``openai``/``dotenv`` present, and tests can pass a stub client.
  - Malformed / non-JSON model output → no edges added + a warning, never raises.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from webapp.graph.resolver import Edge


FALLBACK_GATE_RATIO = 0.3

# Structured-output schema: forces the model to return a parseable object so the
# topology pass can't silently fail (the job-43 bug: a 207-node single prompt
# returned text we couldn't parse → 0 edges). Tolerant `_parse_pairs` is still
# the secondary path for models/endpoints that ignore `response_format`.
_CONNECTIONS_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "pid_connections",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "connections": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                }
            },
            "required": ["connections"],
            "additionalProperties": False,
        },
    },
}


def should_use_fallback(num_nodes: int, num_edges: int, ratio: float = FALLBACK_GATE_RATIO) -> bool:
    """Gate: fire fallback when edge density is below ``ratio`` of node count.

    No nodes → no fallback (nothing to connect). At least one node and zero
    edges always fires.
    """
    if num_nodes <= 0:
        return False
    return num_edges < ratio * num_nodes


def _default_client():
    """Lazily build the OpenRouter (OpenAI-compatible) client from extractor."""
    import extractor  # repo-root module; imports openai + dotenv

    return extractor.get_client()


def _default_model() -> str:
    import extractor

    return extractor.DEFAULT_MODEL


def _image_to_base64(path: str) -> str:
    import extractor

    return extractor.image_to_base64(path)


def _build_prompt(nodes: Sequence[Dict[str, Any]]) -> str:
    """Structured prompt describing nodes; asks for connection pairs as JSON."""
    lines = ["Nodes (id: tag / class @ bbox[x1,y1,x2,y2]):"]
    for n in nodes:
        nid = n.get("node_id") or n.get("id")
        tag = n.get("tag") or "?"
        cls = n.get("class") or "?"
        bbox = n.get("bbox")
        lines.append(f"  {nid}: {tag} / {cls} @ {bbox}")
    body = "\n".join(lines)
    return (
        "You are reading a P&ID engineering drawing. The labelled symbols (nodes) "
        "below are connected by process pipes. Return ONLY a JSON array of pairs "
        'of node ids that are directly connected by a pipe, e.g. '
        '[["n_001","n_004"],["n_002","n_007"]]. Do not include explanations.\n\n'
        + body
    )


def _parse_pairs(text: str) -> List[Tuple[str, str]]:
    """Parse the model's response into (source, target) id pairs.

    Tolerant: strips markdown fences, finds the first JSON array, ignores
    malformed entries. Returns [] on any parse failure.
    """
    import json
    import re

    if not text:
        return []
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()

    data: Any = None
    # Prefer parsing the whole payload (structured-output object or bare array);
    # fall back to grabbing the first array substring for chatty responses.
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except (json.JSONDecodeError, ValueError):
                return []
    # Structured shape: {"connections": [...]} or {"edges": [...]}.
    if isinstance(data, dict):
        data = data.get("connections") or data.get("edges") or []
    if not isinstance(data, list):
        return []
    pairs: List[Tuple[str, str]] = []
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            a, b = item[0], item[1]
            if a is not None and b is not None:
                pairs.append((str(a), str(b)))
        elif isinstance(item, dict):
            a = item.get("source") or item.get("from") or item.get("a")
            b = item.get("target") or item.get("to") or item.get("b")
            if a is not None and b is not None:
                pairs.append((str(a), str(b)))
    return pairs


def _select_nodes_in_tile(
    nodes: Sequence[Dict[str, Any]], tile_box: Sequence[float]
) -> List[Dict[str, Any]]:
    """Nodes whose bbox centre falls inside ``tile_box`` (x0, y0, x1, y1).

    The 20% tile overlap (loader.compute_tile_offsets) means a node near a tile
    boundary appears in adjacent tiles too — so a pipe crossing the boundary is
    seen together in at least one tile. v1 relies on this instead of a separate
    cross-tile stitch pass.
    """
    x0, y0, x1, y1 = tile_box[0], tile_box[1], tile_box[2], tile_box[3]
    out: List[Dict[str, Any]] = []
    for n in nodes:
        bbox = n.get("bbox")
        if not bbox:
            continue
        cx = (bbox[0] + bbox[2]) / 2.0
        cy = (bbox[1] + bbox[3]) / 2.0
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            out.append(n)
    return out


def _build_region_prompt(
    nodes: Sequence[Dict[str, Any]], origin: Tuple[float, float] = (0.0, 0.0)
) -> str:
    """Prompt for one tile region; bboxes are localized to the crop's origin so
    they line up with the tile image the model sees."""
    ox, oy = origin
    lines = ["Nodes in this region (id: tag / class @ bbox[x1,y1,x2,y2], region-local px):"]
    for n in nodes:
        nid = n.get("node_id") or n.get("id")
        tag = n.get("tag") or "?"
        cls = n.get("class") or "?"
        b = n.get("bbox")
        lb = [round(b[0] - ox), round(b[1] - oy), round(b[2] - ox), round(b[3] - oy)] if b else None
        lines.append(f"  {nid}: {tag} / {cls} @ {lb}")
    body = "\n".join(lines)
    return (
        "You are reading a cropped region of a P&ID engineering drawing. The "
        "labelled symbols (nodes) below are connected by process pipes/lines. "
        "Return ONLY the node-id pairs that are DIRECTLY connected by a pipe "
        'visible in this image, as JSON: {"connections": [["n_001","n_004"], ...]}. '
        "Use only the node ids listed. No explanations.\n\n" + body
    )


def _connections_for_region(
    client: Any,
    model: Optional[str],
    image_path: Optional[str],
    region_nodes: Sequence[Dict[str, Any]],
    origin: Tuple[float, float],
    warnings: List[str],
) -> List[Tuple[str, str]]:
    """One structured LLM call for a single tile region. Non-fatal: any failure
    appends a warning and returns []."""
    content: List[Dict[str, Any]] = [
        {"type": "text", "text": _build_region_prompt(region_nodes, origin)}
    ]
    if image_path and os.path.exists(image_path):
        try:
            b64 = _image_to_base64(image_path)
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            )
        except Exception as _img_err:  # noqa: BLE001
            warnings.append(f"fallback: region image unreadable ({_img_err})")
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            response_format=_CONNECTIONS_SCHEMA,
        )
        raw = response.choices[0].message.content or ""
    except Exception as _err:  # noqa: BLE001 — one tile failing must not kill the rest
        warnings.append(f"fallback: tile call failed ({_err})")
        return []
    return _parse_pairs(raw)


def _collect_pairs_single(
    client: Any,
    model: Optional[str],
    nodes: Sequence[Dict[str, Any]],
    full_page_image_path: Optional[str],
    warnings: List[str],
) -> List[Tuple[str, str]]:
    """Legacy single-shot path (whole page, all nodes in one prompt)."""
    content: List[Dict[str, Any]] = [{"type": "text", "text": _build_prompt(nodes)}]
    if full_page_image_path:
        try:
            b64 = _image_to_base64(full_page_image_path)
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            )
        except Exception as _img_err:  # noqa: BLE001
            warnings.append(f"fallback: image unreadable ({_img_err})")
    try:
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": content}]
        )
        raw = response.choices[0].message.content or ""
    except Exception as _err:  # noqa: BLE001
        warnings.append(f"fallback: LLM call failed ({_err})")
        return []
    pairs = _parse_pairs(raw)
    if not pairs:
        warnings.append("fallback: no usable connections parsed from LLM output")
    return pairs


def _collect_pairs_chunked(
    client: Any,
    model: Optional[str],
    nodes: Sequence[Dict[str, Any]],
    job_dir: str,
    page_width: int,
    page_height: int,
    warnings: List[str],
) -> List[Tuple[str, str]]:
    """Chunked path: one structured call per 3×3 tile that holds ≥2 nodes."""
    from webapp.graph.loader import compute_tile_offsets

    tile_boxes = compute_tile_offsets(int(page_width), int(page_height), page_index=0)
    out: List[Tuple[str, str]] = []
    qualifying = 0
    for tile_name, box in tile_boxes.items():
        region = _select_nodes_in_tile(nodes, box)
        if len(region) < 2:
            continue  # no possible edge → skip the call
        qualifying += 1
        img = os.path.join(job_dir, "tmp", tile_name)
        if not os.path.exists(img):
            alt = os.path.join(job_dir, tile_name)
            if os.path.exists(alt):
                img = alt
        out.extend(
            _connections_for_region(client, model, img, region, (box[0], box[1]), warnings)
        )
    if qualifying == 0:
        warnings.append("fallback: no tile had >=2 nodes")
    return out


def run_fallback(
    nodes: Sequence[Dict[str, Any]],
    existing_edges: Sequence[Edge],
    *,
    job_dir: Optional[str] = None,
    page_width: Optional[int] = None,
    page_height: Optional[int] = None,
    full_page_image_path: Optional[str] = None,
    client: Any = None,
    model: Optional[str] = None,
    warnings: Optional[List[str]] = None,
) -> Tuple[List[Edge], bool]:
    """Ask the LLM for pipe connections and merge them as ``llm_fallback`` edges.

    When ``job_dir`` + ``page_width`` + ``page_height`` are given, runs the
    **chunked** path (one structured call per 3×3 tile with ≥2 nodes) — reliable
    on dense pages where a single whole-page prompt returns unparseable output.
    Otherwise falls back to the legacy single-shot whole-page call.

    Returns ``(merged_edges, fallback_used)``. Never raises. Duplicate (unordered)
    and unknown-id pairs are skipped.
    """
    if warnings is None:
        warnings = []

    valid_ids = {str(n.get("node_id") or n.get("id")) for n in nodes}
    existing_pairs = {frozenset((e.source, e.target)) for e in existing_edges}

    try:
        client = client or _default_client()
        if model is None:
            try:
                model = _default_model()
            except Exception:  # noqa: BLE001 — extractor import optional
                model = "google/gemini-2.5-flash"
    except Exception as _err:  # noqa: BLE001
        warnings.append(f"fallback: client init failed ({_err})")
        return list(existing_edges), False

    if job_dir is not None and page_width and page_height:
        pairs = _collect_pairs_chunked(
            client, model, nodes, job_dir, int(page_width), int(page_height), warnings
        )
    else:
        pairs = _collect_pairs_single(client, model, nodes, full_page_image_path, warnings)

    merged = list(existing_edges)
    seen = set(existing_pairs)
    added = 0
    for src, tgt in pairs:
        if src == tgt:
            continue
        if src not in valid_ids or tgt not in valid_ids:
            continue
        key = frozenset((src, tgt))
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            Edge(
                source=src,
                target=tgt,
                polyline=[],  # LLM gives no geometry
                tile="page",
                method="llm_fallback",
                confidence=0.5,
            )
        )
        added += 1

    return merged, added > 0


def _build_floating_prompt(
    floating_nodes: Sequence[Dict[str, Any]],
    all_nodes: Sequence[Dict[str, Any]],
) -> str:
    """Targeted prompt for nodes that have no detected pipe connections.

    Lists the unconnected symbols first so the model focuses on them, then
    lists all other nodes as potential connection targets.
    """
    def _fmt(n: Dict[str, Any]) -> str:
        nid = n.get("node_id") or n.get("id")
        tag = n.get("tag") or "?"
        cls = n.get("class") or "?"
        bbox = n.get("bbox")
        return f"  {nid}: {tag} / {cls} @ {bbox}"

    floating_ids = {n.get("node_id") or n.get("id") for n in floating_nodes}
    other_nodes = [n for n in all_nodes if (n.get("node_id") or n.get("id")) not in floating_ids]

    lines = [
        "You are reading a P&ID engineering drawing.",
        "",
        "The following symbols were DETECTED but have NO pipe connection found yet.",
        "Look carefully at the drawing image and find which other symbols each one",
        "is directly connected to via a pipe line.",
        "",
        "UNCONNECTED symbols (focus on these):",
    ]
    for n in floating_nodes:
        lines.append(_fmt(n))

    lines += ["", "All other symbols (potential connection targets):"]
    for n in other_nodes:
        lines.append(_fmt(n))

    lines += [
        "",
        "Return ONLY a JSON array of connected pairs using node ids, e.g.",
        '[["n_001","n_004"],["n_002","n_007"]].',
        "Only include pairs where a pipe is clearly visible between them.",
        "Do not include explanations.",
    ]
    return "\n".join(lines)


def run_floating_node_fallback(
    floating_nodes: Sequence[Dict[str, Any]],
    all_nodes: Sequence[Dict[str, Any]],
    existing_edges: Sequence["Edge"],
    *,
    full_page_image_path: Optional[str] = None,
    client: Any = None,
    model: Optional[str] = None,
    warnings: Optional[List[str]] = None,
) -> Tuple[List["Edge"], bool]:
    """Targeted LLM pass for nodes that have zero connections after CV tracing.

    Unlike the density-gate fallback (run_fallback), this always runs when
    there are floating nodes — it asks the model specifically about those
    unconnected symbols rather than the whole graph.
    """
    if warnings is None:
        warnings = []
    if not floating_nodes:
        return list(existing_edges), False

    valid_ids = {str(n.get("node_id") or n.get("id")) for n in all_nodes}
    existing_pairs = {frozenset((e.source, e.target)) for e in existing_edges}

    try:
        client = client or _default_client()
        if model is None:
            try:
                model = _default_model()
            except Exception:  # noqa: BLE001
                model = "google/gemini-2.5-flash"

        prompt_text = _build_floating_prompt(floating_nodes, all_nodes)
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt_text}]
        if full_page_image_path:
            try:
                b64 = _image_to_base64(full_page_image_path)
                content.append(
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                )
            except Exception as _img_err:  # noqa: BLE001
                warnings.append(f"floating_fallback: image unreadable ({_img_err})")

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
        )
        raw = response.choices[0].message.content or ""
    except Exception as _err:  # noqa: BLE001
        warnings.append(f"floating_fallback: LLM call failed ({_err})")
        return list(existing_edges), False

    pairs = _parse_pairs(raw)
    if not pairs:
        warnings.append("floating_fallback: no usable connections from LLM")
        return list(existing_edges), False

    merged = list(existing_edges)
    added = 0
    for src, tgt in pairs:
        if src == tgt:
            continue
        if src not in valid_ids or tgt not in valid_ids:
            continue
        key = frozenset((src, tgt))
        if key in existing_pairs:
            continue
        existing_pairs.add(key)
        merged.append(
            Edge(
                source=src,
                target=tgt,
                polyline=[],
                tile="page",
                method="llm_fallback",
                confidence=0.5,
            )
        )
        added += 1

    warnings.append(
        f"floating_fallback: connected {added} of {len(floating_nodes)} unlinked nodes"
    )
    return merged, added > 0


