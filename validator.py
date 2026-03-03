"""
Stage 4: Validate rows and output CSV.
Flags incomplete rows, checks tag format, writes final CSV.
"""
import re
import pandas as pd
from pathlib import Path
from parser import ValveRow

TAG_REGEX = re.compile(r"^\d{2}-[A-Z]{2,4}-\d{5,6}$")
VALID_CATEGORIES = {
    "BF", "BV", "VB", "VC", "VM", "VG", "VGL", "NV", "SV",
    "CV", "PCV", "FCV", "LCV",
    "GL",   # Globe valve
    "CK",   # Check valve
    "DB",   # Double Block & Bleed assembly
    "DBB",  # Double Block & Bleed (alternate code)
}


def validate_row(row: ValveRow) -> list[str]:
    """Return list of warning strings for this row. Empty = valid."""
    warnings = []
    if not TAG_REGEX.match(row.raw_tag.upper()):
        warnings.append(f"Unusual tag format: '{row.raw_tag}'")
    if row.category.upper() not in VALID_CATEGORIES:
        warnings.append(f"Unknown valve category: '{row.category}'")
    if row.size == "TBA":
        warnings.append("Size not extracted from line number")
    if not row.fluid_code:
        warnings.append("Fluid code missing")
    if not row.piping_class:
        warnings.append("Piping class missing")
    return warnings


def validate_and_report(rows: list[ValveRow]) -> tuple[list[ValveRow], list[dict]]:
    """
    Validate all rows. Returns (valid_rows, issues_list).
    Issues list contains dicts with {tag, warnings} for manual review.
    """
    valid = []
    issues = []
    for row in rows:
        warns = validate_row(row)
        valid.append(row)  # Include all rows in output, flag issues separately
        if warns:
            issues.append({"tag": row.raw_tag, "warnings": warns})
    return valid, issues


def write_csv(rows: list[ValveRow], output_path: str = "docs/output_valve_list.csv") -> None:
    """Write validated rows to CSV matching the expected output format."""
    records = [r.to_csv_dict() for r in rows]
    df = pd.DataFrame(records)
    df.to_csv(output_path, index=False)
    print(f"Wrote {len(rows)} valves to {output_path}")


def compare_with_ground_truth(
    output_path: str = "docs/output_valve_list.csv",
    ground_truth_path: str = "docs/Output-Valve List.csv",
) -> dict:
    """
    Compare output against ground truth CSV.
    Returns accuracy metrics.
    """
    try:
        out_df = pd.read_csv(output_path).dropna(how="all")
        gt_df = pd.read_csv(ground_truth_path).dropna(how="all")
    except Exception as e:
        print(f"Cannot compare: {e}")
        return {}

    def clean_serial(s):
        """Convert pandas float-read serials like '151031.0' → '151031'"""
        s = str(s).strip()
        if s.endswith(".0"):
            s = s[:-2]
        return s

    # Match on Area Code + Serial No (filter to current drawing if possible)
    out_pid = out_df["P&ID No"].astype(str).str.strip().iloc[0] if len(out_df) else ""
    if out_pid and out_pid in gt_df["P&ID No"].astype(str).str.strip().values:
        gt_df = gt_df[gt_df["P&ID No"].astype(str).str.strip() == out_pid]

    out_keys = set(
        zip(out_df["Area Code"].astype(str).str.strip().apply(clean_serial),
            out_df["Serial No"].astype(str).str.strip().apply(clean_serial))
    )
    gt_keys = set(
        zip(gt_df["Area Code"].astype(str).str.strip().apply(clean_serial),
            gt_df["Serial No"].astype(str).str.strip().apply(clean_serial))
    )

    found = out_keys & gt_keys
    missed = gt_keys - out_keys
    extra = out_keys - gt_keys

    recall = len(found) / len(gt_keys) if gt_keys else 0
    precision = len(found) / len(out_keys) if out_keys else 0

    print(f"\n=== Accuracy Report ===")
    print(f"Ground truth valves : {len(gt_keys)}")
    print(f"Extracted valves    : {len(out_keys)}")
    print(f"Correctly found     : {len(found)}")
    print(f"Missed              : {len(missed)} → {missed}")
    print(f"Extra (false pos.)  : {len(extra)}")
    print(f"Recall              : {recall:.1%}")
    print(f"Precision           : {precision:.1%}")

    return {
        "recall": recall,
        "precision": precision,
        "found": len(found),
        "missed": len(missed),
        "extra": len(extra),
        "missed_tags": list(missed),
    }


if __name__ == "__main__":
    import json
    from parser import parse_raw_extractions

    with open("tmp/raw_extractions.json") as f:
        raw = json.load(f)

    rows = parse_raw_extractions(raw)
    valid_rows, issues = validate_and_report(rows)

    if issues:
        print(f"\nValidation issues ({len(issues)} rows):")
        for iss in issues:
            print(f"  {iss['tag']}: {', '.join(iss['warnings'])}")

    write_csv(valid_rows)
    compare_with_ground_truth()
