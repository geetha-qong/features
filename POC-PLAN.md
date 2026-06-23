# POC Plan: Automated Valve List Extraction from P&ID

## Problem Statement

Given a scanned P&ID drawing (image-based PDF, no embedded text), extract all valves and output a structured CSV matching `docs/Output-Valve List.csv` format.

**Why it's hard:**
- P&ID is a raster image — no selectable text
- Valve symbols are small and dense
- Each valve needs 3 data sources: tag (symbol label), adjacent line number, actuator symbols
- 90%+ recall required — must not miss valves

---

## Root Cause Analysis of the Input

From examining `INPUT-MUK-62-1-15-1004-001-24C7-D.pdf`:

```
P&ID drawing: FW Transfer Pump (62-P-151005)
Image size: 4768 × 3368 px (2x zoom of A1-size drawing)
Valve tag format: [AreaCode]-[TypeCode]-[SerialNo]
  Example: 62-BF-151031
Line number format: [Size]"-[FluidCode]-[AreaCode][SerialNo]-[PipingClass]
  Example: 20"-W-62151031-BGA
```

Each CSV row is assembled from:
1. **Valve tag** → Area Code + Category + Serial No
2. **Adjacent line number** → Size + Fluid Code + Piping Class + line
3. **Actuator symbol** → Dynamic Code + Motor/Pneumatic/Solenoid columns
4. **Title block** → P&ID No

---

## Recommended Approach: Claude Vision Tile Pipeline

### Why not traditional CV (YOLO/template matching)?
- No training data for these specific P&ID symbols
- Template matching breaks with scale/rotation variations
- Building a training dataset adds weeks; Claude Vision works today

### Why Claude Vision?
- Can read text labels directly — no separate OCR step
- Understands spatial context (valve + adjacent tag + line number)
- Legends can be passed as reference images
- Achievable in days, not weeks

---

## Pipeline Architecture

```
Stage 1: PDF → Tiles
┌─────────────────────────────────────┐
│  pdf_to_tiles.py                    │
│  PyMuPDF renders PDF at 3x DPI      │
│  Split into 3×3 grid = 9 tiles      │
│  25% overlap between tiles          │
│  Output: tmp/tile_r{r}_c{c}.png     │
└─────────────────────────────────────┘

Stage 2: Per-Tile Vision Extraction
┌─────────────────────────────────────┐
│  extractor.py                       │
│  For each tile:                     │
│    - Send tile + legend summary     │
│    - Claude returns JSON list of    │
│      detected valves with:          │
│      {tag, line_no, actuator,       │
│       size, confidence}             │
└─────────────────────────────────────┘

Stage 3: Parse + Deduplicate
┌─────────────────────────────────────┐
│  parser.py                          │
│  - Deduplicate by (AreaCode+Serial) │
│  - Parse tag → Category, Area, Ser  │
│  - Parse line_no → Size, Fluid,     │
│    PipingClass                      │
│  - Map actuator → Dynamic Code +    │
│    Motor/Pneumatic/Solenoid columns │
└─────────────────────────────────────┘

Stage 4: Validate + Output
┌─────────────────────────────────────┐
│  validator.py                       │
│  - Regex check on tag format        │
│  - Flag missing Size / PipingClass  │
│  - Output CSV to docs/              │
└─────────────────────────────────────┘
```

---

## Implementation

### File Structure
```
qong_poc/
├── pipeline.py          # Main entry point
├── pdf_to_tiles.py      # Stage 1: PDF → PNG tiles
├── extractor.py         # Stage 2: Claude Vision extraction
├── parser.py            # Stage 3: Parse tags → CSV columns
├── validator.py         # Stage 4: Validate + output CSV
├── prompts.py           # All Claude prompt templates
├── docs/                # Input/output files (do not commit PDFs if proprietary)
├── tmp/                 # Intermediate tiles and debug images
└── CLAUDE.md
```

---

## Prompt Design (Critical for 90%+ Accuracy)

### System Prompt for Valve Extraction
```
You are a P&ID (Piping & Instrumentation Diagram) expert.
You will be shown a section of a P&ID drawing.

VALVE SYMBOLS to look for (from project legends):
- Butterfly valve (BF): bowtie/diamond shape on a pipe line
- Ball valve (BV/VB): circle with a line through it
- Check valve (VC): arrow or half-circle on pipe
- Manual gate/globe valve (VM): bow-tie shape
- Control valve: circle with a line, often with actuator symbol above
- Safety/relief valve (SV): specific arrow-up symbol

ACTUATOR SYMBOLS attached to valves:
- Motor actuator (M): square box with "M" or motor symbol
- Pneumatic actuator (P): half-circle/dome above valve
- Solenoid (SL): "SL" text or coil symbol

For EACH valve you identify, extract:
1. valve_tag: the alphanumeric tag near the valve symbol (e.g. "62-BF-151031")
2. line_number: the pipe line label near the valve (e.g. "20\"-W-62151031-BGA")
3. actuator: "M" | "P" | "SL" | "none"
4. confidence: 0.0-1.0

Return ONLY a JSON array. No explanation.
Example:
[
  {"valve_tag": "62-BF-151031", "line_number": "20\"-W-62151031-BGA", "actuator": "none", "confidence": 0.95},
  {"valve_tag": "62-BV-151073", "line_number": "2\"-W-62151073-BGA", "actuator": "none", "confidence": 0.9}
]
```

### Tag Parsing Logic
```python
# Valve tag: "62-BF-151031"
parts = tag.split("-")
area_code = parts[0]       # "62"
type_code = parts[1]       # "BF"
serial_no  = parts[2]      # "151031"

# Line number: "20\"-W-62151031-BGA"
# Regex: (\d+)["']-([A-Z]+)-(\d+)-([A-Z0-9\-]+)
size       = match.group(1)   # "20"
fluid_code = match.group(2)   # "W"
piping_cls = match.group(4)   # "BGA"

# Actuator mapping
dynamic_code   = {"M": "M", "P": "P", "SL": "SL", "none": "-"}[actuator]
motor_act      = "x" if actuator == "M" else "-"
pneumatic_act  = "x" if actuator == "P" else "-"
solenoid       = "x" if actuator == "SL" else "-"
```

---

## Accuracy Strategy: How to Hit 90%+

| Risk | Mitigation |
|------|-----------|
| Valve missed at tile boundary | 25% tile overlap — valve appears in 2 tiles, dedup by tag |
| Small text unreadable | Render PDF at 3x DPI (300→450 DPI effective); use 9-tile grid not 4 |
| Wrong tag read (OCR error) | Validate tag regex `^\d{2}-[A-Z]{2,3}-\d{6}$`; flag for review |
| Line number not near valve | Claude sees spatial context in tile; fallback: search surrounding tile area |
| Actuator misidentified | Always cross-check: if `M` in Dynamic Code → Motor Actuator must be `x` |
| Novel valve types | Include legends page 0 image as reference with every API call |

---

## Phase 1: Minimum Working POC (Day 1–2)

Goal: Get _any_ valves into CSV, verify format is correct.

1. `pdf_to_tiles.py` — render PDF to 9 PNG tiles
2. `extractor.py` — call Claude Vision on 2-3 tiles, print raw JSON
3. `parser.py` — parse JSON → CSV rows manually
4. Compare against `docs/Output-Valve List.csv`

## Phase 2: Full Pipeline (Day 3–4)

1. Run all 9 tiles
2. Implement deduplication
3. Add full line number regex parser
4. Generate complete CSV

## Phase 3: Accuracy Tuning (Day 5)

1. Count matches against ground truth CSV
2. Identify missed/wrong valves
3. Refine prompt or add tile-specific re-runs for missed areas
4. Target: ≥90% recall, ≥85% full-row accuracy

---

## Ground Truth Validation

From `docs/Output-Valve List.csv`, the known valve from this P&ID:
```
MUK-1004-001 | - | BF | 20 | 62 | 151031 | - | W | BGA | 1 | - | - | - |
```

This confirms:
- Valve `62-BF-151031` on line `20"-W-62151031-BGA`
- Manual valve (no actuator)
- P&ID reference `MUK-1004-001`

Use this as the validation anchor for pipeline testing.

---

## API Cost Estimate

| Tiles | Image tokens/tile | Calls | Est. cost |
|-------|------------------|-------|-----------|
| 9 tiles × 1 P&ID | ~1,600 tokens | 9 | ~$0.05 |
| With legends context | +800 tokens/call | 9 | ~$0.10 total |

Extremely low cost for a POC. Can scale to 100+ drawings for <$10.
