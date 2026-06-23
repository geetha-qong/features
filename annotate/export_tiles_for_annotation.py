"""
Export tiles from all job outputs into the annotation working directory.

Usage:
    python3 annotate/export_tiles_for_annotation.py

Copies all tile_*.png from job_outputs/*/tmp/ into:
  annotate/tiles/job{N}_tile_{r}_{c}.png

Then you load these into Label Studio for bounding box annotation.
"""
import shutil
from pathlib import Path

JOB_OUTPUTS = Path("job_outputs")
OUT_DIR = Path("annotate/tiles")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Job ID → P&ID name mapping (for reference)
JOB_NAMES = {
    1: "MUK-1005",
    2: "MUK-1004",
    3: "MUK-1003",
    4: "MUK-1002",
    5: "MUK-1001",
}

total = 0
for job_dir in sorted(JOB_OUTPUTS.iterdir()):
    if not job_dir.is_dir():
        continue
    job_id = int(job_dir.name) if job_dir.name.isdigit() else None
    if job_id is None:
        continue

    tmp = job_dir / "tmp"
    if not tmp.exists():
        continue

    pid_name = JOB_NAMES.get(job_id, f"job{job_id}")
    for tile in sorted(tmp.glob("tile_*.png")):
        # tile_p0_r0_c0.png → job1_MUK-1005_r0_c0.png
        parts = tile.stem.split("_")  # ['tile', 'p0', 'r0', 'c0']
        row = parts[2] if len(parts) > 2 else "rX"
        col = parts[3] if len(parts) > 3 else "cX"
        dest_name = f"job{job_id}_{pid_name}_{row}_{col}.png"
        shutil.copy2(tile, OUT_DIR / dest_name)
        print(f"  Copied {tile.name} → {dest_name}")
        total += 1

print(f"\nTotal tiles exported: {total}")
print(f"Output directory: {OUT_DIR.resolve()}")
print("\nNext step:")
print("  pip install label-studio")
print("  label-studio start")
print("  Import images from:", OUT_DIR.resolve())
print("  Use 10 classes from datasets/pid_valves/data.yaml")
