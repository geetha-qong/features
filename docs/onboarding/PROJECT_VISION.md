# PROJECT_VISION.md

This file describes the end product. It changes rarely. Every session should read it before doing anything.

## The end product, in one paragraph

An on-premises software appliance that ingests P&ID drawings from an oil and gas plant, extracts every component and the directed connections between them, lets a human reviewer correct any mistakes in a web UI, and produces a set of proprietary customer deliverables (Valve List, Instrument Index, Datasheets, BOM, Equipment List, Loop Trace report) derived from a queryable internal graph. The graph itself stays inside the product — we deliberately do NOT export an industry-standard format like DEXPI, so that customers cannot trivially migrate the digitized data off our platform. The reviewer's corrections are captured as training data and used to improve the underlying models over time. The system runs without internet access at the client site.

## Why this exists

Oil and gas operators have thousands of legacy P&IDs trapped as PDFs and scans. Digitizing them manually takes 3–6 months per facility at a cost of tens of lakhs. A single mid-size refinery may have 10,000+ sheets. The current commercial alternatives (Hexagon SmartPlant, AVEVA, Bentley) cost crores in licensing and still require manual cleanup. There is room for a focused, accurate, affordable, on-premises product.

## What "done" looks like for v1

| Capability | v1 target |
|---|---|
| Symbol detection accuracy (mAP@0.5) on real P&IDs | >= 0.88 |
| Line and edge detection F1 | >= 0.85 |
| Direction (arrowhead) detection F1 | >= 0.80 |
| Tag-to-symbol association accuracy | >= 0.92 |
| Time to digitize one A1 sheet (cold start, GPU) | < 60 seconds |
| Reviewer time per sheet to reach 99% accuracy | < 15 minutes |
| Proprietary deliverables (Valve List, Instrument Index, Datasheets, BOM, Equipment List, Loop Trace) generate cleanly from the internal graph | 100% |
| Runs fully offline after install | yes |
| Single-box deployment (one GPU server) | yes |

If we hit those numbers on a held-out set of real customer P&IDs across three different EPC styles, v1 ships.

## Non-goals (this is what we do NOT build)

- We do NOT build a P&ID drawing or authoring tool. We only digitize existing diagrams.
- We do NOT build a 3D plant model or digital twin. We produce a graph; downstream systems can build twins from it.
- We do NOT parse non-P&ID engineering documents in v1. No Instrument Index extraction, no Cause and Effect matrix parsing, no datasheet reading, no cable schedule import. These are v2 candidates and must NOT bleed into v1 scope.
- We do NOT support cloud deployment. Every architectural decision must work on a single on-prem GPU box.
- We do NOT support real-time streaming or live plant data integration. We are an offline batch digitizer.
- We do NOT compete on price with free open-source tools. We compete on accuracy and on the review workflow.

If a request would expand any of the above, it is out of scope. Push back and ask whether the vision is changing.

## Target user

Two distinct users, both inside the same client organization:

1. **Plant engineer / project lead.** Uploads sheets, supervises a team of reviewers, downloads the proprietary deliverable bundle (CSV/PDF/XLSX) for their existing engineering workflow. Cares about throughput and correctness.
2. **Reviewer / drafter.** Spends the day in the review UI, correcting model output one sheet at a time. Cares about UI speed, clear visualizations of low-confidence regions, and not having to relearn the tool each release.

The system is NOT designed for plant operators, control room engineers, or HSE auditors. They are downstream consumers of the graph, not users of the tool.

## Technical pillars

These are the load-bearing decisions. They should not be changed without a recorded discussion in `docs/decisions/`.

1. **Modular detection pipeline.** Symbols, lines, direction, text are separate models that can be improved and swapped independently. Migration to a joint-detection transformer (Relationformer family) is a v2 candidate, not v1.
2. **Proprietary deliverables as the only customer-facing output.** Internal JSON / NetworkX graph stays inside the product. Customers receive Valve List CSV, Instrument Index CSV, Datasheets PDF, BOM XLSX, Equipment List XLSX, and a Loop Trace report — never the raw graph and never a standards-based interchange format. We deliberately do NOT export DEXPI 2.0 XML or any other industry-standard format: providing a clean exit format would let customers walk the digitized data off our platform. See FEATURES.md #04 for the full rationale; this is a reversible decision but only on a per-customer paid-for basis.
3. **Human-in-the-loop is a feature, not a fallback.** The review UI is core product, not scaffolding. Reviewer corrections feed an active-learning loop that improves models over time.
4. **Offline by design at the customer site.** The *shipped product* must run with no internet at the client. No telemetry, no licence check phoning home, no model weights pulled at runtime. Updates ship as signed bundles. This constraint applies to production deployment only — see "Development vs production environments" below for the dev-side picture.
5. **One small box per site.** Target hardware is NVIDIA DGX Spark (or higher in the DGX family). 128 GB unified Grace-Blackwell memory, ARM64 architecture, 4 TB NVMe. Code must run in that envelope.

## Development vs production environments

Two environments. Do not confuse them.

**Development and training (cloud is fine):**
- AWS and GCP are used freely for training runs, experimentation, CI, synthetic data generation, model evaluation, dataset storage during development.
- Cloud GPUs (A100, H100, H200 on demand) are appropriate for the multi-day training jobs that would tie up a DGX Spark for too long.
- Engineers may use hosted APIs (HuggingFace, OpenAI, Anthropic) for *evaluation and tooling* — never as a dependency the shipped product relies on.

**Production deployment (no cloud, ever):**
- The shipped appliance is a DGX Spark sitting on the client's network with no internet.
- All model weights are bundled into the deployment artifact.
- No API calls leave the box. No telemetry. No update-check pings.
- Model updates arrive as signed `.tar.gz` bundles via sneakernet or the client's own air-gapped channel.

**The rule that connects them:** *every production code path must be runnable on a DGX Spark with no network*. Cloud is allowed for development and training; cloud is forbidden in anything that runs at the customer site. Code paths that are cloud-only during dev (e.g. a training pipeline that streams from S3) must have an equivalent on-prem path before shipping (e.g. reading from local MinIO).

## Repository layout

```
.
|-- CLAUDE.md                    (this is the rules file for Claude Code sessions)
|-- PROJECT_VISION.md            (this file)
|-- FEATURES.md                  (append-only feature log)
|-- SESSION_STATE.md             (overwritten every session)
|-- README.md                    (human-facing, for new team members)
|-- docs/
|   |-- decisions/               (one markdown per major architectural decision)
|   |-- templates/               (templates for the four files above)
|   `-- references/              (papers, vendor docs, dataset notes)
|-- pipeline/                    (Python: detection, OCR, graph build)
|   |-- symbols/
|   |-- lines/
|   |-- direction/
|   |-- text/
|   |-- associate/
|   |-- graph/
|   |-- validate/
|   `-- export/
|-- api/                         (FastAPI service exposing pipeline + storage)
|-- web/                         (review UI - React or Inertia, decide separately)
|-- training/                    (data prep, training scripts, eval harness)
|-- schemas/                     (JSON Schema for internal canonical graph, versioned)
|-- models/                      (model weights, gitignored, fetched from registry)
|-- deploy/                      (Docker Compose, installer scripts, licence)
`-- tests/                       (cross-cutting; unit tests live next to code)
```

## Known risks we are accepting

- **Real-world accuracy below the v1 target on novel EPC styles.** Mitigation: ship vendor-specific LoRA adapters and update mechanism, sell as "review accelerator" not "fully automated".
- **Training data scarcity.** Mitigation: synthetic data pipeline, anonymized contributions from clients written into the contract.
- **Commercial competition from Hexagon and AVEVA.** Mitigation: focus on price-sensitive plants and on the review-workflow quality, not on feature breadth.

## How this file gets updated

Only with explicit human approval. When the user asks for a vision change, the agent must:
1. Quote the section that would change.
2. Propose the new text.
3. Wait for confirmation.
4. Apply, and log the change in `FEATURES.md` as type `architecture`.

Silent edits to this file are forbidden.
