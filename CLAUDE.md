# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Goal

Extract a **Valve List** from scanned P&ID drawings (PDFs) and output a structured CSV.
Target: **≥90% recall** on valve identification.

**Current status**: Production webapp live at https://dev.theqong.com
**Next phase**: Replace API with own offline model (see `OWN_SYSTEM_DESIGN.md`)

## Branches

- `main` — stable, production-deployed API-based pipeline
- `feature/own-system` — offline YOLO+PaddleOCR system (annotation → training → replace extractor.py)

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

## Current Architecture (main branch — API-based)

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

## Webapp Features (production at https://dev.theqong.com)

- Login/register (JWT cookie auth). Admin: `admin / Qong@2024`
- Upload P&ID PDF → background pipeline job (serialized via `_pipeline_lock`)
- Dashboard: job list with status, valve count, processing time
- Job detail: valve table, collapsible AI log, engineer feedback
- Control valve toggle, job re-run, CSV download per job
- Auto-extract Drawing No. from title block (bottom-right 40%×22% crop)

## Environment

- Python 3.12 server (Ubuntu 24.04), Python 3.9 local dev
- Use `Optional[X]` not `X | None`, use `python3` not `python`
- OpenRouter API: `OPENROUTER_API_KEY` env var required (not Anthropic directly)
- Default model: `google/gemini-2.0-flash-001` (fast); override via `OPENROUTER_MODEL`
- Temp files → `tmp/` per job in `job_outputs/{job_id}/tmp/` (never commit)

## Deployment (Production)

- Server: `root@157.180.20.168` (Ubuntu 24.04, aaPanel)
- App: FastAPI + uvicorn, port 8001, systemd `qong_poc`
- Nginx: `/www/server/panel/vhost/nginx/dev.theqong.com.conf`
- Code: `/www/wwwroot/qong_poc/`, auto-deploy via GitHub webhook
- **To deploy**: `git push origin main` (webhook triggers pull + restart)
- SSH alias for Winn-Projects GitHub: `winn-projects`

## DB Schema Notes

- SQLite at `webapp.db` (local) — NOT committed
- `run_migrations()` in `database.py` handles ALTER TABLE on startup
- Job columns: `processing_time` (Float), `processing_log` (Text), `include_control_valves` (Bool),
  `original_filename` (Str) — used to derive `drawing_stem` for corrections lookup

## Critical Bug Fixes (already applied)

1. **Corrections not applying**: `pipeline_runner.py` passes `input.pdf` as path →
   `drawing_stem` was always `"input"`. Fixed: pass `original_filename` through to `pipeline.run()`.
2. **DB valve size NOT DEFINED**: Parser now auto-assigns size=`"2"` for DB category.
3. **P&ID No truncated**: Title block prompt updated to capture full revision suffix (e.g. `24C7-D`).
4. **Jinja2 template path**: Use `Path(__file__).parent.parent / "templates"` (absolute) in all 3 router files.
5. **Stale processing jobs**: Reset to `failed` on app startup.

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

## Own System Design (feature/own-system branch)

See `OWN_SYSTEM_DESIGN.md` for full spec. Summary:
- **Detection**: YOLOv8s ONNX at imgsz=1280, 10 classes (8 valve + 2 actuator types)
- **OCR**: PaddleOCR PP-OCRv4, `use_angle_cls=True`
- **Association**: geometric spatial linking (symbol bbox → tag text → line text)
- **Annotation tool**: Label Studio (local), ~11 hrs to annotate all 45 tiles
- **Integration**: `detector.py` replaces `extractor.py` with identical public API
- **Pipeline.py change**: one line — `from extractor import` → `from detector import`

### Annotation Classes (10 YOLO classes)
`valve_bf`, `valve_bv`, `valve_ck`, `valve_gl`, `valve_db`, `valve_cv`, `valve_gen`,
`actuator_motor`, `actuator_pneumatic`, `actuator_solenoid`

## Temporary Files

All intermediate files go in `job_outputs/{id}/tmp/` — never commit. Also never commit `webapp.db`, `uploads/`, `job_outputs/`.
