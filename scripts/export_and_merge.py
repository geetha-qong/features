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

EXPORT_PROJECTS = [1, 3]  # fully annotated projects

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
    "valve_3way_relief",  # 18  ← new
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
    # future classes (project 25 etc.) — add here when ready
    "valve_ncbv": 19,
    "valve_relief_safety": 20,
    "valve_pnuectrl": 21,
}


def _headers():
    return {"Authorization": f"Token {LS_API_KEY}"}


def export_project_yolo(project_id: int) -> Path:
    """Export LS project as YOLO ZIP, return local path to ZIP."""
    print(f"\nExporting project {project_id}...")

    # Trigger export
    r = requests.post(
        f"{LS_URL}/api/projects/{project_id}/exports/",
        headers=_headers(),
        json={"export_type": "YOLO"},
        timeout=60,
    )
    if r.status_code not in (200, 201):
        sys.exit(f"Export trigger failed ({r.status_code}): {r.text[:200]}")

    export_data = r.json()
    export_id = export_data.get("id")

    # Poll until ready
    for _ in range(60):
        time.sleep(3)
        status_r = requests.get(
            f"{LS_URL}/api/projects/{project_id}/exports/{export_id}/",
            headers=_headers(),
            timeout=15,
        )
        if status_r.status_code == 200:
            sd = status_r.json()
            if sd.get("status") == "completed":
                break
            if sd.get("status") == "failed":
                sys.exit(f"Export failed: {sd}")
        print(f"  waiting... status={sd.get('status','?')}")
    else:
        sys.exit("Export timed out after 3 minutes")

    # Download
    dl_url = f"{LS_URL}/api/projects/{project_id}/exports/{export_id}/download/"
    dl_r = requests.get(dl_url, headers=_headers(), timeout=120, stream=True)
    if dl_r.status_code != 200:
        sys.exit(f"Download failed ({dl_r.status_code})")

    out_zip = Path(f"/tmp/ls_export_proj{project_id}.zip")
    with open(out_zip, "wb") as f:
        for chunk in dl_r.iter_content(chunk_size=65536):
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


def process_export_zip(zip_path: Path) -> tuple:
    """Extract YOLO ZIP, remap indices, write into dataset. Returns (images, labels) counts."""
    images_added = labels_added = 0

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

        # Find notes.json for class mapping
        notes_file = next((n for n in names if "notes.json" in n), None)
        if not notes_file:
            sys.exit(f"notes.json not found in {zip_path}")

        notes = json.loads(zf.read(notes_file))
        ls_class_map = get_ls_class_map(notes)
        print(f"  LS class map: {ls_class_map}")

        # Build LS index → canonical index mapping
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

        # Process images and labels
        for name in names:
            if name.endswith(("notes.json", "classes.txt", "/")):
                continue

            data = zf.read(name)
            filename = Path(name).name

            if any(name.endswith(ext) for ext in (".jpg", ".jpeg", ".png")):
                dest = TRAIN_IMG / filename
                dest.write_bytes(data)
                images_added += 1

            elif name.endswith(".txt") and filename != "classes.txt":
                content = data.decode("utf-8")
                remapped = remap_label_file(content, ls_idx_to_canonical)
                dest = TRAIN_LBL / filename
                dest.write_text(remapped)
                labels_added += 1

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
        imgs, lbls = process_export_zip(zip_path)
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
