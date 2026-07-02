"""Shared: read page pixel dimensions for a job from canonical_graph.json."""
import json
from pathlib import Path
from typing import Any, Optional, Tuple


def page_dims_for_job(job: Any) -> Optional[Tuple[int, int]]:
    path = getattr(job, "output_csv_path", None)
    if not path:
        return None
    cg = Path(path).parent / "canonical_graph.json"
    if not cg.exists():
        return None
    try:
        data = json.loads(cg.read_text(encoding="utf-8"))
    except Exception:
        return None
    w, h = data.get("page_width"), data.get("page_height")
    if isinstance(w, (int, float)) and isinstance(h, (int, float)) and w and h:
        return int(w), int(h)
    return None
