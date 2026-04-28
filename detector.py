"""
Stage 2 (offline): YOLO ONNX + PaddleOCR valve detection.
Drop-in replacement for extractor.py — same public API:
  extract_all_tiles(tiles, ...) -> list of valve dicts
  extract_drawing_number(pdf_path, tmp_dir) -> str
"""
import json
import re
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
    "actuator_motor", "actuator_pneu", "actuator_sol",
    "valve_bf", "valve_bv", "valve_ck", "valve_cv",
    "valve_db", "valve_gen", "valve_gl",
]

# YOLO class → valve type code (None = infer from nearby OCR text)
CLASS_TO_TYPE: Dict[str, Optional[str]] = {
    "valve_bf": "BF", "valve_bv": "BV", "valve_ck": "CK",
    "valve_cv": "CV", "valve_db": "DB", "valve_gen": None, "valve_gl": "GL",
}
ACTUATOR_CLASSES = {"actuator_motor": "M", "actuator_pneu": "P", "actuator_sol": "SL"}
VALVE_CLASSES = set(CLASS_TO_TYPE.keys())

# Known valve type codes — used to filter OCR tags from instrument tags (FIT, LIT, XZT, etc.)
VALVE_TYPE_CODES = {
    "BF", "BV", "VB", "DB", "CK", "GL", "VM", "VG", "NV", "SV",
    "PV", "UZV", "FV", "CV", "FO", "FC", "GV", "TV",
}

# Text patterns
TAG_RE = re.compile(r'(\d{2,3})-([A-Z]{2,4})-(\d{4,8})')
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

    valve_tag = None
    line_number = None

    m = TAG_RE.search(combined)
    if m:
        valve_tag = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    m = LINE_RE.search(combined)
    if m:
        line_number = f'{m.group(1)}"-{m.group(2)}-{m.group(3)}-{m.group(4)}'

    return valve_tag, line_number


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

    # Strategy 1: OCR-centric — find all complete tags in individual OCR texts,
    # then associate the nearest YOLO detection for type classification.
    for t in ocr_texts:
        m = TAG_RE.search(t["text"].upper())
        if not m:
            continue
        type_code = m.group(2)
        if type_code not in VALVE_TYPE_CODES:
            continue  # instrument tag (FIT, LIT, XZT, etc.) — skip
        tag = f"{m.group(1)}-{type_code}-{m.group(3)}"

        # Nearest YOLO valve (for type classification)
        best_idx, best_v, best_d = None, None, 400.0
        for i, v in enumerate(valves):
            d = _dist(t["cx"], t["cy"], v["cx"], v["cy"])
            if d < best_d:
                best_d, best_idx, best_v = d, i, v

        yolo_class = best_v["class_name"] if best_v else "valve_gen"
        yolo_conf = best_v["conf"] if best_v else 0.0
        if best_idx is not None:
            yolo_indices_used.add(best_idx)

        line_number = _find_line_near(t, ocr_texts)
        actuator = _associate_actuator({"cx": t["cx"], "cy": t["cy"]}, actuators, max_dist=200)

        print(f"      {tag:25s}  line={line_number or '—':35s}  act={actuator}  [{yolo_class} {round(yolo_conf,3)}]")
        results.append({
            "valve_tag": tag,
            "line_number": line_number,
            "actuator": actuator,
            "yolo_class": yolo_class,
            "yolo_conf": round(yolo_conf, 3),
            "tile_row": tile["row"],
            "tile_col": tile["col"],
        })

    # Strategy 2: YOLO-only fallback — high-confidence detections with no matched OCR tag
    for i, v in enumerate(valves):
        if i in yolo_indices_used:
            continue
        if v["conf"] < 0.5:
            continue
        line_number = _find_line_near(v, ocr_texts)
        actuator = _associate_actuator(v, actuators)
        print(f"      {'?':25s}  line={line_number or '—':35s}  act={actuator}  [{v['class_name']} {round(v['conf'],3)}] (YOLO-only)")
        results.append({
            "valve_tag": None,
            "line_number": line_number,
            "actuator": actuator,
            "yolo_class": v["class_name"],
            "yolo_conf": round(v["conf"], 3),
            "tile_row": tile["row"],
            "tile_col": tile["col"],
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


def _save_raw(data: List[Dict], path: str) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved → {path}")
