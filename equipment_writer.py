"""Write extracted equipment items to equipment_list.csv."""

import csv
from pathlib import Path
from typing import List, Optional

EQUIPMENT_CSV_COLUMNS = [
    "Tag",
    "Equipment Name",
    "Equipment Type",
    "P&ID No",
]


def write_equipment_list(equipment_items: List[dict], output_path: Optional[str]) -> None:
    """Write equipment items to CSV.

    Args:
        equipment_items: list of dicts with keys equipment_tag, equipment_name,
                         equipment_type, pid_no — as returned by extractor.extract_instruments.
        output_path: destination CSV path. If None, skips writing.
    """
    if not output_path:
        return
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EQUIPMENT_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for item in equipment_items:
            writer.writerow({
                "Tag": item.get("equipment_tag", ""),
                "Equipment Name": item.get("equipment_name", ""),
                "Equipment Type": item.get("equipment_type", "other"),
                "P&ID No": item.get("pid_no", ""),
            })
    print(f"  Saved equipment list → {output_path}")
