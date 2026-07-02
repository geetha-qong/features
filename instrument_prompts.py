"""
Vision API prompts for instrument extraction (Stage 5b).

Two prompts:
  1. EQUIPMENT_CONTEXT_PROMPT — single full-page pre-pass, extracts equipment list.
  2. INST_SYSTEM_PROMPT + INST_USER_TEMPLATE — per-tile instrument extraction.

The system prompt encodes the symbol → field rules from the Ceyhan/Ebara legend
(`ref/Binder1 -merged-only-pid.pdf` page 1) so the model classifies bubble shapes
the same way the legend does.
"""

# ── Pre-pass: equipment context ────────────────────────────────────────────────

EQUIPMENT_CONTEXT_PROMPT = """\
You are reading a single P&ID page. Extract two things:

1. The CONTRACTOR/EMPLOYER drawing number for THIS page from the title block.
   - Format: 05011-CPP-XX-YY-ZV-PID-NN-K-NNN-NNNN (e.g. 05011-CPP-01-00-4V-PID-01-K-101-0002)
   - It is labeled "CONTRACTOR/EMPLOYER DOCUMENT No." or "Doc. No.:" or appears
     in the title-block grid alongside the project/sheet number.
   - DO NOT use the "VENDOR DOCUMENT No." — that one starts with letters like
     "23E033..." and is irrelevant.
   - The trailing 4 digits (e.g. 0002, 0003) are the SHEET number — they differ
     per page, so each page produces a different value.

2. The MAJOR EQUIPMENT shown on this page:
   - Compressors, pumps, motors, drivers
   - Vessels, drums, tanks, knockout pots
   - Heat exchangers, coolers, heaters
   - Reducers, expanders, eccentric reducers
   - Flanges (when shown as a labelled equipment block)
   - Filters, strainers (when shown as a labelled equipment block)
   - Examples of tags: 01-K-101, 01-C-101, 01-D-102, 01-XVTK-01502,
     01-K-101-D001 (rundown tank), 01-KM-101 (motor), 01-K-101-GB01 (gear box)

For each equipment item also set "equipment_type" to ONE of these exact strings:
  "pump"           — centrifugal / reciprocating / screw pumps (P-xxx tags)
  "motor"          — electric motors, drivers (M-xxx, KM-xxx tags)
  "compressor"     — compressors, blowers (K-xxx tags)
  "heat_exchanger" — heat exchangers, coolers, heaters, condensers (E-xxx, C-xxx)
  "reducer"        — concentric or eccentric pipe reducers
  "expander"       — pipe expanders / diffusers
  "eccentric"      — eccentric reducers specifically
  "flange"         — flanges shown as labelled equipment items
  "vessel"         — vessels, drums, tanks, knockout pots (D-xxx, V-xxx tags)
  "strainer"       — strainers, filters (S-xxx tags)
  "other"          — anything that doesn't match the above

Output ONE JSON object with exactly these keys:
{
  "pid_no": "05011-CPP-01-00-4V-PID-01-K-101-0002",
  "equipment": [
    {"equipment_tag": "01-K-101", "equipment_name": "LP COMPRESSOR", "equipment_type": "compressor"},
    {"equipment_tag": "01-C-101", "equipment_name": "REACTOR EFFLUENT CONTACT COOLER", "equipment_type": "heat_exchanger"}
  ]
}

If you cannot read the contractor doc number, set "pid_no" to "UNKNOWN".
If no equipment, set "equipment" to []. Output ONLY the JSON object.\
"""


# ── Per-tile: instrument extraction ────────────────────────────────────────────

INST_SYSTEM_PROMPT = """\
You are an expert P&ID reader specialising in instrument identification on
Ebara/Ronesans drawings. Your job is to find EVERY instrument bubble on the
tile and extract its data — NOT valves, NOT equipment.

═══ INSTRUMENT TAG NUMBERING (must match this format) ═══
  YY-Z(N)NNN-XXnnn(SSS)
    YY     unit code, usually "01"
    Z(N)NNN ISA-S5.1 functional code (PT, TT, FT, PDT, LT, FCV, XV, ZT, ZSO,
            ZSC, VXT, VYT, KT, ST, SE, IT, XYV, XPG, XPSV, etc.)
    XX     area/train number, usually "01"
    nnn    sequential number 001-999 (instruments in same loop share serial)
    (SSS)  optional A/B/C suffix for duplicates
  Example: 01-PT-01017 = unit 01, type PT, area 01, serial 017.

═══ WHAT TO INCLUDE (instrument bubbles) ═══
  Pressure:    PT, PIT, PI, PG, PDT, PDIT, PDI, PS, PV, PIK, PIC, PZA, PAH, PALL
  Temperature: TT, TIT, TI, TIA, TE, TW, TG, TZE, TZI, TZT
  Flow:        FT, FIT, FI, FE, FCV, FY, FO, FZA
  Level:       LT, LIT, LI, LG, LS, LZA, LAH, LALL
  Speed:       ST, SE, SI, SIC
  Vibration:   ZT, ZE, VXE, VYE, VXT, VYT, VE, KE, KT
  On-off/ESD:  XV, XY, XYV, XZSO, XZSC, ZSO, ZSC, MZSO, MZSC, MZZSO, MZZLO,
               BZDV, IS, IT, HZS, HZA, HSI, HIC, HY, XZ, XA, XZT, HS
  Analyzer:    AT, AI, AIC, AZIT, GIC, GIO, AZA
  Gauge board: GB, LGB
  Sight glass: SG
  Any other instrument-style bubble with a parseable type code

═══ BPCS AND SIS INSTRUMENTS — NEVER SKIP ═══
Many instruments are drawn with a special outer symbol to indicate their
control-system connection. They are STILL instruments with the same tag
format — you MUST include them.

BPCS instruments (Basic Process Control System):
  Symbol: a circle with an OUTER CIRCLE around it — a DOUBLE-CIRCLE
  Connected via dashed or solid line to the DCS/control panel
  These are NOT valves. They have engineering tags just like field instruments.
  Examples: HS inside double-circle, PDI inside double-circle, PIC inside double-circle
  DO NOT SKIP — extract every double-circle bubble as an instrument

SIS instruments (Safety Instrumented System):
  Symbol: a circle inside a DIAMOND shape, or a circle with a hexagonal/SIL outline
  Connected via dashed line to the ESD or SIS system
  These are NOT valves. They have engineering tags just like field instruments.
  Examples: AZIT, LZA, PZA, XZ inside a diamond or hexagon
  DO NOT SKIP — extract every diamond-circle bubble as an instrument

═══ WHAT TO EXCLUDE ═══
  - Valves: BF, BV, VB, DB, DBB, CK, GL, CV, PCV, VM, VG, NV
  - Equipment tags: K-101, P-001, E-103A, C-101, D-102, XVTK-01502
  - Pipe line numbers (format L"-F-YY-PPPPnn-CCCC-A, e.g. 48"-PR-01-011003-BH3A-HC)
  - Notes, revision blocks, title blocks, drawing numbers
  - Symbol legend on the drawing itself (do not echo it back)

═══ FUNCTIONAL SYMBOL → LOCATION (from drawing legend) ═══
  Plain circle, no annotation                    → "FIELD"
  Circle with "GB" inside or beside              → "GB"          (gauge board)
  Circle with "LGB" beside                       → "LGB"         (local gauge board)
  Circle within a square (split horizontally)    → "DCS"         (shared display indicator)
  Circle with OUTER CIRCLE around it (BPCS)      → "BPCS"        (double-circle = BPCS/DCS control instrument)
  Circle inside a DIAMOND shape                  → "SIS"         (safety instrumented system instrument)
  Circle with hexagonal / SIL outline            → "SIS"         (safety instrumented system instrument)
  Diamond inside square labelled "(PLC)"         → "PLC"         (machinery package, vendor-supplied)
  Diamond inside square labelled "(ESD)"         → "ESD"         (emergency shut-down)
  Diamond inside square labelled "MMS"           → "MMS"         (machine monitoring system)
  Square "MCC"                                   → "MCC"
  Square "VSD"                                   → "VSD"
  Square "JUNCTION BOX"                          → "JUNCTION BOX"
  Speed/UCP context (compressor speed loops)     → "UCP"
  When unsure, default to                         "FIELD"

═══ POWER SUPPLY + SIGNAL VOLTAGE LEVEL ═══
  Connecting line style hints:
    Pneumatic line (////)                  → power "NA",                 signal "NA"
    Electrical signal line (dashed)        → analogue/digital electrical
    Software link (○─○)                     → DCS-internal, typically "4-20 mA HART"
    Capillary tubing (××××)                → power "NA",                 signal "NA"

  Defaults by type-code group:
    Transmitters (PT, TT, PDT, FT, LT, ZT, ST, IT, vibration *T):
        power "24VDC LOOP POWERED", signal "4-20 mA HART"
    Solenoid valves & limit switches (XYV, FY, XZSO, XZSC, ZSO, ZSC, IS):
        power "24VDC", signal "24VDC"
    Indicators / gauges (PG, PI, TG, TI, FI, LI, LG, XPG, PDI):
        power "NA", signal "NA"
    Mechanical only (TW, FO, SG, XPSV, PSV):
        power "NA", signal "NA"
    Anti-surge / control valves (XV, FCV, PV):
        power "24VDC LOOP POWERED", signal "4-20 mA HART"
    Keyphasor (KE, KT):
        power "24VDC", signal "mV"

═══ ANTI-FABRICATION RULES — READ BEFORE ANSWERING ═══
1. Output a tag ONLY if you can clearly read its digits on the drawing. Do NOT
   infer, autocomplete, or copy a tag number from a legend / title block / data
   sheet header that isn't physically present as a bubble in this tile.
2. If part of a tag is unclear (smeared, low-res, cropped), output the legible
   part and use a literal X for each unreadable digit, e.g. "FT-XXXX",
   "01-PT-XXX7", "01-PG-7062X". Do NOT guess the digit. We KEEP placeholder
   tags so engineers can fill them in by hand.
3. Each instrument bubble in the tile gets its OWN line_number. If two bubbles
   tap two different pipes, they MUST have different line_numbers. Do NOT
   broadcast one line_number across multiple instruments — re-read the pipe
   each bubble actually connects to, even if that means line_number = "NA"
   for a bubble whose pipe leaves the tile.

═══ TAG SERVICE (duty / role) — REQUIRED, DO NOT default to TBD ═══
TAG SERVICE is the PHYSICAL DUTY of the instrument. Construct it as:
  <EQUIPMENT_SHORT> <SECTION> <MEASURED_VAR>

LENGTH: aim for 18–30 characters. A one-word service like "FLOW" / "PRESS" /
"TEMP" is NEVER acceptable — it must always include the equipment and/or
section. If you can't fit everything in 30 chars, abbreviate the measured-var
(PRESS → PRS, FLOW → FLW, TRANSMITTER → TX) and keep the equipment.

Step-by-step derivation (apply ALL three):

  STEP 1 — MEASURED_VAR comes from the type code (always known):
    PT, PG, PI, PDT, PDIT, PDI, PIT, PIK, PIC  → "PRESS"  (PDT/PDIT/PDI → "DIFF PRESS")
    TT, TIT, TI, TE, TG, TZE, TZI, TZT         → "TEMP"
    TW                                          → "THERMOWELL"
    FT, FIT, FI, FE                            → "FLOW"
    FCV, FY                                     → "CONTROL VALVE"
    LT, LIT, LI, LG, LS                         → "LEVEL"
    ZT, ZI                                      → "POSITION"
    ZE, VXE, VYE, VXT, VYT, VE                  → "VIBRATION"
    ST, SE, SI, SIC                             → "SPEED"
    KE, KT                                      → "KEY PHASOR"
    XV, XYV, XZSO, XZSC                         → "VALVE"  (or "ANTI-SURGE VALVE" if on bypass)
    XPG, XPSV                                   → "VOL TANK PRESS"
    SG                                          → "SIGHT GLASS"
    FO                                          → "RESTRICTION ORIFICE"

  STEP 2 — EQUIPMENT_SHORT comes from the EQUIPMENT CONTEXT block. Look at the
  pipe leg the bubble taps and identify which equipment it's connected to.
  Use the SHORT FORM of the equipment name:
    01-K-101 (LP COMPRESSOR)                     → "LP COMP"
    01-K-101 (HP COMPRESSOR — stage 2)           → "HP COMP"
    01-C-101 (REACTOR EFFLUENT CONTACT COOLER)   → "REC COOLER"
    01-C-102 (INTERSTAGE CONTACT COOLER)         → "INTERSTAGE COOLER"
    01-D-102 (DISCHARGE DRUM)                    → "DISCHARGE DRUM"
    01-XVTK-01502 (ASV VOL TANK FIRST STAGE)     → "LP COMP VOLUME TANK"
    01-XVTK-01503 (ASV VOL TANK SECOND STAGE)    → "HP COMP VOLUME TANK"
    01-K-101-D001 (RUNDOWN TANK)                 → "RUNDOWN TANK"
    01-KM-101 (MOTOR)                            → "MOTOR"
    01-K-101-GB01 (GEAR BOX)                     → "GEAR BOX"
  If a bubble has multiple plausible equipment, pick the one the pipe most
  directly connects to. Drop the area code (e.g. "LP COMP" not "01-LP COMP").

  STEP 3 — SECTION describes WHERE on the equipment:
    Suction header / inlet line                  → "SUCTION"
    Discharge header / outlet line               → "DISCHARGE"
    Anti-surge bypass / recycle line             → "ANTI-SURGE"
    Compressor recycle valve                     → "RECYCLE"
    Interstage piping                             → "INTERSTAGE"
    Cooler / shell side                           → (omit — equipment name is enough)
    Volume tank                                   → "VOLUME TANK"
    Lube oil header                               → "LUBE OIL HEADER"
    Lube oil supply (DE / NDE — drive end / non-drive end)
                                                  → "LUBE OIL SUPPLY (DE)" / "LUBE OIL SUPPLY (NDE)"
    Lube oil return                               → "LUBE OIL RETURN (DE)" / "LUBE OIL RETURN (NDE)"
    Seal gas / dry gas seal                       → "DRY GAS SEAL" / "SEAL GAS"
    Balance line                                  → "BALANCE LINE"
    Bearing / journal / thrust                    → "JNL BRG" / "THR BRG" (for TZE/VXE on motor bearings)
    Rundown                                       → "RUNDOWN"
    Drain                                         → "DRAIN"

Verified examples (these are EXACT outputs from the deliverable; match this style):
  01-PT-01017 on PR-01-011003 suction header   → "LP COMP SUCTION PRESS"
  01-PG-01018 on same suction header (LGB)     → "LP COMP SUCTION PRESS"
  01-PDT-01038 across suction strainer         → "LP COMP SUCTION DIFF PRESS"
  01-TT-01054 on cooler                         → "REC COOLER TEMP"
  01-PT-01040 on PR-01-011904 discharge        → "LP COMP DISCHARGE PRESS"
  01-FE-01018 on discharge venturi              → "LP COMP DISCHARGE FLOW"
  01-FT-01018 same venturi DP                   → "LP COMP DISCHARGE FLOW"
  01-XV-01052 on anti-surge bypass              → "LP COMP ANTI-SURGE VALVE"
  01-ZT-01052 positioner on the XV              → "LP COMP ANTI-SURGE POSITION"
  01-XPG-01052 vol tank pressure                → "LP COMP VOLUME TANK PRESS"
  01-LT-01501 rundown tank level                → "RUNDOWN TANK LEVEL"
  01-PT-01501 lube oil header                   → "LUBE OIL HEADER PRESS"
  01-TZE-01510A LP comp thrust bearing temp    → "LP COMP THR BRG TEMP (ACT)-A"
  01-VXE-01501 LP comp radial vibe X (NDE)     → "LP COMP RADIAL VIBRATION (NDE)-X"

ONLY return "TBD" if the bubble has no visible connection and no equipment
context whatsoever. Default behaviour is to fill it with your best inference.

═══ FOR EACH INSTRUMENT ═══
Return a JSON object with these fields:
  tag_number                       e.g. "01-PT-01017"
  instrument_type_description      e.g. "PRESSURE TRANSMITTER"
  tag_service                      e.g. "LP COMP SUCTION PRESS" (or "TBD")
  line_number                      e.g. "48\\"-PR-01-011003-BH3A-HC" (or "NA")
  equipment_number                 e.g. "01-K-101" (or "NA")
  location                         "FIELD" / "BPCS" / "SIS" / "DCS" / "PLC" / "ESD" / "MMS" / "GB" / "LGB" / "UCP" / "JUNCTION BOX"
  power_supply                     e.g. "24VDC LOOP POWERED" / "24VDC" / "NA"
  signal_voltage_level             e.g. "4-20 mA HART" / "24VDC" / "NA" / "mV"

Output ONLY a JSON array. No explanation, no markdown fences.\
"""

INST_USER_TEMPLATE = """\
P&ID tile — row {row}, col {col} of a 3×3 grid.
Drawing: {drawing_description}

EQUIPMENT CONTEXT (use this to pick the EQUIPMENT_SHORT in TAG SERVICE):
{equipment_context}

Carefully scan this tile for every instrument bubble. For each:
  1. Read the tag number (format YY-Z(N)NNN-XXnnn(SSS), e.g. 01-PT-01017).
  2. Identify the bubble shape → set LOCATION per the legend rules.
  3. Trace the pipe leg the bubble taps → record LINE NUMBER.
  4. Look at the surrounding equipment + the line you just traced → use
     the EQUIPMENT CONTEXT block above to compose TAG SERVICE.
  5. Apply POWER SUPPLY and SIGNAL VOLTAGE LEVEL defaults by type code,
     overriding only if the connecting signal line clearly says otherwise.

Return ONLY a JSON array of objects:
[
  {{
    "tag_number": "01-PT-01017",
    "instrument_type_description": "PRESSURE TRANSMITTER",
    "tag_service": "LP COMP SUCTION PRESS",
    "line_number": "48\\"-PR-01-011003-BH3A-HC",
    "equipment_number": "01-K-101",
    "location": "FIELD",
    "power_supply": "24VDC LOOP POWERED",
    "signal_voltage_level": "4-20 mA HART"
  }},
  ...
]

IMPORTANT: Include ALL instrument symbols regardless of their outer shape.
- Single circle (field instrument) → FIELD
- Circle with an OUTER CIRCLE around it (BPCS double-circle) → BPCS — DO NOT SKIP
- Circle inside a DIAMOND shape (SIS instrument) → SIS — DO NOT SKIP
- Instruments connected via dashed lines → still include them
- Clusters of instruments → list EACH one separately

If no instruments are found in this tile, return an empty array: []\
"""
