"""
Stage 2 (offline): YOLO ONNX + PaddleOCR valve detection.
Drop-in replacement for extractor.py — same public API:
  extract_all_tiles(tiles, ...) -> list of valve dicts
  extract_drawing_number(pdf_path, tmp_dir) -> str
"""
import json
import re
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Tuple

import numpy as np
from PIL import Image

# ── Model / inference config ───────────────────────────────────────────────────
MODEL_PATH = str(Path(__file__).parent / "models/best.onnx")
IMGSZ = 1280
CONF_THRESH = 0.25
IOU_THRESH = 0.45

CLASS_NAMES = [
    "actuator_motor",      # 0
    "actuator_pneu",       # 1
    "actuator_sol",        # 2
    "valve_bf",            # 3
    "valve_bv",            # 4
    "valve_ck",            # 5
    "valve_cv",            # 6
    "valve_db",            # 7
    "valve_gen",           # 8
    "valve_gl",            # 9
    "inst_field",          # 10
    "DCS",                 # 11
    "PLC",                 # 12
    "interlock",           # 13
    "interlock-R",         # 14
    "inst_field-R",        # 15
    "Pump_Dwg_Pump",       # 16
    "Motor",               # 17
    "valve_3way_relief",   # 18
    "valve_ncbv",          # 19
    "valve_relief_safety", # 20
    "valve_pnuectrl",      # 21
]

# YOLO class → valve type code (None = infer from nearby OCR text)
CLASS_TO_TYPE: Dict[str, Optional[str]] = {
    "valve_bf": "BF", "valve_bv": "BV", "valve_ck": "CK",
    "valve_cv": "CV", "valve_db": "DB", "valve_gen": None, "valve_gl": "GL",
    "valve_3way_relief": "SV", "valve_ncbv": "BV",
    "valve_relief_safety": "SV", "valve_pnuectrl": "PV",
}
ACTUATOR_CLASSES = {"actuator_motor": "M", "actuator_pneu": "P", "actuator_sol": "SL"}
VALVE_CLASSES = set(CLASS_TO_TYPE.keys())

# Instrument bubble classes → LOCATION value (per Ebara/Ronesans legend)
INSTRUMENT_CLASSES = {"inst_field", "DCS", "PLC", "interlock", "interlock-R", "inst_field-R"}
LOCATION_FROM_YOLO_CLASS: Dict[str, str] = {
    "inst_field":   "FIELD",
    "inst_field-R": "FIELD",
    "DCS":          "DCS",
    "PLC":          "PLC",
    "interlock":    "ESD",
    "interlock-R":  "ESD",
}

# Known valve type codes — used to filter OCR tags from instrument tags (FIT, LIT, XZT, etc.)
VALVE_TYPE_CODES = {
    "BF", "BV", "VB", "DB", "CK", "GL", "VM", "VG", "NV", "SV",
    "PV", "UZV", "FV", "CV", "FO", "FC", "GV", "TV",
}

# Text patterns
TAG_RE = re.compile(r'(?<!\d)(\d{2})-([A-Z]{2,4})-(\d{6})(?!\d)')
LINE_RE = re.compile(
    r'(\d{1,3})["\u201d\u2019\']?\s*[-\u2013]\s*([A-Z]{1,3})\s*[-\u2013]\s*(\d{5,8})\s*[-\u2013]\s*([A-Z0-9]{2,6})'
)
GENERIC_TYPE_RE = re.compile(r'\b(VM|VG|NV|SV|UZV|PV|FV)\b')
DRAWING_NO_RE = re.compile(r'[A-Z]{2,4}-\d{2}-\d{1,2}-\d{2}-\d{4}-\d{3}')

_session = None
_ocr = None


def _get_session():
    global _session
    if _session is None:
        import onnxruntime as ort
        _session = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
    return _session


def _get_ocr():
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(
            lang="en",
            use_textline_orientation=False,
            ocr_version="PP-OCRv4",      # lighter than PP-OCRv5 server models
            cpu_threads=4,               # cap CPU to avoid thermal shutdown
        )
    return _ocr


# ── YOLO inference ─────────────────────────────────────────────────────────────

def _preprocess(img: Image.Image) -> Tuple[np.ndarray, float, int, int]:
    """Letterbox resize to IMGSZ, normalise to [0,1], return (BCHW, scale, pad_x, pad_y)."""
    orig_w, orig_h = img.size
    scale = min(IMGSZ / orig_w, IMGSZ / orig_h)
    new_w, new_h = int(orig_w * scale), int(orig_h * scale)
    resized = img.resize((new_w, new_h), Image.BILINEAR)
    canvas = Image.new("RGB", (IMGSZ, IMGSZ), (114, 114, 114))
    pad_x, pad_y = (IMGSZ - new_w) // 2, (IMGSZ - new_h) // 2
    canvas.paste(resized, (pad_x, pad_y))
    arr = np.array(canvas, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)[np.newaxis]  # HWC → BCHW
    return arr, scale, pad_x, pad_y


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thresh: float) -> List[int]:
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        order = order[1:][iou <= iou_thresh]
    return keep


def _decode(output: np.ndarray, scale: float, pad_x: int, pad_y: int,
            orig_w: int, orig_h: int) -> List[Dict]:
    """YOLOv8 output [1,14,33600] → list of detection dicts in original image coords."""
    preds = output[0].T  # (33600, 14): cols 0-3 = xywh, 4-13 = class scores
    class_scores = preds[:, 4:]
    conf = class_scores.max(axis=1)
    class_ids = class_scores.argmax(axis=1)
    mask = conf >= CONF_THRESH
    preds, conf, class_ids = preds[mask], conf[mask], class_ids[mask]
    if len(conf) == 0:
        return []

    cx, cy, w, h = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
    x1 = np.clip((cx - w / 2 - pad_x) / scale, 0, orig_w)
    y1 = np.clip((cy - h / 2 - pad_y) / scale, 0, orig_h)
    x2 = np.clip((cx + w / 2 - pad_x) / scale, 0, orig_w)
    y2 = np.clip((cy + h / 2 - pad_y) / scale, 0, orig_h)

    detections = []
    for cls_id in np.unique(class_ids):
        m = class_ids == cls_id
        bboxes = np.stack([x1[m], y1[m], x2[m], y2[m]], axis=1)
        scores = conf[m]
        for idx in _nms(bboxes, scores, IOU_THRESH):
            bx1, by1, bx2, by2 = bboxes[idx]
            detections.append({
                "class_name": CLASS_NAMES[cls_id],
                "conf": float(scores[idx]),
                "x1": float(bx1), "y1": float(by1),
                "x2": float(bx2), "y2": float(by2),
                "cx": float((bx1 + bx2) / 2),
                "cy": float((by1 + by2) / 2),
            })
    return detections


# Common OCR substitutions on P&ID drawings
_OCR_SUBS = [
    (re.compile(r'\bD8B\b'), 'DB'),
    (re.compile(r'\b8V\b'),  'BV'),
    (re.compile(r'\b8F\b'),  'BF'),
    (re.compile(r'\bCl\b'),  'CK'),
]

def _ocr_correct(text: str) -> str:
    for pattern, replacement in _OCR_SUBS:
        text = pattern.sub(replacement, text)
    return text


# ── OCR ────────────────────────────────────────────────────────────────────────

def _run_ocr(img_path: str) -> List[Dict]:
    """PaddleOCR v3 on an image file. Returns [{text, x1, y1, x2, y2, cx, cy}]."""
    try:
        result = _get_ocr().predict(img_path)
    except Exception as e:
        print(f"  OCR error: {e}")
        return []
    texts = []
    if not result or not result[0]:
        return texts
    page = result[0]
    rec_texts = page.get("rec_texts", [])
    rec_scores = page.get("rec_scores", [])
    dt_polys = page.get("dt_polys", [])  # list of np.ndarray shape (N,2)
    for i, text in enumerate(rec_texts):
        score = rec_scores[i] if i < len(rec_scores) else 1.0
        if score < 0.5:
            continue
        if i < len(dt_polys):
            pts = dt_polys[i]
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
        else:
            continue
        cleaned = _ocr_correct(text.strip())
        texts.append({
            "text": cleaned,
            "x1": min(xs), "y1": min(ys),
            "x2": max(xs), "y2": max(ys),
            "cx": sum(xs) / len(xs),
            "cy": sum(ys) / len(ys),
        })
    return texts


# ── Text association ───────────────────────────────────────────────────────────

def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _associate_text(valve: Dict, ocr_texts: List[Dict],
                    radius: float = 500) -> Tuple[Optional[str], Optional[str]]:
    """Find nearest valve_tag and line_number strings within radius pixels."""
    vx, vy = valve["cx"], valve["cy"]
    nearby = sorted(
        [t for t in ocr_texts if _dist(vx, vy, t["cx"], t["cy"]) <= radius],
        key=lambda t: _dist(vx, vy, t["cx"], t["cy"]),
    )
    combined = " ".join(t["text"] for t in nearby[:20]).upper()
    combined_ns = combined.replace(" ", "")  # no-space: catches OCR-fragmented tags

    valve_tag = None
    line_number = None

    for txt in (combined, combined_ns):
        for m in TAG_RE.finditer(txt):
            if m.group(2) in VALVE_TYPE_CODES:
                valve_tag = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                break
        if valve_tag:
            break

    m = LINE_RE.search(combined)
    if m:
        line_number = f'{m.group(1)}"-{m.group(2)}-{m.group(3)}-{m.group(4)}'

    return valve_tag, line_number


def _targeted_crop_ocr(tile_path: str, cx: float, cy: float,
                       tile_x0: int, tile_y0: int,
                       crop_size: int = 400) -> List[Dict]:
    """
    Extract a crop from the full-page image around a YOLO detection and run OCR.
    Returns OCR results with coordinates relative to the tile origin.
    """
    tile_dir = Path(tile_path).parent
    full_png = tile_dir / "page_0_full.png"
    if not full_png.exists():
        return []
    try:
        img = Image.open(str(full_png))
        fx = tile_x0 + cx
        fy = tile_y0 + cy
        x0 = max(0, int(fx - crop_size / 2))
        y0 = max(0, int(fy - crop_size / 2))
        x1 = min(img.width, int(fx + crop_size / 2))
        y1 = min(img.height, int(fy + crop_size / 2))
        crop = img.crop((x0, y0, x1, y1))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            crop.save(f.name)
            crop_texts = _run_ocr(f.name)
        # Shift coordinates into tile space
        dx, dy = x0 - tile_x0, y0 - tile_y0
        for t in crop_texts:
            for key in ("x1", "x2", "cx"):
                t[key] += dx
            for key in ("y1", "y2", "cy"):
                t[key] += dy
        return crop_texts
    except Exception:
        return []


def _extract_tags_from_tile(ocr_texts: List[Dict]) -> List[Tuple[str, float, float]]:
    """
    Find all valve tags from OCR regions, handling fragmented tokens.
    Clusters tokens into approximate text rows, then tries consecutive
    groups of 1-4 tokens to recover tags split across tokens.
    Returns [(tag, cx, cy), ...] deduplicated.
    """
    if not ocr_texts:
        return []

    sorted_texts = sorted(ocr_texts, key=lambda t: (t["cy"], t["cx"]))

    # Cluster into approximate text rows (y within 40px = same row)
    rows: List[List[Dict]] = []
    current_row = [sorted_texts[0]]
    for t in sorted_texts[1:]:
        if abs(t["cy"] - current_row[-1]["cy"]) <= 40:
            current_row.append(t)
        else:
            rows.append(sorted(current_row, key=lambda x: x["cx"]))
            current_row = [t]
    if current_row:
        rows.append(sorted(current_row, key=lambda x: x["cx"]))

    found: List[Tuple[str, float, float]] = []
    seen: set = set()

    for row in rows:
        for start in range(len(row)):
            for end in range(start + 1, min(start + 5, len(row) + 1)):
                group = row[start:end]
                combined = "".join(t["text"] for t in group).upper()
                m = TAG_RE.search(combined)
                if m and m.group(2) in VALVE_TYPE_CODES:
                    tag = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                    if tag not in seen:
                        seen.add(tag)
                        cx = sum(t["cx"] for t in group) / len(group)
                        cy = sum(t["cy"] for t in group) / len(group)
                        found.append((tag, cx, cy))
                    break  # don't extend this start further

    return found


def _associate_actuator(valve: Dict, actuators: List[Dict], max_dist: float = 150) -> str:
    best_dist, best_code = max_dist, "-"
    for act in actuators:
        d = _dist(valve["cx"], valve["cy"], act["cx"], act["cy"])
        if d < best_dist:
            best_dist = d
            best_code = ACTUATOR_CLASSES[act["class_name"]]
    return best_code


def _find_line_near(pos: Dict, ocr_texts: List[Dict], radius: float = 500) -> Optional[str]:
    """Find line number in OCR texts near a given position."""
    nearby = sorted(
        [t for t in ocr_texts if _dist(pos["cx"], pos["cy"], t["cx"], t["cy"]) <= radius],
        key=lambda t: _dist(pos["cx"], pos["cy"], t["cx"], t["cy"]),
    )
    combined = " ".join(t["text"] for t in nearby[:20]).upper()
    m = LINE_RE.search(combined)
    if m:
        size = str(int(m.group(1)))  # strip leading zeros (e.g. "004" → "4")
        return f'{size}"-{m.group(2)}-{m.group(3)}-{m.group(4)}'
    return None


# ── Per-tile detection ─────────────────────────────────────────────────────────

def _detect_tile(tile: Dict) -> List[Dict]:
    img = Image.open(tile["path"]).convert("RGB")
    orig_w, orig_h = img.size

    inp, scale, pad_x, pad_y = _preprocess(img)
    session = _get_session()
    output = session.run(None, {session.get_inputs()[0].name: inp})[0]
    detections = _decode(output, scale, pad_x, pad_y, orig_w, orig_h)

    valves = [d for d in detections if d["class_name"] in VALVE_CLASSES]
    actuators = [d for d in detections if d["class_name"] in ACTUATOR_CLASSES]
    print(f"    YOLO: {len(valves)} valves, {len(actuators)} actuators")

    ocr_texts = _run_ocr(tile["path"])
    print(f"    OCR:  {len(ocr_texts)} text regions")

    results = []
    yolo_indices_used = set()

    # Strategy 1: OCR-driven tile scan — find valve tags by combining adjacent OCR
    # row tokens. Handles fragmented tags (e.g. "62-BF-" + "151031").
    tag_hits = _extract_tags_from_tile(ocr_texts)

    for tag, tcx, tcy in tag_hits:
        # Nearest YOLO valve within 500px for class/bbox
        best_idx, best_v, best_d = None, None, 500.0
        for vi, v in enumerate(valves):
            d = _dist(tcx, tcy, v["cx"], v["cy"])
            if d < best_d:
                best_d, best_idx, best_v = d, vi, v

        if best_idx is not None:
            yolo_indices_used.add(best_idx)

        yolo_class = best_v["class_name"] if best_v else "valve_gen"
        yolo_conf = best_v["conf"] if best_v else 0.0

        line_number = _find_line_near({"cx": tcx, "cy": tcy}, ocr_texts)
        actuator = _associate_actuator({"cx": tcx, "cy": tcy}, actuators, max_dist=200)

        bbox = [best_v["x1"], best_v["y1"], best_v["x2"], best_v["y2"]] if best_v else \
               [tcx - 30, tcy - 30, tcx + 30, tcy + 30]
        print(f"      {tag:25s}  line={line_number or '—':35s}  act={actuator}  [{yolo_class} {round(yolo_conf,3)}]")
        results.append({
            "valve_tag": tag,
            "line_number": line_number,
            "actuator": actuator,
            "yolo_class": yolo_class,
            "yolo_conf": round(yolo_conf, 3),
            "tile_row": tile["row"],
            "tile_col": tile["col"],
            "bbox_tile": bbox,
            "source": "OCR",
        })

    # Strategy 2: YOLO-anchored — for detections not matched by OCR above.
    # Uses _associate_text which combines all nearby OCR tokens (+ no-space fallback).
    SERIAL_RE = re.compile(r'^-?(\d{6,8})$')
    AREA_RE = re.compile(r'^\d{2}$')
    for i, v in enumerate(valves):
        if i in yolo_indices_used:
            continue
        if v["conf"] < 0.35:
            continue

        valve_tag, line_number = _associate_text(v, ocr_texts, radius=500)

        # Targeted crop OCR — if still no tag, zoom in on the valve location
        # in the full-page image to get better OCR on small/noisy text
        if not valve_tag:
            tile_x0 = tile.get("x0", 0)
            tile_y0 = tile.get("y0", 0)
            crop_texts = _targeted_crop_ocr(tile["path"], v["cx"], v["cy"], tile_x0, tile_y0)
            if crop_texts:
                crop_tag_hits = _extract_tags_from_tile(crop_texts)
                if crop_tag_hits:
                    valve_tag = crop_tag_hits[0][0]  # first hit from crop
                if not valve_tag:
                    valve_tag, line_number = _associate_text(v, crop_texts, radius=300)

        # Serial reassembly fallback — require BOTH area + serial fragments
        if not valve_tag:
            type_code = CLASS_TO_TYPE.get(v["class_name"])
            if type_code:
                nearby = [t for t in ocr_texts if _dist(v["cx"], v["cy"], t["cx"], t["cy"]) <= 300]
                serial = None
                area_code = None
                for t in sorted(nearby, key=lambda t: _dist(v["cx"], v["cy"], t["cx"], t["cy"])):
                    txt = t["text"].strip()
                    if serial is None and SERIAL_RE.match(txt):
                        serial = SERIAL_RE.match(txt).group(1)
                    if area_code is None and AREA_RE.match(txt):
                        area_code = txt
                if serial and area_code:  # require BOTH to reduce false positives
                    valve_tag = f"{area_code}-{type_code}-{serial}"

        actuator = _associate_actuator(v, actuators)
        suffix = "(crop)" if valve_tag else "(YOLO-only)"
        label = valve_tag or "?"
        print(f"      {label:25s}  line={line_number or '—':35s}  act={actuator}  [{v['class_name']} {round(v['conf'],3)}] {suffix}")
        results.append({
            "valve_tag": valve_tag,
            "line_number": line_number,
            "actuator": actuator,
            "yolo_class": v["class_name"],
            "yolo_conf": round(v["conf"], 3),
            "tile_row": tile["row"],
            "tile_col": tile["col"],
            "bbox_tile": [v["x1"], v["y1"], v["x2"], v["y2"]],
            "source": suffix,
        })

    return results


# ── Public API (mirrors extractor.py) ─────────────────────────────────────────

def extract_all_tiles(tiles: List[Dict], model: str = None, save_raw: bool = True) -> List[Dict]:
    """
    Offline detection across all tiles using YOLO ONNX + PaddleOCR.
    API-compatible with extractor.extract_all_tiles().
    `model` param accepted but ignored (uses local ONNX).
    """
    print(f"\n  --- Offline detection: YOLO+OCR ---")
    print(f"  Model: {MODEL_PATH}")
    all_valves = []

    for i, tile in enumerate(tiles):
        print(f"  [{i+1}/{len(tiles)}] Tile r{tile['row']}c{tile['col']}...")
        try:
            tile_valves = _detect_tile(tile)
            # Annotate each detection with tile page offsets for visualization
            for v in tile_valves:
                v["tile_x0"] = tile.get("x0", 0)
                v["tile_y0"] = tile.get("y0", 0)
                v["tile_page"] = tile.get("page", 0)
            all_valves.extend(tile_valves)
        except Exception as e:
            print(f"    ERROR: {e}")

    with_line = sum(1 for v in all_valves if v.get("line_number"))
    print(f"\n  Detection complete: {len(all_valves)} valves, {with_line} with line numbers")

    if save_raw:
        _save_raw(all_valves, "tmp/raw_extractions.json")

    return all_valves


def extract_drawing_number(pdf_path: str, tmp_dir: str = "tmp") -> str:
    """
    Extract drawing number from title block via OCR.
    Falls back to API extractor on failure.
    """
    import fitz

    try:
        doc = fitz.open(pdf_path)
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        Path(tmp_dir).mkdir(exist_ok=True)
        full_path = Path(tmp_dir) / "titleblock_full.png"
        pix.save(str(full_path))
        doc.close()

        img = Image.open(str(full_path))
        W, H = img.size
        crop = img.crop((int(W * 0.60), int(H * 0.78), W, H))
        crop_path = Path(tmp_dir) / "titleblock_crop.png"
        crop.save(str(crop_path))

        ocr_texts = _run_ocr(str(crop_path))
        all_text = "".join(t["text"] for t in ocr_texts).replace(" ", "")
        m = DRAWING_NO_RE.search(all_text)
        if m:
            result = m.group(0)
            print(f"  Extracted Drawing No. (OCR): {result}")
            return result
    except Exception as e:
        print(f"  OCR title block extraction failed: {e}")

    # Fallback to API
    print("  Falling back to API for drawing number extraction...")
    try:
        from extractor import extract_drawing_number as _api
        return _api(pdf_path, tmp_dir)
    except Exception as e:
        print(f"  API fallback failed: {e}")
        return "UNKNOWN"


def _extract_inst_tags_from_ocr(ocr_texts: List[Dict]) -> List[Tuple[str, float, float]]:
    """
    Find instrument tags (format YY-XX-NNNNN, e.g. 01-PT-01017) in OCR results.
    Uses the same row-clustering approach as _extract_tags_from_tile but with
    a tag pattern that targets instrument bubbles, not valve serials.
    """
    from instrument_parser import TYPE_MAP

    if not ocr_texts:
        return []

    INST_TAG_RE = re.compile(r'(\d{1,3}(?:-\d{1,3})?)-([A-Z]{2,5})-(\d{3,6})([A-Z]{1,2})?')

    sorted_texts = sorted(ocr_texts, key=lambda t: (t["cy"], t["cx"]))
    rows: List[List[Dict]] = []
    current = [sorted_texts[0]]
    for t in sorted_texts[1:]:
        if abs(t["cy"] - current[-1]["cy"]) <= 40:
            current.append(t)
        else:
            rows.append(sorted(current, key=lambda x: x["cx"]))
            current = [t]
    if current:
        rows.append(sorted(current, key=lambda x: x["cx"]))

    found: List[Tuple[str, float, float]] = []
    seen = set()
    for row in rows:
        for start in range(len(row)):
            for end in range(start + 1, min(start + 5, len(row) + 1)):
                group = row[start:end]
                combined = "".join(t["text"] for t in group).upper().replace(" ", "")
                m = INST_TAG_RE.search(combined)
                if not m:
                    continue
                type_code = m.group(2)
                if type_code in VALVE_TYPE_CODES or type_code not in TYPE_MAP:
                    continue
                suffix = m.group(4) or ""
                tag = f"{m.group(1)}-{type_code}-{m.group(3)}{suffix}"
                if tag in seen:
                    break
                seen.add(tag)
                cx = sum(t["cx"] for t in group) / len(group)
                cy = sum(t["cy"] for t in group) / len(group)
                found.append((tag, cx, cy))
                break
    return found


def extract_instruments(tiles: List[Dict], drawing_description: str = "", model: str = None) -> List[Dict]:
    """
    Offline instrument extraction across all tiles.
    YOLO finds instrument bubbles → OCR reads tag → returns raw dicts shaped
    identically to the API path (extractor.extract_instruments).
    """
    from instrument_parser import default_power_signal, TYPE_MAP

    print(f"\n  --- Offline instrument extraction: YOLO + OCR ---")
    all_instruments: List[Dict] = []

    for i, tile in enumerate(tiles):
        print(f"  [{i+1}/{len(tiles)}] Tile r{tile['row']}c{tile['col']}...")
        try:
            img = Image.open(tile["path"]).convert("RGB")
            orig_w, orig_h = img.size
            inp, scale, pad_x, pad_y = _preprocess(img)
            session = _get_session()
            output = session.run(None, {session.get_inputs()[0].name: inp})[0]
            detections = _decode(output, scale, pad_x, pad_y, orig_w, orig_h)

            inst_dets = [d for d in detections if d["class_name"] in INSTRUMENT_CLASSES]
            print(f"    YOLO: {len(inst_dets)} instrument bubbles")
            if not inst_dets:
                continue

            ocr_texts = _run_ocr(tile["path"])
            tile_x0 = tile.get("x0", 0)
            tile_y0 = tile.get("y0", 0)

            # Tile-wide OCR scan for instrument tags (handles fragmented tokens)
            tag_hits = _extract_inst_tags_from_ocr(ocr_texts)

            for det in inst_dets:
                # Find nearest OCR-discovered tag to this bubble
                best_tag, best_d = None, 200.0
                for tag, tcx, tcy in tag_hits:
                    d = _dist(det["cx"], det["cy"], tcx, tcy)
                    if d < best_d:
                        best_d, best_tag = d, tag

                # Fallback: targeted crop OCR around the bubble
                if not best_tag:
                    crop_texts = _targeted_crop_ocr(
                        tile["path"], det["cx"], det["cy"], tile_x0, tile_y0,
                        crop_size=300,
                    )
                    crop_hits = _extract_inst_tags_from_ocr(crop_texts)
                    if crop_hits:
                        best_tag = crop_hits[0][0]

                if not best_tag:
                    continue  # cannot identify this bubble

                # Type code → instrument type description + defaults
                type_code = best_tag.split("-")[-2] if best_tag.count("-") >= 2 else ""
                type_desc = TYPE_MAP.get(type_code, type_code)
                power, signal = default_power_signal(type_code)

                line_number = _find_line_near(
                    {"cx": det["cx"], "cy": det["cy"]}, ocr_texts, radius=500,
                )
                location = LOCATION_FROM_YOLO_CLASS.get(det["class_name"], "FIELD")

                all_instruments.append({
                    "tag_number": best_tag,
                    "instrument_type_description": type_desc,
                    "tag_service": "TBD",  # offline path can't infer service from drawing topology
                    "line_number": line_number or "NA",
                    "equipment_number": "NA",
                    "location": location,
                    "power_supply": power,
                    "signal_voltage_level": signal,
                    "tile_row": tile["row"],
                    "tile_col": tile["col"],
                    "yolo_class": det["class_name"],
                    "yolo_conf": round(det["conf"], 3),
                })
                print(f"      {best_tag:25s}  loc={location:8s}  line={line_number or '—'}")
        except Exception as e:
            print(f"    ERROR: {e}")

    print(f"\n  Offline instrument extraction complete: {len(all_instruments)} detections")
    return all_instruments


def _save_raw(data: List[Dict], path: str) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved → {path}")
