"""
Stage 1: Convert P&ID PDF to overlapping PNG tiles.
Renders the PDF at 6x zoom and splits into a grid with overlap.

Why 6x (bumped from 4x on 2026-06-13): the earlier 4x cap was chosen for
*canvas* sharpness, but it starved the *extraction*. On dense, tag-heavy A3
sheets (e.g. the 70310-20-* drawings), 4x renders each 3x3 tile at only ~1900px,
leaving tag text ~10-15px tall — too small for the OpenRouter Vision pass to
read, so it returned 0 entities and the deliverables came out empty. Measured
on job 50 page 0: zoom 4 → 0 valves; zoom 6 → 121 valves, all 121 tagged. The
PDFs are vector (no text layer, ~95% vector objects), so higher DPI yields
genuinely crisp text rather than upscaled blur. Cost: render pixels grow
(6/4)^2 = 2.25x → bigger tile PNGs + more tokens per Vision call. Accepted —
recall is the product's core metric. YOLO inference is unaffected (it
letterboxes to 640). Grid stays 3x3 so the tile-geometry contract shared with
PidCanvas.computeTileOffsets + webapp/graph/loader.py is untouched.
"""
import fitz  # PyMuPDF
from pathlib import Path
from PIL import Image
import math


def pdf_to_tiles(
    pdf_path: str,
    output_dir: str = "tmp",
    zoom: float = 6.0,
    grid_rows: int = 3,
    grid_cols: int = 3,
    overlap_pct: float = 0.20,
) -> list:
    """
    Render PDF page(s) and split into overlapping tiles.

    Returns list of tile dicts:
      {"path": str, "row": int, "col": int, "x0": int, "y0": int, "x1": int, "y1": int}
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(exist_ok=True)

    doc = fitz.open(pdf_path)
    tiles = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        full_img_path = out_dir / f"page_{page_idx}_full.png"
        pix.save(str(full_img_path))

        img = Image.open(str(full_img_path))
        W, H = img.size

        tile_w = math.ceil(W / grid_cols)
        tile_h = math.ceil(H / grid_rows)
        overlap_x = int(tile_w * overlap_pct)
        overlap_y = int(tile_h * overlap_pct)

        for r in range(grid_rows):
            for c in range(grid_cols):
                x0 = max(0, c * tile_w - overlap_x)
                y0 = max(0, r * tile_h - overlap_y)
                x1 = min(W, (c + 1) * tile_w + overlap_x)
                y1 = min(H, (r + 1) * tile_h + overlap_y)

                tile = img.crop((x0, y0, x1, y1))
                tile_path = out_dir / f"tile_p{page_idx}_r{r}_c{c}.png"
                tile.save(str(tile_path))

                tiles.append({
                    "path": str(tile_path),
                    "page": page_idx,
                    "row": r,
                    "col": c,
                    "x0": x0, "y0": y0,
                    "x1": x1, "y1": y1,
                })
                print(f"  Tile p{page_idx}_r{r}_c{c}: ({x0},{y0})-({x1},{y1}) -> {tile_path.name}")

    doc.close()
    return tiles


if __name__ == "__main__":
    import sys
    pdf = sys.argv[1] if len(sys.argv) > 1 else "docs/INPUT-MUK-62-1-15-1004-001-24C7-D.pdf"
    print(f"Converting {pdf} to tiles...")
    tiles = pdf_to_tiles(pdf)
    print(f"\nGenerated {len(tiles)} tiles in tmp/")
