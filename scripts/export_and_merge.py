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

EXPORT_PROJECTS = [1, 3, 4, 5, 6, 11, 12, 13, 14]  # fully annotated projects

_HERE = Path(__file__).resolve().parent.parent
DATASET_DIR = _HERE / "datasets" / "pid_valves"
TRAIN_IMG = DATASET_DIR / "images" / "train"
TRAIN_LBL = DATASET_DIR / "labels" / "train"

# Canonical class list — indices 0-9 MUST match existing label files exactly
CANONICAL_CLASSES = [
    "actuator_motor",     # 0
    "actuator_pneu",      # 1
    "actuator_sol",       # 2
    "valve_bf",           # 3
    "valve_bv",           # 4
    "valve_ck",           # 5
    "valve_cv",           # 6
    "valve_db",           # 7
    "valve_gen",          # 8
    "valve_gl",           # 9
    "inst_field",         # 10  ← new
    "DCS",                # 11  ← new
    "PLC",                # 12  ← new
    "interlock",          # 13  ← new
    "interlock-R",        # 14  ← new
    "inst_field-R",       # 15  ← new
    "Pump_Dwg_Pump",      # 16  ← new (slash/space replaced for filesystem safety)
    "Motor",              # 17  ← new
    "valve_3way_relief",  # 18
    "valve_ncbv",         # 19
    "valve_relief_safety",# 20
    "valve_pnuectrl",     # 21
]

# LS label name → canonical index (handles name differences)
LS_NAME_TO_IDX: Dict[str, int] = {
    "actuator_motor": 0,
    "actuator_pneumatic": 1,   # LS name ≠ canonical
    "actuator_solenoid": 2,    # LS name ≠ canonical
    "actuator_pneu": 1,        # fallback if old name appears
    "actuator_sol": 2,
    "valve_bf": 3,
    "valve_bv": 4,
    "valve_ck": 5,
    "valve_cv": 6,
    "valve_db": 7,
    "valve_gen": 8,
    "valve_gl": 9,
    "inst_field": 10,
    "DCS": 11,
    "PLC": 12,
    "interlock": 13,
    "interlock-R": 14,
    "inst_field-R": 15,
    "Pump/Dwg Pump": 16,
    "Pump_Dwg_Pump": 16,
    "Motor": 17,
    "valve_3way_relief": 18,
    "valve_ncbv": 19,
    "valve_relief_safety": 20,
    "valve_pnuectrl": 21,
    "valve_pneuctrl": 21,      # spelling variant in project 6
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

    create_transfer_archive()
    print("\nDone. Next step: scp /tmp/dataset_for_gpu.tar.gz to Windows and run train_gpu.py")


if __name__ == "__main__":
    main()
