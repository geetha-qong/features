# Label Studio Annotation Setup

## Install & Start

```bash
pip install label-studio
label-studio start
# Opens at http://localhost:8080
```

## Export Tiles First

```bash
python3 annotate/export_tiles_for_annotation.py
# Creates: annotate/tiles/ (45 PNG files, one per tile across 5 drawings)
```

## Label Studio Project Setup

1. Create new project → **Object Detection with Bounding Boxes**
2. Import images from `annotate/tiles/`
3. Add these 10 labels (in this exact order, IDs match YOLO class IDs):

| ID | Label | What to look for |
|----|-------|-----------------|
| 0 | `valve_bf` | Butterfly: bowtie / diamond shape bisecting a pipe |
| 1 | `valve_bv` | Ball: circle with a line through it on a pipe |
| 2 | `valve_ck` | Check: arrowhead or half-circle showing flow direction |
| 3 | `valve_gl` | Globe: circle with internal plug/cross symbol |
| 4 | `valve_db` | Double Block & Bleed: cluster of 3 small valve symbols on an instrument tap |
| 5 | `valve_cv` | Control valve: circle with pneumatic dome actuator on top (often on a control loop) |
| 6 | `valve_gen` | Generic: any other valve (VM, VG, NV, SV, UZV, PV, FV) |
| 7 | `actuator_motor` | Motor box: square box with "M" label attached to a valve |
| 8 | `actuator_pneu` | Pneumatic: dome/diaphragm shape above a valve body |
| 9 | `actuator_sol` | Solenoid: "SL" text box or coil symbol near a valve |

## Annotation Tips

- **Use ground truth CSV as a guide**: `job_outputs/{id}/valve_list.csv` tells you
  exactly which serial numbers exist in each drawing. Cross-reference to not miss valves.
- **Annotate the symbol body only** (not the tag text). Keep boxes tight around the symbol.
- **Actuators**: draw a separate box for each actuator attached to a valve — they are
  separate YOLO classes from the valve body.
- **DB valves**: the entire 3-symbol cluster gets one `valve_db` box.
- **Instruments** (PDT, FT, LT — circles with letters): DO NOT annotate these.
- **Pumps** (62-P-XXXXXX): DO NOT annotate — they are equipment, not valves.
  The M motor symbols on pumps should NOT be annotated as `actuator_motor`.

## Export

Export → YOLO format → download ZIP.

Extract to `datasets/pid_valves/`:
```
datasets/pid_valves/
  images/train/   ← tiles from drawings 1002, 1003, 1004, 1005
  images/val/     ← tiles from drawing 1001 (our largest, best ground truth)
  labels/train/   ← .txt label files
  labels/val/
  data.yaml       ← already created
```

Move 9 tiles from the 1001 drawing to val/, rest to train/.

## Validation

```bash
python3 -c "
from ultralytics import YOLO
model = YOLO('yolov8s.pt')
model.val(data='datasets/pid_valves/data.yaml')
"
# Should load without errors before starting training
```

## Then Train

```bash
python3 train.py
```

Expected time:
- CPU only (8-core): ~12-18 hours for 100 epochs
- GPU (RTX 3080): ~2 hours
- Cloud (Colab Pro, A100): ~30 minutes
