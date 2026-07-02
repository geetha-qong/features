#!/usr/bin/env python3
"""Generate the frontend taxonomy module from webapp/taxonomy.json.

Single source of truth for P&ID symbol metadata is webapp/taxonomy.json. This
script reads it and emits a typed TS module the studio frontend imports for
per-class colors, display names, glyph kinds, the palette grouping, and the
model class list — so the palette / labelMap / PidSymbol surfaces never drift
from the backend.

Frontend palette surfaces are keyed by (entity_class, sub_class) where the
sub_class is non-null. YOLO-only rows (sub_class=null) and pure-visual rows
(arrows/connectors, entity_class=null) are excluded from the by-sub maps — they
have no palette/sub_class identity on the frontend (the model-label surface is
labelMap.MODEL_LABEL_NAMES, which stays hand-authored). Their YOLO labels are
still emitted in CLASS_NAMES for the model channel order.

Run:  python3 scripts/gen_taxonomy_ts.py
Output: webapp/frontend/src/studio/taxonomy.generated.ts
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_JSON = ROOT / "webapp" / "taxonomy.json"
OUT_TS = ROOT / "webapp" / "frontend" / "src" / "studio" / "taxonomy.generated.ts"

HEADER = "// GENERATED — do not edit; run scripts/gen_taxonomy_ts.py\n"


def main() -> None:
    tax = json.loads(TAXONOMY_JSON.read_text())
    classes = sorted(tax["classes"], key=lambda c: c["order"])

    # Frontend-facing maps cover only rows that have a sub_class identity.
    sub_rows = [c for c in classes if c["entity_class"] and c["sub_class"]]

    color_by_key: dict[str, str] = {}
    glyph_by_key: dict[str, str] = {}
    display_by_sub: dict[str, str] = {}
    # entity_class -> ordered list of {sub, color} for the palette grouping.
    palette: dict[str, list[dict[str, str]]] = {}
    for c in sub_rows:
        ec = c["entity_class"]
        sc = c["sub_class"]
        key = f"{ec}|{sc}"
        color_by_key[key] = c["color"]
        glyph_by_key[key] = c["glyph_kind"]
        display_by_sub[sc] = c["display_name"]
        palette.setdefault(ec, []).append({"sub": sc, "color": c["color"]})

    # Ordered YOLO label list (model channel order) — null yolo_labels excluded.
    class_names = [c["yolo_label"] for c in classes if c["yolo_label"] is not None]

    def emit_str_record(name: str, data: dict[str, str]) -> str:
        body = "".join(
            f"  {json.dumps(k)}: {json.dumps(v)},\n" for k, v in data.items()
        )
        return f"export const {name}: Record<string, string> = {{\n{body}}};\n"

    def emit_palette(data: dict[str, list[dict[str, str]]]) -> str:
        lines = ["export const PALETTE_DATA: Record<string, { sub: string; color: string }[]> = {\n"]
        for ec, entries in data.items():
            lines.append(f"  {json.dumps(ec)}: [\n")
            for e in entries:
                lines.append(
                    f"    {{ sub: {json.dumps(e['sub'])}, color: {json.dumps(e['color'])} }},\n"
                )
            lines.append("  ],\n")
        lines.append("};\n")
        return "".join(lines)

    parts = [
        HEADER,
        "//\n",
        "// Source: webapp/taxonomy.json. COLOR/GLYPH keys are\n",
        "// `${entity_class}|${sub_class}`; DISPLAY_NAME is keyed by sub_class.\n",
        "\n",
        f"export const SCHEMA_VERSION = {json.dumps(tax.get('schema_version'))};\n",
        "\n",
        emit_str_record("COLOR_BY_KEY", color_by_key),
        "\n",
        emit_str_record("GLYPH_KIND_BY_KEY", glyph_by_key),
        "\n",
        emit_str_record("DISPLAY_NAME_BY_SUB", display_by_sub),
        "\n",
        emit_palette(palette),
        "\n",
        f"export const CLASS_NAMES: string[] = {json.dumps(class_names)};\n",
    ]

    OUT_TS.write_text("".join(parts))
    print(f"Wrote {OUT_TS.relative_to(ROOT)} ({len(sub_rows)} sub-class rows, {len(class_names)} yolo classes)")


if __name__ == "__main__":
    main()
