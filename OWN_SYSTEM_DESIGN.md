# Own System Design: Offline P&ID Valve Extraction (No API)

**Goal**: Replace the OpenRouter/Claude Vision API with a fully local, offline pipeline.
**Constraint**: `parser.py`, `validator.py`, `corrections.py`, `webapp/` — all unchanged.
**Integration point**: `pipeline.py` changes one line: `from extractor import` → `from detector import`

---

## Architecture Overview

```
PDF
 │
 ▼
[pdf_to_tiles.py]          ← UNCHANGED (3×3 grid, 25% overlap)
9 PNG tiles per drawing
 │
 ▼
[detector.py]              ← NEW — replaces extractor.py entirely
 ├── symbol_detector.py    ← YOLOv8s (ONNX) — finds valve/actuator bboxes
 ├── ocr_engine.py         ← PaddleOCR PP-OCRv4 — reads all text in tile
 ├── ocr_normalize.py      ← Fix common OCR misreads (O/0, l/1, " variants)
 ├── associate.py          ← Links symbol bbox → tag text → line number text
 └── pipe_tracer.py        ← OpenCV Hough lines for pass-2 line number recovery
 │   Produces identical JSON schema to extractor.py:
 │   [{"valve_tag": "62-BF-151031", "line_number": "20\"-W-62151019-BGA",
 │     "actuator": "none", "confidence": 0.92}]
 ▼
[parser.py]                ← UNCHANGED
[corrections.py]           ← UNCHANGED
[validator.py]             ← UNCHANGED
[webapp/]                  ← UNCHANGED
```

---

## 1. Symbol Detection: YOLOv8s

**Why YOLOv8s** (not v5, not RT-DETR, not template matching):
- Single-class + multi-class detection, fast CPU inference
- Ultralytics Python API: 3 lines of code
- ONNX export → no PyTorch needed in production
- Handles small objects at `imgsz=1280` (P&ID symbols are 40–80px at 3× zoom)
- Pre-trains from COCO weights → converges in 20–30 epochs vs 100+ from scratch

**Training config:**
```python
from ultralytics import YOLO
model = YOLO('yolov8s.pt')
model.train(
    data='datasets/pid_valves/data.yaml',
    epochs=100,
    imgsz=1280,       # critical — do NOT use default 640
    batch=4,
    lr0=0.005,
    degrees=15,
    fliplr=0.5,
    flipud=0.3,
    mosaic=1.0,
)
model.export(format='onnx', imgsz=1280, simplify=True)
```

**YOLO Classes (10 total):**

| ID | Class | Symbol |
|----|-------|--------|
| 0 | `valve_bf` | Butterfly — bowtie/diamond on pipe |
| 1 | `valve_bv` | Ball — circle with line through it |
| 2 | `valve_ck` | Check — arrowhead / half-circle |
| 3 | `valve_gl` | Globe — circle with internal plug |
| 4 | `valve_db` | Double Block & Bleed — cluster of 3 small symbols |
| 5 | `valve_cv` | Control valve — circle with actuator dome |
| 6 | `valve_gen` | Generic (VM, VG, NV, SV, UZV, PV) |
| 7 | `actuator_motor` | Motor box with M label |
| 8 | `actuator_pneumatic` | Pneumatic dome / diaphragm |
| 9 | `actuator_solenoid` | Solenoid coil or SL text box |

Actuators are separate classes because they attach to valves at variable positions — detecting them as distinct objects is more robust than reading "SL"/"M" text via OCR.

---

## 2. OCR: PaddleOCR PP-OCRv4

**Why PaddleOCR** (not Tesseract, not EasyOCR):
- Best accuracy on dense, small, rotated engineering annotation text
- `use_angle_cls=True` handles rotated line number labels (run parallel to pipes)
- Fully offline, models pre-downloadable
- Returns bbox + text + confidence for every text region

```python
from paddleocr import PaddleOCR
ocr = PaddleOCR(
    use_angle_cls=True,
    lang='en',
    use_gpu=False,
    det_model_dir='models/paddle_det/',
    rec_model_dir='models/paddle_rec/',
    cls_model_dir='models/paddle_cls/',
    show_log=False,
)
result = ocr.ocr(tile_img_array, cls=True)
# Returns: [[[bbox_4pts], (text, confidence)], ...]
```

**OCR normalization** (`ocr_normalize.py`):
- `O` → `0` when surrounded by digits (serial numbers)
- `l` / `I` → `1` when surrounded by digits
- `''` / `"` / `"` → `"` (inches symbol)
- `—` / `_` → `-` (hyphen in line numbers)

---

## 3. Spatial Association (`associate.py`)

Replaces the LLM's "trace the pipe" reasoning with geometric rules.

```
For each detected valve symbol S:

  1. FIND TAG
     Search radius = 2.5 × symbol_size
     Candidates: OCR text matching TAG_PATTERN_1 or TAG_PATTERN_2 (from parser.py)
     Pick: nearest to symbol center

  2. FIND LINE NUMBER (Pass 1 — tight)
     Search radius = 5.0 × symbol_size
     Candidates: OCR text matching line number regex (digit + " + - + letters)
     Score: 0.6 × normalized_distance + 0.4 × angle_penalty(vs pipe axis)
     Pipe axis: estimated from symbol bbox aspect ratio

  3. FIND LINE NUMBER (Pass 2 — pipe tracing)
     If Pass 1 fails: detect pipe segments via OpenCV HoughLinesP
     Follow nearest pipe segment to its label text
     (Replicates "trace the pipe" in prompts.py)

  4. DETECT ACTUATOR
     Primary: check for nearby `actuator_*` YOLO detections
     Fallback: check for "SL" / "M" / "P" text within 1.5 × symbol_size above/below symbol
```

Pipe tracing (for pass-2):
```python
import cv2, numpy as np
gray = cv2.cvtColor(tile_img, cv2.COLOR_BGR2GRAY)
edges = cv2.Canny(gray, 50, 150)
lines = cv2.HoughLinesP(edges, 1, np.pi/180,
                        threshold=80, minLineLength=50, maxLineGap=10)
# Follow nearest pipe segment → find its line label
```

---

## 4. Training Data Strategy

### What We Have
- 5 P&ID drawings × ~38 valves = **193 labeled valve instances**
- 45 tiles (5 drawings × 9 tiles)
- Ground truth from `docs/Output-Valve List.csv` (guides annotation)

### Annotation Tool
**Label Studio** (open source, local, exports YOLO format):
```bash
pip install label-studio
label-studio start
```
Load all 45 tiles. Draw bounding boxes for 10 classes.
Export → YOLO format.

Estimated time: ~11 hours (45 tiles × 15 min/tile, guided by known valve list).

### Dataset Structure
```
datasets/pid_valves/
  images/train/   ← 36 tiles (4 drawings)
  images/val/     ← 9 tiles (1 drawing)
  labels/train/   ← .txt files (class_id cx cy w h, normalized)
  labels/val/
  data.yaml
```

### Augmentation (critical with small dataset)
Built into YOLOv8 training:
- Horizontal + vertical flip
- Rotation ±15°
- Brightness/contrast jitter ±30%
- Gaussian noise
- Mosaic (4 tiles → 1 training image)

Additional:
- Synthetic copies: crop valve symbols, paste into blank regions at ±20% scale
- Scan simulation: slight blur (1–3px kernel), JPEG artifacts, perspective warp

### Expected mAP@0.5

| Scenario | Instances | Expected mAP |
|----------|-----------|--------------|
| 1 drawing (minimum) | ~38 | 55–65% |
| 3 drawings | ~115 | 72–80% |
| 5 drawings (full) | ~190 | 82–88% |
| 5 drawings + augmentation | ~500 effective | 88–93% |

---

## 5. Implementation Phases

### Phase 1 — Annotation (Week 1)
- Install Label Studio locally
- Generate all 45 tiles from 5 drawings
- Annotate all 10 classes per tile
- Export YOLO dataset, validate it loads

### Phase 2 — YOLO Training (Week 2, Days 1–3)
- Train `yolov8s.pt` on annotated dataset at `imgsz=1280`
- Target: >75% mAP@0.5 on validation set
- Export `best.onnx` for production inference

### Phase 3 — PaddleOCR Integration (Week 2, Days 3–5)
- Install PaddleOCR, pre-download models
- Build `ocr_engine.py` + `ocr_normalize.py`
- Run on all 45 tiles, verify tag/line reading accuracy
- Target: <5% CER on valve tags, <8% on line numbers

### Phase 4 — Spatial Associator (Week 3)
- Implement `associate.py` with 2-pass strategy
- Implement `pipe_tracer.py` for pass-2 recovery
- Wire into `detector.py` with same public API as `extractor.py`
- End-to-end test on the 193-valve ground truth
- Target: ≥85% recall

### Phase 5 — Accuracy Tuning (Week 4)
- Analyze misses: YOLO miss vs OCR miss vs association miss
- Hard negative mining for YOLO misses
- Tune OCR confidence threshold and normalization rules
- Update `corrections.py` for systematic drawing-specific issues
- Target: ≥90% recall, ≥90% complete rows

### Phase 6 — Webapp Integration (Week 5)
- Update `requirements.txt` (remove openai/anthropic, add ultralytics/paddleocr/opencv)
- Model warm-up on app startup
- Remove `OPENROUTER_API_KEY` dependency
- Docker image update (CPU-only torch to keep image size manageable)
- Full regression test on all 5 drawings

---

## 6. New Files

| File | Purpose |
|------|---------|
| `detector.py` | Drop-in for `extractor.py`. Same public API. |
| `symbol_detector.py` | YOLOv8 ONNX inference wrapper |
| `ocr_engine.py` | PaddleOCR wrapper |
| `ocr_normalize.py` | OCR post-processing corrections |
| `associate.py` | Spatial symbol→tag→line linking |
| `pipe_tracer.py` | OpenCV pipe segment detection |
| `train.py` | Training script with all hyperparameters |
| `models/` | `best.onnx` + PaddleOCR weights |
| `datasets/pid_valves/` | YOLO annotation dataset |

---

## 7. Dependency Changes

**Remove:**
```
anthropic
openai
```

**Add:**
```
ultralytics>=8.2.0
paddlepaddle>=2.6.0
paddleocr>=2.7.3
opencv-python-headless>=4.9.0
onnxruntime>=1.18.0
# CPU-only torch (saves ~1.8GB in Docker image):
# torch --index-url https://download.pytorch.org/whl/cpu
```

---

## 8. Accuracy Expectations

| Metric | Current (API) | Offline v1 | Offline v2 (tuned) |
|--------|--------------|------------|-------------------|
| Recall | ~90% | ~80–85% | ~88–92% |
| Complete rows | ~93% | ~75–85% | ~85–92% |
| Processing (CPU) | 45–90s (API) | 90–180s | 60–120s |
| Processing (GPU) | 45–90s | 15–30s | 10–20s |
| Hallucinations | Occasional | None | None |
| Cost per drawing | ~$0.10 | $0 | $0 |
| Works offline | No | Yes | Yes |

**Key advantage**: No hallucinations. The current system occasionally invents valve tags
(see `corrections.py` removes 151076, 151077). A detection model only reports what it sees.

---

## 9. Air-Gap Deployment

For oil & gas plant networks with no internet:

1. Pre-download all wheels: `pip download -r requirements.txt -d wheelhouse/`
2. Pre-download model weights on internet machine, copy to `models/`
3. Build Docker image with `--no-index --find-links wheelhouse/`
4. Zero external calls at runtime

**Hardware minimum (CPU-only):**
- 4-core CPU, 8GB RAM, 5GB disk, no GPU required

**Recommended (GPU):**
- NVIDIA GPU 4GB VRAM+, CUDA 11.8+, 16GB RAM
- Processing: ~15 sec/drawing vs ~2 min on CPU
