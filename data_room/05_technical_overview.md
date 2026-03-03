# Technical Overview

*For technical VCs and engineering due diligence*

---

## Architecture

```
INPUT: Scanned P&ID PDF (image-based, no embedded text)
       ↓
┌─────────────────────────────────────────────────────┐
│  Stage 1: pdf_to_tiles.py                           │
│  PyMuPDF renders PDF at 3x DPI                      │
│  Splits into 3×3 grid = 9 overlapping PNG tiles     │
│  25% overlap ensures no symbol is cut at boundary   │
└─────────────────────────────────────────────────────┘
       ↓ 9 PNG tiles
┌─────────────────────────────────────────────────────┐
│  Stage 2: extractor.py                              │
│  For each tile:                                     │
│    - Sends tile image + project legend reference    │
│    - AI vision model identifies valve symbols       │
│    - Returns JSON: [{tag, line_no, actuator, conf}] │
│  Model: Claude claude-opus-4-6 (OpenRouter)         │
└─────────────────────────────────────────────────────┘
       ↓ ~50 raw detections (with duplicates)
┌─────────────────────────────────────────────────────┐
│  Stage 3: parser.py                                 │
│  Deduplicates by (AreaCode + SerialNo)              │
│  Parses valve tag → Category, Area, Serial          │
│  Parses line number → Size, Fluid Code, Piping Class│
│  Maps actuator code → Dynamic Code + Motor/Pneu/Sol │
└─────────────────────────────────────────────────────┘
       ↓ 27 unique structured rows
┌─────────────────────────────────────────────────────┐
│  Stage 4: validator.py                              │
│  Regex validates tag format: ^\d{2}-[A-Z]{2,3}-\d+ │
│  Flags missing Size / PipingClass for review        │
│  Outputs final CSV                                  │
└─────────────────────────────────────────────────────┘
       ↓
OUTPUT: output_valve_list.csv (14-column structured data)
```

---

## Current Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| PDF processing | PyMuPDF (fitz) | Renders scanned PDF to high-res PNG |
| Image tiling | Pillow | Splits image into overlapping tiles |
| AI vision | Claude Vision API (via OpenRouter) | Reads symbols, text, spatial relationships |
| Parsing | Python (regex, pandas) | Structures raw AI output into CSV columns |
| API / Backend | FastAPI | REST API for job submission and status |
| Database | SQLite | Job queue, user accounts, output storage |
| Frontend | Jinja2 templates (HTML/CSS) | Upload UI, job dashboard, CSV download |
| Auth | JWT (python-jose) | User registration, login, session tokens |
| Deployment | Docker + Ubuntu VPS | Production server at dev.theqong.com |
| CI/CD | Webhook auto-deploy | Push-to-deploy pipeline |

---

## Key Engineering Decisions

### Why AI Vision Instead of Traditional CV?

Traditional computer vision approaches (YOLO object detection, template matching) require:
- A labeled training dataset of P&ID valve symbols
- The dataset must cover the specific symbol style used by each project
- Different EPC firms use slightly different P&ID notation standards

Building a YOLO training set would take 4–6 weeks before the first valve is detected.

**Claude Vision** can read P&ID symbols out-of-the-box because it was trained on a vast corpus including engineering drawings. We provide the project legend as a reference image, and it correctly identifies all valve types with no training data required.

This is the correct first step. Phase 2 is the own-model approach — but only after we have real labeled data from Phase 1 outputs.

### Why 25% Tile Overlap?

A 4,768 × 3,368 px drawing tiled into a 3×3 grid produces tiles of ~1,589 × 1,123 px. At tile boundaries, valve symbols may be partially cut. With 25% overlap:
- Every point in the drawing appears in at least one complete tile
- Valves at boundaries appear in two tiles
- Deduplication by (AreaCode + SerialNo) collapses these to one row

This is the core accuracy mechanism. Without overlap, recall at tile boundaries drops significantly.

### Why PyMuPDF at 3x DPI?

The source PDFs are scanned at ~150 DPI. At native resolution, small text (valve tags like `62-BF-151031`) is 8–10 pixels tall — too small for reliable vision model reading.

Rendering at 3x (450+ effective DPI) makes all text clearly legible. The tradeoff is larger files and slower tile generation — acceptable for a processing pipeline.

---

## Prompting Architecture

The extraction prompt is structured in `prompts.py`:

```
System prompt:
  - Expert P&ID engineer persona
  - Valve symbol definitions (all codes: BF, BV, VC, VM, VG, VGL, NV, SV)
  - Actuator symbol definitions (M=Motor, P=Pneumatic, SL=Solenoid)
  - Output format specification (JSON array only)
  - Example expected output

User message:
  - Tile image (base64 encoded)
  - Legend reference image (first page of project legend PDF)
  - Instruction: "Find all valves in this P&ID section"
```

The legend image is included with every API call. This means the AI adapts to the specific symbol set used in each project's drawing package without any re-configuration.

---

## Cost Model

### Phase 1 (Current — Claude Vision API)

| Component | Tokens | Cost (Claude claude-opus-4-6) |
|-----------|--------|---------------------------|
| Tile image | ~1,600 image tokens | |
| Legend image | ~800 image tokens | |
| System + user text | ~500 text tokens | |
| Response (JSON) | ~200 output tokens | |
| **Per tile** | ~3,100 tokens | **~$0.02** |
| **Per P&ID (9 tiles)** | ~28,000 tokens | **~$0.18** |

### Phase 2 (Own Model — Target)

| Component | Cost |
|-----------|------|
| YOLO inference | ~$0.001/image (GPU) |
| OCR (PaddleOCR or custom) | ~$0.001/image |
| **Per P&ID** | **< $0.01** |

Phase 2 eliminates the API dependency entirely. The model runs on our own GPU infrastructure. Marginal cost per drawing drops by ~95%.

---

## Phase 2 — Own Model Roadmap

### Training Data Strategy

Every Phase 1 extraction generates labeled data:
- Input: P&ID tile PNG
- Label: Valve bounding boxes + tag text (from AI extraction + human validation)

After processing 500–1,000 drawings, we have a dataset sufficient to train a YOLO model specialized for P&ID valve detection.

### Architecture

```
Stage 1: YOLO v8 (object detection)
  - Detects valve symbol bounding boxes
  - Classifies type: BF, BV, VC, VM, etc.
  - Detects actuator symbols attached to valves

Stage 2: PaddleOCR (or custom OCR)
  - Reads text within detected regions
  - Extracts valve tag and adjacent line number

Stage 3: Parser + Validator (same as Phase 1)
  - Structures detections into CSV columns
```

### Training Requirements

- Dataset: ~5,000 annotated tile images (achievable in 6 months of POC operation)
- Compute: 1× NVIDIA A100 × 48 hours training run ($200–400 one-time)
- Inference: 1× NVIDIA T4 in production (~$0.50/hr spot instance)

---

## Security & Data Handling

- All uploaded P&IDs are processed server-side and stored per-user in isolated directories
- No P&ID data is retained beyond the user's session unless explicitly saved
- API keys stored in environment variables, not in code or database
- JWT-based authentication with configurable expiry
- HTTPS enforced in production (Nginx + Let's Encrypt)

---

## File Reference

```
qong_poc/
├── pipeline.py          # Orchestrates all stages end-to-end
├── pdf_to_tiles.py      # Stage 1: PDF → PNG tiles (PyMuPDF)
├── extractor.py         # Stage 2: AI vision extraction per tile
├── parser.py            # Stage 3: Parse + deduplicate
├── validator.py         # Stage 4: Validate + output CSV
├── prompts.py           # All Claude prompt templates
├── webapp/
│   ├── main.py          # FastAPI app entry point
│   ├── routers/         # auth, dashboard, jobs, feedback routes
│   ├── templates/       # Jinja2 HTML templates
│   ├── models.py        # SQLAlchemy ORM models
│   ├── database.py      # DB connection + migration
│   └── pipeline_runner.py  # Async job runner
├── Dockerfile           # Container build
└── docker-compose.yml   # Production deployment config
```
