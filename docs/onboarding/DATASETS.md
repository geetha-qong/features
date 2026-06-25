# docs/DATASETS.md

Where our training data comes from and how to fetch it. All sources listed here are either public or contributed by clients under contract.

## Public datasets

### Digitize-PID synthetic dataset (Paliwal et al., 2021)

The starter dataset. 500 synthetic P&IDs with annotations for 32 symbol classes. Bounding boxes, line annotations, and text labels are provided.

- Original: https://drive.google.com/drive/u/1/folders/1gMm_YKBZtXB3qUKUpI-LF1HE_MgzwfeR
- HuggingFace mirror (YOLO format): https://huggingface.co/datasets/hamzas/digitize-pid-yolo
- License: research use. Verify before any commercial deployment.

Fetch with:

```bash
pip install datasets
python -c "from datasets import load_dataset; load_dataset('hamzas/digitize-pid-yolo', cache_dir='./training/data/digitize-pid')"
```

Limitations: synthetic only, 32 symbol classes, not oil-and-gas-specific. Bootstrap value is high; real-world generalization is poor without our own data on top.

### PID2Graph (Stürmer et al., 2024)

Real-world P&IDs with graph-level annotations — symbols, nodes, AND their connections labeled together. This is the first dataset that lets us train and evaluate the connection-detection stage properly.

- Paper: https://arxiv.org/abs/2411.13929
- Dataset: linked from the paper (check arXiv supplementary materials for the latest URL)

Use this as our **primary evaluation set** for line and edge detection accuracy. Do not train on it; train on synthetic + our own data and evaluate on PID2Graph.

### ISA S5.1 reference legends

Not a dataset — a set of canonical symbol images per ISA standard. We render these into synthetic data and also use them for few-shot classification when a client uses a non-standard symbol set.

Source: bundled reference images in `training/synthetic/isa_legends/` (committed to the repo because they are small and stable).

## Synthetic data generation

Our own synthetic pipeline lives in `training/synthetic/`. It composes P&IDs from ISA S5.1 templates with controlled variation:

- Symbol density (5 to 80 symbols per A1 sheet)
- Line density and routing (straight, L-bend, multi-bend)
- Symbol style variation (different vendor templates)
- Text font, size, rotation
- Noise: speckle, blur, scan artifacts, compression
- Sheet borders and title blocks
- Off-page connectors (1-of-12, 2-of-12 patterns)

Target: 50,000+ synthetic sheets generated and stored in MinIO before Phase 2 model training begins. Generation cost: ~6 hours on the dev workstation.

This is the bulk of our training data until real-world contributions accumulate.

## Client-contributed data

Subject to contract terms with each client. The expected default contract includes:

- Anonymization of all tags, equipment numbers, and proprietary identifiers before the data leaves the client site
- Use limited to our internal model training; no redistribution
- Client receives free model updates for 24 months
- Client can opt out of training contribution at any time per sheet (sheet-level flag in the database)

Anonymization is automated by a separate pipeline (`training/anonymize/`) that runs on the client box BEFORE any data leaves it. The reviewer reviews the anonymized version and approves shipment.

Storage layout in our central training pool:

```
training/data/clients/{anonymized_client_id}/{sheet_uuid}/
  ├── source.png
  ├── annotation.json
  ├── corrections.jsonl       (TrainingEvents from the review session)
  └── manifest.json           (consent, anonymization log, hash chain)
```

## Reviewer-correction stream

Every confirmed `ReviewEvent` produces zero or more `TrainingEvent` rows that feed the active learning loop. This is described in `ACTIVE_LEARNING_SPEC.md`. The data lives in:

- Postgres `training_events` table (metadata, source of truth)
- MinIO `training-artifacts/` bucket (image tiles, masks, label files)

## Held-out evaluation set

We maintain a frozen "golden" test set of 100 P&IDs that **never** enters training. Composition target:

- 40 sheets from PID2Graph (real, public, graph-annotated)
- 40 sheets anonymized from at least 3 different paying clients
- 20 synthetic sheets representing edge cases (very high density, unusual symbol sets, scanned-paper noise)

Models cannot ship unless they meet the metrics in `PROJECT_VISION.md` on this set. See the eval harness in `training/eval/run.py`.

## What we do NOT use

- We do NOT scrape P&IDs from the web. Most are confidential and the legal position is shaky.
- We do NOT use any dataset whose license is unclear. If a contributor offers us data, we get a signed release first.
- We do NOT use ImageNet pre-trained weights for the line segmenter. Synthetic P&ID pre-training works better.
- We do NOT mix client data across clients in a way that would let one client's patterns leak into another's results. Per-client LoRA adapters keep client-specific styles isolated.

## Storage estimates

For planning the on-prem hardware spec:

| Data | Per sheet | At 10,000 sheets |
|---|---|---|
| Source PNG (A1 at 600 DPI) | ~25 MB | 250 GB |
| Tiles (640x640 PNG, 20% overlap) | ~80 MB | 800 GB |
| Annotation JSON | ~50 KB | 500 MB |
| TrainingEvent artifacts per sheet | ~5 MB | 50 GB |

A 4 TB NVMe + 16 TB HDD configuration handles roughly 50,000 sheets with headroom for two model versions and exports. Most clients will not exceed 10,000 sheets in v1.
