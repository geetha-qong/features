"""Pass 4.5 — orientation-aware line-number coverage pass.

Gated by ``LINE_ORIENT_OCR=1``. When the flag is unset this module is never
imported by the pipeline, so behaviour/API-usage/output are byte-identical to
today.

Design contract (docs/superpowers/specs/2026-06-26-orientation-aware-line-ocr-design.md):

  * Gemini Vision (via ``extractor.get_client()``) is the ONLY OCR engine. The
    OpenCV tracer and candidate-region logic choose better crops + orientations;
    they NEVER recognise text.
  * Additive only — runs after Pass 4 and touches only pipelines/line numbers
    that Pass 4 left unresolved or produced incomplete. It repairs/adds, never
    deletes Pass-4 data.
  * Full-resolution page ROIs (``tmp/page_0_full.png``) — no re-tiling.
  * Hard cap on Vision calls (``LINE_ORIENT_OCR_MAX_CALLS``, default 40).
  * Writes ``line_coverage.json`` for QA only (not exposed by any prod API).

NEVER import ``detector.py`` here — production rule (CLAUDE.md).
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Vision API helpers + model — same engine as the rest of the extractor.
from extractor import (
    DEFAULT_MODEL,
    extract_json_object,
    get_client,
    image_to_base64,
)

# ── Tunables (env-overridable) ──────────────────────────────────────────────
_MAX_CALLS = int(os.environ.get("LINE_ORIENT_OCR_MAX_CALLS", "40"))
# ROI padding (page px) around a pipe polyline / entity bbox before rotation.
_ROI_PAD_PX = int(os.environ.get("LINE_ORIENT_OCR_ROI_PAD", "60"))
# A traced pipe is "covered" if an existing line-number entity sits within this
# many page px of the polyline — then it is NOT re-queried (cost protection).
_COVERED_DIST_PX = int(os.environ.get("LINE_ORIENT_OCR_COVERED_DIST", "180"))
# Edge-band thickness (fraction of page dim) scanned for continuation / off-page
# connector tables along the right and bottom margins.
_EDGE_BAND_FRAC = 0.16

# ── Engineering-aware validation (req 6) ────────────────────────────────────
# First dash-segment must be a numeric pipe size: 300, 3", 1/2", 20"
_LINE_PREFIX_RE = re.compile(r'^\d+(?:/\d+)?"?$')
# Each segment: uppercase alnum plus / " . (covers sizes, fluid codes, classes).
_SEGMENT_RE = re.compile(r'^[A-Z0-9/".]+$')


def _normalize_line(s: str) -> str:
    """Canonical comparison form: upper, trimmed, collapsed internal spaces."""
    return re.sub(r"\s+", "", (s or "").strip().upper())


def _engineering_line_valid(s: Optional[str]) -> bool:
    """True only for a COMPLETE engineering line number.

    Accepts: 300-WWE-XXXX-AS1LC, 50-ABL-XXXX-AS2LC, 3"-P-62151007-BGA.
    Rejects truncated forms: 4"-X, 20"-W, BGA, XXXX-AS1LC.
    """
    if not s or not isinstance(s, str):
        return False
    val = _normalize_line(s)
    parts = val.split("-")
    if len(parts) < 3:                       # size-service-…-class minimum
        return False
    if not _LINE_PREFIX_RE.match(parts[0]):  # must start with a numeric size
        return False
    for p in parts:
        if not p or not _SEGMENT_RE.match(p):
            return False
    # Reject a trailing stray single letter (e.g. ...-W, ...-X) that signals a
    # truncated suffix — a real class/insulation tail is >= 2 chars OR numeric.
    last = parts[-1]
    if len(last) == 1 and last.isalpha():
        return False
    return True


def _completeness(s: str) -> Tuple[int, int]:
    """Sort key for "most complete" — (segment count, char length)."""
    norm = _normalize_line(s)
    return (len(norm.split("-")), len(norm))


# ── Multi-signal confidence (req: don't trust a regex alone) ────────────────
# A recovered line is only "confirmed" when corroborated by several signals;
# otherwise it is kept but flagged "needs_review".
_CONFIRM_THRESHOLD = float(os.environ.get("LINE_ORIENT_OCR_CONFIRM", "0.60"))


def _stem(norm: str) -> str:
    """All-but-last segment — groups SP5LC vs SP5XX style variants together."""
    parts = norm.split("-")
    return "-".join(parts[:-1]) if len(parts) > 1 else norm


def _build_project_profile(resolved_lines: List[str]) -> Dict[str, Any]:
    """Project-wide numbering convention learned from CONFIRMED canonical lines:
    the vocab of sizes / fluid codes / piping classes and the typical segment
    count. Used to judge whether a recovered candidate "looks like" this
    project's lines (so SP5LC, seen elsewhere, beats a one-off SP5XX)."""
    from collections import Counter
    sizes: set = set()
    fluids: set = set()
    classes: set = set()
    counts: Counter = Counter()
    for ln in resolved_lines:
        p = _normalize_line(ln).split("-")
        if len(p) < 3:
            continue
        sizes.add(p[0])
        fluids.add(p[1])
        classes.add(p[-1])
        counts[len(p)] += 1
    return {
        "sizes": sizes, "fluids": fluids, "classes": classes,
        "typical_count": counts.most_common(1)[0][0] if counts else 4,
    }


def _score_candidate(norm: str, info: Dict[str, Any],
                     profile: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    """Combine signals into a confidence in [0,1] plus an explanation dict.

    Signals: cross-ROI occurrence, source diversity (pipe / connector /
    continuation / truncated), orientation agreement (same value read at
    multiple rotations), and conformance to the project's size/fluid/class
    vocab + typical segment count.
    """
    parts = norm.split("-")
    occ = len(info["targets"])          # distinct ROIs that produced it
    src = len(info["sources"])          # distinct source types
    rots = len(info["rotations"])       # distinct orientations agreeing
    score = 0.0
    sig: Dict[str, Any] = {"occurrences": occ, "sources": sorted(info["sources"]),
                           "orientations": sorted(info["rotations"])}
    if occ >= 2:
        score += 0.30
    if src >= 2:
        score += 0.15
    if rots >= 2:
        score += 0.20
    if len(parts) >= 3:
        if parts[-1] in profile["classes"]:
            score += 0.15; sig["class_match"] = True
        if parts[1] in profile["fluids"]:
            score += 0.10; sig["fluid_match"] = True
        if parts[0] in profile["sizes"]:
            score += 0.10; sig["size_match"] = True
    if len(parts) == profile.get("typical_count", 4):
        score += 0.05; sig["seg_count_ok"] = True
    return min(1.0, score), sig


# ── Geometry helpers ────────────────────────────────────────────────────────
def _bbox_center(bbox: Any) -> Optional[Tuple[float, float]]:
    if not bbox or len(bbox) < 4:
        return None
    x1, y1, x2, y2 = bbox[:4]
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _point_to_polyline_dist(px: float, py: float,
                            poly: List[Tuple[int, int]]) -> float:
    """Min distance from a point to a polyline (page px)."""
    best = float("inf")
    for i in range(len(poly) - 1):
        ax, ay = poly[i]
        bx, by = poly[i + 1]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        if seg2 == 0:
            d = math.hypot(px - ax, py - ay)
        else:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
            cx, cy = ax + t * dx, ay + t * dy
            d = math.hypot(px - cx, py - cy)
        if d < best:
            best = d
    return best


def _polyline_angle_deg(poly: List[Tuple[int, int]]) -> float:
    """Dominant orientation of a polyline in degrees (0 = horizontal)."""
    if len(poly) < 2:
        return 0.0
    x0, y0 = poly[0]
    x1, y1 = poly[-1]
    return math.degrees(math.atan2(y1 - y0, x1 - x0))


def _polyline_bbox(poly: List[Tuple[int, int]]) -> Tuple[int, int, int, int]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def _orientation_angles(est_angle_deg: float) -> List[int]:
    """Rotation order: original → estimated pipe orientation → 90 → 270 → 180.

    Returns the rotation (CCW degrees) to apply to the crop to bring text
    horizontal. Deduped, preserving order (req 5).
    """
    # To make text along a pipe at angle `a` horizontal, rotate by -a. Snap to
    # the nearest cardinal for a clean rotation; vertical pipes (±90) dominate.
    snapped = int(round(est_angle_deg / 90.0)) * 90
    est_rot = (-snapped) % 360
    order = [0, est_rot, 90, 270, 180]
    seen: set = set()
    out: List[int] = []
    for a in order:
        a %= 360
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


# ── Vision OCR (single line number per ROI) ─────────────────────────────────
_ROI_SYSTEM = (
    "You read a single engineering pipe LINE NUMBER from a small crop of a "
    "P&ID drawing. The text may be horizontal. Return ONLY the complete line "
    "number identifier exactly as printed (e.g. 300-WWE-1234-AS1LC, "
    '3"-P-62151007-BGA). Do not truncate, reverse, or invent characters. If no '
    "complete line number is clearly legible, return null. Reply as JSON: "
    '{"line_number": "<value or null>"}'
)


def _vision_read_line(client: Any, model: str, crop_png_path: str) -> Optional[str]:
    """One Vision call on a (already rotated-horizontal) crop. Returns the
    raw string the model read, or None."""
    try:
        img_b64 = image_to_base64(crop_png_path)
        resp = client.chat.completions.create(
            model=model,
            max_tokens=64,
            messages=[
                {"role": "system", "content": _ROI_SYSTEM},
                {"role": "user", "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": "Read the line number in this crop."},
                ]},
            ],
        )
        raw = resp.choices[0].message.content or ""
        obj = extract_json_object(raw)
        if isinstance(obj, dict):
            val = obj.get("line_number")
            if val and str(val).strip().lower() != "null":
                return str(val).strip()
    except Exception as exc:  # noqa: BLE001
        print(f"    Pass 4.5 vision error: {exc}")
    return None


# ── ROI candidate generation ────────────────────────────────────────────────
class _Candidate:
    __slots__ = ("pid", "source", "bbox", "angle", "traced")

    def __init__(self, pid: str, source: str,
                 bbox: Tuple[int, int, int, int],
                 angle: float, traced: bool) -> None:
        self.pid = pid
        self.source = source
        self.bbox = bbox
        self.angle = angle
        self.traced = traced


def _build_candidates(
    segments: List[Any],
    resolved_centers: List[Tuple[float, float]],
    invalid_entities: List[Dict[str, Any]],
    page_w: int,
    page_h: int,
) -> List[_Candidate]:
    """Unresolved ROIs from three sources (req 2, 3, 9).

    Ordered HIGH-VALUE FIRST so a tight ``LINE_ORIENT_OCR_MAX_CALLS`` budget is
    never starved by tracer noise:
      1. truncated-entity repairs (we know a real line is there, just garbled),
      2. edge-band continuation / off-page connector tables (req 3 — these
         carry line-number lists and the tracer alone misses them),
      3. traced pipes with no nearby line, longest-first (longer pipes are far
         likelier to carry a printed line label than short skeleton fragments).
    """
    cands: List[_Candidate] = []

    # Source 1 (highest value): entities whose existing line failed validation.
    for ent in invalid_entities:
        c = _bbox_center(ent.get("bbox"))
        if not c:
            continue
        x, y = c
        bbox = (int(x - 140), int(y - 70), int(x + 140), int(y + 70))
        cands.append(_Candidate(
            pid=f"trunc-{ent.get('entity_id', '?')[:8]}", source="truncated",
            bbox=bbox, angle=0.0, traced=False,
        ))

    # Source 2: edge-band tables (continuation / off-page connector tables).
    band_w = int(page_w * _EDGE_BAND_FRAC)
    band_h = int(page_h * _EDGE_BAND_FRAC)
    cands.append(_Candidate(
        pid="edge-right", source="off_page_connector",
        bbox=(page_w - band_w, 0, page_w, page_h), angle=0.0, traced=False,
    ))
    cands.append(_Candidate(
        pid="edge-bottom", source="continuation_table",
        bbox=(0, page_h - band_h, page_w, page_h), angle=0.0, traced=False,
    ))

    # Source 3: traced pipes with NO resolved line number nearby, longest-first.
    pipe_cands: List[Tuple[float, _Candidate]] = []
    for idx, seg in enumerate(segments):
        poly = list(seg.polyline)
        if len(poly) < 2:
            continue
        covered = False
        for (cx, cy) in resolved_centers:
            if _point_to_polyline_dist(cx, cy, poly) <= _COVERED_DIST_PX:
                covered = True
                break
        if covered:
            continue
        x1, y1, x2, y2 = _polyline_bbox(poly)
        length = math.hypot(x2 - x1, y2 - y1)
        pipe_cands.append((length, _Candidate(
            pid=f"pipe-{idx}", source="pipe",
            bbox=(x1, y1, x2, y2),
            angle=_polyline_angle_deg(poly), traced=True,
        )))
    pipe_cands.sort(key=lambda t: t[0], reverse=True)
    cands.extend(c for _, c in pipe_cands)
    return cands


def _crop_and_rotate(page_img: Any, bbox: Tuple[int, int, int, int],
                     rot_deg: int, tmp_dir: Path, name: str) -> Optional[str]:
    """Crop the ROI from the full page (+pad), rotate CCW by rot_deg so target
    text becomes horizontal, save PNG, return path. Uses PIL only (no OCR)."""
    try:
        from PIL import Image
        import PIL.Image
        PIL.Image.MAX_IMAGE_PIXELS = None
        w, h = page_img.size
        x1, y1, x2, y2 = bbox
        x1 = max(0, int(x1) - _ROI_PAD_PX)
        y1 = max(0, int(y1) - _ROI_PAD_PX)
        x2 = min(w, int(x2) + _ROI_PAD_PX)
        y2 = min(h, int(y2) + _ROI_PAD_PX)
        if x2 - x1 < 8 or y2 - y1 < 8:
            return None
        crop = page_img.crop((x1, y1, x2, y2))
        if rot_deg:
            crop = crop.rotate(rot_deg, expand=True, fillcolor="white")
        out = tmp_dir / f"p45_{name}_r{rot_deg}.png"
        crop.save(out)
        return str(out)
    except Exception as exc:  # noqa: BLE001
        print(f"    Pass 4.5 crop error ({name}): {exc}")
        return None


# ── Tracer setup (geometry only — req 2) ────────────────────────────────────
def _trace_segments(page_path: Path, canonical: Dict[str, Any]) -> List[Any]:
    """Run the OpenCV tracer on the full page (read-only). bbox interiors masked
    so symbol glyphs aren't traced as pipes."""
    try:
        import numpy as np
        import cv2
        from webapp.graph.tracer import OpenCVLineTracer

        gray = cv2.imread(str(page_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return []
        h, w = gray.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        for ent in canonical.get("entities", []):
            bb = ent.get("bbox")
            if bb and len(bb) >= 4:
                x1, y1, x2, y2 = [int(v) for v in bb[:4]]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                if x2 > x1 and y2 > y1:
                    mask[y1:y2, x1:x2] = 1
        return OpenCVLineTracer().trace(gray, bbox_mask=mask)
    except Exception as exc:  # noqa: BLE001
        print(f"  Pass 4.5: tracer unavailable ({exc}) — coverage via edge/trunc only")
        return []


# ── Public entry point ──────────────────────────────────────────────────────
def apply_orientation_pass(job_dir: str, model: str = DEFAULT_MODEL) -> dict:
    """Orientation-aware coverage pass. Additive; repairs/adds line numbers,
    never deletes Pass-4 data. Returns a stats dict."""
    job_path = Path(job_dir)
    canon_path = job_path / "canonical.json"
    line_data_path = job_path / "line_list_data.json"
    page_path = job_path / "tmp" / "page_0_full.png"
    if not page_path.exists():
        page_path = job_path / "page_0_full.png"

    if not canon_path.exists():
        print("  Pass 4.5: canonical.json not found — skipping.")
        return {"skipped": True, "reason": "no canonical.json"}
    if not page_path.exists():
        print("  Pass 4.5: full-page image not found — skipping.")
        return {"skipped": True, "reason": "no page image"}

    with open(canon_path) as f:
        canonical = json.load(f)

    line_data: Dict[str, Any] = {}
    if line_data_path.exists():
        try:
            with open(line_data_path) as f:
                line_data = json.load(f)
        except Exception:
            line_data = {}

    # Inventory existing line numbers from canonical entities (req 2, 6, 9).
    resolved_norms: set = set()
    resolved_lines: List[str] = []          # raw, for the project numbering profile
    resolved_centers: List[Tuple[float, float]] = []
    invalid_entities: List[Dict[str, Any]] = []
    for ent in canonical.get("entities", []):
        line_val = ent.get("fields", {}).get("line")
        if not (line_val and isinstance(line_val, str) and "-" in line_val):
            continue
        c = _bbox_center(ent.get("bbox"))
        if _engineering_line_valid(line_val):
            resolved_norms.add(_normalize_line(line_val))
            resolved_lines.append(line_val)
            if c:
                resolved_centers.append(c)
        else:
            invalid_entities.append(ent)
    # Confirmed Pass-4 line_list_data.json keys also inform the project profile.
    for k in line_data:
        if isinstance(k, str) and _engineering_line_valid(k):
            resolved_lines.append(k)

    # Load full page once.
    try:
        from PIL import Image
        import PIL.Image
        PIL.Image.MAX_IMAGE_PIXELS = None
        page_img = Image.open(page_path).convert("RGB")
        page_w, page_h = page_img.size
    except Exception as exc:  # noqa: BLE001
        print(f"  Pass 4.5: cannot open page image ({exc}) — skipping.")
        return {"skipped": True, "reason": "page open failed"}

    segments = _trace_segments(page_path, canonical)
    candidates = _build_candidates(
        segments, resolved_centers, invalid_entities, page_w, page_h
    )

    tmp_dir = job_path / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    client = get_client()
    profile = _build_project_profile(resolved_lines)

    coverage: List[Dict[str, Any]] = []
    # Global evidence accumulator across ALL ROIs/orientations:
    #   norm → {raw(best), targets:set(pid), sources:set, rotations:set}
    evidence: Dict[str, Dict[str, Any]] = {}
    calls = 0

    def _record(norm: str, raw: str, pid: str, source: str, rot: int) -> None:
        e = evidence.setdefault(norm, {
            "raw": raw, "targets": set(), "sources": set(), "rotations": set(),
        })
        if _completeness(raw) > _completeness(e["raw"]):
            e["raw"] = raw
        e["targets"].add(pid)
        e["sources"].add(source)
        e["rotations"].add(rot)

    for cand in candidates:
        if calls >= _MAX_CALLS:
            print(f"  Pass 4.5: hit max-calls cap ({_MAX_CALLS}) — stopping.")
            break
        # Sweep ALL orientations (no early break) so orientation-agreement is a
        # usable signal (req: validate via OCR consistency across 0/90/270/180).
        readings: List[str] = []
        for rot in _orientation_angles(cand.angle):
            if calls >= _MAX_CALLS:
                break
            crop_path = _crop_and_rotate(page_img, cand.bbox, rot, tmp_dir, cand.pid)
            if not crop_path:
                continue
            calls += 1
            raw = _vision_read_line(client, model, crop_path)
            try:
                os.remove(crop_path)
            except OSError:
                pass
            if raw and _engineering_line_valid(raw):
                readings.append(raw)
                _record(_normalize_line(raw), raw, cand.pid, cand.source, rot)

        coverage.append({
            "pipeline_id": cand.pid,
            "traced": cand.traced,
            "source": cand.source,
            "readings": readings,                       # all valid orientation reads
            "line_number_found": readings[0] if readings else None,
        })

    # ── Confidence scoring + conflict resolution (req: multi-signal) ─────────
    scored: Dict[str, Dict[str, Any]] = {}
    for norm, info in evidence.items():
        score, sig = _score_candidate(norm, info, profile)
        scored[norm] = {"raw": info["raw"], "score": score, "signals": sig}

    # Resolve SP5LC-vs-SP5XX style conflicts: within a stem group prefer a
    # candidate whose piping class matches the project vocab, then by score.
    from collections import defaultdict
    groups: Dict[str, List[str]] = defaultdict(list)
    for norm in scored:
        groups[_stem(norm)].append(norm)
    winners: Dict[str, Dict[str, Any]] = {}
    for stem, members in groups.items():
        def _rank(n: str):
            cls_ok = n.split("-")[-1] in profile["classes"]
            return (1 if cls_ok else 0, scored[n]["score"])
        best = max(members, key=_rank)
        winners[best] = scored[best]
        if len(members) > 1:
            # losing siblings demote the winner's certainty unless it clearly wins
            others = [m for m in members if m != best]
            top_other = max(scored[o]["score"] for o in others)
            if scored[best]["score"] - top_other < 0.20:
                winners[best]["ambiguous_with"] = [scored[o]["raw"] for o in others]

    # ── Emit recovered lines (additive — req 7). Confirmed vs needs_review. ──
    existing_keys = {_normalize_line(k): k for k in line_data}
    added = 0
    confirmed = 0
    needs_review = 0
    for norm, w in winners.items():
        if norm in resolved_norms or norm in existing_keys:
            continue  # already a known line — merge, never duplicate
        status = "confirmed" if (w["score"] >= _CONFIRM_THRESHOLD
                                 and "ambiguous_with" not in w) else "needs_review"
        line_data[w["raw"]] = {
            "fluid": None, "phase": None, "op_pressure": None, "op_temp": None,
            "design_pressure": None, "design_temp": None, "pipe_size": None,
            "schedule": None, "piping_class": None, "insulation": None,
            "material": None,
            "_source": w["signals"].get("sources") or ["orientation"],
            "_confidence": round(w["score"], 2),
            "_status": status,
            "_signals": w["signals"],
        }
        if "ambiguous_with" in w:
            line_data[w["raw"]]["_ambiguous_with"] = w["ambiguous_with"]
        added += 1
        if status == "confirmed":
            confirmed += 1
        else:
            needs_review += 1

    with open(line_data_path, "w") as f:
        json.dump(line_data, f, indent=2)

    # Annotate coverage rows with the chosen status/confidence for QA.
    for row in coverage:
        rn = _normalize_line(row["line_number_found"]) if row["line_number_found"] else ""
        w = winners.get(rn)
        if rn in resolved_norms:
            row["validation_status"] = "corroborates_existing"
            row["confidence"] = round(scored.get(rn, {}).get("score", 1.0), 2)
        elif w:
            row["validation_status"] = ("confirmed"
                if (w["score"] >= _CONFIRM_THRESHOLD and "ambiguous_with" not in w)
                else "needs_review")
            row["confidence"] = round(w["score"], 2)
        else:
            row["validation_status"] = "unresolved"
            row["confidence"] = 0.0

    cov_path = job_path / "line_coverage.json"
    with open(cov_path, "w") as f:
        json.dump({
            "job_dir": str(job_dir),
            "segments_traced": len(segments),
            "candidates": len(candidates),
            "vision_calls": calls,
            "new_line_numbers": added,
            "confirmed": confirmed,
            "needs_review": needs_review,
            "confirm_threshold": _CONFIRM_THRESHOLD,
            "pipelines": coverage,
        }, f, indent=2)

    stats = {
        "skipped": False,
        "segments_traced": len(segments),
        "candidates": len(candidates),
        "vision_calls": calls,
        "new_line_numbers": added,
        "confirmed": confirmed,
        "needs_review": needs_review,
        "invalid_repaired_targets": len(invalid_entities),
    }
    print(f"  Pass 4.5 complete: traced={len(segments)} candidates={len(candidates)} "
          f"calls={calls} new={added} (confirmed={confirmed} needs_review={needs_review}) "
          f"cap={_MAX_CALLS}")
    print(f"  Pass 4.5: wrote {cov_path}")
    return stats


if __name__ == "__main__":  # pragma: no cover — manual QA on one job
    import sys
    jd = sys.argv[1] if len(sys.argv) > 1 else "."
    print(json.dumps(apply_orientation_pass(jd), indent=2))
