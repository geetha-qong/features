# How To Guide & Learning Reference
### P&ID Valve Extraction — Own System (No API)

This document explains every concept you need to understand and guide the solution.
Written for someone who knows software/business but is new to ML/Computer Vision.

---

## Table of Contents
1. [What We're Building — Big Picture](#1-what-were-building)
2. [Phase 1: Annotation — What It Is and How To Do It](#2-annotation)
3. [Phase 2: YOLO — Object Detection Explained](#3-yolo-object-detection)
4. [Phase 3: PaddleOCR — Reading Text in Images](#4-paddleocr)
5. [Phase 4: Spatial Association — Linking Symbols to Text](#5-spatial-association)
6. [Key ML Concepts You Must Know](#6-key-ml-concepts)
7. [File and Folder Structure Explained](#7-file-structure)
8. [How to Run Each Step](#8-how-to-run)
9. [How to Judge If It's Working](#9-how-to-judge-quality)
10. [Glossary](#10-glossary)

---

## 1. What We're Building

### Current system (API-based)
```
P&ID drawing (PDF)
      ↓
We send the image to Claude/OpenRouter API (paid, internet required)
The AI reads it and returns: "I see valve 62-BF-151031 on line 20"-W-..."
      ↓
We format that into a CSV
```

### Own system (what we're building)
```
P&ID drawing (PDF)
      ↓
Step A: Our own YOLO model looks at the image and draws boxes around valve symbols
Step B: Our own OCR reads the text labels near each box
Step C: Our code links symbol → tag text → line number
      ↓
Same CSV output — no internet, no API cost, no data leaving your network
```

**Why bother?**
- Zero cost per drawing (currently ~$0.10 each, scales to $100s for large projects)
- Works offline / on client premises (oil & gas plants often have no internet)
- No hallucinations (the current AI sometimes invents valves that don't exist)
- Faster once set up (~15 sec vs ~4 min per drawing)
- You own the IP

---

## 2. Annotation

### What is annotation?
Annotation means drawing boxes around objects in images and labeling what they are.
This is how you teach a computer vision model what to look for.

Think of it like this:
- You show a child 1000 photos of cats and say "this is a cat" each time
- Eventually the child can recognize cats in new photos
- Annotation is the "this is a cat" labeling step

### What we're annotating
We have 45 tile images (5 drawings × 9 tiles each).
For each tile, we draw a rectangle around each valve symbol and label it.

Example: You see a bowtie shape on a pipe → draw a box around it → label it `valve_bf`

### The 10 classes we annotate

| Label | What it looks like on a P&ID |
|-------|------------------------------|
| `valve_bf` | Butterfly valve — looks like a **bowtie or diamond** shape crossing a pipe line |
| `valve_bv` | Ball valve — looks like a **circle with a line through it** on a pipe |
| `valve_ck` | Check valve — looks like an **arrowhead or half-moon** shape (shows flow direction) |
| `valve_gl` | Globe valve — looks like a **circle with a cross or plug** inside |
| `valve_db` | Double Block & Bleed — **cluster of 3 small valve symbols** on a small branch pipe |
| `valve_cv` | Control valve — **circle with a dome on top** (the dome = pneumatic actuator) |
| `valve_gen` | Any other valve (UZV, PV, FV, VM, SV, NV etc.) |
| `actuator_motor` | Motor actuator — **square box with letter M** sitting on top of a valve |
| `actuator_pneu` | Pneumatic actuator — **dome or diaphragm shape** above the valve body |
| `actuator_sol` | Solenoid — **"SL" text in a box** or coil symbol near a valve |

### What NOT to annotate (common mistakes)
- **Pump symbols** (labelled 62-P-151005 etc.) — equipment, not valves
- **M symbols on pumps** — these are pump motors, not valve actuators
- **Instrument circles** (PDT, FT, LT, PT — circles with letters) — instruments, not valves
- **Text labels** themselves — only the valve symbol body, not the tag text next to it

### The tool: Label Studio
Label Studio is a free, open-source annotation tool that runs locally in a browser.
We run it via Docker so nothing is installed on your machine permanently.

**Current URL**: http://localhost:8090

### Step-by-step annotation workflow
1. Open http://localhost:8090
2. Open a task (image tile)
3. Select a label from the left panel (or press hotkey 1-0)
4. Click and drag to draw a rectangle around the valve symbol
5. Repeat for every valve on the tile
6. Click Submit (saves and moves to next tile)

**Hotkeys** (saves a lot of time):
- `1` through `7` = select valve class
- `8`, `9`, `0` = select actuator class
- `Space` = submit current annotation and go to next
- `Ctrl+Z` = undo last box
- Scroll wheel = zoom in/out

### How to use the ground truth to guide annotation
Each drawing's CSV (`job_outputs/N/valve_list.csv`) tells you which valves exist.
Cross-reference while annotating:
- If the CSV says valve `151031` (BF type) is in this drawing, find the bowtie symbol
- This prevents missing valves that are hard to spot

### How long does annotation take?
Roughly 10–15 minutes per tile × 45 tiles = **8–11 hours total**.
You don't have to do it all at once. Label Studio saves progress automatically.

---

## 3. YOLO — Object Detection

### What is object detection?
Object detection = "find all objects of these types in this image and draw boxes around them"

It's different from:
- **Image classification** = "what is this image of?" (one answer for the whole image)
- **Object detection** = "where are all the cats in this image, and where exactly?" (boxes + labels)

### What is YOLO?
YOLO stands for **You Only Look Once**.
It's a family of fast object detection models. We use **YOLOv8** (version 8, released 2023).

Before YOLO, detection was slow (models looked at many regions separately).
YOLO looks at the whole image once and outputs all detections simultaneously — hence the name.

### How YOLO learns (training)
1. You give it thousands of annotated images (image + box coordinates + labels)
2. It learns patterns: "bowtie shapes crossing horizontal lines = butterfly valve"
3. After training, it can detect these patterns in new images it has never seen

### What is "pre-trained" and "fine-tuning"?
- **Pre-trained**: A model already trained on millions of general images (COCO dataset — cars, people, dogs, etc.)
- **Fine-tuning**: Taking that pre-trained model and training it further on YOUR specific images

We use `yolov8s.pt` (pre-trained on COCO) and fine-tune it on our P&ID tiles.
This works because:
- Valve symbols share geometric primitives with COCO objects (circles, lines, diamonds)
- Fine-tuning needs far less data (~190 examples vs millions for from-scratch)
- It converges in ~20-30 epochs instead of 100+ from scratch

### What is `imgsz=1280`?
YOLO resizes all input images to a fixed size for training/inference.
Default is 640×640 pixels. We use **1280×1280**.

Why? Because our tile images are large (1600×900px approx) and valve symbols are SMALL
(roughly 40-80 pixels). At 640px, small symbols fall below the detection threshold.
At 1280px, the model can see them clearly.

The tradeoff: 1280px uses more RAM and runs slower.

### What is a "confidence threshold"?
When YOLO detects something, it gives a confidence score (0.0 to 1.0).
- 0.95 = very confident it's a valve
- 0.35 = not very sure

We use `conf=0.35` as minimum — below this, the detection is discarded.
- Too high threshold (0.7) → misses real valves (low recall)
- Too low threshold (0.2) → detects non-valves as valves (low precision)

### YOLO output format (what the model returns)
```python
results = model.predict("tile.png")
for box in results[0].boxes:
    x1, y1, x2, y2 = box.xyxy[0]   # bounding box corners
    class_id = int(box.cls[0])       # which class (0=valve_bf, 1=valve_bv, etc.)
    confidence = float(box.conf[0])  # how sure the model is
```

### YOLO dataset format (what annotation must produce)
Each image has a corresponding `.txt` file with one line per object:
```
class_id  center_x  center_y  width  height
```
All values are normalized 0.0-1.0 (relative to image size). Example:
```
0  0.523  0.341  0.042  0.031
```
= class 0 (valve_bf), centered at 52.3% from left, 34.1% from top, 4.2% wide, 3.1% tall

Label Studio exports this format automatically when you choose "YOLO" export.

---

## 4. PaddleOCR

### What is OCR?
OCR = **Optical Character Recognition** — reading text from images.

In our case: the tile images contain text labels (valve tags like "62-BF-151031" and
line numbers like `20"-W-62151019-BGA`) printed in engineering drawing fonts.
OCR reads these characters and returns the text.

### Why PaddleOCR specifically?

| Engine | Why we chose / rejected |
|--------|------------------------|
| **Tesseract** | Old, poor on small/rotated text, needs heavy preprocessing |
| **EasyOCR** | Good general purpose but slower, less accurate on dense technical text |
| **PaddleOCR** | ✅ Best accuracy on dense, small, rotated engineering text. Free, offline, fast |
| **TrOCR** | Very accurate but too slow without a GPU |

### What `use_angle_cls=True` means
Line number labels on P&IDs run **parallel to the pipe** — which means they're often rotated 90°.
This setting makes PaddleOCR detect text at any angle, not just horizontal.

### What PaddleOCR returns
```python
result = ocr.ocr("tile.png")
# Returns list of detected text regions:
# [
#   [[[x1,y1],[x2,y2],[x3,y3],[x4,y4]], ("62-BF-151031", 0.97)],
#   [[[x1,y1],[x2,y2],[x3,y3],[x4,y4]], ("20\"-W-62151019-BGA", 0.89)],
# ]
```
Each entry has:
- 4 corner points of the text bounding box (a quadrilateral, not always a rectangle)
- The text string
- Confidence score

### Common OCR errors on engineering drawings
- `O` vs `0` (letter O vs digit zero) — in serial numbers, usually should be 0
- `l` vs `1` (lowercase L vs digit one)
- `"` (double-quote for inches) misread as `''` or `"` (curly quote)
- `-` (hyphen in line numbers) misread as `—` (em dash) or `_` (underscore)

We fix these in `ocr_normalize.py` using regex rules.

---

## 5. Spatial Association

### The problem
After YOLO detects valve symbols and PaddleOCR reads all text in the tile, we have:
- A list of valve boxes: `[{bbox: ..., class: "valve_bf"}, ...]`
- A list of text strings with their positions: `[{bbox: ..., text: "62-BF-151031"}, ...]`

But we don't know WHICH text belongs to WHICH valve.
This is the "spatial association" problem.

### How we solve it
**Rule 1: The valve tag is the nearest tag-format text to the valve symbol**
```
For each detected valve:
  search within 2.5 × symbol_size radius
  find text that matches the tag regex (e.g. "62-BF-151031")
  pick the closest one
```

**Rule 2: The line number runs parallel to the pipe, further away**
```
For each detected valve:
  search within 5.0 × symbol_size radius
  find text that matches line number pattern (starts with digit, contains "-")
  score by: distance + angle alignment with the pipe direction
  pick the best scoring one
```

**Rule 3: Pipe tracing for hard cases (Pass 2)**
```
If no line number found in Rule 2:
  detect pipe segments in the image using OpenCV line detection
  find the pipe the valve sits on
  follow that pipe to find its label text
```

### Why this is harder than just using an LLM
The Claude Vision API understands the *meaning* of "trace the pipe the valve is mounted on."
Our spatial associator uses pure geometry — it doesn't understand meaning.
For clear, well-structured P&IDs it works well.
For complex overlapping pipes it needs tuning.

This is why `corrections.py` exists — for cases where the geometry alone can't determine
the right answer, an engineer manually specifies the correct values.

---

## 6. Key ML Concepts

### Training vs Inference
- **Training**: Showing the model thousands of examples so it learns. Slow, done once (or few times).
- **Inference**: Using the trained model to make predictions on new images. Fast, done every time.

### Epochs
One epoch = the model has seen all training images once.
We train for 100 epochs = the model sees all 45 tiles 100 times, learning a little each time.

### mAP — Mean Average Precision
The main accuracy metric for object detection. Range: 0 to 1 (or 0% to 100%).
- **mAP@0.5** means: at 50% overlap threshold between predicted and actual boxes
- mAP = 0.85 means the model is 85% accurate overall across all classes
- Our target: mAP@0.5 > 0.80

### Recall vs Precision
- **Recall**: Of all real valves in the drawing, what % did we find? (catching everything)
- **Precision**: Of all detections we made, what % were actually valves? (not hallucinating)

High recall + high precision = ideal
Low recall = missing valves (bad — client doesn't get complete list)
Low precision = detecting non-valves as valves (bad — client gets wrong data)

### Overfitting
When a model memorizes the training data instead of learning general patterns.
Signs: works perfectly on training tiles but poorly on new drawings.
Solution: use more diverse training data, data augmentation, train/val split.

### Data Augmentation
Artificially creating more training examples from existing ones by applying transformations:
- Flip horizontally (butterfly valve looks the same flipped)
- Rotate ±15°
- Adjust brightness/contrast (simulates different scan qualities)
- Add noise (simulates scanner artifacts)

With only 45 tiles, augmentation is critical — it effectively multiplies our dataset size.

### ONNX Export
After training, we export the model to **ONNX** (Open Neural Network Exchange) format.
ONNX is a standard format that can run without PyTorch installed.
- PyTorch (~2GB) is the training framework
- ONNX Runtime (~50MB) is the inference runtime
- This makes the production deployment much lighter

### Transfer Learning
Using knowledge from one task to help with another.
We use a model pre-trained on 80 general object classes (COCO dataset) and
transfer that knowledge to our 10 P&ID valve classes.
The model already knows "circles", "lines", "diamonds" from COCO — it just needs to
learn which combinations mean "butterfly valve".

---

## 7. File Structure

```
qong_poc/
│
├── HOWTO_AND_LEARNING_GUIDE.md   ← You are here
├── OWN_SYSTEM_DESIGN.md          ← Full technical architecture
├── CLAUDE.md                      ← AI assistant instructions
│
├── pipeline.py                    ← Main orchestrator
├── pdf_to_tiles.py                ← PDF → PNG tiles (unchanged)
├── extractor.py                   ← CURRENT: sends tiles to API (to be replaced)
├── parser.py                      ← Parses tag/line text → CSV columns (unchanged)
├── corrections.py                 ← Manual overrides per drawing (unchanged)
├── validator.py                   ← Validates output, writes CSV (unchanged)
├── prompts.py                     ← Claude Vision prompts (documents association rules)
│
├── train.py                       ← YOLOv8 training script
│
├── annotate/
│   ├── export_tiles_for_annotation.py   ← Copies tiles to annotate/tiles/
│   ├── label_studio_config.xml          ← Paste into Label Studio settings
│   ├── label_studio_setup.md            ← Step-by-step annotation guide
│   └── tiles/                           ← 45 PNGs ready for annotation (gitignored)
│
├── datasets/
│   └── pid_valves/
│       ├── data.yaml              ← YOLO dataset config (10 classes)
│       ├── images/train/          ← Training tile images (from annotation export)
│       ├── images/val/            ← Validation tile images
│       ├── labels/train/          ← YOLO .txt label files
│       └── labels/val/
│
├── models/
│   ├── best.onnx                  ← Trained model for production (gitignored, large)
│   └── [paddle weights]           ← PaddleOCR model files (gitignored, large)
│
├── webapp/                        ← FastAPI web application (unchanged)
│
└── job_outputs/                   ← Per-job results (gitignored)
    └── {job_id}/
        ├── input.pdf
        ├── valve_list.csv
        └── tmp/
            ├── tile_p0_r0_c0.png  ← The 9 tiles used for extraction
            └── raw_extractions.json
```

### Key distinction: `main` branch vs `feature/own-system` branch
- `main` branch: the current working system (API-based). Always deployable. Don't break this.
- `feature/own-system` branch: where we build the offline system. Experimental. Will be merged when ready.

---

## 8. How to Run Each Step

### Start Label Studio (annotation tool)
```bash
docker start label-studio          # if already created
# OR first time:
docker run -d --name label-studio -p 8090:8080 \
  -v "$(pwd)/annotate/tiles:/label-studio/tiles" \
  -v "$(pwd)/annotate/ls_data:/label-studio/data" \
  -e LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true \
  heartexlabs/label-studio:latest
# Open: http://localhost:8090
```

### Export tiles for annotation
```bash
python3 annotate/export_tiles_for_annotation.py
# Creates annotate/tiles/ with 45 named PNG files
```

### Train the YOLO model (after annotation is done)
```bash
pip install ultralytics
python3 train.py
# Takes 2 hrs on GPU, 12-18 hrs on CPU
# Outputs: runs/detect/pid_valves_v1/weights/best.pt
```

### Export trained model to ONNX (for production)
```bash
python3 train.py --export runs/detect/pid_valves_v1/weights/best.pt
# Outputs: runs/detect/pid_valves_v1/weights/best.onnx
# Copy to: models/best.onnx
```

### Run the local webapp (API-based, main branch)
```bash
OPENROUTER_API_KEY=sk-or-v1-... python3 -m uvicorn webapp.main:app --port 8000 --reload
# Open: http://localhost:8000
```

### Check job status
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('webapp.db')
c = conn.cursor()
c.execute('SELECT id, original_filename, status, valve_count FROM jobs ORDER BY id')
for r in c.fetchall(): print(r)
"
```

### Deploy to production server
```bash
git push origin main
# Webhook auto-deploys to https://dev.theqong.com
# Takes ~30 seconds
```

---

## 9. How to Judge If It's Working

### During annotation
- Are you finding roughly the same number of valves per tile as the CSV shows?
- Are valve symbols clearly distinguishable at your zoom level?
- If a symbol is ambiguous, zoom in more before deciding

### After YOLO training
Open `runs/detect/pid_valves_v1/results.png` (auto-generated).
Look for:
- `mAP50` curve going up and plateauing → good training
- `mAP50` curve not improving → need more data or adjust learning rate
- Training loss going down, validation loss going down together → healthy
- Training loss going down but validation loss going up → overfitting (memorizing, not learning)

**Target: mAP50 > 0.80**

### After full pipeline runs
Compare output CSV against the ground truth CSV:
```bash
python3 -c "
import pandas as pd
gt = pd.read_csv('docs/Output-Valve List.csv')
out = pd.read_csv('job_outputs/2/valve_list.csv')
print('Ground truth valves:', len(gt))
print('Our output valves:', len(out))
# Find which serials we missed
gt_serials = set(gt['Serial No'].astype(str))
out_serials = set(out['serial_no'].astype(str))
missed = gt_serials - out_serials
extra = out_serials - gt_serials
print('Missed:', missed)
print('Extra (hallucinations):', extra)
"
```

**Target: recall ≥ 90% (miss no more than 1 in 10 valves)**

### Quality checks for each valve row
A "complete" row has all 3 key fields filled:
- **Size**: a number (2, 4, 6, 8, 10, 16, 20) — not "NOT DEFINED"
- **Fluid Code**: a letter code (W=Water, P=Process, D=Drain, etc.)
- **Piping Class**: an alphanumeric code (BGA, H5-IN, etc.)

**Target: ≥90% complete rows**

---

## 10. Glossary

| Term | Plain English |
|------|--------------|
| **P&ID** | Piping & Instrumentation Diagram — engineering drawing showing pipes, valves, instruments |
| **Valve tag** | The alphanumeric label on each valve, e.g. `62-BF-151031` |
| **Line number** | Label on each pipe showing size, fluid type, and spec, e.g. `20"-W-62151019-BGA` |
| **Tile** | A cropped section of the full P&ID image. We split each drawing into 9 overlapping tiles |
| **Bounding box** | A rectangle drawn around an object in an image. The core output of object detection |
| **Class** | The category label assigned to a bounding box (e.g. `valve_bf`) |
| **Annotation** | The process of manually drawing bounding boxes and assigning class labels |
| **Ground truth** | The correct answers — in our case, the manually verified valve list CSV |
| **YOLO** | You Only Look Once — our object detection model family (we use YOLOv8) |
| **mAP** | Mean Average Precision — main accuracy score for object detection (higher = better) |
| **Recall** | % of real valves that we detected (missing valves = low recall) |
| **Precision** | % of our detections that are actually valves (false detections = low precision) |
| **Training** | Showing labeled examples to a model so it learns patterns |
| **Inference** | Using a trained model to make predictions on new data |
| **Epoch** | One complete pass through all training data |
| **Overfitting** | Model memorizes training data but fails on new data |
| **Fine-tuning** | Training a pre-trained model further on specific data |
| **Transfer learning** | Reusing knowledge from one task to help with another |
| **OCR** | Optical Character Recognition — reading text from images |
| **ONNX** | Open Neural Network Exchange — portable model format for deployment |
| **Confidence score** | How certain the model is about a detection (0.0 to 1.0) |
| **Threshold** | Minimum confidence to accept a detection |
| **Augmentation** | Artificially creating more training data by transforming existing images |
| **Label Studio** | Open-source annotation tool we use to draw bounding boxes |
| **PaddleOCR** | The OCR library we use to read text from P&ID tile images |
| **Spatial association** | Linking a detected valve symbol to its nearby tag text and line number |
| **DB valve** | Double Block & Bleed valve — always on a 2" instrument tap line |
| **Actuator** | A mechanism that opens/closes a valve automatically (motor, pneumatic, solenoid) |
| **API** | Application Programming Interface — in our case, the cloud AI service we're replacing |
| **OpenRouter** | The AI API gateway we currently use (routes to Claude, Gemini, etc.) |
| **Docker** | Container technology that runs apps in isolated environments (we use it for Label Studio) |
| **FastAPI** | Python web framework used for the webapp |
| **SQLite** | Lightweight database (single file `webapp.db`) used to store job results |
| **Git branch** | Parallel version of the code. `main` = stable, `feature/own-system` = in-development |
| **Webhook** | Automatic trigger: when code is pushed to GitHub, server pulls and restarts |

---

## Quick Reference: The Annotation Priority Order

Do drawings in this order (easiest to hardest):

1. **job2_MUK-1004** (28 valves) — start here, it's the one we know best, smallest
2. **job3_MUK-1003** (35 valves) — similar structure
3. **job1_MUK-1005** (34 valves) — pump arrangement, all manual valves
4. **job4_MUK-1002** (42 valves) — has actuated valves (good for training actuator classes)
5. **job5_MUK-1001** (54 valves) — largest, most complex, save for last

After annotating 3 drawings (~25 tiles), you could already do a first training run
to see if the model is learning — no need to annotate all 45 before getting feedback.

---

## Next Steps After Annotation

```
1. Annotate 45 tiles in Label Studio       → ~11 hrs
2. Export YOLO format → datasets/ folder   → 10 min
3. python3 train.py                        → 2-18 hrs depending on hardware
4. Evaluate: check mAP, run on test tile   → 1 hr
5. Build detector.py (code the associator) → 2-3 days coding
6. End-to-end test on 5 drawings           → 1 hr
7. Merge feature/own-system → main         → done
```

Total estimate from annotation start to working offline system: **2–3 weeks**
(most of that is annotation time, not coding)
