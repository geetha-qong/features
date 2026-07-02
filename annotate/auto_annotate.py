#!/usr/bin/env python3
"""
auto_annotate.py — Push AI-generated bounding box predictions into Label Studio
for all unannotated P&ID tiles using a free OpenRouter vision model.

Usage:
  python3 annotate/auto_annotate.py
  python3 annotate/auto_annotate.py --project 1 --model qwen/qwen2.5-vl-72b-instruct:free
  python3 annotate/auto_annotate.py --dry-run        # show what would be sent, don't push
"""
import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────
LS_URL        = "http://localhost:8080"
REFRESH_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6ODA4NDQ4MTk5NiwiaWF0IjoxNzc3"
    "MjgxOTk2LCJqdGkiOiIyY2MxYmRkMzUyNWM0MWUwYjlkYjAxZDNkYTcwNmIzNCIsInVz"
    "ZXJfaWQiOiIyIn0"
    ".stPAqLKlea9ZJsTIB2BfIycgWhwRGWM_IlKjneXR0pQ"
)
LS_MEDIA_DIR = Path(__file__).parent / "ls_data" / "media" / "upload" / "1"

# Models to try (in order)
FREE_MODELS = [
    "google/gemini-2.0-flash-001",
    "google/gemini-2.0-flash-lite-001",
]

PROMPT = """You are analyzing a tile from a P&ID (Piping and Instrumentation Diagram).
Detect all valve and actuator symbols and return their bounding boxes.

IMPORTANT: All coordinates must be PERCENTAGES of the image size (0 to 100).
x=0 means left edge, x=100 means right edge.
y=0 means top edge, y=100 means bottom edge.
x, y is the TOP-LEFT corner of the box.

VALVE CLASSES:
- valve_bf  : Butterfly valve — bowtie / hourglass / diamond shape (two triangles pointing inward)
- valve_bv  : Ball valve — circle with a line (stem) through it
- valve_ck  : Check valve — arrowhead or half-circle indicating flow direction
- valve_gl  : Globe valve — circle with plug/bonnet on top
- valve_db  : Double Block & Bleed — cluster of 3 valve symbols together
- valve_cv  : Control valve — circle with dome/diaphragm actuator on top
- valve_gen : Generic valve (gate, needle, safety, pressure, flow valves)

ACTUATOR CLASSES (separate box on the actuator symbol only):
- actuator_motor : Motor — square box with letter M
- actuator_pneu  : Pneumatic — dome/diaphragm shape sitting above the valve
- actuator_sol   : Solenoid — box labelled SL or coil symbol

INSTRUMENT CLASSES:
- inst_bubble   : Instrument tag circle (PT, TT, FT, LT, PDT, PI, TI, FI, PS, ZSO, ZSC, ZT, VXT, VYT, KT, LS, SG) — draw box around the circle+tag text
- inst_cv       : Control/shutdown valve instrument (FCV, XV) — looks like valve symbol with actuator; draw box around the whole symbol
- inst_solenoid : Solenoid instrument (FY, XY) — solenoid box/coil symbol; draw box around it

Return ONLY a valid JSON array. No markdown fences, no explanation.
Example (note: all numbers 0-100):
[
  {"label": "valve_bf", "x": 23.5, "y": 41.2, "width": 4.1, "height": 3.8},
  {"label": "actuator_motor", "x": 23.8, "y": 37.5, "width": 3.5, "height": 3.0}
]

If no valves are visible, return: []
"""

# ── Auth helpers ──────────────────────────────────────────────────────────────
_access_token = None
_token_fetched_at = 0


def get_access_token():
    global _access_token, _token_fetched_at
    if _access_token and (time.time() - _token_fetched_at) < 800:
        return _access_token
    resp = requests.post(
        f"{LS_URL}/api/token/refresh/",
        json={"refresh": REFRESH_TOKEN},
        timeout=10,
    )
    resp.raise_for_status()
    _access_token = resp.json()["access"]
    _token_fetched_at = time.time()
    return _access_token


def ls_get(path, **kwargs):
    return requests.get(
        f"{LS_URL}{path}",
        headers={"Authorization": f"Bearer {get_access_token()}"},
        timeout=30,
        **kwargs,
    )


def ls_post(path, **kwargs):
    return requests.post(
        f"{LS_URL}{path}",
        headers={"Authorization": f"Bearer {get_access_token()}"},
        timeout=30,
        **kwargs,
    )


def ls_patch(path, **kwargs):
    return requests.patch(
        f"{LS_URL}{path}",
        headers={"Authorization": f"Bearer {get_access_token()}"},
        timeout=30,
        **kwargs,
    )

# ── Label Studio helpers ───────────────────────────────────────────────────────

def get_all_tasks(project_id):
    tasks, page = [], 1
    while True:
        r = ls_get(f"/api/tasks?project={project_id}&page={page}&page_size=100")
        r.raise_for_status()
        data = r.json()
        tasks.extend(data["tasks"])
        if len(tasks) >= data["total"]:
            break
        page += 1
    return tasks


def update_label_config(project_id):
    """Ensure the project has all 13 classes in its label config."""
    config = """<View>
  <Image name="image" value="$image" zoom="true" zoomControl="true"/>
  <RectangleLabels name="label" toName="image" showInline="true">
    <Label value="valve_bf"        background="#E74C3C"/>
    <Label value="valve_bv"        background="#3498DB"/>
    <Label value="valve_ck"        background="#2ECC71"/>
    <Label value="valve_gl"        background="#9B59B6"/>
    <Label value="valve_db"        background="#F39C12"/>
    <Label value="valve_cv"        background="#1ABC9C"/>
    <Label value="valve_gen"       background="#95A5A6"/>
    <Label value="actuator_motor"  background="#E67E22"/>
    <Label value="actuator_pneu"   background="#C0392B"/>
    <Label value="actuator_sol"    background="#8E44AD"/>
    <Label value="inst_bubble"     background="#27AE60"/>
    <Label value="inst_cv"         background="#16A085"/>
    <Label value="inst_solenoid"   background="#8E44AD"/>
  </RectangleLabels>
</View>"""
    r = ls_patch(f"/api/projects/{project_id}/", json={"label_config": config})
    r.raise_for_status()
    print("  Label config updated with all 13 classes.")


# ── OpenRouter helpers ────────────────────────────────────────────────────────

def encode_image(image_path: Path) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def call_vision_model(image_path: Path, api_key: str, model: str) -> list:
    """Send image to OpenRouter vision model; return list of bbox dicts."""
    b64 = encode_image(image_path)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 2048,
        "temperature": 0.1,
    }
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/qong-systems/pid-annotator",
            "X-Title": "PID Auto Annotator",
        },
        json=payload,
        timeout=90,
    )
    if resp.status_code == 429:
        raise RuntimeError("rate_limit")
    resp.raise_for_status()

    text = resp.json()["choices"][0]["message"]["content"].strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    return json.loads(text)


def boxes_to_ls_result(boxes: list) -> list:
    """Convert list of {label,x,y,width,height} dicts to LS prediction result."""
    result = []
    for b in boxes:
        label = b.get("label", "")
        x = min(max(float(b.get("x", 0)), 0), 100)
        y = min(max(float(b.get("y", 0)), 0), 100)
        w = min(max(float(b.get("width", 0)), 0), 100 - x)
        h = min(max(float(b.get("height", 0)), 0), 100 - y)
        if not label or w <= 0 or h <= 0:
            continue
        result.append({
            "from_name": "label",
            "to_name": "image",
            "type": "rectanglelabels",
            "value": {
                "x": round(x, 2),
                "y": round(y, 2),
                "width": round(w, 2),
                "height": round(h, 2),
                "rotation": 0,
                "rectanglelabels": [label],
            },
        })
    return result


def push_prediction(task_id: int, result: list, model: str, dry_run: bool):
    if dry_run:
        print(f"    [dry-run] Would push {len(result)} boxes to task {task_id}")
        return
    payload = {
        "task": task_id,
        "result": result,
        "score": 0.6,
        "model_version": model,
    }
    r = ls_post("/api/predictions/", json=payload)
    if not r.ok:
        print(f"    ERROR pushing prediction: {r.status_code} {r.text[:200]}")
    else:
        print(f"    Pushed {len(result)} boxes.")


# ── Image path resolver ───────────────────────────────────────────────────────

def resolve_image(data_path: str) -> Path:
    """Convert LS data path like /data/upload/1/abc-job1.png → local filesystem path."""
    filename = Path(data_path).name
    local = LS_MEDIA_DIR / filename
    if local.exists():
        return local
    raise FileNotFoundError(f"Image not found locally: {local}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Auto-annotate P&ID tiles in Label Studio")
    parser.add_argument("--project", type=int, default=1)
    parser.add_argument("--model", default=FREE_MODELS[0])
    parser.add_argument("--skip-annotated", action="store_true", default=True,
                        help="Skip tasks that already have annotations (default: True)")
    parser.add_argument("--overwrite-predictions", action="store_true",
                        help="Re-run even if task already has predictions")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't push anything, just show what would happen")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Seconds between API calls (avoid rate limits)")
    args = parser.parse_args()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        # Try reading from .env
        env_file = Path(__file__).parent.parent / ".env"
        for line in env_file.read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break
    if not api_key:
        sys.exit("ERROR: OPENROUTER_API_KEY not set")

    print(f"Project: {args.project} | Model: {args.model}")
    print(f"Dry-run: {args.dry_run} | Delay: {args.delay}s between calls\n")

    # Update label config to include all 10 classes
    if not args.dry_run:
        print("Updating label config...")
        update_label_config(args.project)

    tasks = get_all_tasks(args.project)
    print(f"Found {len(tasks)} tasks total.\n")

    ok = skip = fail = 0
    for task in tasks:
        tid = task["id"]
        img_path_str = task["data"]["image"]
        has_annotations = task["total_annotations"] > 0
        has_predictions = task["total_predictions"] > 0

        if has_annotations and args.skip_annotated:
            print(f"Task {tid}: SKIP (already annotated)")
            skip += 1
            continue
        if has_predictions and not args.overwrite_predictions:
            print(f"Task {tid}: SKIP (already has predictions)")
            skip += 1
            continue

        try:
            img_path = resolve_image(img_path_str)
        except FileNotFoundError as e:
            print(f"Task {tid}: SKIP ({e})")
            skip += 1
            continue

        print(f"Task {tid}: {img_path.name}")

        # Try models in order until one works; retry rate limits up to 3x
        boxes = None
        used_model = args.model
        models_to_try = [args.model] + [m for m in FREE_MODELS if m != args.model]

        for model in models_to_try:
            for attempt in range(3):
                try:
                    print(f"  → Calling {model}...")
                    boxes = call_vision_model(img_path, api_key, model)
                    used_model = model
                    break
                except RuntimeError as e:
                    if "rate_limit" in str(e):
                        wait = 15 * (attempt + 1)
                        print(f"  Rate limited, waiting {wait}s...")
                        time.sleep(wait)
                    else:
                        print(f"  Error: {e}")
                        break
                except json.JSONDecodeError as e:
                    print(f"  Bad JSON from {model}: {e}")
                    break
                except Exception as e:
                    print(f"  Error with {model}: {e}")
                    break
            if boxes is not None:
                break

        if boxes is None:
            print(f"  FAILED all models.")
            fail += 1
            continue

        print(f"  Got {len(boxes)} boxes from {used_model}")
        if boxes:
            result = boxes_to_ls_result(boxes)
            push_prediction(tid, result, used_model, args.dry_run)
        else:
            print("  No valves detected — skipping prediction push.")

        ok += 1
        time.sleep(args.delay)

    print(f"\nDone. processed={ok} skipped={skip} failed={fail}")


if __name__ == "__main__":
    main()
