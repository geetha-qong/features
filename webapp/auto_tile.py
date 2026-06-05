"""Auto-tile worker — converts a PDF-as-task into N PNG-tile tasks in Label Studio.

Triggered by the LS `TASKS_CREATED` webhook (see `webapp/routers/webhooks.py`).
The webhook handler enqueues `auto_tile_ls_task_rq` per qualifying task onto
the cpu-worker queue so the HTTP response goes back to LS in <100ms — the
heavy lifting (PDF download, tiling, multipart upload, delete) happens off
the request thread.

Why this exists: LS's `<Image>` control can only render raster formats. When
a user uploads a PDF via LS's Import UI, LS stores the file and creates a
task with `data.image` pointing at it — but the labeling canvas can't render
the PDF and shows "issue loading URL". This worker watches for that case and
silently converts the PDF into 9 PNG tiles (3x3 grid, 3x zoom, 20% overlap —
same `pdf_to_tiles.py` config the main pipeline uses).

Idempotency: if the task no longer exists (e.g. already-processed retry),
the worker returns cleanly. If the task's image is already a PNG, no-op.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from webapp import label_studio_client as ls


def _is_pdf_task_image(image_path: Optional[str]) -> bool:
    """True if the task's data.image points at a PDF that needs tiling."""
    if not image_path:
        return False
    return image_path.lower().endswith(".pdf")


def auto_tile_ls_task_rq(
    project_id: int,
    task_id: int,
    image_path: str,
) -> dict:
    """RQ entrypoint — download PDF, tile, upload, delete original.

    Args:
        project_id: LS project id (used as upload target for tile tasks).
        task_id: LS task id to delete after replacement tiles are created.
        image_path: value of the task's `data.image` field. Must end in `.pdf`
                    or this is a no-op.

    Returns a small status dict for the RQ log.
    """
    # Re-import inside the function so worker startup doesn't require pdf_to_tiles
    # at module-import time (the worker container's PYTHONPATH includes the
    # project root where pdf_to_tiles.py lives).
    from pdf_to_tiles import pdf_to_tiles

    if not _is_pdf_task_image(image_path):
        return {"status": "skip", "reason": "not-a-pdf", "image": image_path}

    pdf_bytes = ls.download_task_image(image_path)
    if not pdf_bytes:
        return {"status": "fail", "reason": "download-failed", "image": image_path}

    with tempfile.TemporaryDirectory(prefix=f"autotile-{task_id}-") as tmp:
        tmp_path = Path(tmp)
        pdf_file = tmp_path / "input.pdf"
        pdf_file.write_bytes(pdf_bytes)

        tiles_dir = tmp_path / "tiles"
        try:
            pdf_to_tiles(str(pdf_file), output_dir=str(tiles_dir))
        except Exception as exc:
            return {"status": "fail", "reason": f"tiling-error: {exc!r}"}

        # Filter to the tile_p*_r*_c*.png outputs (drop page_*_full.png).
        tile_pngs = sorted(tiles_dir.glob("tile_p*_r*_c*.png"))
        if not tile_pngs:
            return {"status": "fail", "reason": "no-tiles-produced"}

        uploaded = ls.upload_tile_files(project_id, tile_pngs)

    if uploaded == 0:
        # Upload failed — don't delete the original; user keeps the broken
        # task but at least the PDF data isn't lost.
        return {"status": "fail", "reason": "upload-zero", "tile_count": len(tile_pngs)}

    deleted = ls.delete_task(task_id)
    return {
        "status": "ok",
        "project_id": project_id,
        "original_task_id": task_id,
        "tiles_uploaded": uploaded,
        "original_deleted": deleted,
    }
