# docs/REFERENCES.md

Research papers and reference implementations that inform this project. Read these before reimplementing a stage from scratch.

## Foundational papers

### Mani et al., 2020 — Automatic Digitization of Engineering Diagrams Using Deep Learning and Graph Search (CVPR-W)
https://openaccess.thecvf.com/content_CVPRW_2020/papers/w8/Mani_Automatic_Digitization_of_Engineering_Diagrams_Using_Deep_Learning_and_Graph_CVPRW_2020_paper.pdf

The original modular pipeline: CNN for symbols, traditional CV for lines, graph search for connections. This is the mental model our pipeline starts from. Read it first; everything else is a refinement.

### Paliwal et al., 2021 — Digitize-PID: Automatic Digitization of Piping and Instrumentation Diagrams (arXiv 2109.03794)
https://arxiv.org/pdf/2109.03794

The paper that released the synthetic 500-sheet, 32-symbol dataset that is now the de facto training corpus. See `docs/DATASETS.md` for how to fetch it. The paper itself describes a YOLOv2-based pipeline that's been superseded by later work, but the dataset is gold.

### Stürmer et al., 2024 — From Engineering Diagrams to Graphs: Digitizing P&IDs with Transformers (arXiv 2411.13929)
https://arxiv.org/pdf/2411.13929

Current state of the art. Uses **Relationformer** to jointly detect symbols AND their edges in one model, outperforming modular pipelines by 25%+ on edge detection. Released **PID2Graph**, the first publicly available P&ID dataset with graph-level annotations. This is the v2 architecture target — our v1 modular pipeline is the fallback.

### Byun et al., 2025 — Optimizing image format P&ID recognition (Oxford JCDE)
https://academic.oup.com/jcde/article/12/6/55/8156798

Integrated symbol + text detection in one backbone using text-spotting techniques. Faster inference than the modular approach. Useful for the OCR stage when we're ready to consolidate.

### Nature Scientific Reports, 2025 — Automated inspection of P&ID object recognition
https://www.nature.com/articles/s41598-025-25506-2

Methods for catching detection errors automatically — feature-vector similarity for misclassified symbols, distance-based text error detection, intersection inspection for misrouted lines. Useful for the `validate/` stage and for prioritizing issues in the review UI.

## Reference implementations

### Microsoft / Azure-Samples — digitization-of-piping-and-instrument-diagrams
https://github.com/Azure-Samples/digitization-of-piping-and-instrument-diagrams

The most complete end-to-end reference available. Production-grade architecture decisions. Read `docs/architecture.md` in that repo before designing our own. They use YOLOv5; we use YOLOv11.

### AWS Solutions Library — guidance-for-piping-and-instrumentation-diagrams-digitization-on-aws
https://github.com/aws-solutions-library-samples/guidance-for-piping-and-instrumentation-diagrams-digitization-on-aws

AWS Bedrock Data Automation + SageMaker version. The cloud bits don't apply to us (we're on-prem). Their **JSON output schema** for bounding boxes + tag associations is worth copying directly. Skip the DEXPI export step they include — we deliberately do NOT ship DEXPI (see FEATURES.md #04); our customer deliverables are proprietary CSV / PDF / XLSX instead.

### Mohit Gupta — PID_Symbol_Detection and PID-KnowledgeGraph-demo
- https://github.com/mgupta70/PID_Symbol_Detection
- https://github.com/mgupta70/PID-KnowledgeGraph-demo

SAHI-based patch inference for large P&IDs, plus a working demo of P&ID → knowledge graph conversion. Useful patterns for our `lines/` and `graph/` stages.

### RahulRaj-DDC — PidDetector
https://github.com/RahulRaj-DDC/PidDetector

YOLOv8-based detector with multi-OCR support (PaddleOCR, EasyOCR), a Tkinter GUI, and XLSX export. The GUI is not what we want, but the multi-OCR fallback pattern is worth borrowing.

### ch-hristov — p-id-symbols
https://github.com/ch-hristov/p-id-symbols

Older YOLOv5 symbol extraction. Read for clean training-pipeline structure.

### mohdahmad242 — PID-detection
https://github.com/mohdahmad242/PID-detection

Detectron2-based alternative. Good if we ever want to compare against Detectron's two-stage detectors.

## Standards and formats

### ISA S5.1 (we use this)
The instrument symbology standard. Every oil-and-gas P&ID respects it. Tag prefixes (PT, TT, FT, LT, PV, FV, FCV, ...) are defined here. Keep a copy of the standard at hand when writing the `associate/` stage. This is the only external standard the product reads from.

### DEXPI 2.0 — evaluated and intentionally rejected
https://dexpi.org/specifications/

DEXPI 2.0 is an ISO-15926-based XML interchange format for P&ID data, well-supported by EPCs and major engineering platforms. An earlier draft of this project committed to it as the canonical output. **That decision was reversed on 2026-05-26** (see FEATURES.md #04): exporting a clean industry-standard format would make it trivially easy for customers to migrate digitized data off our platform, undermining the commercial moat. We therefore ship **only proprietary deliverables** (Valve List, Instrument Index, Datasheets, BOM, Equipment List, Loop Trace) in CSV / PDF / XLSX. The internal graph schema in `schemas/version.json` is independent of DEXPI. Do not add `pydexpi` to requirements. Reversible later only on a per-customer paid-for basis.

## When to reach for which paper

| Building | Read |
|---|---|
| `pipeline/symbols/` | Mani 2020, Paliwal 2021 |
| `pipeline/lines/` | Mani 2020 (graph search), then Stürmer 2024 (Relationformer) for v2 |
| `pipeline/direction/` | Stürmer 2024 (edge-direction handling), our own ablation experiments |
| `pipeline/text/` | Byun 2025 (integrated detection), PaddleOCR docs |
| `pipeline/associate/` | Mani 2020 (text-symbol association), ISA S5.1 |
| `pipeline/validate/` | Nature 2025 (error detection methods) |
| `pipeline/export/` | Internal canonical schema in `schemas/version.json`; pandas / openpyxl / reportlab for CSV / XLSX / PDF deliverables |
| `web/` (review UI) | None — this is product work, not research |
| `training/` | All four foundational papers, plus our own eval results in `docs/decisions/` |
