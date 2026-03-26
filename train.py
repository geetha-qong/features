"""
YOLOv8s training script for P&ID valve symbol detection.

Prerequisites:
    pip install ultralytics

Usage:
    # First training run:
    python3 train.py

    # Resume from checkpoint:
    python3 train.py --resume

    # Fine-tune existing model (add new drawings):
    python3 train.py --finetune runs/detect/pid_valves_v1/weights/best.pt

After training, export to ONNX for production (no PyTorch needed at inference):
    python3 train.py --export runs/detect/pid_valves_v1/weights/best.pt
"""
import argparse
from pathlib import Path
from ultralytics import YOLO


DATA_YAML = "datasets/pid_valves/data.yaml"
BASE_MODEL = "yolov8s.pt"          # COCO pre-trained, download on first run
PROJECT = "runs/detect"
RUN_NAME = "pid_valves_v1"


def train(resume: bool = False, finetune: str = None):
    if finetune:
        print(f"Fine-tuning from: {finetune}")
        model = YOLO(finetune)
        epochs = 30
        lr0 = 0.001  # lower LR for fine-tuning
    else:
        print(f"Training from base: {BASE_MODEL}")
        model = YOLO(BASE_MODEL)
        epochs = 100
        lr0 = 0.005

    results = model.train(
        data=DATA_YAML,
        epochs=epochs,
        imgsz=1280,       # CRITICAL: P&ID symbols are 40-80px; need high res
        batch=4,          # 4 tiles at 1280px fits 8GB RAM (CPU); use 8-16 on GPU
        lr0=lr0,
        warmup_epochs=5,
        # Augmentation — tailored for P&ID drawings
        degrees=15,       # ±15° rotation (pipe layouts rotate, valve bodies less so)
        fliplr=0.5,       # horizontal flip valid (butterfly looks same flipped)
        flipud=0.3,       # vertical flip also valid
        mosaic=1.0,       # combine 4 tiles → increases effective dataset 4×
        mixup=0.1,        # blend two images slightly
        # Standard augmentation
        hsv_h=0.015,
        hsv_s=0.3,        # reduce color variation (P&IDs are mostly black & white)
        hsv_v=0.3,        # brightness variation (simulates scan quality)
        perspective=0.0,  # no perspective warp (engineering drawings are orthographic)
        project=PROJECT,
        name=RUN_NAME,
        resume=resume,
        verbose=True,
        save=True,
        save_period=10,   # save checkpoint every 10 epochs
    )

    print(f"\nTraining complete.")
    print(f"Best weights: {results.save_dir}/weights/best.pt")
    print(f"mAP@0.5: {results.results_dict.get('metrics/mAP50(B)', 'N/A'):.3f}")
    return str(Path(results.save_dir) / "weights" / "best.pt")


def export_onnx(weights_path: str):
    """Export to ONNX for production inference without full PyTorch."""
    model = YOLO(weights_path)
    model.export(
        format="onnx",
        imgsz=1280,
        simplify=True,
        opset=17,
        dynamic=False,   # fixed batch size for ONNX runtime
    )
    onnx_path = weights_path.replace(".pt", ".onnx")
    print(f"Exported ONNX: {onnx_path}")
    print(f"Copy to: models/best.onnx")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    parser.add_argument("--finetune", type=str, default=None, help="Path to .pt weights to fine-tune")
    parser.add_argument("--export", type=str, default=None, help="Export .pt weights to ONNX")
    args = parser.parse_args()

    if args.export:
        export_onnx(args.export)
    else:
        best = train(resume=args.resume, finetune=args.finetune)
        print(f"\nNext: export to ONNX:")
        print(f"  python3 train.py --export {best}")
