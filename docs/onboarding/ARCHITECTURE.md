# ARCHITECTURE.md

The technical architecture for the P&ID digitization product. This file is the entry point for any engineer who needs to understand how the system is wired. Read `PROJECT_VISION.md` first to understand WHY; this file covers HOW.

For details on specific subsystems, see:
- `REVIEW_UI_SPEC.md` — the human-in-the-loop review interface
- `ACTIVE_LEARNING_SPEC.md` — how reviewer corrections become better models
- `docs/REFERENCES.md` — research papers and reference implementations
- `docs/DATASETS.md` — training datasets and how to fetch them

---

## 1. Hardware target

### 1.1 Production: NVIDIA DGX Spark (or higher)

The shipped appliance is a single NVIDIA DGX Spark, on-premises at the client site, no internet required.

| Component | DGX Spark (target) |
|---|---|
| Compute | GB10 Grace Blackwell Superchip, 1 PFLOPS FP4 |
| CPU | 20-core ARM64 (10× Cortex-X925 + 10× Cortex-A725) |
| Memory | 128 GB LPDDR5X, unified and coherent CPU+GPU |
| Memory bandwidth | 273 GB/s |
| Storage | 4 TB NVMe (self-encrypting option) |
| Networking | ConnectX-7 200 GbE + 10 GbE + WiFi |
| Form factor | 150×150×50 mm (Mac mini class) |
| OS | NVIDIA DGX OS (Ubuntu-based, ARM64) |
| Power | ~240 W typical |
| Indicative price | $4,000–$4,700 (as of early 2026) |

Two DGX Sparks paired over ConnectX-7 give 256 GB unified memory and serve as the "higher" target for plants that need to digitize a large backlog quickly. Plan for a single unit in v1; design code so a second unit can be added without architectural changes.

**Why unified memory matters.** A DGX Spark can hold the YOLO symbol detector, the line segmenter, the direction classifier, PaddleOCR, AND a 70B-parameter VLM in memory simultaneously, with no swapping. A discrete-GPU box (RTX 6000 Ada, etc.) cannot. This collapses the model-orchestration complexity by an order of magnitude.

### 1.2 ARM64 implications

DGX Spark is ARM64. Most things just work, but watch for:

- **Docker images must be ARM64-native or multi-arch** (`linux/arm64` plus `linux/amd64`). Build with `docker buildx`. CI should produce both.
- **Some Python wheels are x86-only.** Use `pip install --platform manylinux_2_28_aarch64` checks in CI. PaddlePaddle, OpenCV, PyTorch all have working ARM64 wheels; check your other dependencies once before assuming.
- **TensorRT engines are GPU-architecture-specific.** Build them on a Blackwell-generation GPU (same SM version as the Spark). Pre-built TensorRT engines from an Ampere or Hopper machine will not load.
- **CUDA: bundle the runtime in the appliance image.** DGX OS ships CUDA 13.x by default; the appliance image pins a known version.

### 1.3 Development infrastructure (cloud is fine here)

Training, experimentation, and CI use cloud freely. The team's working assumption:

| Use | Where | Why |
|---|---|---|
| Symbol detector training (YOLOv11) | AWS p4d.24xlarge or GCP A3 (H100) | Multi-day runs would tie up a DGX Spark |
| Line segmenter training | AWS p4d / GCP A3 | Same |
| Synthetic data generation | AWS spot (compute-optimized) or GCP preemptible | Embarrassingly parallel; cheap on spot/preemptible |
| Dataset storage during dev | S3 / GCS | Cheap, durable, easy to share across the team |
| Model evaluation runs | AWS / GCP (matching the training instance type) | Reproducibility |
| Experiment tracking | Weights & Biases (cloud) | Convenient. Self-host before production if a client requires it. |
| CI | GitHub Actions, with self-hosted ARM64 runner for the DGX Spark integration test job | Mixed |
| Hosted LLM APIs (Claude API, OpenAI) | Dev tooling only | NEVER as a runtime dependency of the shipped product |

**Hard rule:** every production code path must have a documented offline equivalent. The training pipeline can stream from S3 during development, but the deployment manifest must produce a bundle that works on a DGX Spark with the network cable unplugged. CI runs an end-to-end test on a self-hosted DGX Spark runner that has no internet — if that test passes, the shipped path is offline-clean.

### 1.4 What we no longer recommend

The earlier draft of this document recommended an x86 box with an RTX 6000 Ada or A100. That is now superseded by the DGX Spark target. The reasons: unified memory simplifies multi-model orchestration; the Spark is a branded, finished, support-backed appliance (clients trust hardware they can google); the ARM64 + GB10 platform is what NVIDIA is investing in for edge AI. A discrete-GPU x86 box remains a valid fallback if a customer already owns one and refuses to buy new hardware, but it is not the design target.

The whole stack runs in Docker Compose on this single box. Multi-node is a v2 conversation. Any code path that assumes more than one machine must be flagged in `FEATURES.md` as type `architecture` for review.

## 2. Pipeline overview

The pipeline is modular. Each stage is independently swappable. The current stage status is shown on the architecture diagram (referenced in the chat session that created this repo); the textual version is:

1. **Ingestion** — accepts PDF, TIFF, PNG, DWG (via ODA File Converter). Rasterizes to high-resolution PNG.
2. **Pre-processing** — deskew, denoise, contrast normalize, tile via SAHI with 20% overlap.
3. **Symbol detection** — YOLOv11 fine-tuned on Digitize-PID + client data. Status: **POC done in the existing valve-detection repo**.
4. **Line segmentation** — U-Net producing a 1-channel line mask, then skeletonization and polyline extraction. Status: **build next**.
5. **Direction classification** — small CNN classifier on arrowhead patches detected via the line mask. Status: **build next**.
6. **Text and OCR** — PaddleOCR PP-OCRv4 with rotation handling. Status: **build next** (POC has basic OCR).
7. **Association** — Hungarian assignment from symbols to nearest text tokens; line endpoints matched to nearest symbol or junction. Rule-based with Bayesian-tuned thresholds.
8. **Graph construction** — NetworkX in-process, persisted to Neo4j. Nodes carry symbol attributes; edges carry direction and line type.
9. **Validation** — ISA S5.1 rule checks, orphan detection, cycle detection in directed flows.
10. **Review UI** — human-in-the-loop correction. See `REVIEW_UI_SPEC.md`.
11. **Export** — proprietary customer deliverables generated from the internal canonical JSON: Valve List CSV, Instrument Index CSV, Datasheets PDF, BOM XLSX, Equipment List XLSX, Loop Trace report. Internal canonical JSON is versioned in `schemas/version.json` and is not shipped to customers. No DEXPI XML or other industry-standard export — see FEATURES.md #04.

The two stages that dominate v1 effort are **line + direction** (the technical core) and **review UI** (the product surface). Everything else either exists in POC form or is well-trodden engineering.

## 3. Service topology

```
                    +----------------------------------------+
                    |        On-prem GPU server              |
                    |                                        |
   Reviewer  ----HTTP/WS----+                                |
                            |                                |
                    +-------v--------+                       |
                    | React SPA      |  served as static     |
                    | (review UI)    |  files                |
                    +-------+--------+                       |
                            |                                |
                    +-------v--------+                       |
                    | FastAPI        |                       |
                    | (control plane)|                       |
                    +-+----+----+----+                       |
                      |    |    |                            |
                      |    |    +----> Postgres (jobs, events, tags)
                      |    |                                  |
                      |    +---------> Neo4j (graph)          |
                      |                                       |
                      +--------------> Redis (queue, cache)   |
                                                              |
                    +----------------+                        |
                    | Python worker  | <----- Redis queue     |
                    | (pipeline)     |                        |
                    +----+--+--+--+--+                        |
                         |  |  |  |                           |
                         |  |  |  +----> MinIO (tiles, weights, exports)
                         |  |  +-------> Triton inference server (GPU)
                         |  +----------> PaddleOCR
                         +-------------> NetworkX, deliverable generators (CSV/PDF/XLSX)
                                                              |
                    +----------------+                        |
                    | Triton         |                        |
                    | (model serving)|                        |
                    +----------------+                        |
                                                              |
                    +----------------+                        |
                    | Training       | runs weekly,           |
                    | container      | consumes TrainingEvents |
                    +----------------+                        |
                                                              |
                    +----------------+                        |
                    | Update agent   | watches local update   |
                    | (offline pull) | folder for signed bundles
                    +----------------+                        |
                    +----------------------------------------+
```

Every box above is a Docker container. The whole thing comes up with one `docker compose up`.

## 4. Tech stack

| Layer | Choice | Reason |
|---|---|---|
| Language (backend) | Python 3.12 | ML ecosystem |
| API framework | FastAPI | Async, OpenAPI, easy to test |
| Worker queue | Redis + RQ (or Celery) | Simple, debuggable. Avoid Celery unless team already knows it |
| Object detection | Ultralytics YOLOv11 (v1) → RT-DETRv2 (v2) | Best maintained, ONNX/TensorRT exportable |
| Line segmentation | Custom U-Net (PyTorch) | Standard architecture; train from scratch |
| Direction classifier | Small CNN (PyTorch) | <10M params, trains in minutes |
| OCR | PaddleOCR PP-OCRv4 | Best rotated-text support, open weights |
| Model serving | NVIDIA Triton | Concurrent multi-model on single GPU |
| Graph DB | Neo4j Community | Free, mature, Cypher |
| Relational DB | PostgreSQL 16 | Tags, jobs, ReviewEvents, TrainingEvents |
| Object store | MinIO | S3-compatible, on-prem |
| Cache and queue | Redis 7 | Standard |
| Frontend framework | React 19 + Vite | See `REVIEW_UI_SPEC.md` |
| Canvas renderer | Konva 9 via `react-konva` | Built-in drag/transform/hit-detection; comfortably handles P&IDs in our element range; faster team productivity than PixiJS. See FEATURES.md #03. |
| Frontend state | Zustand + TanStack Query | Light, no Redux ceremony |
| Schema validation | Pydantic v2 (back), Zod (front) | Same contract both sides |
| Deliverable generation | pandas + openpyxl + reportlab | CSV / XLSX / PDF customer outputs (no DEXPI — see FEATURES.md #04) |
| Testing | pytest + Vitest + Playwright | Unit, component, E2E |
| Container runtime | Docker Compose (v1) → k3s (later) | One-box first |
| Monitoring | Prometheus + Grafana | Local-only dashboards |

Notable **non-choices**: no Laravel, no Django, no Flask, no Vue, no Svelte, no Streamlit. Stick to the table above unless `FEATURES.md` records a decision otherwise.

## 5. Phased delivery

For a four-person team (2 ML, 2 full-stack) with the existing symbol-detection POC in hand. Phases overlap where indicated.

| Phase | Duration | What ships | Parallel with |
|---|---|---|---|
| **0. Scaffolding** | 4 weeks | Repo, Docker Compose, FastAPI shell, MinIO, Postgres, Neo4j, Redis, ingestion endpoint, port the existing symbol POC into the pipeline | — |
| **1. Minimal viewer** | 4 weeks | React + Konva canvas (via `react-konva`), displays a P&ID with symbol bboxes overlaid. No editing, just viewing. Enough to QA the symbol POC. | Phase 2 starts in parallel halfway through |
| **2. Line segmentation model** | 8 weeks | U-Net trained on Digitize-PID + synthetic data, integrated into the pipeline, line overlays appear in the viewer | Phase 3 starts in parallel last 2 weeks |
| **3. Direction classifier** | 4 weeks | Arrowhead detector + classifier, direction overlays in the viewer | Phase 4 starts in parallel |
| **4. Association and graph** | 4 weeks | Tag-to-symbol association, line-endpoint resolution, graph persisted to Neo4j, queryable | — |
| **5. Full review UI** | 6 weeks | Everything in `REVIEW_UI_SPEC.md`: editing, keyboard shortcuts, issue panel, ReviewEvent capture | — |
| **6. Active learning loop** | 6 weeks | TrainingEvent pipeline, weekly retraining, eval harness, signed model bundles. See `ACTIVE_LEARNING_SPEC.md` | — |
| **7. Proprietary deliverables export** | 4 weeks | Generators for Valve List CSV, Instrument Index CSV, Datasheets PDF, BOM XLSX, Equipment List XLSX, Loop Trace report. Smoke test that every deliverable opens cleanly in Excel / Acrobat. | — |
| **8. Offline deployment** | 4 weeks | Installer, licensing, signed-bundle update mechanism, on-prem monitoring | — |

Approximate total calendar time with parallelism: **~9 months**. Without parallelism it stretches to 12+. Plan for the longer number — interruptions and integration debt always cost more than planned.

## 6. Key contracts that must not silently change

These are the interfaces that downstream code and external systems depend on. Changing them is allowed; changing them silently is not. Any change is a FEATURES.md entry of type `architecture`.

- **`ReviewEvent` schema** (Postgres + API) — see `REVIEW_UI_SPEC.md`
- **`TrainingEvent` schema** (Postgres + MinIO artifacts) — see `ACTIVE_LEARNING_SPEC.md`
- **Internal canonical JSON** — version pinned in `schemas/version.json`; this is the contract every deliverable generator reads from
- **Proprietary deliverable file formats** — Valve List / Instrument Index CSV column order, Datasheet PDF template, BOM / Equipment List XLSX sheet structure — all locked once a customer signs off; changes go in `schemas/version.json` and FEATURES.md
- **Model artifact layout in MinIO** — `models/{model_target}/{version}/`
- **Pipeline job state machine** — `queued → preprocessing → detecting → associating → building_graph → validating → ready_for_review → reviewed → exported`

## 7. Repository layout

```
.
├── CLAUDE.md
├── PROJECT_VISION.md
├── ARCHITECTURE.md             (this file)
├── REVIEW_UI_SPEC.md
├── ACTIVE_LEARNING_SPEC.md
├── FEATURES.md
├── SESSION_STATE.md
├── README.md
├── .gitignore
├── docs/
│   ├── REFERENCES.md
│   ├── DATASETS.md
│   ├── decisions/              (one .md per major decision)
│   └── templates/              (templates for the four root .md files)
├── pipeline/
│   ├── ingestion/
│   ├── preprocess/
│   ├── symbols/                (POC code lands here)
│   ├── lines/
│   ├── direction/
│   ├── text/
│   ├── associate/
│   ├── graph/
│   ├── validate/
│   └── export/
├── api/                        (FastAPI service)
├── web/                        (React review UI)
├── training/
│   ├── data/                   (gitignored, large)
│   ├── synthetic/              (synthetic data generation)
│   ├── runs/                   (training scripts, one per model_target)
│   └── eval/                   (eval harness)
├── schemas/                    (JSON Schema for internal canonical graph)
├── models/                     (gitignored; weights fetched from registry)
├── deploy/
│   ├── docker-compose.yml
│   ├── installer/
│   └── rollback.sh
└── tests/                      (cross-cutting; unit tests live next to code)
```

## 8. Risks worth re-reading every quarter

| Risk | Severity | Current mitigation |
|---|---|---|
| Line segmentation accuracy plateaus below 0.85 F1 on real oil & gas P&IDs | High | Add Relationformer (arXiv 2411.13929) as v2 path; the modular pipeline is a fallback |
| Reviewers don't actually hit 15-min-per-sheet | High | Validate the target early with 3 real reviewers in Phase 5 acceptance testing |
| Training data scarcity from real oil & gas plants | High | Build a synthetic generator early (Phase 2 onward); make data contribution a contract term |
| Single-GPU box can't run all models concurrently | Medium | Triton scheduling + INT8 quantization. Profile at end of Phase 2 |
| Konva performance ceiling hit on unusually dense sheets (>10,000 overlay elements) | Low | Tile overlays by region; if recurring, migrate the renderer to PixiJS. Don't pre-optimize. |
| Hexagon SmartPlant bundles a free P&ID parser as response | Medium | Compete on review workflow, not on detection accuracy alone |
| Deliverable file formats rejected by client (column naming, sheet ordering, PDF layout) | Low | Lock per-customer deliverable templates at signing; smoke-test that every deliverable opens cleanly in Excel + Acrobat in CI |

## 9. What this file is not

This is not an installation guide, not a developer setup guide, and not a code-style guide. Those belong in `README.md` and `docs/`. This file describes the system at the architectural level — the boxes, the arrows, the contracts between them, and the phased path to v1.
