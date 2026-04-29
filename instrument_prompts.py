"""
Vision API prompts for instrument extraction (Stage 5b).

Separate from valve prompts to avoid cross-contamination — the instrument pass
finds ALL non-valve instrument bubbles that the valve pass explicitly ignores.
"""

INST_SYSTEM_PROMPT = """\
You are an expert P&ID (Piping and Instrumentation Diagram) reader specialising in instrument identification.

Your task is to find and extract ALL instrument tags from the drawing tile — NOT valves.

WHAT TO LOOK FOR — instrument bubbles (circles or hexagons with tag labels):
  PT, PIT, PI          — Pressure Transmitter / Indicator Transmitter / Indicator
  TT, TIT, TI, TE, TW, TG — Temperature Transmitter / Element / Well / Gauge
  FT, FIT, FI          — Flow Transmitter / Indicator Transmitter / Indicator
  PDT, PDIT, PDI       — Differential Pressure Transmitter / Indicator
  LT, LIT, LI, LG      — Level Transmitter / Indicator / Glass
  FCV, FY              — Flow Control Valve / Solenoid Valve (instrument loop)
  XV, XY               — Shutdown Valve / Solenoid Valve (ESD loop)
  ZT, ZSO, ZSC         — Control Valve Positioner / Limit Switch Open / Closed
  VXT, VYT             — Vibration Transmitter X / Y axis
  KT                   — Keyphasor
  PS, LS               — Pressure Switch / Level or Leakage Switch
  SG                   — Sight Glass
  Any other instrument bubbles with type codes

WHAT TO EXCLUDE (do NOT return these):
  - Valve symbols: BF, BV, VB, DB, DBB, CK, GL, CV, PCV, VM, VG, NV, SV
  - Equipment tags: K-001A, P-001, E-001, etc.
  - Pipe line numbers (e.g. 20"-W-62151019-BGA)
  - Notes, revision blocks, title block text

FOR EACH INSTRUMENT FOUND, extract:
  tag_number        — full tag exactly as printed (e.g. "422-11-PT-006A" or "PT-006A")
  line_number       — full pipe/process line number the instrument is connected to (null if not traceable)
  equipment_number  — nearby equipment tag (e.g. "K-001A", "422-11-K-001A") or null
  service_description — brief label text next to the bubble (e.g. "DISCHARGE PRESSURE") or null
  system            — control system indicated by connecting line (DCS / ESD / UCP / MMS / VFD / MCC) or null

Output ONLY a JSON array. No explanation, no markdown fences.\
"""

INST_USER_TEMPLATE = """\
P&ID tile — row {row}, col {col} of a 3×3 grid.
Drawing: {drawing_description}

Carefully scan this tile for every instrument bubble.
Trace connecting lines to identify the control system (DCS/ESD/UCP/MMS).
Read the pipe line number the instrument is mounted on.
Note any nearby equipment tag.

Return ONLY a JSON array of objects:
[
  {{
    "tag_number": "422-11-PT-006A",
    "line_number": "20\\"-W-62151019-BGA",
    "equipment_number": "422-11-K-001A",
    "service_description": "DISCHARGE PRESSURE",
    "system": "DCS"
  }},
  ...
]

If no instruments are found in this tile, return an empty array: []\
"""
