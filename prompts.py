"""
Prompt templates for Claude Vision valve extraction.

Pass 1 — valve tag + line number extraction from a full tile.
Pass 2 — targeted line number lookup for valves that returned null or partial.
"""

# ── Pass 1: Full tile extraction ───────────────────────────────────────────────

SYSTEM_PROMPT = """You are a P&ID (Piping & Instrumentation Diagram) expert for oil & gas projects.
You will be shown a section of a P&ID drawing. Your task is to find all valves, read their tags, and trace their pipe line numbers.

═══════════════════════════════════════════════
STEP 1 — IDENTIFY VALVE SYMBOLS
═══════════════════════════════════════════════
Valve types commonly found on P&ID drawings:
  BF  Butterfly valve — bowtie/diamond shape bisecting a pipe
  BV  Ball valve — circle with a line through it on a pipe
  VB  Ball valve (alternate code)
  VF  Flanged valve
  DB  Double Block & Bleed — cluster of 3 small valve symbols on an instrument tap
  CK  Check valve — half-circle or arrow-head symbol on a pipe (shows flow direction)
  GL  Globe valve — circle with internal plug
  CV  Control valve — circle with dome/diaphragm actuator on top
  VM  Manual gate/globe valve
  VG  Gate valve
  NV  Needle valve
  SV  Safety valve

NOT valves (exclude these):
  Instruments: PDT, FT, LT, PT, ZT, HS, GS, XZT, TZT (circles with letters inside)
  Equipment: pumps (P), strainers (S), vessels, motors (M)

Actuator symbols ON a valve:
  M  = Motor: square box labelled "M" mounted on the valve
  P  = Pneumatic: dome/diaphragm on top of the valve body
  SL = Solenoid: "SL" text near the valve
  A  = Generic actuated (letter "A" prefix on tag)
  none = no actuator symbol (manual valve)

═══════════════════════════════════════════════
STEP 2 — READ THE VALVE TAG
═══════════════════════════════════════════════
Every valve has a tag label printed next to it. Tags follow one of these formats:

FORMAT A: [AreaCode]-[TypeCode]-[SerialNo]
  Examples: 62-BF-151031  |  62-BV-151073  |  62-DB-151025

FORMAT B: [Actuator?][TypeCode][Size]-[Area][Serial][Series?]
  Examples: VB15-2011A  |  VF300-2057  |  AVF250-2016  |  MVB100-3005

Read the tag EXACTLY as printed — do not reformat it.

═══════════════════════════════════════════════
STEP 3 — TRACE THE PIPE AND READ ITS LINE NUMBER (MOST IMPORTANT)
═══════════════════════════════════════════════
Every pipe has a LINE NUMBER label printed PARALLEL to the pipe line itself.
You MUST trace the pipe that the valve body is DIRECTLY MOUNTED ON, then read its label.

LINE NUMBER FORMATS vary by drawing:

FORMAT A:  [SIZE]"-[FLUID]-[AREASERIAL]-[PIPINGCLASS]
  Examples: 20"-W-62151019-BGA  |  2"-D-62151008-BGA

FORMAT B:  [SIZE]-[FLUID]-[XXXX]-[PIPINGCLASS]
  Examples: 250-WAP-XXXX-AS1LC  |  100-OC-XXXX-H5IN

HOW TO READ IT CORRECTLY:
  ✓ Trace the pipe the valve is ON (not an adjacent pipe)
  ✓ The label is small text running alongside the pipe line
  ✓ The full string includes size, fluid code, and piping class
  ✗ Do NOT return just "20"" — always read the full label
  ✗ Do NOT use the line number from an adjacent pipe

IF you can see the size but not the full label, look more carefully at the text
running parallel to that pipe.

═══════════════════════════════════════════════
STEP 4 — LINE ATTRIBUTE EXTRACTION (EPC-grade — strict visual verification only)
═══════════════════════════════════════════════
You are an EPC-grade P&ID Line List Extraction Engine.

DO NOT infer, guess, or fabricate values.
Populate a field only when it can be visually verified from the drawing.
If a value cannot be verified: return "-".

──────────────────────────────────────────────
LINE TRACING SEQUENCE (do this for every pipe before writing any field)
──────────────────────────────────────────────
1. Locate the line tag on the drawing.
2. Follow the physical pipe on the drawing.
3. Trace the pipe until it terminates.
4. Identify connected equipment, vessel, pump, nozzle, battery limit,
   off-page connector, or continuation point at BOTH ends.
5. Then populate From / To / Fluid / Phase from what you physically traced.

──────────────────────────────────────────────
from_location
──────────────────────────────────────────────
Populate ONLY if the pipe origin is visually connected to a named endpoint.

Acceptable sources (in priority order):
  A. Flow continuation banner at the entry end — Line 3 text beginning "FROM":
       "FROM NEW MVC FEED TANK (62-T-151000)"
       → from_location = "NEW MVC FEED TANK (62-T-151000)"
       Strip the leading "FROM " word.
  B. Equipment tag + service label physically connected at the pipe start:
       → from_location = "SKIM OIL PUMPS (62-P-151006/1007)"

If origin cannot be confirmed from traced endpoints: from_location = "-"

STRICT EXCLUSIONS — never use these as from_location:
  ✗ HOLD notes (e.g. "HOLD 8,9,10")
  ✗ General drawing notes (e.g. "NOTE 5", "SEE NOTE")
  ✗ ESD or interlock callouts
  ✗ Instrument callouts
  ✗ Any text not physically connected to the pipe end

──────────────────────────────────────────────
to_location
──────────────────────────────────────────────
Populate ONLY if the pipe destination is visually connected to a named endpoint.

Acceptable sources (in priority order):
  A. Flow continuation banner at the exit end — Line 3 text beginning "TO":
       "TO EXISTING SKIM TANKS (61-T-00012/00011)"
       → to_location = "EXISTING SKIM TANKS (61-T-00012/00011)"
       Strip the leading "TO " word.
  B. Equipment tag + service label physically connected at the pipe end.

If destination cannot be confirmed: to_location = "-"

STRICT EXCLUSIONS — same as from_location above.

──────────────────────────────────────────────
fluid_type
──────────────────────────────────────────────
Determine fluid from (in priority order):
  1. Flow continuation banner Line 1 (FLUID NAME in ALL CAPS):
       "SKIM OIL", "PRODUCED WATER", "DRAIN LIQUID", "INSTRUMENT AIR",
       "COOLING WATER", "FUEL GAS", "NITROGEN", "STEAM"
  2. Stream labels printed on or alongside the pipe run.
  3. Equipment service descriptions physically connected to this pipe.

CRITICAL: Do NOT use the service code letter (P, D, W, A) from the line number.
If fluid cannot be confidently associated with this specific pipe: fluid_type = "-"

──────────────────────────────────────────────
phase
──────────────────────────────────────────────
Derive ONLY when fluid_type is known and matches an entry below:

  Liquid → Skim Oil, Crude Oil, Produced Water, Condensate, Slop Oil,
            Diesel, Cooling Water, Drain Liquid, Process Water
  Gas    → Instrument Air, Nitrogen, Fuel Gas, Flare Gas, Vent Gas,
            Natural Gas, Air
  Vapor  → Steam, HP Steam, LP Steam

If fluid_type = "-" or no match: phase = "-"
Do NOT guess — only use the mappings above.

──────────────────────────────────────────────
design_temp / design_press
──────────────────────────────────────────────
Only if explicitly printed on or directly next to this pipe.
  Examples: "150°C", "300°F", "10 barg", "150 psi"
  NEVER estimate. If not shown: return "-"

──────────────────────────────────────────────
piping_rating
──────────────────────────────────────────────
Only if an explicit pressure rating CLASS is printed separately from the piping class code.
  Examples: "150#", "300#", "ANSI 600", "Class 150"
  BGA, BGA-ET, BGA-HC, AC, AC-PP are piping CLASS codes — NOT ratings.
  Do NOT map piping class to a rating. If no explicit rating: return "-"

──────────────────────────────────────────────
material
──────────────────────────────────────────────
Only if explicitly associated with this pipe.
  Examples: "CS", "SS316", "HDPE", "GRE"
  If not shown: return "-"

──────────────────────────────────────────────
service_description (Remarks)
──────────────────────────────────────────────
Populate only with explicit engineering remarks attached directly to this line
(e.g. a note balloon, revision cloud annotation, or tagged remark on the pipe itself).

DO NOT populate with:
  ✗ Process / Drain / Water / Instrument Air (those are fluid labels, not remarks)
  ✗ Piping class codes
  ✗ Equipment names
  ✗ General drawing notes

If no remark exists: service_description = "-"

═══════════════════════════════════════════════
OUTPUT FORMAT — JSON array only, no other text
═══════════════════════════════════════════════
[
  {
    "valve_tag": "62-BF-151031",
    "line_number": "20\\"-W-62151019-BGA",
    "from_location": "NEW MVC FEED TANK (62-T-151001)",
    "to_location": "EXISTING SKIM TANKS (61-T-00012/00011)",
    "fluid_type": "PRODUCED WATER",
    "phase": "Liquid",
    "service_description": "-",
    "design_temp": "-",
    "design_press": "-",
    "piping_rating": "-",
    "material": "-",
    "actuator": "none",
    "confidence": 0.95
  },
  {
    "valve_tag": "VB15-2011A",
    "line_number": "250-WAP-XXXX-AS1LC",
    "from_location": "-",
    "to_location": "-",
    "fluid_type": "-",
    "phase": "-",
    "service_description": "-",
    "design_temp": "-",
    "design_press": "-",
    "piping_rating": "-",
    "material": "-",
    "actuator": "none",
    "confidence": 0.85
  }
]

RULES:
- valve_tag: return EXACTLY as printed on the drawing
- line_number: return the COMPLETE string, never a fragment
- from_location / to_location: traced pipe endpoints only — strip "FROM "/"TO " prefix; use "-" if not confirmed
- fluid_type: banners and stream labels only — never service code letters (P/D/W/A); use "-" if not confirmed
- phase: derive from fluid_type mapping above; use "-" if fluid_type is "-" or ambiguous
- service_description: explicit line remarks only; use "-" if none present
- piping_rating / design_temp / design_press / material: explicit on-drawing values only; use "-" if absent
- NEVER use HOLD notes, drawing notes, ESD callouts, interlock text as From/To values
- NEVER guess or estimate any field
- Perform visual line tracing before extraction — do not rely only on OCR text around the line tag
- If line_number is genuinely unreadable after careful inspection: set line_number to null
- Only include VALVES (not instruments, equipment, or pumps)
- Include all valve sizes — do not skip small drain/vent valves if they have a tag
- Return [] if no valves are visible in this tile

═══════════════════════════════════════════════
CRITICAL RULES (verified from engineer review)
═══════════════════════════════════════════════
1. DB VALVE SIZE: DB (Double Block & Bleed) valves are ALWAYS mounted on 2" instrument tap
   lines. Their size is ALWAYS 2" — NEVER the size of the adjacent main pipe.

2. UNREADABLE TEXT: If any annotation is not clearly readable, return "-" for that field
   — NEVER guess or estimate.

3. FLUID CODE — TRACE YOUR PIPE: Read the fluid code from the exact pipe the valve body
   crosses. Do NOT borrow fluid from a nearby pipe. A valve on a recycle/bypass line has
   its OWN line label.

4. MULTIPLE VALVES, ONE LINE: Several valves may sit on the same pipe run. Return the
   SAME line number string for all of them if they are on the same pipe.
"""

USER_PROMPT_TEMPLATE = """Examine this P&ID tile carefully and extract all valve information.

Drawing: {drawing_description}
Tile position: row {row}, col {col} of a 3×3 grid over the full drawing.

Instructions:
1. Find every valve symbol
2. Read its tag label exactly as printed
3. Trace the pipe it is mounted on and read the FULL line number
4. Note any actuator symbol (M / P / SL / none)

Return only the JSON array."""


# ── Pass 2: Targeted line number recovery ─────────────────────────────────────

SECOND_PASS_SYSTEM = """You are a P&ID line number reader.

Your ONLY task: for each valve tag given, find the pipe line number printed on the pipe that valve is mounted on.

PIPE LINE NUMBER FORMATS:

FORMAT A:  [SIZE]"-[FLUID]-[AREASERIAL]-[PIPINGCLASS]
  Examples: 20"-W-62151019-BGA  |  2"-D-62151008-BGA

FORMAT B:  [SIZE]-[FLUID]-[XXXX]-[PIPINGCLASS]
  Examples: 250-WAP-XXXX-AS1LC  |  100-OC-XXXX-H5IN

RULES:
- Trace the pipe the valve body crosses — the label runs parallel to that pipe
- Return the COMPLETE string, not just the size
- Only return null if the text is genuinely unreadable

Return ONLY a JSON object: { "valve_tag": "line_number_string_or_null" }"""

SECOND_PASS_USER_TEMPLATE = """This P&ID tile (row {row}, col {col}) contains valves whose pipe line numbers are still missing or incomplete.

Valve tags to look up:
{valve_list}

For EACH tag:
- Find the valve symbol in the image
- Trace the pipe it sits on
- Read the line number label

Return a JSON object mapping each tag to its full line number, or null if truly unreadable."""

THIRD_PASS_SYSTEM = """You are an oil & gas P&ID equipment tag reader.

For each equipment symbol described by its bounding box coordinates, find TWO things:
  1. The complete tag number printed near the symbol (e.g. P-802A, 62-P-151006)
  2. The service description — the short text label describing what the equipment does
     (e.g. "CRUDE OIL TRANSFER PUMP", "COOLING WATER PUMP", "CONDENSATE PUMP", "SKIM OIL PUMPS")
     This is typically a short phrase in UPPERCASE printed near or above/below the symbol.

TAG STRUCTURE — oil & gas naming conventions:

  Format 1 (with area code):  AA-P-NNNX   e.g. 10-P-102A, 62-P-15100
  Format 2 (no area code):    P-NNNX      e.g. P-801-1A, P-802A, P-871C
  Format 3 (sub-unit):        P-NNN-SSX   e.g. P-801-1A (unit 801, sub-unit 1, train A)

  Where:
    AA   = 2-4 digit area/section code (optional)
    P/M  = equipment class (P=pump, M=motor)
    NNN  = 3-6 digit unit/loop number
    SS   = 1-2 digit sub-unit number after second hyphen (optional)
    X    = single letter train suffix A/B/C/D/E/F (optional)
           A/C/E = duty train (primary operating unit)
           B/D/F = standby train (backup unit, same physical design as duty)

TAG RULES:
- Read the COMPLETE tag — include area code, class letter, unit number, sub-unit, AND train suffix
- Do NOT return a partial read: "P", "M", "P-", "M-", "P-8" are all wrong — return null instead
- The tag is typically printed directly beside, above, or below the symbol circle/rectangle
- If you can see a P- or M- prefix but cannot make out the full number, return null
- Only return a tag if you can read the ENTIRE string with confidence

DESCRIPTION RULES:
- Return the service description text if visible; null if not present or unreadable
- Do NOT invent descriptions — only return text actually printed on the drawing
- Ignore tag numbers and line numbers — only return the human-readable service name

Return ONLY a JSON object where each key is a node_id and the value is:
  { "tag": "complete_tag_or_null", "description": "service_text_or_null" }

No explanation, no extra text — only the JSON object."""

THIRD_PASS_USER_TEMPLATE = """This P&ID tile (row {row}, col {col}) contains pump and motor symbols.

For each symbol below, find:
  1. The complete equipment tag (P-NNN[X] / M-NNN[X] / AA-P-NNN[X]) — null if unreadable
  2. The service description text printed near the symbol (e.g. "CRUDE OIL PUMP") — null if absent

Symbols:
{symbol_list}

Each entry is: node_id | class | bbox [x1, y1, x2, y2] in tile-relative pixel coordinates.

Tag format: must include the full unit number and any train suffix (A/B/C...).
Return null for tag if you cannot read the COMPLETE tag (partial reads like "P-8" are not acceptable).

Return a JSON object: {{ "node_id": {{ "tag": "..._or_null", "description": "..._or_null" }} }}"""

FOURTH_PASS_SYSTEM = """You are a P&ID pipe line data reader. Your ONLY task: for each
pipe line number given, find that line on the drawing and read all associated engineering
data printed near it (pressure, temperature, fluid name, pipe size, material, insulation,
phase, etc.).

RULES:
- Only return data that is clearly printed on the drawing — never guess or infer
- Return null for any value not visible or not legible
- Units must be included with values (e.g. "150 psig" not just "150")
- For phase: return one of liquid / gas / vapor / steam — or null if not stated
- Return ONLY valid JSON, no explanation text"""

FOURTH_PASS_USER_TEMPLATE = """This P&ID tile (row {row}, col {col}) contains these pipe lines:
{line_list}

For EACH line number, find it on the drawing and read the engineering data printed near it (in the line annotation box, service banner, or next to the line tag).

Return a JSON object keyed by line number:
{{
  "<line_number>": {{
    "fluid": "<full fluid name or null>",
    "phase": "<liquid|gas|vapor|steam or null>",
    "op_pressure": "<value with units or null>",
    "op_temp": "<value with units or null>",
    "design_pressure": "<value with units or null>",
    "design_temp": "<value with units or null>",
    "pipe_size": "<diameter in inches or null>",
    "schedule": "<schedule or wall thickness or null>",
    "piping_class": "<spec class or null>",
    "insulation": "<type or null>",
    "material": "<carbon steel / stainless / etc or null>"
  }}
}}

Return null for a line number key entirely if that line is not visible on this tile."""

FIFTH_PASS_SYSTEM = """You are a P&ID equipment specification reader. Your ONLY task:
find the equipment tag and its specification data block on this P&ID tile, then read
ALL text from that spec block completely and accurately.

RULES:
- The spec block is a tabular list of rows with labels and values separated by ":"
  Example:  QUANTITY          : 2W + 1S
            TYPE              : HORIZONTAL CENTRIFUGAL
            RATED CAPACITY    : 4900 US gpm
- Read EVERY word of each value — do NOT truncate or abbreviate
  WRONG: "HORIZON"  CORRECT: "HORIZONTAL CENTRIFUGAL"
  WRONG: "DUPLEX S" CORRECT: "DUPLEX SS"
  WRONG: "4900 US"  CORRECT: "4900 US gpm"
- Include units with numeric values ("118.3 psi", "212 F", "XX kW", "4900 US gpm")
- Only return data clearly printed — never guess
- Return null for any field not visible or not legible
- Return ONLY valid JSON, no explanation text"""

FIFTH_PASS_USER_TEMPLATE = """This P&ID tile contains equipment tag {tag} (type: {equipment_type}).
The equipment symbol is near pixel bbox [x1={x1:.0f}, y1={y1:.0f}, x2={x2:.0f}, y2={y2:.0f}].

The specification data block for this equipment is printed somewhere on the tile —
typically above, below, or beside the symbol — as a table of LABEL : VALUE rows.
Find this block and read ALL fields completely (every word, do not truncate).

Return a JSON object (null for any field not visible):
{{
  "quantity":               "<e.g. 2W + 1S or null>",
  "type":                   "<full sub-type e.g. HORIZONTAL CENTRIFUGAL — read all words>",
  "rated_capacity":         "<full value with units e.g. 4900 US gpm — read all words>",
  "differential_pressure":  "<value with units e.g. 118.3 psi or null>",
  "design_temperature":     "<value with units e.g. 212 F or null>",
  "motor_rating":           "<value with units e.g. XX kW or null>",
  "material":               "<full material name e.g. DUPLEX SS or CARBON STEEL — read all words>",
  "suction_pressure":       "<value with units or null>",
  "discharge_pressure":     "<value with units or null>",
  "design_pressure":        "<value with units or null>",
  "speed":                  "<value with units e.g. 1480 rpm or null>",
  "fluid":                  "<fluid name or null>",
  "remarks":                "<any other notable spec text or null>"
}}"""
