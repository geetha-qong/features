# Graph Ground-Truth Anchor & Scoring Harness — Design

**Date:** 2026-06-26
**Status:** Approved (brainstorming), pending implementation plan
**Author:** session 2026-06-26 (graph topology measurement)
**Related:** FEATURES #65/#66 (graph fixed end-to-end), `docs/superpowers/specs/2026-06-05-graph-extraction-design.md`, `docs/superpowers/specs/2026-06-17-self-learning-loop-design.md` (Phase 2 eval gate)

## Problem

The graph extraction pipeline (`webapp/graph/`) now produces a reasonable per-job
graph (job 43: 128 nodes / 155 edges, 92% connected after #66). But **topology is
spot-checked, not measured** — there is no ground-truth graph anywhere, so we cannot
answer "did this change make the graph more or less correct?" objectively.

CLAUDE.md names the long-term headline metric as graph isomorphism
(`networkx.is_isomorphic`) vs human ground truth. The Self-Learning Loop Phase 2
eval gate (gated retrain) is **blocked on this**: it must compare a candidate model's
graph against a frozen ground truth and refuse to promote if topology regresses.

This spec delivers the **measurement foundation**: a frozen ground-truth graph for
one anchor job plus a reusable scoring harness. It does **not** change extraction.

## Goals

1. Freeze a human-verified ground-truth graph for one anchor job (**job 43**).
2. A pure, importable scoring module that aligns an extracted graph to the ground
   truth and reports graded edge F1 + a strict `is_isomorphic` gate.
3. A thin CLI to score any job against its ground truth and print a report.
4. Be reusable by the Phase 2 eval gate (programmatic import, no DB, no CLI).

## Non-Goals (explicit, deferred follow-ups)

- **Cross-tile pipe stitching** — only build it if the metric shows the seam gap is
  lossy. Deferred until measured. (The gap lives in the chunked LLM fallback path,
  `fallback.py:_select_nodes_in_tile`; the CV tracer already traces the full page.)
- **A Studio ground-truth editor UI** — GT is hand-corrected JSON for now.
- **Multiple anchor jobs** — one job (43) first; the format generalizes to more later.
- **Changing the extraction pipeline** in any way.

## Decisions (locked in brainstorming)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Sequencing | GT + metric **first**; stitch later | Can't validate a stitch fix without a metric; avoid building unmeasurable fixes |
| GT authoring | **Seed-from-extraction, hand-correct JSON** | Leverages the 92%-connected graph; far less effort than authoring 128 nodes from scratch |
| GT storage | **Frozen versioned JSON in the repo** | git diff/PR review is exactly the audit trail a ground truth needs |
| Metric | **Node-aligned graded edge F1** + strict `is_isomorphic` boolean | F1 gives the gradient to track progress; boolean is the "perfect" gate; pure structural isomorphism is meaningless for P&IDs |
| Anchor job | **Job 43** | Healed, #66-validated, highest-quality current graph |
| Reuse | Logic in importable module, CLI is a thin wrapper | Phase 2 eval gate must call scoring programmatically |

## Architecture

```
Frozen GT (tests/graph_ground_truth/job_43.json)  ─┐
                                                    ├─→ scoring.align_nodes() ─→ node map + unmatched
job_outputs/.../canonical_graph.json (extracted) ──┘                │
                                                                    ▼
                                              scoring.score_graph() ─→ GraphScore
                                                                    │
                              ┌─────────────────────────────────────┼───────────────────────────────┐
                         CLI report (human)              JSON (--json)             Phase 2 eval gate (imports score_graph)
```

### Components

#### 1. Frozen ground truth — `tests/graph_ground_truth/job_43.json`

Same `JobGraph` shape the pipeline emits (see `assembler.py`), so it round-trips with
no translation:

- `nodes`: `node_id`, `entity_id`, `tag`, `class`, `bbox`
- `edges`: `source`, `target`, optional `directed` (bool) + `direction` if known
- `meta` block (new, GT-only): `source_job_id`, `source_commit`, `source_model`,
  `authored_by`, `frozen_at` (Z-suffixed ISO-8601), `notes`

**Authoring workflow (documented, mostly manual):**
1. Seed: copy job 43's current `canonical_graph.json` → `tests/graph_ground_truth/job_43.json`
   (via the CLI `--seed` flag; see below). Job 43's graph lives on the dev box — pull
   it down (SSM/ORM read of `Job.output...` dir) during implementation.
2. A human edits the seeded file: add missing edges, delete wrong edges, fix node
   tags. Fill the `meta` block.
3. Commit the frozen file. Changes to it are reviewable in PRs.

#### 2. Scoring module — `webapp/graph/scoring.py` (pure, DB-free, importable)

Mirrors the rest of `webapp/graph/`: no SQLAlchemy, lazy-imports heavy deps.

- `align_nodes(extracted_nodes, gt_nodes, *, iou_threshold=0.5, centroid_px=None) -> NodeAlignment`
  - **Cascade, first match wins, each GT node matched at most once:**
    1. `entity_id` exact
    2. `tag` exact (non-empty)
    3. spatial: centroid distance ≤ `centroid_px` (defaults to a fraction of page
       diagonal), tiebreak by best bbox-IoU ≥ `iou_threshold`
  - Returns `{extracted_id: gt_id}` + `unmatched_extracted` + `unmatched_gt`.
- `score_graph(extracted_graph, gt_graph) -> GraphScore`
  - **node** precision / recall / F1 (matched vs unmatched)
  - **undirected edge** precision / recall / F1 — headline. Edges compared as a set of
    frozenset(aligned source, aligned target) pairs; an extracted edge counts only if
    both endpoints aligned to GT nodes.
  - **directed agreement** — over the subset of edges where GT sets a direction:
    fraction the extraction orients identically (secondary; never affects headline).
  - **`is_isomorphic`** — `networkx.is_isomorphic` with `node_match` on (tag or class).
    The strict "perfect" gate. Wrapped so a slow/pathological call returns `False`,
    never raising.
  - **connectivity** — connected-component count + largest-component fraction for both.
  - **`missing_edges` / `extra_edges`** — explicit lists (GT-id pairs) for debugging.

`GraphScore` is a dataclass/NamedTuple, JSON-serializable.

#### 3. CLI — `webapp/scripts/score_graph.py`

`python -m webapp.scripts.score_graph --job-id 43 [--graph PATH] [--gt PATH] [--json] [--seed]`

- Resolves the extracted graph from `--graph` or the job's output dir `canonical_graph.json`.
- Resolves GT from `--gt` or `tests/graph_ground_truth/job_{id}.json`.
- `--seed`: copies the resolved extracted graph to the GT path (starting point for
  hand-correction) and exits — does not score.
- Prints a readable report; `--json` emits the `GraphScore` as JSON for piping.
- Non-zero exit + clear message on missing/malformed GT or extracted graph.

## Data flow & alignment detail

Alignment runs extracted→GT. Edges are then compared as **sets of aligned node-id
pairs**: an extracted edge `(a,b)` becomes `frozenset(map[a], map[b])`; if either
endpoint is unaligned the edge is dropped from the comparison (and its unaligned
endpoints already count against node recall/precision). Set intersection with GT
edges gives TP; GT-only = FN (missing); extracted-only = FP (extra).

The **anchor-job sanity case**: because the GT is seeded from a specific extraction,
scoring *that same* extraction against the GT must yield F1 = 1.0 and `is_isomorphic`
True before any human edits. After human edits the score drops by exactly the edits —
a useful self-check that the harness is wired correctly.

## Error handling

Pure module never raises on bad graph data. CLI converts missing/malformed inputs into
a non-zero exit with a clear message. `is_isomorphic` is wrapped (try/except + the
graded scores are computed independently), defaulting the boolean to `False` so it
never blocks the gradient metrics or the Phase 2 gate.

## Testing — `tests/unit/test_graph_scoring.py`

Synthetic small graphs (NOT job 43):

- Perfect copy → node & edge F1 = 1.0, `is_isomorphic` True
- One missing edge → recall < 1, precision = 1
- One extra edge → precision < 1, recall = 1
- Tag-renamed node → alignment falls through to spatial, still matches
- Untagged node pair matched by centroid; beyond threshold → unmatched (counts FN/FP)
- Reversed directed edge → undirected F1 unaffected; directed agreement drops
- Empty extracted graph → recall 0, no crash
- Missing/malformed GT file (CLI-level) → non-zero exit, clear message

Run via the container (`docker run --rm -v $(pwd):/app … qong_poc-web:latest
python3 -m pytest tests/unit/test_graph_scoring.py`) — local host is Py3.9 and can't
collect routers.

## Dependencies

`networkx` is already in `requirements.txt` (used by `assembler.py`, `orient.py`) — no
new dependency. Verify import availability in the container during implementation.

## Acceptance criteria

1. `tests/graph_ground_truth/job_43.json` exists, hand-corrected, with a filled `meta` block.
2. `webapp/graph/scoring.py` exposes `align_nodes` + `score_graph` returning a
   JSON-serializable `GraphScore`; no DB import.
3. `python -m webapp.scripts.score_graph --job-id 43` prints node F1, undirected edge
   F1, directed agreement, `is_isomorphic`, connectivity, and missing/extra edge lists.
4. `--seed` produces a valid GT starting point.
5. New unit tests pass; full suite stays green.
6. FEATURES.md entry recording the metric definition + the frozen GT's provenance.

## Follow-ups (out of scope here)

- Measure job 43's current graph against the frozen GT; if cross-tile seam loss is
  material, design the stitch pass (merge tile-local fallback edges across seams).
- Extend ground truth to more jobs (1/38/39/41/42) once the format proves out.
- Wire `score_graph` into the Phase 2 gated-retrain eval gate.
