"""
Stage 2: Vision extraction via OpenRouter API (OpenAI-compatible).

Pass 1 — extract valve tags + line numbers from each tile.
Pass 2 — targeted re-query for valves still missing line numbers after pass 1.

Wrapper design: swap MODEL or base_url to change provider without touching pipeline.
"""
import os
import base64
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv
from prompts import (
    SYSTEM_PROMPT, USER_PROMPT_TEMPLATE,
    SECOND_PASS_SYSTEM, SECOND_PASS_USER_TEMPLATE,
    THIRD_PASS_SYSTEM, THIRD_PASS_USER_TEMPLATE,
    FOURTH_PASS_SYSTEM, FOURTH_PASS_USER_TEMPLATE,
    FIFTH_PASS_SYSTEM, FIFTH_PASS_USER_TEMPLATE,
)
from instrument_prompts import (
    INST_SYSTEM_PROMPT, INST_USER_TEMPLATE, EQUIPMENT_CONTEXT_PROMPT,
)

load_dotenv(Path(__file__).parent / ".env")

# ── Provider config ────────────────────────────────────────────────────────────
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Best vision models on OpenRouter for technical P&ID drawings:
#   google/gemini-2.5-flash         — fastest, excellent dense-text vision (current default)
#   anthropic/claude-sonnet-4-6     — best reasoning
#   openai/gpt-4o                   — strong alternative
# Note: gemini-2.0-flash-001 was retired by OpenRouter mid-2026 — selecting it
# now returns "No endpoints found" 404. Override via OPENROUTER_MODEL env var.
DEFAULT_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash")

DRAWING_DESCRIPTION = "FW Transfer Pump (62-P-151005), Occidental Mukhaizna LLC, drawing MUK-62-1-15-1004-001"
# ──────────────────────────────────────────────────────────────────────────────

# Pass 3 — tag validation patterns (oil & gas conventions)
# Accepts: P-801-1A, P-806-6A, P-802A, P-871C, 10-P-102A, 62-P-15100
# Rejects: P, P-, P-1, P-12, P-1234567, P-abc, garbage text
_PUMP_TAG_RE  = re.compile(r'^(\d{2,4}-)?P-\d{3,6}(-\d{1,2})?[A-Z]?$')
_MOTOR_TAG_RE = re.compile(r'^(\d{2,4}-)?M-\d{3,6}(-\d{1,2})?[A-Z]?$')

# Single regex that captures all tag components for parsing
_TAG_PARSE_RE = re.compile(
    r'^(?:(?P<area>\d{2,4})-)?(?P<cls>[PM])-(?P<unit>\d{3,6})(?:-(?P<sub>\d{1,2}))?(?P<train>[A-Z])?$'
)

# A-suffix = duty train, B-suffix = standby train (first two pairs cover most sites)
_DUTY_TRAINS    = {"A", "C", "E"}
_STANDBY_TRAINS = {"B", "D", "F"}
_TRAIN_FLIP     = {"A": "B", "B": "A", "C": "D", "D": "C", "E": "F", "F": "E"}


def parse_equipment_tag(tag: str) -> dict:
    """
    Parse an oil & gas equipment tag into structured components.

    Handled formats:
      10-P-102A    area=10, cls=P, unit=102, train=A
      P-801-1A     area=None, cls=P, unit=801, sub=1, train=A
      P-802A       area=None, cls=P, unit=802, train=A
      62-P-15100   area=62, cls=P, unit=15100, no train
    """
    empty = {
        "area_code": None, "equipment_class": None, "unit_number": None,
        "train_suffix": None, "is_duty": None, "is_standby": None, "parallel_tag": None,
    }
    if not tag or not isinstance(tag, str):
        return empty

    m = _TAG_PARSE_RE.match(tag.strip())
    if not m:
        return empty

    area  = m.group("area")   # e.g. "10" or None
    cls   = m.group("cls")    # "P" or "M"
    unit  = m.group("unit")   # e.g. "801"
    sub   = m.group("sub")    # e.g. "1" (the part after second hyphen) or None
    train = m.group("train")  # e.g. "A" or None

    # Reconstruct unit_number as the numeric portion after class letter
    unit_number = f"{unit}-{sub}" if sub else unit

    is_duty     = (train in _DUTY_TRAINS)    if train else None
    is_standby  = (train in _STANDBY_TRAINS) if train else None

    # Build the parallel tag (duty ↔ standby pair) by flipping the train letter
    parallel_tag = None
    if train and train in _TRAIN_FLIP:
        flipped = _TRAIN_FLIP[train]
        if area:
            parallel_tag = f"{area}-{cls}-{unit_number}{flipped}"
        else:
            parallel_tag = f"{cls}-{unit_number}{flipped}"

    return {
        "area_code":       area,
        "equipment_class": cls,
        "unit_number":     unit_number,
        "train_suffix":    train,
        "is_duty":         is_duty,
        "is_standby":      is_standby,
        "parallel_tag":    parallel_tag,
    }


def get_client() -> OpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENROUTER_API_KEY not set. Add it to .env file."
        )
    return OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)


def image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def extract_json_array(text: str) -> list:
    """Extract JSON array from model response, handles markdown fences."""
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return []
    return []


def extract_json_object(text: str) -> dict:
    """Extract JSON object from model response, handles markdown fences."""
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {}
    return {}


# ── Title block extraction ──────────────────────────────────────────────────────

def extract_drawing_number(pdf_path: str, tmp_dir: str = "tmp") -> str:
    """
    Crop the bottom-right 35% × 20% of the first PDF page (title block area)
    and ask the vision model to read the 'Drawing No.' field.
    Returns the drawing number string, or 'UNKNOWN' on failure.
    """
    import fitz
    from PIL import Image

    try:
        doc = fitz.open(pdf_path)
        page = doc[0]
        mat = fitz.Matrix(2.0, 2.0)  # 2x zoom is enough for title block
        pix = page.get_pixmap(matrix=mat)
        full_path = Path(tmp_dir) / "titleblock_full.png"
        Path(tmp_dir).mkdir(exist_ok=True)
        pix.save(str(full_path))
        doc.close()

        img = Image.open(str(full_path))
        W, H = img.size
        # Title block is bottom-right corner: rightmost 40%, bottom 22%
        crop = img.crop((int(W * 0.60), int(H * 0.78), W, H))
        crop_path = Path(tmp_dir) / "titleblock_crop.png"
        crop.save(str(crop_path))

        client = get_client()
        img_b64 = image_to_base64(str(crop_path))
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            max_tokens=128,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": (
                        "This is the title block from a P&ID engineering drawing. "
                        "Find the field labelled 'Drawing No.' or 'DRG NO' or 'Drawing Number' and return ONLY its full value including any revision suffix. "
                        "Example outputs: MUK-62-1-15-1004-001-24C7-D  or  MUK-62-1-15-1005-001-24C7-D "
                        "(note the trailing -D or similar revision code must be included if present). "
                        "Return ONLY the drawing number string, nothing else. "
                        "If you cannot find it, reply with: UNKNOWN"
                    )},
                ],
            }],
        )
        result = (response.choices[0].message.content or "").strip()
        # Strip any surrounding quotes or whitespace
        result = result.strip('"\'').strip()
        print(f"  Extracted Drawing No.: {result}")
        return result if result else "UNKNOWN"

    except Exception as e:
        print(f"  Warning: could not extract drawing number: {e}")
        return "UNKNOWN"


# ── Pass 1 ─────────────────────────────────────────────────────────────────────

def pass1_tile(tile: dict, client: OpenAI, model: str) -> list:
    """
    Pass 1: Send full tile → get valve tags + line numbers.
    Returns list of valve dicts.
    """
    img_b64 = image_to_base64(tile["path"])
    user_text = USER_PROMPT_TEMPLATE.format(
        drawing_description=DRAWING_DESCRIPTION,
        row=tile["row"],
        col=tile["col"],
    )
    response = client.chat.completions.create(
        model=model,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": user_text},
                ],
            },
        ],
    )
    raw_text = response.choices[0].message.content or ""
    valves = extract_json_array(raw_text)
    for v in valves:
        v["tile_row"] = tile["row"]
        v["tile_col"] = tile["col"]
        v["page"] = tile.get("page", 0)
    return valves


# ── Pass 2 ─────────────────────────────────────────────────────────────────────

def pass2_tile(tile: dict, missing_tags: list, client: OpenAI, model: str) -> dict:
    """
    Pass 2: Re-send a tile with specific valve tags, ask only for line numbers.
    Returns dict mapping valve_tag → line_number string (or None).
    """
    if not missing_tags:
        return {}

    img_b64 = image_to_base64(tile["path"])
    valve_list = "\n".join(f"  - {tag}" for tag in missing_tags)
    user_text = SECOND_PASS_USER_TEMPLATE.format(
        row=tile["row"],
        col=tile["col"],
        valve_list=valve_list,
    )
    response = client.chat.completions.create(
        model=model,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": SECOND_PASS_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": user_text},
                ],
            },
        ],
    )
    raw_text = response.choices[0].message.content or ""
    return extract_json_object(raw_text)


def apply_second_pass(all_valves: list, tile_map: dict, client: OpenAI, model: str) -> list:
    """
    For any valve still missing line_number after pass 1:
      - Group by tile
      - Run pass 2 on each affected tile
      - Backfill line_number into the valve dicts
    Returns updated valve list.
    """
    # Find valves with null OR incomplete line numbers (no "-" separator = partial string)
    def is_incomplete(line_no):
        if not line_no:
            return True
        s = str(line_no).strip()
        # Incomplete if it has no fluid-piping section (no second "-" after size)
        # e.g. "20"" or "2"-" or "10",LO" are all incomplete
        return "-" not in s or s.count("-") < 2

    missing_by_tile = defaultdict(list)
    for v in all_valves:
        if is_incomplete(v.get("line_number")):
            key = (v["tile_row"], v["tile_col"])
            missing_by_tile[key].append(v.get("valve_tag") or v.get("tag", ""))

    if not missing_by_tile:
        print("  Pass 2: All valves already have line numbers — skipping.")
        return all_valves

    total_missing = sum(len(tags) for tags in missing_by_tile.values())
    print(f"  Pass 2: {total_missing} valves missing line numbers across {len(missing_by_tile)} tiles")

    # Run pass 2 per tile
    recovered = 0
    for (row, col), tags in missing_by_tile.items():
        tile_key = (row, col)
        if tile_key not in tile_map:
            continue
        tile = tile_map[tile_key]
        unique_tags = list(dict.fromkeys(tags))  # preserve order, dedup

        print(f"    Tile r{row}c{col}: asking for line numbers of {len(unique_tags)} valves...")
        try:
            line_map = pass2_tile(tile, unique_tags, client, model)
            for tag, line_no in line_map.items():
                if line_no:
                    # Backfill into all matching valve dicts for this tile
                    for v in all_valves:
                        if (v.get("valve_tag") or v.get("tag", "")) == tag and v["tile_row"] == row and v["tile_col"] == col:
                            if not v.get("line_number"):
                                v["line_number"] = line_no
                                recovered += 1
            # Print what we got back
            for tag in unique_tags:
                result = line_map.get(tag)
                status = result if result else "still null"
                print(f"      {tag:25s} → {status}")
        except Exception as e:
            print(f"    ERROR on pass 2 tile r{row}c{col}: {e}")

    print(f"  Pass 2: recovered line numbers for {recovered} valve entries")
    return all_valves


# ── Pass 3 ─────────────────────────────────────────────────────────────────────

def _reconstruct_tile_origins(job_dir: str) -> dict:
    """
    Recompute tile (x0, y0) origins from the saved full-page image.
    Mirrors the tiling math in pdf_to_tiles.py (3×3 grid, 20% overlap).
    Returns {(row, col): (x0, y0)}.
    """
    import math
    from PIL import Image as _Image
    full_page = Path(job_dir) / "tmp" / "page_0_full.png"
    if not full_page.exists():
        return {}
    img = _Image.open(str(full_page))
    W, H = img.size
    img.close()
    grid_rows, grid_cols, overlap_pct = 3, 3, 0.20
    tile_w = math.ceil(W / grid_cols)
    tile_h = math.ceil(H / grid_rows)
    overlap_x = int(tile_w * overlap_pct)
    overlap_y = int(tile_h * overlap_pct)
    origins = {}
    for r in range(grid_rows):
        for c in range(grid_cols):
            origins[(r, c)] = (
                max(0, c * tile_w - overlap_x),
                max(0, r * tile_h - overlap_y),
            )
    return origins


def pass3_tile(tile_path: str, tile_row: int, tile_col: int,
               nodes: list, client: OpenAI, model: str) -> dict:
    """
    Pass 3: send one tile to Vision API, ask for equipment tags near each bbox.
    nodes: list of {node_id, class, tile_rel_bbox [x1,y1,x2,y2]}
    Returns {node_id: tag_string_or_null}.
    """
    if not nodes:
        return {}
    img_b64 = image_to_base64(tile_path)
    symbol_list = "\n".join(
        f"  {n['node_id']} | {n['class']} | bbox {[round(v) for v in n['tile_rel_bbox']]}"
        for n in nodes
    )
    user_text = THIRD_PASS_USER_TEMPLATE.format(
        row=tile_row, col=tile_col, symbol_list=symbol_list,
    )
    response = client.chat.completions.create(
        model=model,
        max_tokens=512,
        messages=[
            {"role": "system", "content": THIRD_PASS_SYSTEM},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text",      "text": user_text},
            ]},
        ],
    )
    raw_text = response.choices[0].message.content or ""
    return extract_json_object(raw_text)


def link_parallel_pairs(nodes: list) -> int:
    """
    Mutate nodes in place: set parallel_node_id on each node whose
    parallel_tag matches another node's tag in the same graph.
    Returns count of nodes that received a parallel_node_id.

    Only links when BOTH sides exist.  If a node has a parallel_tag
    but no matching node is found, parallel_node_id stays None.
    Bidirectional: if A points to B, B also points to A.
    """
    tag_to_node_id = {n["tag"]: n["id"] for n in nodes if n.get("tag")}

    linked = 0
    for node in nodes:
        ptag = node.get("parallel_tag")
        if not ptag:
            continue
        partner_node_id = tag_to_node_id.get(ptag)
        if partner_node_id:
            node["parallel_node_id"] = partner_node_id
            linked += 1
        else:
            node.setdefault("parallel_node_id", None)

    return linked


def link_related_instruments(nodes: list, canonical_entities: list) -> int:
    """
    Mutate equipment nodes in place: set related_instruments to a list of
    instrument tags from canonical.json whose numeric loop number contains
    the equipment's unit_number, with train-suffix filtering:
      - If equipment has a train_suffix AND the instrument tag ends with a
        train letter (A-F): only keep instruments whose suffix matches.
      - Instruments with no train suffix (shared/common) always match.

    Returns count of equipment nodes that got at least one related instrument.
    """
    instruments = [
        e for e in canonical_entities
        if e.get("entity_class") == "instrument" and e.get("tag")
    ]

    _TRAIN_LETTERS = _DUTY_TRAINS | _STANDBY_TRAINS  # {"A","B","C","D","E","F"}

    found_count = 0
    for node in nodes:
        if node.get("class") not in ("Pump/Dwg Pump", "Motor"):
            continue

        unit  = node.get("unit_number")
        train = node.get("train_suffix")  # "A"/"B"/None

        if not unit:
            node.setdefault("related_instruments", [])
            continue

        related = []
        for inst in instruments:
            itag = inst["tag"]

            # Skip if the unit_number string is not anywhere in the instrument tag
            if unit not in itag:
                continue

            # If the equipment has a train suffix, exclude instruments that carry
            # the *opposite* train suffix (instruments with no suffix are shared →
            # always included).
            if train:
                last = itag[-1] if itag else ""
                if last.isalpha() and last.upper() in _TRAIN_LETTERS:
                    if last.upper() != train:
                        continue

            related.append(itag)

        node["related_instruments"] = related
        if related:
            found_count += 1

    return found_count


def apply_third_pass(job_dir: str, model: str = DEFAULT_MODEL) -> dict:
    """
    Pass 3 orchestrator: finds untagged Pump/Motor nodes in canonical_graph.json,
    queries Vision API per tile, validates tags, writes results back to the file.
    """
    graph_path = Path(job_dir) / "canonical_graph.json"
    if not graph_path.exists():
        print("  Pass 3: canonical_graph.json not found — skipping.")
        return {"skipped": True}

    with open(graph_path) as f:
        graph = json.load(f)

    nodes = graph.get("nodes", [])
    _EQUIP_CLASSES = {"Pump/Dwg Pump", "Motor"}
    _TILE_RE = re.compile(r'tile_p\d+_r(\d+)_c(\d+)\.png')

    # Query nodes missing a tag OR missing a service_description.
    # Already-tagged nodes still get queried so descriptions can be back-filled.
    to_query = [
        n for n in nodes
        if n.get("class") in _EQUIP_CLASSES
        and (not n.get("tag") or not n.get("service_description"))
        and n.get("tile")
    ]

    print(f"  Pass 3: {len(to_query)} pump/motor nodes to query (tag or description missing)")
    if not to_query:
        return {"untagged_before": 0, "tagged": 0, "descriptions_found": 0}

    origins = _reconstruct_tile_origins(job_dir)
    if not origins:
        print("  Pass 3: could not read full-page image — skipping.")
        return {"skipped": True, "reason": "no page_0_full.png"}

    client = get_client()
    node_by_id = {n["id"]: n for n in nodes}

    # Group nodes by tile
    by_tile = defaultdict(list)
    for n in to_query:
        m = _TILE_RE.search(n["tile"])
        if not m:
            continue
        row, col = int(m.group(1)), int(m.group(2))
        tile_x0, tile_y0 = origins.get((row, col), (0, 0))
        bbox = n.get("bbox", [0, 0, 0, 0])
        by_tile[(row, col)].append({
            "node_id": n["id"],
            "class":   n["class"],
            "tile_rel_bbox": [
                bbox[0] - tile_x0, bbox[1] - tile_y0,
                bbox[2] - tile_x0, bbox[3] - tile_y0,
            ],
        })

    tagged = 0
    descriptions_found = 0
    raw_responses = {}

    for (row, col), tile_nodes in sorted(by_tile.items()):
        tile_path = str(Path(job_dir) / "tmp" / f"tile_p0_r{row}_c{col}.png")
        if not Path(tile_path).exists():
            print(f"    Tile r{row}c{col}: PNG missing — skipping")
            continue
        print(f"    Tile r{row}c{col}: querying {len(tile_nodes)} nodes...")
        try:
            result = pass3_tile(tile_path, row, col, tile_nodes, client, model)
            for entry in tile_nodes:
                nid = entry["node_id"]
                cls = entry["class"]
                raw = result.get(nid)
                raw_responses[nid] = raw

                # Handle new dict format {"tag": "...", "description": "..."}
                # and legacy string format for backward compat
                if isinstance(raw, dict):
                    tag_raw = raw.get("tag") or raw.get("t")
                    desc_raw = raw.get("description") or raw.get("desc") or raw.get("d")
                elif isinstance(raw, str) and raw.lower() not in ("null", "none", ""):
                    tag_raw = raw
                    desc_raw = None
                else:
                    tag_raw = None
                    desc_raw = None

                node = node_by_id[nid]

                # Only set tag if not already present
                if not node.get("tag"):
                    valid = (
                        bool(tag_raw) and isinstance(tag_raw, str) and (
                            (cls == "Pump/Dwg Pump" and _PUMP_TAG_RE.match(tag_raw)) or
                            (cls == "Motor"          and _MOTOR_TAG_RE.match(tag_raw))
                        )
                    )
                    if valid:
                        node["tag"] = tag_raw
                        node.update(parse_equipment_tag(tag_raw))
                        tagged += 1
                        print(f"      {nid} ({cls:14s}) tag={tag_raw}")
                    else:
                        print(f"      {nid} ({cls:14s}) tag=REJECTED({tag_raw!r})")

                # Set service_description (best-effort, no strict validation)
                if desc_raw and isinstance(desc_raw, str) and desc_raw.strip().lower() not in ("null", "none", ""):
                    # Collapse multiline descriptions to a single space-separated line
                    clean_desc = " ".join(desc_raw.split()).upper()
                    node["service_description"] = clean_desc
                    descriptions_found += 1
                    print(f"      {nid} ({cls:14s}) desc={clean_desc}")
        except Exception as e:
            print(f"    ERROR tile r{row}c{col}: {e}")

    # Backfill parsed fields onto any already-tagged nodes that don't have them yet
    backfilled = 0
    for node in graph.get("nodes", []):
        tag = node.get("tag")
        if tag and not node.get("equipment_class"):
            node.update(parse_equipment_tag(tag))
            backfilled += 1

    # Infer motor tags from spatially adjacent pump nodes (pump symbol sits directly
    # above or below motor symbol; Vision API often reads the pump tag for both).
    # Only runs when motor has no tag and a pump with a known tag is within ~600px.
    def _bbox_center(bbox):
        return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)

    tagged_pumps = [
        n for n in graph.get("nodes", [])
        if n.get("class") == "Pump/Dwg Pump" and n.get("tag") and n.get("bbox")
    ]
    motor_inferred = 0
    for node in graph.get("nodes", []):
        if node.get("class") != "Motor" or node.get("tag") or not node.get("bbox"):
            continue
        mx, my = _bbox_center(node["bbox"])
        best_pump, best_dist = None, float("inf")
        for pump in tagged_pumps:
            px, py = _bbox_center(pump["bbox"])
            dist = ((mx - px) ** 2 + (my - py) ** 2) ** 0.5
            if dist < best_dist:
                best_dist, best_pump = dist, pump
        if best_pump and best_dist < 600:
            derived = best_pump["tag"].replace("-P-", "-M-")
            if _MOTOR_TAG_RE.match(derived):
                node["tag"] = derived
                node.update(parse_equipment_tag(derived))
                motor_inferred += 1
                print(f"      {node['id']} (Motor        ) inferred tag={derived} from pump {best_pump['tag']} dist={best_dist:.0f}px")
    backfilled += motor_inferred

    # Link duty/standby pairs via parallel_node_id
    linked = link_parallel_pairs(graph.get("nodes", []))

    # Link related instruments from canonical.json
    canonical_path = Path(job_dir) / "canonical.json"
    instruments_found = 0
    if canonical_path.exists():
        with open(canonical_path) as f:
            canonical_entities = json.load(f).get("entities", [])
        instruments_found = link_related_instruments(graph.get("nodes", []), canonical_entities)
    else:
        for node in graph.get("nodes", []):
            if node.get("class") in ("Pump/Dwg Pump", "Motor"):
                node.setdefault("related_instruments", [])

    with open(graph_path, "w") as f:
        json.dump(graph, f, indent=2)

    print(f"  Pass 3 complete: {tagged} tags set, {descriptions_found} descriptions, {backfilled} backfilled, {linked} paired, {instruments_found} with related instruments")
    return {
        "queried": len(to_query), "tagged": tagged,
        "descriptions_found": descriptions_found,
        "backfilled": backfilled, "linked": linked,
        "instruments_found": instruments_found,
        "raw_responses": raw_responses,
    }


# ── Pass 4 ─────────────────────────────────────────────────────────────────────

def apply_fourth_pass(job_dir: str, model: str = DEFAULT_MODEL) -> dict:
    """
    Pass 4: read engineering data (pressure, temp, fluid, etc.) for each pipe
    line number from P&ID tile images and write line_list_data.json.

    Algorithm:
      1. Load canonical.json → {entity_id: line_number}
      2. Load detections_ocr.json → {entity_id: (row, col)}
      3. Per unique line number: pick the tile that appears most often across
         all entities on that line (best tile = most detections)
      4. One Vision API call per tile, passing all line numbers on that tile
      5. Write line_list_data.json to job_dir
    """
    from collections import Counter

    canonical_path = Path(job_dir) / "canonical.json"
    detections_path = Path(job_dir) / "detections_ocr.json"

    if not canonical_path.exists():
        print("  Pass 4: canonical.json not found — skipping.")
        return {"skipped": True, "reason": "no canonical.json"}

    with open(canonical_path) as f:
        canonical = json.load(f)
    detections_ocr = {}
    if detections_path.exists():
        with open(detections_path) as f:
            detections_ocr = json.load(f)
    else:
        print("  Pass 4: detections_ocr.json absent — all lines will scan all tiles.")

    _TILE_RE = re.compile(r'tile_p\d+_r(\d+)_c(\d+)\.png')

    # entity_id → line_number (skip entities with no line or no dash = not a real line tag)
    entity_to_line: dict = {}
    for ent in canonical.get("entities", []):
        line_val = ent.get("fields", {}).get("line")
        if line_val and isinstance(line_val, str) and "-" in line_val:
            entity_to_line[ent["entity_id"]] = line_val

    if not entity_to_line:
        print("  Pass 4: no line numbers found in canonical.json — skipping.")
        return {"skipped": True, "reason": "no line entities"}

    # entity_id → (row, col) from detections_ocr; also tag → (row, col) as fallback
    # (entity_ids change on job reprocess, but entity_tag is stable per detection)
    entity_to_tile: dict = {}
    tag_to_tile: dict = {}
    for det in detections_ocr.get("detections", []):
        eid = det.get("entity_id")
        etag = (det.get("entity_tag") or "").strip()
        tile_fname = det.get("tile") or det.get("tile_path") or ""
        if not tile_fname:
            continue
        m = _TILE_RE.search(tile_fname)
        if not m:
            continue
        rc = (int(m.group(1)), int(m.group(2)))
        if eid:
            entity_to_tile[eid] = rc
        if etag and etag not in tag_to_tile:
            tag_to_tile[etag] = rc

    # canonical entity_id → tag (needed for tag-based tile fallback)
    eid_to_tag: dict = {
        ent["entity_id"]: ent.get("tag", "")
        for ent in canonical.get("entities", [])
        if ent.get("entity_id") and ent.get("tag")
    }

    # For each unique line number, vote for the best tile
    line_tile_votes: dict = defaultdict(Counter)  # line_number → Counter{(row,col): count}
    for eid, line_no in entity_to_line.items():
        tile = entity_to_tile.get(eid)
        if not tile:
            # Fallback: look up by canonical tag when entity_id changed (e.g. after reprocess)
            tag = eid_to_tag.get(eid, "")
            if tag:
                tile = tag_to_tile.get(tag)
        if tile:
            line_tile_votes[line_no][tile] += 1

    # best tile per line number
    line_to_best_tile = {
        line_no: votes.most_common(1)[0][0]
        for line_no, votes in line_tile_votes.items()
    }

    # Group line numbers by their best tile
    tile_to_lines: dict = defaultdict(list)
    for line_no, tile in line_to_best_tile.items():
        tile_to_lines[tile].append(line_no)

    # Lines not mapped by any detection: scan every available tile for them
    import glob as _glob
    unmapped_lines = [ln for ln in set(entity_to_line.values()) if ln not in line_tile_votes]
    if unmapped_lines:
        all_tile_paths = sorted(_glob.glob(str(Path(job_dir) / "tmp" / "tile_p0_r*.png")))
        for tfpath in all_tile_paths:
            tm = _TILE_RE.search(Path(tfpath).name)
            if tm:
                rc = (int(tm.group(1)), int(tm.group(2)))
                tile_to_lines[rc].extend(unmapped_lines)
        print(f"  Pass 4: {len(unmapped_lines)} unmapped lines → scanning all {len(all_tile_paths)} tiles")

    if not tile_to_lines:
        print("  Pass 4: no tiles to query — skipping.")
        return {"skipped": True, "reason": "no tile mappings"}

    skipped_tiles = 0
    lines_found = 0
    tiles_queried = 0
    result_data: dict = {}

    client = get_client()

    for (row, col), line_numbers in sorted(tile_to_lines.items()):
        tile_path = Path(job_dir) / "tmp" / f"tile_p0_r{row}_c{col}.png"
        if not tile_path.exists():
            print(f"    Pass 4 tile r{row}c{col}: PNG missing — skipping {len(line_numbers)} lines")
            skipped_tiles += 1
            continue

        print(f"    Pass 4 tile r{row}c{col}: querying {len(line_numbers)} line numbers...")
        try:
            img_b64 = image_to_base64(str(tile_path))
            line_list_text = "\n".join(f"  - {ln}" for ln in sorted(line_numbers))
            user_text = FOURTH_PASS_USER_TEMPLATE.format(
                row=row, col=col, line_list=line_list_text,
            )
            response = client.chat.completions.create(
                model=model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": FOURTH_PASS_SYSTEM},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        {"type": "text", "text": user_text},
                    ]},
                ],
            )
            raw_text = response.choices[0].message.content or ""
            tile_result = extract_json_object(raw_text)
            if isinstance(tile_result, dict):
                for line_no, data in tile_result.items():
                    if data is not None and isinstance(data, dict):
                        result_data[line_no] = data
                        lines_found += 1
                        print(f"      {line_no}: fluid={data.get('fluid')}, P={data.get('op_pressure')}, T={data.get('op_temp')}")
            tiles_queried += 1
        except Exception as e:
            print(f"    Pass 4 ERROR tile r{row}c{col}: {e}")
            skipped_tiles += 1

    out_path = Path(job_dir) / "line_list_data.json"
    with open(out_path, "w") as f:
        json.dump(result_data, f, indent=2)

    print(f"  Pass 4 complete: {lines_found} lines populated, {tiles_queried} tiles queried, {skipped_tiles} tiles skipped")
    print(f"  Pass 4: wrote {out_path}")
    return {"lines_found": lines_found, "tiles_queried": tiles_queried, "skipped": False}


# ── Pass 5 ─────────────────────────────────────────────────────────────────────

def apply_fifth_pass(job_dir: str, model: str = DEFAULT_MODEL) -> dict:
    """
    Pass 5: read the specification data block printed near each equipment symbol
    on P&ID tiles and write equipment_specs.json.

    Algorithm:
      1. Load canonical.json → equipment entities that have tags
      2. Load detections_ocr.json → {entity_id: {tile, row, col, bbox}}
      3. For each tagged equipment entity with a matching detection:
         send one Vision API call (tile image + entity bbox) to extract the spec block
      4. Write equipment_specs.json keyed by equipment tag
    """
    canonical_path = Path(job_dir) / "canonical.json"
    detections_path = Path(job_dir) / "detections_ocr.json"

    if not canonical_path.exists():
        print("  Pass 5: canonical.json not found — skipping.")
        return {"skipped": True, "reason": "no canonical.json"}
    if not detections_path.exists():
        print("  Pass 5: detections_ocr.json not found — skipping.")
        return {"skipped": True, "reason": "no detections_ocr.json"}

    with open(canonical_path) as f:
        canonical = json.load(f)
    with open(detections_path) as f:
        detections_ocr = json.load(f)

    _TILE_RE = re.compile(r'tile_p\d+_r(\d+)_c(\d+)\.png')

    # entity_id → {tag, equipment_type} from canonical.json (tagged equipment only)
    equipment_entities: dict = {}
    for ent in canonical.get("entities", []):
        if ent.get("entity_class") != "equipment":
            continue
        tag = ent.get("tag")
        if not tag:
            continue
        equipment_entities[ent["entity_id"]] = {
            "tag": tag,
            "equipment_type": ent.get("fields", {}).get("equipment_type", ""),
        }

    if not equipment_entities:
        print("  Pass 5: no tagged equipment entities in canonical.json — skipping.")
        return {"skipped": True, "reason": "no equipment entities"}

    # entity_id → {tile_fname, row, col, bbox} from detections_ocr.json
    entity_to_detection: dict = {}
    for det in detections_ocr.get("detections", []):
        eid = det.get("entity_id")
        if not eid or eid not in equipment_entities:
            continue
        tile_fname = det.get("tile") or ""
        bbox = det.get("bbox")
        if not tile_fname or not bbox:
            continue
        m = _TILE_RE.search(tile_fname)
        if not m:
            continue
        entity_to_detection[eid] = {
            "tile_fname": tile_fname,
            "row": int(m.group(1)),
            "col": int(m.group(2)),
            "bbox": bbox,
        }

    if not entity_to_detection:
        print("  Pass 5: no equipment detections with tile info — skipping.")
        return {"skipped": True, "reason": "no equipment detections"}

    result_data: dict = {}
    queried = 0
    found = 0
    failed = 0

    client = get_client()

    for eid, equip in equipment_entities.items():
        det = entity_to_detection.get(eid)
        if not det:
            print(f"    Pass 5: no detection found for {equip['tag']} — skipping")
            continue

        tile_path = Path(job_dir) / "tmp" / det["tile_fname"]
        if not tile_path.exists():
            print(f"    Pass 5: tile {det['tile_fname']} missing for {equip['tag']} — skipping")
            failed += 1
            continue

        x1, y1, x2, y2 = det["bbox"]
        print(f"    Pass 5: querying {equip['tag']} ({equip['equipment_type']}) on {det['tile_fname']}...")
        try:
            img_b64 = image_to_base64(str(tile_path))
            user_text = FIFTH_PASS_USER_TEMPLATE.format(
                tag=equip["tag"],
                equipment_type=equip["equipment_type"],
                x1=x1, y1=y1, x2=x2, y2=y2,
            )
            response = client.chat.completions.create(
                model=model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": FIFTH_PASS_SYSTEM},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        {"type": "text", "text": user_text},
                    ]},
                ],
            )
            raw_text = response.choices[0].message.content or ""
            spec = extract_json_object(raw_text)
            if isinstance(spec, dict):
                cleaned = {
                    k: v.strip() if isinstance(v, str) else v
                    for k, v in spec.items()
                    if v is not None and str(v).strip().lower() not in ("null", "none", "")
                }
                result_data[equip["tag"]] = cleaned
                found += 1
                print(f"      {equip['tag']}: capacity={cleaned.get('rated_capacity')}, material={cleaned.get('material')}")
            queried += 1
        except Exception as e:
            print(f"    Pass 5 ERROR {equip['tag']}: {e}")
            failed += 1

    out_path = Path(job_dir) / "equipment_specs.json"
    with open(out_path, "w") as f:
        json.dump(result_data, f, indent=2)

    print(f"  Pass 5 complete: {found} specs extracted, {queried} queried, {failed} failed")
    print(f"  Pass 5: wrote {out_path}")
    return {"found": found, "queried": queried, "failed": failed, "skipped": False}


# ── Orchestrator ───────────────────────────────────────────────────────────────

def extract_all_tiles(tiles: list, model: str = DEFAULT_MODEL, save_raw: bool = True) -> list:
    """
    Full two-pass extraction across all tiles.
    Pass 1: valve tag + line number per tile.
    Pass 2: targeted line number re-query for any still missing.
    Saves tmp/raw_extractions.json after each pass.
    """
    client = get_client()

    # Build tile lookup for pass 2
    tile_map = {(t["row"], t["col"]): t for t in tiles}

    # ── Pass 1 ──
    print(f"\n  --- Pass 1: Valve + line number extraction ({model}) ---")
    all_valves = []
    for i, tile in enumerate(tiles):
        print(f"  [{i+1}/{len(tiles)}] Tile r{tile['row']}c{tile['col']}...")
        try:
            valves = pass1_tile(tile, client, model)
            found_with_line = sum(1 for v in valves if v.get("line_number"))
            print(f"    {len(valves)} valves | {found_with_line} with line numbers")
            for v in valves:
                ln = v.get("line_number") or "—"
                print(f"      {v.get('valve_tag','?'):25s}  line={ln:35s}  act={v.get('actuator','?')}")
            all_valves.extend(valves)
        except Exception as e:
            print(f"    ERROR: {e}")

    p1_with_line = sum(1 for v in all_valves if v.get("line_number"))
    print(f"\n  Pass 1 complete: {len(all_valves)} detections, {p1_with_line} have line numbers")

    _save_raw(all_valves, "tmp/raw_extractions_pass1.json")

    # ── Pass 2 ──
    print(f"\n  --- Pass 2: Line number recovery ---")
    all_valves = apply_second_pass(all_valves, tile_map, client, model)

    p2_with_line = sum(1 for v in all_valves if v.get("line_number"))
    print(f"\n  Pass 2 complete: {p2_with_line}/{len(all_valves)} detections now have line numbers")

    if save_raw:
        _save_raw(all_valves, "tmp/raw_extractions.json")

    return all_valves


def _full_page_path_for(tile: dict) -> Optional[str]:
    """Derive the full-page render path from a tile dict (saved by pdf_to_tiles)."""
    p = Path(tile["path"])
    candidate = p.parent / f"page_{tile.get('page', 0)}_full.png"
    return str(candidate) if candidate.exists() else None


def extract_equipment_context(full_page_image: str, model: str = DEFAULT_MODEL) -> dict:
    """
    Pre-pass: ask Vision for the page's contractor doc number AND the equipment
    list. Returns {"pid_no": str, "equipment": list}. Used to feed TAG SERVICE
    construction and per-page P&ID stamping in the instrument pass.
    """
    if not full_page_image or not Path(full_page_image).exists():
        return {"pid_no": "", "equipment": []}
    client = get_client()
    try:
        img_b64 = image_to_base64(full_page_image)
        response = client.chat.completions.create(
            model=model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": EQUIPMENT_CONTEXT_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        {"type": "text", "text": "Read this P&ID page and return the JSON object as specified."},
                    ],
                },
            ],
        )
        raw_text = response.choices[0].message.content or ""
        # The prompt asks for a single JSON object, but be tolerant if it
        # returns a list-wrapped or markdown-fenced version.
        obj = _extract_json_object(raw_text) or {}
        pid_no = (obj.get("pid_no") or "").strip()
        if pid_no.upper() == "UNKNOWN":
            pid_no = ""
        cleaned_eq = []
        for item in obj.get("equipment", []) or []:
            tag = (item.get("equipment_tag") or "").strip()
            name = (item.get("equipment_name") or "").strip()
            etype = (item.get("equipment_type") or "other").strip().lower()
            if tag and name:
                cleaned_eq.append({"equipment_tag": tag, "equipment_name": name, "equipment_type": etype})
        return {"pid_no": pid_no, "equipment": cleaned_eq}
    except Exception as e:
        print(f"    [equipment-context] ERROR: {e}")
        return {"pid_no": "", "equipment": []}


def _extract_json_object(text: str) -> Optional[dict]:
    """Best-effort: parse the first {...} JSON object from an LLM response."""
    if not text:
        return None
    # Strip markdown fences
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    # Find the first balanced JSON object
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start:i + 1])
                except Exception:
                    return None
    return None


def _format_equipment_context(items: list) -> str:
    if not items:
        return "  (no equipment context available)"
    lines = []
    for it in items:
        lines.append(f"  {it['equipment_tag']:<20} = {it['equipment_name']}")
    return "\n".join(lines)


def extract_instruments(tiles: list, drawing_description: str = "", model: str = DEFAULT_MODEL):
    """
    Single-pass instrument extraction across all tiles, preceded by a per-page
    equipment-context pre-pass. Finds all instrument bubbles (PT, TT, FT, PDT,
    LT, FCV, XV, ZT, etc.) — NOT valves.

    Returns (instruments, equipment_items):
      instruments    — list of raw instrument dicts
      equipment_items — list of {"equipment_tag", "equipment_name", "equipment_type",
                                  "pid_no"} dicts, one per unique tag across all pages
    """
    client = get_client()
    desc = drawing_description or DRAWING_DESCRIPTION
    all_instruments = []

    # Pre-pass: per-page contractor pid_no + equipment context
    print(f"\n  --- Instrument pre-pass: per-page pid_no + equipment ({model}) ---")
    page_context: dict = {}  # page_idx → {"pid_no": str, "equipment": list}
    seen_pages = set()
    for tile in tiles:
        page = tile.get("page", 0)
        if page in seen_pages:
            continue
        seen_pages.add(page)
        full_path = _full_page_path_for(tile)
        ctx = extract_equipment_context(full_path, model=model) if full_path else {"pid_no": "", "equipment": []}
        page_context[page] = ctx
        print(f"  page {page}: pid_no={ctx['pid_no'] or '?'}  equipment={len(ctx['equipment'])} items")

    print(f"\n  --- Instrument pass: bubble extraction ({model}) ---")
    for i, tile in enumerate(tiles):
        print(f"  [{i+1}/{len(tiles)}] Tile r{tile['row']}c{tile['col']}...")
        try:
            img_b64 = image_to_base64(tile["path"])
            page = tile.get("page", 0)
            ctx = page_context.get(page, {"pid_no": "", "equipment": []})
            equipment_context = _format_equipment_context(ctx["equipment"])
            user_text = INST_USER_TEMPLATE.format(
                drawing_description=desc,
                row=tile["row"],
                col=tile["col"],
                equipment_context=equipment_context,
            )
            response = client.chat.completions.create(
                model=model,
                max_tokens=8192,
                messages=[
                    {"role": "system", "content": INST_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                            {"type": "text", "text": user_text},
                        ],
                    },
                ],
            )
            raw_text = response.choices[0].message.content or ""
            instruments = extract_json_array(raw_text)
            for inst in instruments:
                inst["tile_row"] = tile["row"]
                inst["tile_col"] = tile["col"]
                inst["page"] = page
                # Stamp the page-specific contractor pid_no on every detection
                # so the parser uses the correct per-page value (deliverable expects
                # 05011-CPP-...-0002 for page 1's instruments, ...-0003 for page 2, etc.).
                if ctx["pid_no"]:
                    inst["pid_no"] = ctx["pid_no"]
            print(f"    {len(instruments)} instruments found")
            for inst in instruments:
                print(f"      {inst.get('tag_number', '?'):30s}  loc={inst.get('location', '?')}")
            all_instruments.extend(instruments)
        except Exception as e:
            print(f"    ERROR: {e}")

    # Collect equipment items across all pages, deduplicating by tag.
    seen_eq_tags: set = set()
    all_equipment: list = []
    for page_ctx in page_context.values():
        for item in page_ctx.get("equipment", []):
            tag = item.get("equipment_tag", "")
            if tag and tag not in seen_eq_tags:
                seen_eq_tags.add(tag)
                all_equipment.append({
                    "equipment_tag": tag,
                    "equipment_name": item.get("equipment_name", ""),
                    "equipment_type": item.get("equipment_type", "other"),
                    "pid_no": page_ctx.get("pid_no", ""),
                })

    print(f"\n  Instrument pass complete: {len(all_instruments)} raw detections, {len(all_equipment)} equipment items")
    return all_instruments, all_equipment


def _save_raw(data: list, path: str) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved → {path}")


if __name__ == "__main__":
    from pdf_to_tiles import pdf_to_tiles
    print("Stage 1: Generating tiles...")
    tiles = pdf_to_tiles("docs/INPUT-MUK-62-1-15-1004-001-24C7-D.pdf")
    print(f"\nStage 2: Two-pass extraction with {DEFAULT_MODEL}...")
    valves = extract_all_tiles(tiles)
    p_with = sum(1 for v in valves if v.get("line_number"))
    print(f"\nFinal: {len(valves)} detections, {p_with} with line numbers")
