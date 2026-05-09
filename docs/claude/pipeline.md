# Pipeline & Domain

Detailed reference for the P&ID extraction pipeline. See `CLAUDE.md` for top-level rules.

## P&ID Document Structure

### Valve Tag Format
`[AreaCode]-[TypeCode]-[SerialNo]` — e.g. `62-BF-151031`

### Line Number Format
`[Size]"-[FluidCode]-[AreaCode][SerialNo]-[PipingClass]` — e.g. `20"-W-62151031-BGA`

### Valve Type Codes
`BF`=Butterfly, `BV`/`VB`=Ball, `DB`=Double Block & Bleed, `CK`=Check, `GL`=Globe,
`VM`=Manual gate/globe, `VG`=Gate, `NV`=Needle, `SV`=Safety, `PV`=Pressure valve,
`UZV`=Ultrasonic zone valve, `FV`=Flow valve, `CV`=Control valve (pneumatic)

### Actuator Codes (Dynamic Code in CSV)
`M`=Motor, `P`=Pneumatic, `SL`=Solenoid, `-`=Manual

### DB Valve Rule
DB (Double Block & Bleed) valves are **always** on 2" instrument taps — size is always `2"`.
Parser auto-assigns size=2 when NOT DEFINED for DB category.

## Output CSV Schema (14 columns)

`P&ID No`, `Dynamic Code`, `Category`, `Size`, `Area Code`, `Serial No`,
`Series Code`, `Fluid Code`, `Piping Class`, `Qty`, `Motor Actuator`,
`Pneumatic Actuator ` *(trailing space — do not remove)*, `Solenoid`, `line`

## Current Architecture (API-based)

```
PDF → pdf_to_tiles.py → 9 PNG tiles (3×3, 25% overlap)
    → extractor.py (OpenRouter API, claude-sonnet-4-6 or gemini-2.0-flash)
      - Pass 1: valve tag + line number per tile
      - Pass 2: targeted line number recovery for misses
      - Stage 0: title block crop → extract Drawing No.
    → parser.py → corrections.py → validator.py → CSV
```

### Key Files
- `pipeline.py` — orchestrator, one-line swap to go offline: `from extractor` → `from detector`
- `pdf_to_tiles.py` — PDF → PNG tiles (PyMuPDF, 3× DPI)
- `extractor.py` — OpenRouter vision API calls, two-pass extraction, title block OCR
- `parser.py` — tag/line regex parser, ValveRow dataclass, deduplication
- `corrections.py` — drawing-specific manual overrides (post-parse, pre-validate)
- `validator.py` — regex validation, CSV writer
- `prompts.py` — all Claude Vision prompt templates
- `webapp/` — FastAPI web app (upload → job queue → results → download)
- `OWN_SYSTEM_DESIGN.md` — full design doc for offline YOLO+PaddleOCR system

## Correction Rules (verified by engineer, MUK-62-1-15-1004)

See `corrections.py` for full list. Key rules:
- Removed hallucinations: 151076, 151077 (not present in drawing)
- DB valves 151025–151028: size corrected
- BF valves 151065–151068: all on line `10"-W-62151021-BGA-H`

## Ground Truth Results (5 P&IDs, Oman MUK project)

| P&ID | Valves | Actuated | Complete Rows |
|------|--------|----------|---------------|
| MUK-62-1-15-1001 | 54 | 6 | ~91% |
| MUK-62-1-15-1002 | 42 | 9 | 100% ✅ |
| MUK-62-1-15-1003 | 35 | 0 | ~97% |
| MUK-62-1-15-1004 | 28 | 1 | ~100% |
| MUK-62-1-15-1005 | 34 | 0 | ~94% |
| **Total** | **193** | **16** | **~93%** |

These 193 valve instances + 45 tiles are the training dataset for the offline system.

## Instrumentation Index (merged to main)

Pipeline generates a 30-column Instrumentation Index CSV alongside the valve CSV:
- `instrument_prompts.py` — Vision prompts (instrument-focused, excludes valves)
- `instrument_parser.py` — `InstrumentRow` dataclass + `TYPE_MAP` (22 type codes → io_type, signal_type)
- `instrument_validator.py` — 30-column CSV writer
- `extractor.py` — `extract_instruments()` single Vision pass per tile
- `pipeline.py` — Stage 5 writes `instrumentation_index.csv` to job dir alongside `valve_list.csv`
- DB column: `output_inst_index_path` on `jobs` table; stored by `pipeline_runner.py` on success

## Instrument Datasheets (merged to main)

Pipeline Stage 5c generates a ZIP of per-instrument HTML spec forms alongside the CSVs:
- `instrument_datasheet.py` — `generate_datasheet_html(inst)` + `write_datasheet_zip(inst_rows, zip_path)`
- Output: `instrument_datasheets.zip` in job dir; one `.html` file per instrument tag
- Fields from P&ID: tag, type, line, equipment, system. Unknown fields → `TBD` (grey italic) or `LATER` (red italic)
- DB column: `output_inst_datasheet_path` on `jobs` table; stored by `pipeline_runner.py` on success
- Download endpoint: `/jobs/{id}/download-inst-datasheets` → ZIP served as `instrument_datasheets_{pid_no}.zip`
- Button shown on job detail page when `output_inst_datasheet_path` is set

## Non-Standard Tag Format P&IDs

Some customer P&IDs use tags like `VB25`, `VB40 2090`, `VBPP40` — no `AreaCode-TypeCode-SerialNo` pattern.
- Parser skips all 0 valves → valve count = 0 in webapp. **This is not a bug** — it's a different naming convention.
- Instrument index extraction still works (instrument bubbles are standard).
- To support these: extend `parser.py` with new regex patterns alongside existing ones (additive, never modify working patterns).

## Offline Detector Recall Improvements (feature/own-system, committed cf21758)

- `_extract_tags_from_tile()` — row-based OCR token clustering (40px y-tolerance), groups 1–4 tokens to reassemble fragmented tags
- `_targeted_crop_ocr()` — 400×400px crop from full-page image centered on YOLO detection; major win for noisy/hatched tiles
- TAG_RE: `(?<!\d)(\d{2})-([A-Z]{2,4})-(\d{6})(?!\d)` — exact 6-digit serial, no leading-digit leakage
- Benchmark (2 drawings): 73.3% recall (44/60), up from 53.4% baseline
- Annotated PDF named after source drawing: `INPUT-MUK-..._annotated.pdf` (not timestamped CSV name)

## Temporary Files

All intermediate files go in `job_outputs/{id}/tmp/` — never commit. Also never commit `webapp.db`, `uploads/`, `job_outputs/`.
