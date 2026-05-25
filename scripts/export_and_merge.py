"""
Export LS projects 1 and 3 (YOLO format), remap class indices to the
canonical 19-class scheme, merge with existing 44-image MUK dataset,
update data.yaml, and write a transfer archive for Windows training.

Run on GCP VM:
    python3 scripts/export_and_merge.py

Output:
    datasets/pid_valves/  — updated in-place with new images + labels
    datasets/pid_valves/data.yaml  — updated nc + names
    /tmp/dataset_for_gpu.tar.gz  — ready to scp to Windows
"""
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Dict, List

import requests

# ── Config ─────────────────────────────────────────────────────────────────────
LS_URL = os.environ.get("LS_URL", "http://localhost:8080").rstrip("/")
LS_API_KEY = os.environ.get("LS_API_KEY", "")

EXPORT_PROJECTS = [
    1, 3, 4, 5, 6,                                  # MUK 1001-1005 (v1-7 baseline)
    7,                                              # PID Training - All Valves (45 ann) — included v1-9
    8,                                              # MUK 61-0-0218
    10, 11, 12, 13, 14,                             # UNKNOWN-06, 09, 10, 12, 13
    15, 16, 17, 18,                                 # UNKNOWN-16, 16-18, 17, 18
    19, 20, 21, 22, 23, 24,                         # UNKNOWN-4, 5, 7, 8, Pg.17, Pg.5
    25,                                             # WS-25-WTP-01 (new water-treatment domain)
    26,                                             # UNKNOWN (324 tasks, 325 ann) — included v1-9
    27,                                             # MUK-62-0-0002 — included v1-9
    28,                                             # MUK-63-1-0177 — included v1-9
]
# Excluded: 9 (duplicate of 4 — same drawing)

_HERE = Path(__file__).resolve().parent.parent
DATASET_DIR = _HERE / "datasets" / "pid_valves"
TRAIN_IMG = DATASET_DIR / "images" / "train"
TRAIN_LBL = DATASET_DIR / "labels" / "train"

# Canonical class list (v1-9 onwards) — actuator_* dropped (0 instances anywhere
# across all 26 annotated projects; team stopped labelling actuators separately).
# valve_gt added (556 instances were being silently dropped pre-v1-9).
CANONICAL_CLASSES = [
    "valve_bf",            # 0
    "valve_bv",            # 1
    "valve_ck",            # 2
    "valve_cv",            # 3
    "valve_db",            # 4
    "valve_gen",           # 5
    "valve_gl",            # 6
    "valve_gt",            # 7  ← new in v1-9 (gate valve)
    "inst_field",          # 8
    "DCS",                 # 9
    "PLC",                 # 10
    "interlock",           # 11
    "interlock-R",         # 12
    "inst_field-R",        # 13
    "Pump_Dwg_Pump",       # 14  (slash/space replaced for filesystem safety)
    "Motor",               # 15
    "valve_3way_relief",   # 16
    "valve_ncbv",          # 17
    "valve_relief_safety", # 18
    "valve_pnuectrl",      # 19
]

# LS label name → canonical index (handles name differences and typos).
# Indices match CANONICAL_CLASSES order above (v1-9 scheme — actuators dropped, valve_gt added).
LS_NAME_TO_IDX: Dict[str, int] = {
    "valve_bf": 0,
    "valve_bv": 1,
    "valve_ck": 2,
    "valve_cv": 3,
    "valve_db": 4,
    "valve_gen": 5,
    "valve_gl": 6,
    "valve_gt": 7,
    "inst_field": 8,
    "DCS": 9,
    "PLC": 10,
    "interlock": 11,
    "interlock-R": 12,
    "inst_field-R": 13,
    "Pump/Dwg Pump": 14,
    "Pump_Dwg_Pump": 14,
    "Motor": 15,
    "valve_3way_relief": 16,
    "valve_3way_releif": 16,   # typo fix (3 instances in LS)
    "valve_ncbv": 17,
    "valve_relief_safety": 18,
    "valve_pnuectrl": 19,
    "valve_pneuctrl": 19,      # spelling variant in project 6
}


def _headers():
    return {"Authorization": f"Token {LS_API_KEY}"}


def export_project_yolo(project_id: int) -> Path:
    """Export LS project as YOLO ZIP using direct export endpoint."""
    print(f"\nExporting project {project_id}...")

    out_zip = Path(f"/tmp/ls_export_proj{project_id}.zip")
    r = requests.get(
        f"{LS_URL}/api/projects/{project_id}/export",
        headers=_headers(),
        params={"exportType": "YOLO"},
        timeout=120,
        stream=True,
    )
    if r.status_code != 200:
        sys.exit(f"Export failed ({r.status_code}): {r.text[:200]}")

    with open(out_zip, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)
    print(f"  Downloaded: {out_zip} ({out_zip.stat().st_size // 1024} KB)")
    return out_zip


def get_ls_class_map(notes_json: dict) -> Dict[int, str]:
    """Parse notes.json → {ls_index: label_name}."""
    # LS YOLO export notes.json structure:
    # {"categories": [{"id": 0, "name": "valve_bf"}, ...]}
    cats = notes_json.get("categories", [])
    if cats:
        return {c["id"]: c["name"] for c in cats}
    # Fallback: flat list format
    if isinstance(notes_json, list):
        return {i: name for i, name in enumerate(notes_json)}
    return {}


def remap_label_file(content: str, ls_idx_to_canonical: Dict[int, int]) -> str:
    """Rewrite a YOLO .txt label file with remapped class indices."""
    lines_out = []
    for line in content.strip().splitlines():
        parts = line.split()
        if not parts:
            continue
        ls_idx = int(parts[0])
        canonical_idx = ls_idx_to_canonical.get(ls_idx)
        if canonical_idx is None:
            print(f"  WARNING: unknown LS class index {ls_idx} — skipping annotation")
            continue
        lines_out.append(f"{canonical_idx} {' '.join(parts[1:])}")
    return "\n".join(lines_out) + ("\n" if lines_out else "")


def get_task_image_urls(project_id: int) -> Dict[int, str]:
    """Return {task_id: image_url} for all tasks in a project."""
    urls = {}
    page = 1
    while True:
        r = requests.get(
            f"{LS_URL}/api/tasks/?project={project_id}&page_size=200&page={page}",
            headers=_headers(), timeout=20,
        )
        if r.status_code != 200:
            break
        data = r.json()
        tasks = data.get("tasks", data) if isinstance(data, dict) else data
        if not tasks:
            break
        for t in tasks:
            img_url = t.get("data", {}).get("image", "")
            if img_url:
                urls[t["id"]] = img_url
        if len(tasks) < 200:
            break
        page += 1
    return urls


def download_tile_image(url: str, dest: Path) -> bool:
    """Download tile from webapp (rewrite public URL → localhost:8000)."""
    import re as _re
    fetch_url = url
    if url.startswith("/"):
        fetch_url = f"{LS_URL}{url}"
    elif any(h in url for h in ("dev.qongsystems.com", "localhost", "web:")):
        fetch_url = _re.sub(r"https?://[^/]+", "http://localhost:8000", url)
    try:
        r = requests.get(fetch_url, timeout=30)
        if r.status_code == 200:
            dest.write_bytes(r.content)
            return True
        print(f"    Image download failed ({r.status_code}): {fetch_url}")
    except Exception as e:
        print(f"    Image download error: {e}")
    return False


def process_export_zip(zip_path: Path, project_id: int) -> tuple:
    """Extract YOLO ZIP, remap indices, download images, write into dataset."""
    images_added = labels_added = 0

    # Pre-fetch task → image URL mapping so we can download matching images
    task_image_urls = get_task_image_urls(project_id)

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

        notes_file = next((n for n in names if "notes.json" in n), None)
        if not notes_file:
            sys.exit(f"notes.json not found in {zip_path}")

        notes = json.loads(zf.read(notes_file))
        ls_class_map = get_ls_class_map(notes)
        print(f"  LS class map: {ls_class_map}")

        ls_idx_to_canonical: Dict[int, int] = {}
        unknown = []
        for ls_idx, ls_name in ls_class_map.items():
            canonical_idx = LS_NAME_TO_IDX.get(ls_name)
            if canonical_idx is None:
                unknown.append(f"{ls_idx}={ls_name}")
            else:
                ls_idx_to_canonical[ls_idx] = canonical_idx

        if unknown:
            print(f"  WARNING: unmapped LS classes (will be dropped): {unknown}")
        print(f"  Index remap: {ls_idx_to_canonical}")

        for name in names:
            if name.endswith(("notes.json", "classes.txt", "/")):
                continue

            filename = Path(name).name

            if name.endswith(".txt") and filename != "classes.txt":
                content = zf.read(name).decode("utf-8")
                remapped = remap_label_file(content, ls_idx_to_canonical)
                dest_lbl = TRAIN_LBL / filename
                dest_lbl.write_text(remapped)
                labels_added += 1

                # Download the matching image — label stem = "{task_id}__{tile_name}"
                stem = Path(filename).stem          # e.g. "abc123__tile_p0_r0_c0"
                dest_img = TRAIN_IMG / f"{stem}.png"
                if dest_img.exists():
                    continue  # already have it

                # Extract task_id from stem prefix before "__"
                if "__" in stem:
                    # LS uses truncated UUID prefixes; match against known task IDs
                    prefix = stem.split("__")[0]
                    matched_id = None
                    for task_id, img_url in task_image_urls.items():
                        # LS label stem uses first 8 chars of task UUID or task id
                        if str(task_id) in stem or stem.startswith(str(task_id)):
                            matched_id = task_id
                            break
                    if matched_id is None:
                        # Try substring match on tile name part
                        tile_part = stem.split("__", 1)[-1]  # e.g. "tile_p0_r0_c0"
                        for task_id, img_url in task_image_urls.items():
                            if tile_part in img_url:
                                matched_id = task_id
                                break

                    if matched_id and matched_id in task_image_urls:
                        if download_tile_image(task_image_urls[matched_id], dest_img):
                            images_added += 1
                        else:
                            print(f"    Could not download image for {filename}")

    return images_added, labels_added


def update_data_yaml():
    """Rewrite data.yaml with the full canonical class list."""
    yaml_path = DATASET_DIR / "data.yaml"
    content = f"""path: datasets/pid_valves
train: images/train
val: images/val

nc: {len(CANONICAL_CLASSES)}
names: {json.dumps(CANONICAL_CLASSES)}
"""
    yaml_path.write_text(content)
    print(f"\nUpdated data.yaml: nc={len(CANONICAL_CLASSES)} classes")


# Per-class minimum instance target — tiles containing classes below target
# get duplicated (image+label hardlinks) up to OVERSAMPLE_CAP times.
# Targets chosen from v1-9 class distribution analysis to lift rare instrument
# subtypes (DCS/PLC/interlock) closer to inst_field's ~4500 instance count,
# so the model trains discriminating signal between location subtypes.
OVERSAMPLE_TARGETS: Dict[str, int] = {
    "DCS": 1500,            # baseline 542
    "PLC": 1000,            # baseline 242
    "interlock": 500,       # baseline 81
    "interlock-R": 175,     # baseline 35 (5x cap)
    "valve_gl": 250,        # baseline 50
    "valve_3way_relief": 300,  # baseline ~99
}
OVERSAMPLE_CAP = 5    # max duplication factor per tile (prevents overfitting)


def oversample_rare_classes():
    """Duplicate training tiles that contain rare classes to balance distribution.

    For each rare class C with target T, find all tiles containing C, compute the
    duplication factor needed to reach T, cap at OVERSAMPLE_CAP, then copy
    (image, label) pairs with a "_dupN" suffix into the same train dirs.
    A tile containing multiple rare classes gets the MAX factor.
    """
    from collections import defaultdict

    # Count current instances per class + tiles-per-class
    counts: Dict[int, int] = defaultdict(int)
    tiles_with_class: Dict[int, set] = defaultdict(set)
    for lbl_path in TRAIN_LBL.glob("*.txt"):
        for line in lbl_path.read_text().strip().splitlines():
            parts = line.split()
            if not parts:
                continue
            try:
                cls_idx = int(parts[0])
            except ValueError:
                continue
            counts[cls_idx] += 1
            tiles_with_class[cls_idx].add(lbl_path.stem)

    # Compute per-tile duplication factor
    tile_factor: Dict[str, int] = {}
    for cls_name, target in OVERSAMPLE_TARGETS.items():
        if cls_name not in CANONICAL_CLASSES:
            continue
        cls_idx = CANONICAL_CLASSES.index(cls_name)
        current = counts.get(cls_idx, 0)
        if current >= target or current == 0:
            print(f"  skip oversample {cls_name}: have {current}, target {target}")
            continue
        # how much each tile must contribute to reach target
        n_tiles = len(tiles_with_class[cls_idx])
        if n_tiles == 0:
            continue
        factor = min(OVERSAMPLE_CAP, max(1, round(target / current)))
        print(f"  oversample {cls_name}: {current}→~{current*factor} via {factor}x on {n_tiles} tiles")
        for stem in tiles_with_class[cls_idx]:
            tile_factor[stem] = max(tile_factor.get(stem, 1), factor)

    # Materialize duplicates
    n_dup = 0
    for stem, factor in tile_factor.items():
        if factor <= 1:
            continue
        src_lbl = TRAIN_LBL / f"{stem}.txt"
        src_img = None
        for ext in (".png", ".jpg", ".jpeg"):
            cand = TRAIN_IMG / f"{stem}{ext}"
            if cand.exists():
                src_img = cand
                break
        if not src_img or not src_lbl.exists():
            continue
        for i in range(1, factor):  # factor=3 → make 2 duplicates (orig + 2 = 3 total)
            dup_stem = f"{stem}__dup{i}"
            dup_lbl = TRAIN_LBL / f"{dup_stem}.txt"
            dup_img = TRAIN_IMG / f"{dup_stem}{src_img.suffix}"
            if not dup_lbl.exists():
                dup_lbl.write_bytes(src_lbl.read_bytes())
            if not dup_img.exists():
                dup_img.write_bytes(src_img.read_bytes())
            n_dup += 1
    print(f"  Created {n_dup} duplicate tile pairs ({len(tile_factor)} unique tiles oversampled)")


def create_transfer_archive():
    """Pack dataset into /tmp/dataset_for_gpu.tar.gz for scp to Windows."""
    import subprocess
    out = "/tmp/dataset_for_gpu.tar.gz"
    subprocess.run(
        ["tar", "-czf", out, "-C", str(_HERE), "datasets/pid_valves"],
        check=True,
    )
    size_mb = Path(out).stat().st_size // (1024 * 1024)
    print(f"\nTransfer archive: {out} ({size_mb} MB)")


def count_existing():
    """Count existing training images/labels."""
    imgs = list(TRAIN_IMG.glob("*.png")) + list(TRAIN_IMG.glob("*.jpg"))
    lbls = list(TRAIN_LBL.glob("*.txt"))
    return len(imgs), len(lbls)


def main():
    if not LS_API_KEY:
        sys.exit("LS_API_KEY not set")

    TRAIN_IMG.mkdir(parents=True, exist_ok=True)
    TRAIN_LBL.mkdir(parents=True, exist_ok=True)

    n_img, n_lbl = count_existing()
    print(f"Existing dataset: {n_img} images, {n_lbl} label files")

    total_img = total_lbl = 0
    for proj_id in EXPORT_PROJECTS:
        zip_path = export_project_yolo(proj_id)
        imgs, lbls = process_export_zip(zip_path, proj_id)
        print(f"  Project {proj_id}: added {imgs} images, {lbls} label files")
        total_img += imgs
        total_lbl += lbls

    update_data_yaml()

    n_img2, n_lbl2 = count_existing()
    print(f"\nDataset after merge: {n_img2} images, {n_lbl2} label files (+{n_img2-n_img} images, +{n_lbl2-n_lbl} labels)")

    print("\nOversampling rare instrument classes for v1-9...")
    oversample_rare_classes()
    n_img3, n_lbl3 = count_existing()
    print(f"Dataset after oversample: {n_img3} images, {n_lbl3} label files (+{n_img3-n_img2} duplicates)")

    create_transfer_archive()
    print("\nDone. Next step: scp /tmp/dataset_for_gpu.tar.gz to Windows and run train_gpu.py")


if __name__ == "__main__":
    main()
