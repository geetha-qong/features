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

from typing import Any, Dict, List, Optional, Sequence, Tuple

from webapp.graph.resolver import Edge


FALLBACK_GATE_RATIO = 0.3


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
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group())
    except (json.JSONDecodeError, ValueError):
        return []
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


def run_fallback(
    nodes: Sequence[Dict[str, Any]],
    existing_edges: Sequence[Edge],
    *,
    full_page_image_path: Optional[str] = None,
    client: Any = None,
    model: Optional[str] = None,
    warnings: Optional[List[str]] = None,
) -> Tuple[List[Edge], bool]:
    """Query the LLM for connections and merge them as ``llm_fallback`` edges.

    Returns ``(merged_edges, fallback_used)``. ``merged_edges`` is the existing
    edges plus any new LLM edges. ``fallback_used`` is True if the LLM produced
    at least one new edge. Never raises — malformed output appends a warning.

    Duplicate edges (same unordered node pair already present) are skipped.
    Pairs referencing unknown node ids are skipped.
    """
    if warnings is None:
        warnings = []

    valid_ids = {str(n.get("node_id") or n.get("id")) for n in nodes}
    existing_pairs = {
        frozenset((e.source, e.target)) for e in existing_edges
    }

    try:
        client = client or _default_client()
        if model is None:
            try:
                model = _default_model()
            except Exception:  # noqa: BLE001 — extractor import optional
                model = "google/gemini-2.5-flash"

        content: List[Dict[str, Any]] = [
            {"type": "text", "text": _build_prompt(nodes)}
        ]
        if full_page_image_path:
            try:
                b64 = _image_to_base64(full_page_image_path)
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    }
                )
            except Exception as _img_err:  # noqa: BLE001
                warnings.append(f"fallback: image unreadable ({_img_err})")

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
        )
        raw = response.choices[0].message.content or ""
    except Exception as _err:  # noqa: BLE001 — never crash the pipeline
        warnings.append(f"fallback: LLM call failed ({_err})")
        return list(existing_edges), False

    pairs = _parse_pairs(raw)
    if not pairs:
        warnings.append("fallback: no usable connections parsed from LLM output")
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
                polyline=[],  # LLM gives no geometry
                tile="page",
                method="llm_fallback",
                confidence=0.5,
            )
        )
        added += 1

    return merged, added > 0
