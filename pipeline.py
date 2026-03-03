"""
Main pipeline: PDF → Tiles → Claude Vision → Parse → Validate → CSV

Usage:
    python pipeline.py
    python pipeline.py --skip-extraction   # re-use cached tmp/raw_extractions.json
    python pipeline.py --pdf docs/some_other_pid.pdf
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

from pdf_to_tiles import pdf_to_tiles
from extractor import extract_all_tiles
from parser import parse_raw_extractions
from validator import validate_and_report, write_csv, compare_with_ground_truth
from corrections import apply_corrections


DEFAULT_PDF = "docs/INPUT-MUK-62-1-15-1004-001-24C7-D.pdf"
OUTPUT_DIR = Path("docs/runs")  # timestamped outputs go here
RAW_CACHE = "tmp/raw_extractions.json"

# Drawing-specific config — update per P&ID
DRAWING_CONFIG = {
    "docs/INPUT-MUK-62-1-15-1004-001-24C7-D.pdf": {
        "pid_no": "MUK-62-1-15-1004-001-24C7",
        "description": "FW Transfer Pump (62-P-151005), Occidental Mukhaizna LLC",
    },
    "docs/MUK-62-1-15-1005-001-24C7-D.pdf": {
        "pid_no": "MUK-62-1-15-1005-001-24C7",
        "description": "Occidental Mukhaizna LLC",
    },
}


def make_output_path(pdf_path: str) -> str:
    """Generate timestamped output path: docs/runs/output_valve_list_YYYYMMDD_HHMMSS.csv"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = Path(pdf_path).stem.replace("INPUT-", "")
    return str(OUTPUT_DIR / f"valve_list_{stem}_{ts}.csv")


def run(pdf_path: str, output_path: str = None, skip_extraction: bool = False):
    if output_path is None:
        output_path = make_output_path(pdf_path)

    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"P&ID Valve List Extractor  [{run_ts}]")
    print(f"Input:  {pdf_path}")
    print(f"Output: {output_path}")
    print(f"{'='*60}\n")

    config = DRAWING_CONFIG.get(pdf_path, {"pid_no": "UNKNOWN", "description": pdf_path})

    # Stage 1: PDF → tiles
    if not skip_extraction:
        print("Stage 1: Converting PDF to tiles...")
        tiles = pdf_to_tiles(pdf_path)
        print(f"  Generated {len(tiles)} tiles\n")

        # Stage 2: Two-pass Claude Vision extraction
        print("Stage 2: Extracting valves (Pass 1: tags+lines / Pass 2: line recovery)...")
        raw_valves = extract_all_tiles(tiles)
        p_with = sum(1 for v in raw_valves if v.get("line_number"))
        print(f"\n  Total raw detections : {len(raw_valves)}")
        print(f"  With line numbers    : {p_with}/{len(raw_valves)}\n")
    else:
        print("Skipping extraction — loading from cache...")
        with open(RAW_CACHE) as f:
            raw_valves = json.load(f)
        print(f"  Loaded {len(raw_valves)} cached detections\n")
        # Re-generate tile list for reference (no API calls)
        tiles = pdf_to_tiles.__doc__ and []  # just skip

    # Stage 3: Parse + deduplicate
    print("Stage 3: Parsing and deduplicating...")
    rows = parse_raw_extractions(raw_valves, pid_no=config["pid_no"])
    print()

    # Stage 3b: Apply drawing-specific manual corrections
    drawing_stem = Path(pdf_path).stem.replace("INPUT-", "")
    rows = apply_corrections(rows, drawing_stem)
    print()

    # Stage 4: Validate + write CSV
    print("Stage 4: Validating and writing CSV...")
    valid_rows, issues = validate_and_report(rows)

    if issues:
        print(f"  {len(issues)} rows have warnings:")
        for iss in issues:
            print(f"    {iss['tag']}: {', '.join(iss['warnings'])}")

    write_csv(valid_rows, output_path)

    # Compare with ground truth if available
    gt_path = "docs/Output-Valve List.csv"
    if Path(gt_path).exists():
        print()
        metrics = compare_with_ground_truth(output_path, gt_path)
        if metrics.get("recall", 0) >= 0.90:
            print(f"\n✓ TARGET MET: {metrics['recall']:.1%} recall (≥90% required)")
        else:
            print(f"\n✗ Below target: {metrics.get('recall', 0):.1%} recall (need ≥90%)")

    print(f"\nDone. Output: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default=DEFAULT_PDF)
    parser.add_argument("--output", default=None,
                        help="Override output path (default: docs/runs/valve_list_<drawing>_<timestamp>.csv)")
    parser.add_argument("--skip-extraction", action="store_true",
                        help="Skip API calls, use cached tmp/raw_extractions.json")
    args = parser.parse_args()

    run(args.pdf, args.output, skip_extraction=args.skip_extraction)
