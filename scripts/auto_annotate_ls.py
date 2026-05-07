"""
Auto-annotate Label Studio tasks using the YOLO v1-6 model.

Fetches all LS tasks that have zero predictions, runs YOLO inference on each
tile image (downloaded via the task image URL), then POSTs the bounding boxes
as pre-annotations. Annotators then only need to verify/adjust instead of
drawing from scratch.

Usage (run from inside web container or locally with env vars set):
    python3 scripts/auto_annotate_ls.py
    python3 scripts/auto_annotate_ls.py --project 3          # single project
    python3 scripts/auto_annotate_ls.py --dry-run            # count only
    python3 scripts/auto_annotate_ls.py --force              # overwrite existing predictions

From GCP:
    sudo docker compose exec web python3 scripts/auto_annotate_ls.py

Environment:
    LS_URL          http://label-studio:8080   (Docker-internal)
    LS_API_KEY      <token>
    MODEL_PATH      optional override (default: models/best.onnx in project root)
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Dict, Optional

import numpy as np
import requests
from PIL import Image

# ── Config ─────────────────────────────────────────────────────────────────────
LS_URL = os.environ.get("LS_URL", "http://label-studio:8080").rstrip("/")
LS_API_KEY = os.environ.get("LS_API_KEY", "")

_HERE = Path(__file__).resolve().parent.parent
MODEL_PATH = os.environ.get("MODEL_PATH", str(_HERE / "models" / "best.onnx"))

IMGSZ = 1280
CONF_THRESH = 0.25
IOU_THRESH = 0.45
MODEL_VERSION = "yolo-v1-6"

CLASS_NAMES = [
    "actuator_motor", "actuator_pneu", "actuator_sol",
    "valve_bf", "valve_bv", "valve_ck", "valve_cv",
    "valve_db", "valve_gen", "valve_gl",
]

# ── YOLO inference (same logic as detector.py) ─────────────────────────────────

_session = None

def _get_session():
    global _session
    if _session is None:
        import onnxruntime as ort
        if not Path(MODEL_PATH).exists():
            sys.exit(f"Model not found: {MODEL_PATH}")
        providers = [p for p in ["CUDAExecutionProvider", "CPUExecutionProvider"]
                     if p in ort.get_available_providers()]
        _session = ort.InferenceSession(MODEL_PATH, providers=providers)
        print(f"  ONNX loaded: {Path(MODEL_PATH).name}, providers={_session.get_providers()}")
    return _session


def _preprocess(img: Image.Image):
    orig_w, orig_h = img.size
    scale = min(IMGSZ / orig_w, IMGSZ / orig_h)
    new_w, new_h = int(orig_w * scale), int(orig_h * scale)
    resized = img.resize((new_w, new_h), Image.BILINEAR)
    canvas = Image.new("RGB", (IMGSZ, IMGSZ), (114, 114, 114))
    pad_x, pad_y = (IMGSZ - new_w) // 2, (IMGSZ - new_h) // 2
    canvas.paste(resized, (pad_x, pad_y))
    arr = np.array(canvas, dtype=np.float32) / 255.0
    return arr.transpose(2, 0, 1)[np.newaxis], scale, pad_x, pad_y


def _nms(boxes, scores):
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]; keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]]); yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]]); yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        order = order[1:][iou <= IOU_THRESH]
    return keep


def run_yolo(img_path: str) -> List[Dict]:
    """Run YOLO on image file, return list of {class_name, conf, x1, y1, x2, y2}."""
    img = Image.open(img_path).convert("RGB")
    orig_w, orig_h = img.size
    inp, scale, pad_x, pad_y = _preprocess(img)

    sess = _get_session()
    output = sess.run(None, {sess.get_inputs()[0].name: inp})[0]
    preds = output[0].T  # (N, 4+classes)

    class_scores = preds[:, 4:]
    conf = class_scores.max(axis=1)
    class_ids = class_scores.argmax(axis=1)
    mask = conf >= CONF_THRESH
    preds, conf, class_ids = preds[mask], conf[mask], class_ids[mask]
    if len(conf) == 0:
        return []

    cx, cy, w, h = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
    x1 = np.clip((cx - w / 2 - pad_x) / scale, 0, orig_w)
    y1 = np.clip((cy - h / 2 - pad_y) / scale, 0, orig_h)
    x2 = np.clip((cx + w / 2 - pad_x) / scale, 0, orig_w)
    y2 = np.clip((cy + h / 2 - pad_y) / scale, 0, orig_h)

    detections = []
    for cls_id in np.unique(class_ids):
        m = class_ids == cls_id
        bboxes = np.stack([x1[m], y1[m], x2[m], y2[m]], axis=1)
        scores_m = conf[m]
        for idx in _nms(bboxes, scores_m):
            bx1, by1, bx2, by2 = bboxes[idx]
            detections.append({
                "class_name": CLASS_NAMES[cls_id],
                "conf": float(scores_m[idx]),
                "x1": float(bx1), "y1": float(by1),
                "x2": float(bx2), "y2": float(by2),
                "img_w": orig_w, "img_h": orig_h,
            })
    return detections


# ── LS API helpers ─────────────────────────────────────────────────────────────

def _headers():
    return {"Authorization": f"Token {LS_API_KEY}", "Content-Type": "application/json"}


def ls_get(path: str, **kwargs) -> Optional[dict]:
    try:
        r = requests.get(f"{LS_URL}{path}", headers=_headers(), timeout=15, **kwargs)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"  LS GET {path} error: {e}")
    return None


def get_projects() -> List[dict]:
    data = ls_get("/api/projects/?page_size=500")
    if not data:
        return []
    return data.get("results", [])


def get_tasks(project_id: int) -> List[dict]:
    """Fetch all tasks for a project (handles pagination)."""
    tasks = []
    page = 1
    while True:
        data = ls_get(f"/api/tasks/?project={project_id}&page_size=200&page={page}")
        if not data:
            break
        batch = data.get("tasks", data) if isinstance(data, dict) else data
        if not batch:
            break
        tasks.extend(batch)
        if len(batch) < 200:
            break
        page += 1
    return tasks


def task_has_predictions(task_id: int) -> bool:
    data = ls_get(f"/api/tasks/{task_id}/")
    if not data:
        return False
    return len(data.get("predictions", [])) > 0


def post_prediction(task_id: int, detections: List[Dict]) -> bool:
    """Post YOLO detections as LS prediction for a task."""
    if not detections:
        return False
    result = []
    for det in detections:
        iw, ih = det["img_w"], det["img_h"]
        result.append({
            "type": "rectanglelabels",
            "from_name": "label",
            "to_name": "image",
            "original_width": iw,
            "original_height": ih,
            "value": {
                "x": det["x1"] / iw * 100,
                "y": det["y1"] / ih * 100,
                "width": (det["x2"] - det["x1"]) / iw * 100,
                "height": (det["y2"] - det["y1"]) / ih * 100,
                "rotation": 0,
                "rectanglelabels": [det["class_name"]],
            },
            "score": det["conf"],
        })
    payload = {
        "task": task_id,
        "model_version": MODEL_VERSION,
        "result": result,
    }
    try:
        r = requests.post(f"{LS_URL}/api/predictions/", headers=_headers(),
                          json=payload, timeout=15)
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"  POST prediction error: {e}")
        return False


def download_image(url: str, dest: str) -> bool:
    """Download an image from URL to dest path.

    For tile images served by our webapp (https://dev.qongsystems.com/jobs/.../tiles/...),
    rewrites the URL to use the Docker-internal address http://web:8000 so the
    download works from inside the container without going through nginx/TLS.
    """
    try:
        # Rewrite public webapp URL to Docker-internal for faster/reliable access
        fetch_url = url
        if url.startswith("/"):
            fetch_url = f"{LS_URL}{url}"
        elif "dev.qongsystems.com" in url or "localhost" in url:
            import re as _re
            fetch_url = _re.sub(r"https?://[^/]+", "http://web:8000", url)

        r = requests.get(fetch_url, timeout=30)
        if r.status_code == 200:
            with open(dest, "wb") as f:
                f.write(r.content)
            return True
        # Fallback: try original URL
        if fetch_url != url:
            r2 = requests.get(url, timeout=30)
            if r2.status_code == 200:
                with open(dest, "wb") as f:
                    f.write(r2.content)
                return True
        print(f"  Image download failed ({r.status_code}): {fetch_url}")
    except Exception as e:
        print(f"  Image download error: {e}")
    return False


# ── Main ───────────────────────────────────────────────────────────────────────

def process_project(project: dict, dry_run: bool, force: bool) -> tuple:
    """Process one LS project. Returns (skipped, annotated, errors)."""
    pid = project["id"]
    title = project.get("title", "?")
    tasks = get_tasks(pid)
    if not tasks:
        return 0, 0, 0

    skipped = annotated = errors = 0
    for task in tasks:
        task_id = task["id"]
        img_url = task.get("data", {}).get("image", "")
        if not img_url:
            skipped += 1
            continue

        already_has = task_has_predictions(task_id)
        if already_has and not force:
            skipped += 1
            continue

        if dry_run:
            print(f"  [DRY] Would annotate task {task_id}: {img_url.split('/')[-1]}")
            annotated += 1
            continue

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            if not download_image(img_url, tmp_path):
                errors += 1
                continue

            dets = run_yolo(tmp_path)
            if post_prediction(task_id, dets):
                print(f"  task {task_id}: {len(dets)} detections → posted")
                annotated += 1
            else:
                print(f"  task {task_id}: {len(dets)} detections → post failed")
                errors += 1
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    return skipped, annotated, errors


def main():
    parser = argparse.ArgumentParser(description="Auto-annotate LS tasks with YOLO v1-6")
    parser.add_argument("--project", type=int, default=None, help="Process only this project ID")
    parser.add_argument("--dry-run", action="store_true", help="Count tasks without posting")
    parser.add_argument("--force", action="store_true", help="Overwrite existing predictions")
    args = parser.parse_args()

    if not LS_API_KEY:
        sys.exit("LS_API_KEY not set")

    print(f"Auto-annotate: LS_URL={LS_URL}, model={Path(MODEL_PATH).name}")
    print(f"  dry_run={args.dry_run}, force={args.force}")

    if not args.dry_run:
        _get_session()  # load model once upfront

    projects = get_projects()
    if args.project:
        projects = [p for p in projects if p["id"] == args.project]
        if not projects:
            sys.exit(f"Project {args.project} not found")

    print(f"\nFound {len(projects)} projects\n")

    total_skip = total_ann = total_err = 0
    for proj in projects:
        pid, title = proj["id"], proj.get("title", "?")
        num_tasks = proj.get("task_number", "?")
        print(f"Project {pid}: {title!r} ({num_tasks} tasks)")
        s, a, e = process_project(proj, dry_run=args.dry_run, force=args.force)
        print(f"  → skipped={s}, annotated={a}, errors={e}\n")
        total_skip += s; total_ann += a; total_err += e

    print(f"Done. Total: skipped={total_skip}, annotated={total_ann}, errors={total_err}")


if __name__ == "__main__":
    main()
