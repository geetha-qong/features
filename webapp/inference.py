"""In-process YOLO ONNX inference for canvas bbox surfacing.

**Scope (FEATURES #28):** This module is the *only* supported path for running
YOLO inference inside the webapp process. It exists to populate
`Job.gpu_detections` with raw symbol bounding boxes so the studio canvas can
draw overlays without depending on the Windows GPU worker callback.

It is **not** part of the CSV/deliverable pipeline — that path remains
OpenRouter Vision API via `extractor.py`. Do not import this module from
`pipeline.py`. See the "CRITICAL: Two-Mode Architecture" section of CLAUDE.md.

The output dict shape is intentionally identical to the GPU-worker callback
(`worker.run_inference_job` → POST /api/v1/jobs/{id}/gpu-result), so the
existing `gpu_detections` consumer in `webapp/routers/api_v1.py` reads either
source without branching.

`label` is the raw YOLO class name (e.g. `"valve_bf"`, `"inst_bubble"`) —
NOT the OCR'd P&ID tag. Downstream entity_id matching (which lives in the
detections endpoint) will set `entity_id=null` for these, which is the
intended state until a separate class+bbox → tag pass is wired up.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# Pillow is required for tile reading; it's already a base dep.
try:
    from PIL import Image
except ImportError:  # pragma: no cover — tests gate on this
    Image = None  # type: ignore[assignment]

# `onnxruntime` is gated behind a try/except so that the bare module import
# does NOT pull in the native library during unit tests. Tests that don't
# exercise `run_yolo_inference` (i.e. nearly all of them) keep working even if
# the wheel isn't installed locally. Failures surface inside `_get_session()`
# instead, where they belong.
try:
    import onnxruntime as ort  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    ort = None  # type: ignore[assignment]


# ── Config ─────────────────────────────────────────────────────────────────────

MODEL_PATH = "/app/models/v1-11.onnx"
IMGSZ = 640  # v1-11 (like v1-10) was trained + ONNX-exported at 640; using a
             # different IMGSZ here against a fixed-axes ONNX would fail with a
             # shape mismatch. v1-9 used 1280 — don't blindly copy that value.
CONF_THRESH = 0.50  # carried over from v1-10. v1-11 has the same 23-class
                    # layout and a higher mAP50 (0.805 vs 0.745 on the same
                    # val set), so 0.50 remains a reasonable noise-floor;
                    # revisit after dev smoke-test if the canvas overlay
                    # becomes either too sparse or too cluttered.
IOU_THRESH = 0.45

# Class IDs in v1-10 — order = class index (argmax over the output's class-
# score channels). MUST match the training-time `data.yaml` (see
# experiments/digital_twin/data/dataset_v1-10/data.yaml or the CLASSES
# constant in experiments/digital_twin/scripts/export_ls_dataset.py).
#
# v1-10 changes from v1-9 (FEATURES #30):
#   added:   inst_bpcs, inst_sis, SIS-R, inst_local_panel + 6 direction
#            labels (arrow_*, connector_in/out)
#   dropped: valve_cv, valve_gen, DCS, PLC, interlock-R, inst_field-R,
#            valve_pnuectrl typo (all had <100 LS annotations — too thin)
CLASS_NAMES: List[str] = [
    # Valves (9)
    "valve_bv",            # 0
    "valve_ncbv",          # 1
    "valve_gt",            # 2
    "valve_bf",            # 3
    "valve_ck",            # 4
    "valve_db",            # 5
    "valve_relief_safety", # 6
    "valve_gl",            # 7
    "valve_3way_relief",   # 8
    # Instruments / signals (8)
    "inst_field",          # 9
    "inst_bpcs",           # 10
    "Motor",               # 11
    "Pump/Dwg Pump",       # 12  (note: contains slash + space — was Pump_Dwg_Pump in v1-9)
    "inst_sis",            # 13
    "SIS-R",               # 14
    "interlock",           # 15
    "inst_local_panel",    # 16
    # Direction (6 — new in v1-10)
    "arrow_up",            # 17
    "arrow_left",          # 18
    "arrow_right",         # 19
    "arrow_down",          # 20
    "connector_out",       # 21
    "connector_in",        # 22
]


class InferenceError(RuntimeError):
    """Raised on any failure inside :func:`run_yolo_inference` that the caller
    needs to handle. Wraps model-file-missing, onnxruntime errors, and
    Pillow-decode failures so the pipeline runner can log a single failure
    type without swallowing context."""


# ── Lazy session loader (thread-safe via double-checked locking) ───────────────

_session: Optional[Any] = None
_session_lock = threading.Lock()


def _get_session() -> Any:
    """Return a process-wide :class:`onnxruntime.InferenceSession`.

    Double-checked locking: cheap unlocked read on the hot path, lock only
    on first init or after a forked worker's session was inherited as None.
    """
    global _session
    if _session is not None:
        return _session
    with _session_lock:
        if _session is not None:
            return _session
        if ort is None:
            raise InferenceError(
                "onnxruntime is not installed — cannot load YOLO model. "
                "Add `onnxruntime` to requirements.txt and rebuild the image."
            )
        model_path = Path(MODEL_PATH)
        if not model_path.exists():
            raise InferenceError(
                f"YOLO model file missing at {MODEL_PATH}. "
                "The Docker image build is expected to download v1-11.onnx "
                "into /app/models/. Verify the Dockerfile build step succeeded."
            )
        try:
            _session = ort.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:  # onnxruntime raises a variety of types
            raise InferenceError(f"Failed to load ONNX session: {exc!r}") from exc
        return _session


# ── Pre/post processing (mirrors detector.py for byte-for-byte parity) ─────────

def _preprocess(img: "Image.Image") -> tuple:
    """Letterbox to IMGSZ, normalise to [0,1], return (BCHW, scale, pad_x, pad_y)."""
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
    """Pure-numpy NMS — kept here so the module has no ultralytics dep."""
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: List[int] = []
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


def _decode(
    output: np.ndarray,
    scale: float,
    pad_x: int,
    pad_y: int,
    orig_w: int,
    orig_h: int,
) -> List[Dict[str, Any]]:
    """YOLOv8 output [1, 4+nc, N] → list of {label, confidence, bbox} dicts.

    Expects N classes = len(CLASS_NAMES). If the model was exported with a
    different head shape we surface that via InferenceError at caller scope.
    """
    preds = output[0].T  # (N, 4 + nc)
    nc = preds.shape[1] - 4
    if nc != len(CLASS_NAMES):
        raise InferenceError(
            f"Model head has {nc} classes but CLASS_NAMES has "
            f"{len(CLASS_NAMES)}. Refusing to decode."
        )
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

    detections: List[Dict[str, Any]] = []
    for cls_id in np.unique(class_ids):
        m = class_ids == cls_id
        bboxes = np.stack([x1[m], y1[m], x2[m], y2[m]], axis=1)
        scores = conf[m]
        for idx in _nms(bboxes, scores, IOU_THRESH):
            bx1, by1, bx2, by2 = bboxes[idx]
            detections.append({
                "_class_id": int(cls_id),
                "_score": float(scores[idx]),
                "_bbox": [float(bx1), float(by1), float(bx2), float(by2)],
            })
    return detections


# ── Tile filename parser ──────────────────────────────────────────────────────

import re

_TILE_RE = re.compile(r"tile_p(\d+)_r(\d+)_c(\d+)\.png$")


def _parse_tile_name(name: str) -> tuple:
    """Return (page, row, col) or (0, 0, 0) if the filename doesn't match."""
    m = _TILE_RE.search(name)
    if not m:
        return 0, 0, 0
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


# ── Public API ────────────────────────────────────────────────────────────────

def run_yolo_inference(tile_paths: List[Path]) -> List[Dict[str, Any]]:
    """Run YOLO inference across all given tile PNGs.

    Returned shape matches the existing `gpu_detections` consumer:

        [
            {
                "bbox": [x1, y1, x2, y2],   # original tile pixel coords
                "label": "valve_bf",        # raw YOLO class name
                "confidence": 0.91,
                "tile_page": 0,
                "tile_row": 1,
                "tile_col": 2,
                "tile": "tile_p0_r1_c2.png",
            },
            ...
        ]

    Raises :class:`InferenceError` on any unrecoverable failure (model file
    missing, onnxruntime failure, head-shape mismatch). Per-tile decode
    errors are logged via raise — callers should wrap and degrade
    gracefully (see ``pipeline_runner._run_inplace_inference``).
    """
    if Image is None:
        raise InferenceError("Pillow is not installed — cannot read tiles")

    session = _get_session()
    input_name = session.get_inputs()[0].name

    all_dets: List[Dict[str, Any]] = []
    for tile_path in tile_paths:
        path = Path(tile_path)
        page, row, col = _parse_tile_name(path.name)
        try:
            img = Image.open(str(path)).convert("RGB")
        except Exception as exc:
            raise InferenceError(f"Failed to open tile {path}: {exc!r}") from exc

        orig_w, orig_h = img.size
        inp, scale, pad_x, pad_y = _preprocess(img)
        try:
            output = session.run(None, {input_name: inp})[0]
        except Exception as exc:
            raise InferenceError(
                f"onnxruntime.run failed on tile {path.name}: {exc!r}"
            ) from exc

        raw_dets = _decode(output, scale, pad_x, pad_y, orig_w, orig_h)
        for d in raw_dets:
            all_dets.append({
                "bbox": d["_bbox"],
                "label": CLASS_NAMES[d["_class_id"]],
                "confidence": round(d["_score"], 4),
                "tile_page": page,
                "tile_row": row,
                "tile_col": col,
                "tile": path.name,
            })

    return all_dets
