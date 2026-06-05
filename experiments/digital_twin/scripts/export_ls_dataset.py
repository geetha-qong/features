"""
Export all dev-LS annotations into a unified YOLO dataset for v1-10 training.

Output structure:
  experiments/digital_twin/data/dataset_v1-10/
    data.yaml
    images/train/<task_id>.png
    images/val/<task_id>.png
    labels/train/<task_id>.txt   (YOLO format: cls cx cy w h, all normalized)
    labels/val/<task_id>.txt
    manifest.json                (per-image source-of-truth: project, task, label histogram)

Skips:
  - tasks with no annotations
  - annotation results that reference classes outside the 22-class schema
  - LS "cancelled" annotations (was_cancelled=true)

Train/val split: 90/10 deterministic by (sha1(task_id) % 10 == 0).

Run from repo root with DEV_LS_ACCESS in env.
"""
from __future__ import annotations
import hashlib
import json
import os
import sys
import urllib.request
import urllib.error
from collections import Counter, defaultdict
from pathlib import Path

REFRESH_TOKEN = os.environ.get("DEV_LS_REFRESH")
if not REFRESH_TOKEN:
    sys.exit("Set DEV_LS_REFRESH in env (the LS refresh token from SSM).")

BASE = "https://ls-dev.qongsystems.com"


def refresh_access_token() -> str:
    """Exchange the refresh token for a short-lived access token. LS access
    tokens are ~5 min so we re-refresh on any 401."""
    req = urllib.request.Request(
        f"{BASE}/api/token/refresh/",
        data=json.dumps({"refresh": REFRESH_TOKEN}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "qong/1.0",
            "Accept": "application/json",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.load(resp)["access"]


ACCESS = refresh_access_token()
H = {
    "Authorization": f"Bearer {ACCESS}",
    "User-Agent": "qong/1.0",
    "Accept": "application/json",
}

# 22-class schema (id order matters — this becomes the production CLASS_NAMES)
CLASSES = [
    # Valves (9)
    "valve_bv", "valve_ncbv", "valve_gt", "valve_bf", "valve_ck",
    "valve_db", "valve_relief_safety", "valve_gl", "valve_3way_relief",
    # Instruments / signals (7)
    "inst_field", "inst_bpcs", "Motor", "Pump/Dwg Pump", "inst_sis",
    "SIS-R", "interlock", "inst_local_panel",
    # Direction (6)
    "arrow_up", "arrow_left", "arrow_right", "arrow_down",
    "connector_out", "connector_in",
]
CLASS_ID = {name: i for i, name in enumerate(CLASSES)}

OUT_ROOT = Path("experiments/digital_twin/data/dataset_v1-10")


def get(url, *, raw=False, _retry=True):
    """GET with auto-refresh on 401."""
    global ACCESS, H
    req = urllib.request.Request(url, headers=H)
    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        if e.code == 401 and _retry:
            ACCESS = refresh_access_token()
            H["Authorization"] = f"Bearer {ACCESS}"
            return get(url, raw=raw, _retry=False)
        raise
    if raw:
        return resp.read(), resp.headers
    return json.load(resp)


def download_image(image_path: str, dest: Path) -> bool:
    """Download an LS task image, return True on success.

    LS tasks on dev store image as one of:
      - "https://dev.qongsystems.com/jobs/{id}/tiles/{name}.png" (webapp tile route, public)
      - "/data/upload/{pid}/{uuid}.png" (LS's own storage, needs bearer auth)
      - "/data/local-files/?d=..."     (LS local-files, needs bearer auth)
    """
    if dest.exists() and dest.stat().st_size > 0:
        return True
    if image_path.startswith("http://") or image_path.startswith("https://"):
        url = image_path
        headers = {"User-Agent": "qong/1.0"}  # no LS bearer for webapp endpoint
    elif image_path.startswith("/data/"):
        url = f"{BASE}{image_path}"
        headers = H
    else:
        print(f"  unknown image-path shape, skipping: {image_path[:80]}")
        return False
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=120)
        data = resp.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        print(f"  image download FAIL {image_path[:80]}: {e}")
        return False


def task_split(task_id: int) -> str:
    """Deterministic 90/10 train/val split."""
    h = int(hashlib.sha1(str(task_id).encode()).hexdigest(), 16)
    return "val" if h % 10 == 0 else "train"


def yolo_bbox(result: dict) -> tuple[float, float, float, float] | None:
    """LS result.value has x,y,width,height in *percentage* units. YOLO wants
    cx,cy,w,h normalized to [0,1]. Convert."""
    v = result.get("value", {})
    if not all(k in v for k in ("x", "y", "width", "height")):
        return None
    cx = (v["x"] + v["width"] / 2) / 100.0
    cy = (v["y"] + v["height"] / 2) / 100.0
    w = v["width"] / 100.0
    h = v["height"] / 100.0
    # Clamp to [0,1] — LS sometimes stores tiny overshoot
    return (
        max(0.0, min(1.0, cx)),
        max(0.0, min(1.0, cy)),
        max(0.0, min(1.0, w)),
        max(0.0, min(1.0, h)),
    )


def main():
    print(f"Exporting to {OUT_ROOT} — {len(CLASSES)} classes")
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (OUT_ROOT / sub).mkdir(parents=True, exist_ok=True)

    projs = get(f"{BASE}/api/projects/?page_size=200")
    projs = projs.get("results", projs) if isinstance(projs, dict) else projs
    print(f"Scanning {len(projs)} projects\n")

    class_counts = Counter()
    dropped_unknown = Counter()
    n_images_with_labels = 0
    n_images_no_labels = 0
    manifest = []

    for p_idx, p in enumerate(projs, 1):
        pid = p["id"]
        n_anns_for_proj = 0
        page = 1
        while True:
            tasks = get(f"{BASE}/api/tasks/?project={pid}&page={page}&page_size=200&fields=all")
            tlist = tasks.get("tasks", tasks) if isinstance(tasks, dict) else tasks
            if not tlist:
                break
            for t in tlist:
                tid = t["id"]
                image_field = (t.get("data") or {}).get("image", "")
                if not image_field:
                    continue
                # Gather all bboxes from all non-cancelled annotations
                bboxes = []  # (cls_id, cx, cy, w, h)
                project_label_hist = Counter()
                for ann in t.get("annotations", []):
                    if ann.get("was_cancelled"):
                        continue
                    for r in ann.get("result", []) or []:
                        if r.get("type") not in ("rectanglelabels", "rectangle"):
                            continue
                        labs = r.get("value", {}).get("rectanglelabels") or []
                        if not labs:
                            continue
                        label = labs[0]
                        if label not in CLASS_ID:
                            dropped_unknown[label] += 1
                            continue
                        bb = yolo_bbox(r)
                        if bb is None:
                            continue
                        bboxes.append((CLASS_ID[label], *bb))
                        class_counts[label] += 1
                        project_label_hist[label] += 1
                        n_anns_for_proj += 1
                if not bboxes:
                    n_images_no_labels += 1
                    continue
                split = task_split(tid)
                ext = Path(image_field).suffix or ".png"
                img_dest = OUT_ROOT / f"images/{split}/{tid}{ext}"
                if not download_image(image_field, img_dest):
                    continue
                lbl_dest = OUT_ROOT / f"labels/{split}/{tid}.txt"
                with open(lbl_dest, "w") as f:
                    for cls_id, cx, cy, w, h in bboxes:
                        f.write(f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")
                n_images_with_labels += 1
                manifest.append({
                    "task_id": tid,
                    "project_id": pid,
                    "split": split,
                    "n_bboxes": len(bboxes),
                    "labels": dict(project_label_hist),
                    "image_filename": f"{tid}{ext}",
                })
            if len(tlist) < 200:
                break
            page += 1
        print(f"  [{p_idx}/{len(projs)}] project {pid}: +{n_anns_for_proj} annotations")

    # data.yaml
    yaml = ["path: .", "train: images/train", "val: images/val", "",
            f"nc: {len(CLASSES)}", "names:"]
    for i, n in enumerate(CLASSES):
        yaml.append(f"  {i}: {n}")
    (OUT_ROOT / "data.yaml").write_text("\n".join(yaml) + "\n")

    # manifest.json
    (OUT_ROOT / "manifest.json").write_text(json.dumps({
        "classes": CLASSES,
        "n_images_with_labels": n_images_with_labels,
        "n_images_skipped_no_labels": n_images_no_labels,
        "class_counts": dict(class_counts),
        "dropped_unknown_labels": dict(dropped_unknown),
        "items": manifest,
    }, indent=2))

    # Per-split counts
    n_train_imgs = len(list((OUT_ROOT / "images/train").glob("*")))
    n_val_imgs = len(list((OUT_ROOT / "images/val").glob("*")))
    n_train_lbls = len(list((OUT_ROOT / "labels/train").glob("*.txt")))
    n_val_lbls = len(list((OUT_ROOT / "labels/val").glob("*.txt")))

    print(f"\n=== Dataset built ===")
    print(f"Train images / labels: {n_train_imgs} / {n_train_lbls}")
    print(f"Val   images / labels: {n_val_imgs} / {n_val_lbls}")
    print(f"Total annotations exported: {sum(class_counts.values())}")
    print()
    print("Per-class counts in dataset:")
    for L in CLASSES:
        print(f"  {L:25s}  {class_counts.get(L, 0):>5d}")
    if dropped_unknown:
        print(f"\nDropped {sum(dropped_unknown.values())} annotations on unknown classes:")
        for L, n in sorted(dropped_unknown.items(), key=lambda x: -x[1])[:15]:
            print(f"  {L:25s}  {n:>5d}")


if __name__ == "__main__":
    main()
