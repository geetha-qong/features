# Graph Ground-Truth Scoring Harness

Measure how *topologically correct* an extracted P&ID process graph is, against a
frozen human-verified ground truth — instead of eyeballing node/edge counts.

> **Status:** harness shipped (FEATURES #67, branch `feat/graph-ground-truth-scoring`).
> The job-43 ground truth is **seeded but not yet human-verified** — see
> [Ground-truth workflow](#ground-truth-workflow).

---

## Why this exists

The process graph (`webapp/graph/`) is built from YOLO detections (`Job.gpu_detections`)
→ nodes, plus an OpenCV line tracer + an LLM fallback → edges. After FEATURES #65/#66
job 43's graph went from 7 nodes / 4 edges to **128 nodes / 155 edges** — but "is that
*correct*?" had no objective answer. Topology was spot-checked, never measured.

This harness provides the measurement:

- **For us, now:** quantify the error in the current extraction (what edges are missing
  or wrong vs a human truth) and catch topology regressions when we change the pipeline.
- **For Self-Learning Phase 2 (gated retrain):** the eval gate must refuse to promote a
  retrained model if it makes the graph *worse*. `score_graph()` is the topology half of
  that gate — it's a pure, importable function with no DB dependency for exactly this
  reason.

CLAUDE.md names the long-term headline metric as graph isomorphism
(`networkx.is_isomorphic`) vs human ground truth. This is its first implementation.

---

## What's in the box

| File | Responsibility |
|------|----------------|
| `webapp/graph/scoring.py` | Pure, DB-free scoring: node alignment + graph scoring. Importable by Phase 2. |
| `webapp/scripts/score_graph.py` | Thin CLI wrapper around the module. |
| `tests/graph_ground_truth/job_43.json` | The frozen ground-truth graph for the anchor job (job 43). |
| `tests/unit/test_graph_scoring.py` | 19 unit tests (alignment cascade, scoring math, CLI). |

The ground truth uses the **same on-disk shape** the pipeline already emits
(`assembler.assemble`): nodes keyed by `id` with `entity_id`/`tag`/`class`/`bbox`; edges
with `source`/`target`/`directed`. Plus a GT-only `meta` block (provenance + verification
status).

---

## How scoring works

### 1. Node alignment (`align_nodes`)

An extracted graph and the ground truth don't share node IDs (a re-run, or a different
model, produces fresh IDs). So before comparing edges we map extracted nodes → GT nodes
with a **first-match-wins cascade**, each GT node used at most once:

1. **`entity_id` exact** — same canonical entity.
2. **`tag` exact** — same instrument tag (e.g. `FT-101`), for nodes with a tag but no
   entity match.
3. **Spatial** (for the ~84 untagged nodes), two ordered sub-passes:
   a. highest **IoU ≥ `iou_threshold`** (default 0.5), else
   b. **nearest centroid ≤ `centroid_px`**.

Unmatched extracted nodes count as false positives; unmatched GT nodes as false negatives.

### 2. Graph score (`score_graph` → `GraphScore`)

| Metric | What it tells you |
|--------|-------------------|
| **node** precision / recall / F1 | Did we find the right components? |
| **undirected edge** precision / recall / F1 | **The headline.** Is "A connects to B" correct? Edges are compared as `frozenset` pairs in GT-id space; an extracted edge counts only if *both* endpoints aligned. |
| **directed agreement** | *Secondary.* Of GT edges that carry a flow direction and are present, the fraction oriented the same way. `None` if GT has no directed edges. **Never affects undirected F1.** |
| **`is_isomorphic`** | The strict "are we topologically perfect (with labels)" gate — `networkx.is_isomorphic` with a tag/class `node_match`. Wrapped so it never raises. |
| **connectivity** | Connected-component count + largest-component fraction, for both graphs. |
| **`missing_edges` / `extra_edges`** | Explicit GT-id pair lists for debugging exactly what's wrong. |

Graded F1 gives you the *gradient* (slightly better vs much better); `is_isomorphic` is
the binary gate. Pure structural isomorphism alone would be meaningless for a P&ID — two
unrelated drawings can share a shape — which is why node identity drives the comparison.

---

## CLI usage

```bash
# Score job 43's current graph against its frozen ground truth (human-readable report)
python -m webapp.scripts.score_graph --job-id 43

# Explicit paths (e.g. scoring a freshly re-extracted graph from a tmp location)
python -m webapp.scripts.score_graph --job-id 43 \
    --graph /tmp/new_extraction.json \
    --gt tests/graph_ground_truth/job_43.json

# Machine-readable output (for piping into the Phase 2 gate or a dashboard)
python -m webapp.scripts.score_graph --job-id 43 --json

# Seed a NEW ground truth from a job's current extraction (starting point to hand-correct)
python -m webapp.scripts.score_graph --job-id 43 --graph /tmp/extraction.json --seed
```

The CLI resolves the extracted graph by globbing `job_outputs` (handles both the flat
`≤39` layout and the org-scoped `≥40` layout) unless `--graph` is given. It is **DB-free** —
run it from the repo root.

Sample report:

```
Graph score — job 43
  nodes: P=1.000 R=1.000 F1=1.000 (tp=128 fp=0 fn=0)
  edges (undirected): P=1.000 R=1.000 F1=1.000 (tp=155 fp=0 fn=0)
  directed_agreement: n/a
  is_isomorphic: True
  connectivity: extracted 36 comp / largest 0.11  |  gt 36 comp / largest 0.11
  missing_edges: 0   extra_edges: 0
```

---

## Ground-truth workflow

A ground truth must be **human-verified** — but authoring 128 nodes / 155 edges from
scratch is brutal, so we **seed from an extraction and correct it**:

1. **Seed** — `--seed` copies a job's current `canonical_graph.json` into
   `tests/graph_ground_truth/job_{id}.json`. (Job 43 is already seeded.)
2. **Correct (human)** — open the file, review against the source P&ID, **add missing
   edges** (especially pipes crossing tile seams), **delete wrong edges**, **fix node
   tags**. Fill `meta.authored_by` / `meta.frozen_at` and set `meta.status = "verified"`.
3. **Commit** — the file lives in git, so every change to "truth" is reviewable in a PR.

> **Self-check oracle:** scoring an *un-corrected* seed against itself is trivially
> perfect (F1 = 1.0) by construction. So if the harness ever reports 1.0 on an *edited*
> GT, the bug is in the scorer, not the data.

---

## Current status & findings (job 43)

- Harness self-check on the real 128-node graph: node/edge **F1 = 1.000**,
  **`is_isomorphic` = True**, in **0.3s** — confirms `is_isomorphic` scales fine to this
  size (no need for the graph-edit-distance fallback we'd worried about).
- **Job 43 is 36 connected components, largest only 0.11** (~14 nodes). Note this differs
  from FEATURES #66's "92% connected" — that figure counted *non-floating* nodes (118/128
  have ≥1 edge), not graph connectivity. The graph is wired but **fragmented**, which is
  the first quantitative fingerprint of the **cross-tile seam gap** (per-tile LLM edge
  calls can't connect a node in one tile to a node in another). This is the signal that
  will justify (or not) the deferred cross-tile stitch pass — confirmed once the GT is
  hand-corrected.

---

## Follow-ups (deferred)

Before Phase 2 wires `score_graph` in as the eval gate:

1. **Hand-correct the job-43 GT** (the one outstanding human step) → then **measure the
   seam gap** (edge-recall drop vs the corrected GT).
2. **Calibrate `centroid_px`** — currently hardcoded to 40 px, but job-43 coords run to
   ~10000 px, so the spatial fallback barely fires. Fine for the seed-from-extraction
   anchor (entity_id/tag carry alignment), but too strict for a *different* model's
   shifted bboxes. Plumb page dimensions through so it can be a fraction of the page
   diagonal.
3. **Add a cross-run test** where extracted IDs ≠ GT IDs (the real Phase-2 case; logic is
   verified correct by trace but not yet by a test).

Larger follow-ups: **cross-tile pipe stitching** (if the measured seam gap is material),
extending ground truth to more jobs (1/38/39/41/42), and untagged-node dedup.

---

## Testing

```bash
# In the container (full suite; local host is Py3.9 and can't collect routers)
docker run --rm -v $(pwd):/app qong_poc-web:latest python3 -m pytest tests/unit/test_graph_scoring.py -v

# On the host (scoring.py is pure; needs networkx, already a dependency)
SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") \
    python3 -m pytest tests/unit/test_graph_scoring.py -v
```

---

## References

- Design spec: [`docs/superpowers/specs/2026-06-26-graph-ground-truth-scoring-design.md`](superpowers/specs/2026-06-26-graph-ground-truth-scoring-design.md)
- Implementation plan: [`docs/superpowers/plans/2026-06-26-graph-ground-truth-scoring.md`](superpowers/plans/2026-06-26-graph-ground-truth-scoring.md)
- Decision log: `FEATURES.md` #67 (and #65/#66 for the graph fixes this builds on)
- Graph pipeline overview: `docs/claude/pipeline.md`
