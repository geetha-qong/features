#!/usr/bin/env python3
"""Generate the Label Studio labeling config from webapp/taxonomy.json.

Single source of truth for the P&ID symbol taxonomy is webapp/taxonomy.json.
This script reads it and emits scripts/ls_label_config.xml — a RectangleLabels
<View> whose <Label> values are exactly the YOLO classes (rows with a non-null
``yolo_label``), each carrying its taxonomy ``color`` as the LS background.

Keeping LS labels derived from the taxonomy means the model channel order, the
studio palette, and the annotation tool never drift from one another. Ordering
follows the taxonomy ``order`` field; label *values* are the YOLO labels.

Run:  python3 scripts/gen_ls_label_config.py
Output: scripts/ls_label_config.xml
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_JSON = ROOT / "webapp" / "taxonomy.json"
OUT_XML = ROOT / "scripts" / "ls_label_config.xml"

HEADER = """<!--
  GENERATED — do not edit by hand; run scripts/gen_ls_label_config.py
  (source of truth: webapp/taxonomy.json).

  Canonical Label Studio labeling config for P&ID annotation projects.
  - To add/remove a label: edit webapp/taxonomy.json, then re-run this script
    and `scripts/ls_sync_labels.py`.
  - For NEW projects: paste this XML into the LS "Labeling Setup" step.

  Label values are the YOLO classes (taxonomy rows with a non-null yolo_label),
  in taxonomy order; backgrounds are the taxonomy colors.
-->
"""


def main() -> None:
    tax = json.loads(TAXONOMY_JSON.read_text())
    classes = sorted(tax["classes"], key=lambda c: c["order"])
    yolo_rows = [c for c in classes if c.get("yolo_label") is not None]

    lines = [
        HEADER,
        "<View>\n",
        '  <Image name="image" value="$image"/>\n',
        '  <RectangleLabels name="label" toName="image">\n',
    ]
    for c in yolo_rows:
        value = c["yolo_label"]
        background = c["color"]
        lines.append(f'    <Label value="{value}" background="{background}"/>\n')
    lines.append("  </RectangleLabels>\n")
    lines.append("</View>\n")

    OUT_XML.write_text("".join(lines))
    print(f"Wrote {OUT_XML.relative_to(ROOT)} ({len(yolo_rows)} YOLO labels)")


if __name__ == "__main__":
    main()
