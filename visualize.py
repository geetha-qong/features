"""
Generate an annotated PDF/PNG showing detected valves with numbered bounding boxes.

Usage (from pipeline):
    from visualize import generate_annotated_pdf
    generate_annotated_pdf(raw_valves, tiles, pdf_path, output_pdf)
"""
from pathlib import Path
from typing import List, Dict, Optional
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF


# Colours per detection source
COLOR_OCR   = (0, 180, 0)    # green  — full tag from OCR
COLOR_REASM = (255, 140, 0)   # orange — tag reassembled from serial fragments
COLOR_YOLO  = (220, 50, 50)   # red    — YOLO-only, no tag found

FONT_SIZE = 28
BOX_PADDING = 6


def _get_font(size: int = FONT_SIZE):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except Exception:
        return ImageFont.load_default()


def _color_for(v: Dict) -> tuple:
    tag = v.get("valve_tag")
    if not tag:
        return COLOR_YOLO
    if "(reassembled)" in str(v.get("source", "")):
        return COLOR_REASM
    # distinguish: if bbox_tile came from OCR text (conf==0) vs YOLO detection
    if v.get("yolo_conf", 1) == 0.0:
        return COLOR_REASM
    return COLOR_OCR


def generate_annotated_pdf(
    raw_valves: List[Dict],
    tiles: List[Dict],
    full_png_path: str,
    output_path: str,
    deduped_tags: Optional[List[str]] = None,
) -> str:
    """
    Draw numbered bounding boxes on the full-page PNG and save as PDF.

    - Green box  = full tag found directly in OCR text
    - Orange box = tag reassembled from serial fragments
    - Red box    = YOLO detection only, no readable tag

    Numbers correspond to rows in the output CSV (1-indexed).
    """
    full_png = Path(full_png_path)
    if not full_png.exists():
        print(f"  [visualize] Full page image not found: {full_png_path}")
        return ""

    img = Image.open(str(full_png)).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = _get_font(FONT_SIZE)
    small_font = _get_font(max(18, FONT_SIZE - 8))

    # Deduplicate: keep one detection per tag (prefer highest conf)
    seen_tags = {}
    ordered = []
    for v in raw_valves:
        tag = v.get("valve_tag")
        bbox = v.get("bbox_tile")
        if not bbox:
            continue
        tx0 = v.get("tile_x0", 0)
        ty0 = v.get("tile_y0", 0)
        # Full-page coords
        fx1 = tx0 + bbox[0]
        fy1 = ty0 + bbox[1]
        fx2 = tx0 + bbox[2]
        fy2 = ty0 + bbox[3]
        if fx2 <= fx1 or fy2 <= fy1:
            continue
        key = tag or f"yolo_{round(fx1)}_{round(fy1)}"
        entry = {"tag": tag, "fx1": fx1, "fy1": fy1, "fx2": fx2, "fy2": fy2, "v": v, "key": key}
        if key not in seen_tags:
            seen_tags[key] = entry
            ordered.append(entry)
        elif v.get("yolo_conf", 0) > seen_tags[key]["v"].get("yolo_conf", 0):
            seen_tags[key].update(entry)

    # Sort by position: top-to-bottom, left-to-right
    ordered.sort(key=lambda e: (round(e["fy1"] / 200) * 10000 + e["fx1"]))

    # Filter to deduped_tags if provided (i.e. only draw what made it to CSV)
    if deduped_tags:
        deduped_set = set(deduped_tags)
        ordered = [e for e in ordered if e["tag"] in deduped_set] + \
                  [e for e in ordered if e["tag"] not in deduped_set]

    for seq, entry in enumerate(ordered, start=1):
        tag = entry["tag"]
        fx1, fy1, fx2, fy2 = entry["fx1"], entry["fy1"], entry["fx2"], entry["fy2"]
        color = _color_for(entry["v"])

        # Draw box
        for thickness in range(3):
            draw.rectangle(
                [fx1 - BOX_PADDING - thickness,
                 fy1 - BOX_PADDING - thickness,
                 fx2 + BOX_PADDING + thickness,
                 fy2 + BOX_PADDING + thickness],
                outline=color
            )

        # Label background
        label = f"{seq}" if not tag else f"{seq}: {tag}"
        try:
            bbox_text = font.getbbox(label)
            tw, th = bbox_text[2] - bbox_text[0], bbox_text[3] - bbox_text[1]
        except Exception:
            tw, th = len(label) * 14, FONT_SIZE
        lx = fx1 - BOX_PADDING
        ly = max(0, fy1 - BOX_PADDING - th - 6)
        draw.rectangle([lx - 2, ly - 2, lx + tw + 4, ly + th + 4], fill=color)
        draw.text((lx, ly), label, fill=(255, 255, 255), font=font)

    # Legend in top-left corner
    _draw_legend(draw, font, small_font)

    # Save as PNG then wrap in PDF with fitz
    png_out = Path(output_path).with_suffix(".png")
    img.save(str(png_out), dpi=(150, 150))
    print(f"  [visualize] Annotated PNG saved → {png_out}")

    # Wrap PNG in a PDF page
    pdf_doc = fitz.open()
    img_w, img_h = img.size
    # 72 DPI page — scale so it fits on A1-ish page at ~150 DPI equivalent
    scale = 72 / 150
    page = pdf_doc.new_page(width=img_w * scale, height=img_h * scale)
    rect = fitz.Rect(0, 0, img_w * scale, img_h * scale)
    page.insert_image(rect, filename=str(png_out))
    pdf_doc.save(output_path)
    pdf_doc.close()
    print(f"  [visualize] Annotated PDF saved → {output_path}  ({len(ordered)} detections marked)")
    return output_path


def _draw_legend(draw: ImageDraw.ImageDraw, font, small_font):
    items = [
        (COLOR_OCR,   "Tag found (OCR)"),
        (COLOR_REASM, "Tag reassembled"),
        (COLOR_YOLO,  "YOLO only"),
    ]
    x, y = 20, 20
    box_w = 300
    row_h = FONT_SIZE + 12
    pad = 10
    total_h = row_h * len(items) + pad * 2
    draw.rectangle([x - pad, y - pad, x + box_w, y + total_h], fill=(0, 0, 0, 200))
    for color, label in items:
        draw.rectangle([x, y + 4, x + FONT_SIZE, y + FONT_SIZE + 4], fill=color)
        draw.text((x + FONT_SIZE + 8, y), label, fill=(255, 255, 255), font=font)
        y += row_h
