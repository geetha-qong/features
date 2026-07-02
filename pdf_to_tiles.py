"""
Stage 1: Convert P&ID PDF to overlapping PNG tiles.
Renders the PDF at up to 6x zoom and splits into a 3x3 grid with overlap.

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

Large-page safety (added 2026-06-19): A0/A1 sheets at zoom 6 can exceed
100 MP, causing OOM in the worker. We auto-reduce zoom so the full-page
render stays within MAX_SAFE_PIXELS. For large sheets the native page is
already big enough that even zoom 2-3 gives tiles with adequate tag legibility.
"""
import fitz  # PyMuPDF
from pathlib import Path
from PIL import Image
import math

# PIL warns at 89 MP by default; we manage zoom ourselves so raise the limit.
Image.MAX_IMAGE_PIXELS = 300_000_000  # 300 MP ceiling — ~900 MB RAM at RGB

# Pixel budget per full-page render. Kept below 300 MP to avoid OOM.
_MAX_SAFE_PIXELS = 200_000_000  # 200 MP

# Minimum tile width in pixels for tag legibility in the Vision API pass.
_MIN_TILE_PX = 1900


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

        # Auto-cap zoom for large pages to stay within safe memory budget.
        # PDF points are 1/72 inch; page.rect gives native dimensions.
        native_w = page.rect.width   # points
        native_h = page.rect.height  # points
        max_zoom_memory  = math.sqrt(_MAX_SAFE_PIXELS / max(native_w * native_h, 1))
        min_zoom_quality = (_MIN_TILE_PX * grid_cols) / max(native_w, 1)
        # Quality floor wins if memory cap would go below it (better to OOM-warn
        # than to produce tiles too small to extract tags from).
        effective_zoom = max(min_zoom_quality, min(zoom, max_zoom_memory))
        if effective_zoom < zoom:
            print(
                f"  [pdf_to_tiles] page {page_idx}: large page "
                f"({native_w:.0f}×{native_h:.0f} pt) — zoom capped "
                f"{zoom}x → {effective_zoom:.2f}x to stay within memory budget"
            )

        mat = fitz.Matrix(effective_zoom, effective_zoom)
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
