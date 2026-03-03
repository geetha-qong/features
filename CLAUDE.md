# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Goal

POC to automatically extract a **Valve List** from a scanned P&ID drawing (PDF) and output a structured CSV. Target accuracy: **≥90% recall** on valve identification.

- **Input**: `docs/INPUT-MUK-62-1-15-1004-001-24C7-D.pdf` — scanned P&ID (image-based, single page, 4768×3368px)
- **Legends**: `docs/PID-Legends-Oman North Projects.pdf` — 5 pages of P&ID symbol definitions
- **Expected output**: `docs/Output-Valve List.csv` — 14-column valve list

## P&ID Document Structure

### Valve Tag Format
Tags on the drawing follow: `[AreaCode]-[TypeCode]-[SerialNo]`
- Example: `62-BF-151031` → Area=62, Type=BF (Butterfly), Serial=151031

### Line Number Format
Process lines follow: `[Size]"-[FluidCode]-[AreaCode][SerialNo]-[PipingClass]`
- Example: `20"-W-62151031-BGA` → Size=20", Fluid=W (Water), Piping Class=BGA

### Valve Type Codes (from legends)
`BF`=Butterfly, `BV`/`VB`=Ball, `VC`=Check, `VM`=Manual gate/globe, `VG`=Gate, `VGL`=Globe, `NV`=Needle, `SV`=Safety

### Actuator Codes (Dynamic Code in CSV)
`M`=Motor actuator, `P`=Pneumatic actuator, `SL`=Solenoid, `-`=Manual (no actuator)

## Output CSV Schema

| Column | Source |
|--------|--------|
| `P&ID No` | Drawing title block (e.g. `MUK-1004-001`) |
| `Dynamic Code` | Actuator symbol near valve (`M`, `SL`, `P`, `-`) |
| `Category` | Valve type from tag (`BF`, `VB`, `VC`, etc.) |
| `Size` | From adjacent line number annotation |
| `Area Code` | From valve tag prefix (e.g., `62`) |
| `Serial No` | From valve tag suffix (e.g., `151031`) |
| `Series Code` | Usually `-` unless specified |
| `Fluid Code` | From line number fluid segment (`W`, `OC`, `GL`, etc.) |
| `Piping Class` | From line number piping spec (`BGA`, `H5-IN`, `A5-N`, etc.) |
| `Qty` | Always `1` per valve instance |
| `Motor Actuator` | `x` if motor actuator present, else `-` |
| `Pneumatic Actuator` | `x` if pneumatic actuator present, else `-` |
| `Solenoid` | `x` if solenoid present, else `-` |
| `line` | Process line number string |

## Architecture

```
docs/*.pdf
    ↓ fitz (PyMuPDF)          [pdf_to_tiles.py]
High-res PNG tiles (overlapping grid)
    ↓ Claude Vision API        [extract_valves.py]
Per-tile JSON: [{tag, line_no, actuator, ...}]
    ↓ Deduplication + parsing  [parse_tags.py]
Structured rows (tag → CSV columns)
    ↓ Validation               [validate.py]
docs/output_valve_list.csv
```

### Key Files (once built)
- `extract_valves.py` — existing reference script (from PID-KnowledgeGraph-demo pattern)
- `pipeline.py` — main entry point: orchestrates all stages
- `pdf_to_tiles.py` — PDF → overlapping PNG tiles using PyMuPDF
- `parse_tags.py` — parses valve tags and line numbers into CSV columns
- `validate.py` — checks tag format regex, flags anomalies

## Environment

Uses Python 3 with:
- `pymupdf` (`fitz`) — PDF to image (already installed)
- `anthropic` — Claude Vision API for valve extraction
- `pillow` — image tiling
- `pandas` — CSV output

Secrets/keys: `ANTHROPIC_API_KEY` environment variable required.

Install: `pip install anthropic pymupdf pillow pandas`

## Temporary Files

All intermediate files (PNG tiles, debug crops) go in `tmp/` — never commit this directory.

## Reference Codebase

`../PID-KnowledgeGraph-demo/` is a working RAG demo on P&IDs using Neo4j + LangChain + GPT for QA. The pattern of using an LLM to interpret P&ID data is directly applicable here. Key reference: `../PID-KnowledgeGraph-demo/app.py` (LLM pipeline), `extract_valves.py` (symbol extraction pattern).
