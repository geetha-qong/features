"""Sync the canonical labeling config (scripts/ls_label_config.xml) into every
Label Studio project: adds missing labels, preserves existing annotations.

Usage (on dev VM):
    python3 scripts/ls_sync_labels.py            # dry-run, shows what would change
    python3 scripts/ls_sync_labels.py --apply    # actually update LS projects

Run after editing ls_label_config.xml whenever you add or rename a label.

Behaviour:
- For each existing project, adds any canonical <Label> missing from its config
  (keeping the canonical color and ordering near the end of RectangleLabels).
- Does NOT remove labels from a project that aren't in canonical — use
  scripts/ls_cleanup.py for that.
- Existing annotations are preserved (LS keeps the bounding boxes; only the
  label list in the config changes).
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

LS_URL = os.environ.get("LS_URL", "http://localhost:8080").rstrip("/")
CANONICAL_CFG = Path(__file__).resolve().parent / "ls_label_config.xml"


def parse_canonical_labels(xml_text: str):
    """Return list of (value, background_color) tuples in canonical order."""
    return re.findall(r'<Label\s+value="([^"]+)"\s+background="([^"]+)"\s*/>', xml_text)


def parse_project_labels(cfg: str):
    """Return set of label values currently in a project's config."""
    return set(re.findall(r'<Label\s+[^/]*value="([^"]+)"[^/]*/>', cfg))


def insert_labels(cfg: str, missing: list) -> str:
    """Insert missing <Label> elements just before </RectangleLabels>."""
    new_lines = "\n".join(
        f'    <Label value="{v}" background="{c}"/>' for v, c in missing
    )
    return re.sub(
        r"(\s*)</RectangleLabels>",
        f"\n{new_lines}\n\\1</RectangleLabels>",
        cfg,
        count=1,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually PATCH LS (default: dry-run)")
    args = ap.parse_args()

    key = os.environ.get("LS_API_KEY", "")
    if not key:
        # Fall back to .env on VM
        env_path = Path("/app/qong_poc/.env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("LS_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    if not key:
        sys.exit("LS_API_KEY not set (env or /app/qong_poc/.env)")

    if not CANONICAL_CFG.exists():
        sys.exit(f"Canonical config not found: {CANONICAL_CFG}")

    canonical_xml = CANONICAL_CFG.read_text()
    canonical_labels = parse_canonical_labels(canonical_xml)
    canonical_names = {v for v, _ in canonical_labels}
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN (no changes)'}")
    print(f"Canonical labels ({len(canonical_labels)}): {sorted(canonical_names)}\n")

    H = {"Authorization": f"Token {key}", "Content-Type": "application/json"}
    req = urllib.request.Request(f"{LS_URL}/api/projects/?page_size=100", headers=H)
    projects = json.load(urllib.request.urlopen(req))
    projects = projects.get("results", projects) if isinstance(projects, dict) else projects

    n_changed = 0
    for p in sorted(projects, key=lambda x: x["id"]):
        pid = p["id"]
        full = json.load(urllib.request.urlopen(
            urllib.request.Request(f"{LS_URL}/api/projects/{pid}/", headers=H)
        ))
        cfg = full.get("label_config", "")
        if not cfg or "<RectangleLabels" not in cfg:
            print(f"  proj {pid}: not a rectangle-labels project — skipped")
            continue

        present = parse_project_labels(cfg)
        missing = [(v, c) for v, c in canonical_labels if v not in present]
        extra = present - canonical_names

        if not missing and not extra:
            continue

        title = p.get("title", "")[:40]
        print(f"Project {pid} ({title!r}):")
        if missing:
            print(f"  + ADD: {[v for v, _ in missing]}")
        if extra:
            print(f"  ! EXTRA (not in canonical, left alone): {sorted(extra)}")

        if missing and args.apply:
            new_cfg = insert_labels(cfg, missing)
            payload = json.dumps({"label_config": new_cfg}).encode()
            patch = urllib.request.Request(
                f"{LS_URL}/api/projects/{pid}/",
                data=payload, headers=H, method="PATCH"
            )
            try:
                urllib.request.urlopen(patch)
                print(f"  ✓ updated")
                n_changed += 1
            except urllib.error.HTTPError as e:
                print(f"  ✗ FAILED: HTTP {e.code} — {e.read().decode()[:200]}")
        elif missing:
            n_changed += 1

    print(f"\nDone. {n_changed} projects {'updated' if args.apply else 'would be updated'}.")


if __name__ == "__main__":
    main()
