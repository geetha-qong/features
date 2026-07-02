# `data/` — fixtures & symlinks

This folder is **gitignored** (except this README and `.gitkeep`). Don't commit job artefacts here.

## Convention

```
data/
├── README.md          ← this file
├── jobs/              ← symlinks per job:  jobs/41 → ../../../job_outputs/{org_id}/41
├── samples/           ← curated test PDFs (small, < 5 MB), for notebook fixtures
└── ground_truth/      ← hand-labelled graphs (JSON) for is_isomorphic evaluation
```

## Adding a job for experiments

```bash
# from experiments/digital_twin/
ln -s ../../job_outputs/<org-uuid>/41 data/jobs/41
```

Or if jobs ≤ 39 (pre-org-scoping):

```bash
ln -s ../../job_outputs/41 data/jobs/41
```

## Why symlinks (not copies)

- Job artefacts are tens to hundreds of MB. Copying duplicates storage.
- Symlinks track the live state — if a job is re-run on the team's side, our notebook reflects it.
- Symlinks don't get committed (the `.gitignore` ignores `data/*` except this README + `.gitkeep`).
