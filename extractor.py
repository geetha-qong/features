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
from openai import OpenAI
from dotenv import load_dotenv
from prompts import (
    SYSTEM_PROMPT, USER_PROMPT_TEMPLATE,
    SECOND_PASS_SYSTEM, SECOND_PASS_USER_TEMPLATE,
)
from instrument_prompts import INST_SYSTEM_PROMPT, INST_USER_TEMPLATE

load_dotenv(Path(__file__).parent / ".env")

# ── Provider config ────────────────────────────────────────────────────────────
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Best vision models on OpenRouter for technical P&ID drawings:
#   google/gemini-2.0-flash-001     — fastest, excellent dense-text vision
#   anthropic/claude-sonnet-4-6 — best reasoning
#   openai/gpt-4o                   — strong alternative
DEFAULT_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")

DRAWING_DESCRIPTION = "FW Transfer Pump (62-P-151005), Occidental Mukhaizna LLC, drawing MUK-62-1-15-1004-001"
# ──────────────────────────────────────────────────────────────────────────────


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
            missing_by_tile[key].append(v["valve_tag"])

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
                        if v["valve_tag"] == tag and v["tile_row"] == row and v["tile_col"] == col:
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


def extract_instruments(tiles: list, drawing_description: str = "", model: str = DEFAULT_MODEL) -> list:
    """
    Single-pass instrument extraction across all tiles.
    Finds all instrument bubbles (PT, TT, FT, PDT, LT, FCV, XV, ZT, etc.) — NOT valves.
    Returns list of raw instrument dicts.
    """
    client = get_client()
    desc = drawing_description or DRAWING_DESCRIPTION
    all_instruments = []

    print(f"\n  --- Instrument Pass: bubble extraction ({model}) ---")
    for i, tile in enumerate(tiles):
        print(f"  [{i+1}/{len(tiles)}] Tile r{tile['row']}c{tile['col']}...")
        try:
            img_b64 = image_to_base64(tile["path"])
            user_text = INST_USER_TEMPLATE.format(
                drawing_description=desc,
                row=tile["row"],
                col=tile["col"],
            )
            response = client.chat.completions.create(
                model=model,
                max_tokens=2048,
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
            print(f"    {len(instruments)} instruments found")
            for inst in instruments:
                print(f"      {inst.get('tag_number', '?'):30s}  sys={inst.get('system', '?')}")
            all_instruments.extend(instruments)
        except Exception as e:
            print(f"    ERROR: {e}")

    print(f"\n  Instrument pass complete: {len(all_instruments)} raw detections")
    return all_instruments


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
