"""
YOLOv8s training on Windows GPU (NVIDIA RTX 2000 Ada Generation).

Usage:
    python train_gpu.py                          # fresh train from yolov8s.pt
    python train_gpu.py --export runs/.../best.pt  # export best.pt → best.onnx

Run from C:\\Users\\qongsystems\\qong-poc-gpu\\ after copying dataset there:
    "C:\\Program Files\\Python311\\python.exe" -X utf8 train_gpu.py
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

# Must add cuda_dlls before any torch/onnxruntime import
if sys.platform == "win32":
    _dll = Path(__file__).parent / "cuda_dlls"
    if _dll.is_dir():
        os.add_dll_directory(str(_dll))

DATASET_DIR = Path(__file__).parent / "datasets" / "pid_valves"
RUNS_DIR    = Path(__file__).parent / "runs" / "detect"
MODEL_OUT   = Path(__file__).parent / "models" / "best.onnx"

EPOCHS   = 100
IMGSZ    = 1280
BATCH    = 4     # RTX 2000 Ada has 8GB VRAM — safe at batch=4, imgsz=1280
WORKERS  = 4
PROJECT  = "pid_valves"


def train():
    from ultralytics import YOLO

    data_yaml = DATASET_DIR / "data.yaml"
    if not data_yaml.exists():
        sys.exit(f"data.yaml not found at {data_yaml}")

    model = YOLO("yolov8s.pt")
    model.train(
        data=str(data_yaml),
        epochs=EPOCHS,
        imgsz=IMGSZ,
        batch=BATCH,
        workers=WORKERS,
        device="cuda:0",
        project=str(RUNS_DIR),
        name=PROJECT,
        amp=True,           # safe with CUDA (unlike MPS)
        exist_ok=False,
        patience=30,        # early stopping if no improvement for 30 epochs
        save=True,
        save_period=10,
    )
    print("\nTraining complete.")
    _export_best()


def _find_best_pt() -> Path:
    candidates = sorted(RUNS_DIR.rglob("best.pt"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        sys.exit("No best.pt found under runs/")
    return candidates[-1]


def _export_best(pt_path: Path = None):
    from ultralytics import YOLO

    if pt_path is None:
        pt_path = _find_best_pt()

    print(f"\nExporting {pt_path} → ONNX...")
    model = YOLO(str(pt_path))
    model.export(format="onnx", imgsz=IMGSZ, simplify=False, opset=12)

    onnx_path = pt_path.with_suffix(".onnx")
    if onnx_path.exists():
        MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(onnx_path, MODEL_OUT)
        print(f"Copied to {MODEL_OUT}")
    else:
        print(f"WARNING: expected {onnx_path} but not found")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", metavar="BEST_PT", default=None,
                        help="Export this best.pt to ONNX without training")
    args = parser.parse_args()

    if args.export:
        _export_best(Path(args.export))
    else:
        train()


if __name__ == "__main__":
    main()
