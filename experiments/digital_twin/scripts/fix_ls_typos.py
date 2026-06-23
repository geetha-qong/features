"""
Fix two LS label typos on dev:
  valve_3way_releif → valve_3way_relief  (3 results in 1 annotation, project 19)
  valve_pnuectrl    → valve_pneuctrl      (16 results in 15 annotations, project 25)
                                          (28 project label_configs)

Idempotent: re-running finds zero remaining occurrences and exits clean.

Run from repo root with DEV_LS_ACCESS in env (refresh token exchanged first).
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
import urllib.error
from collections import defaultdict

ACCESS = os.environ.get("DEV_LS_ACCESS")
if not ACCESS:
    sys.exit("Set DEV_LS_ACCESS in env (refresh-exchange first).")

BASE = "https://ls-dev.qongsystems.com"
H_GET = {
    "Authorization": f"Bearer {ACCESS}",
    "User-Agent": "qong/1.0",
    "Accept": "application/json",
}
H_PATCH = {**H_GET, "Content-Type": "application/json"}

TYPOS = {
    "valve_3way_releif": "valve_3way_relief",
    "valve_pnuectrl": "valve_pneuctrl",
}


def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=H_GET), timeout=60))


def patch(url, body):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=H_PATCH,
        method="PATCH",
    )
    return json.load(urllib.request.urlopen(req, timeout=60))


def rewrite_value(val: dict) -> bool:
    """Mutate a result.value dict to replace typo labels. Return True if changed."""
    changed = False
    for key in ("rectanglelabels", "labels"):
        if key in val and isinstance(val[key], list):
            new = []
            for L in val[key]:
                if L in TYPOS:
                    new.append(TYPOS[L])
                    changed = True
                else:
                    new.append(L)
            val[key] = new
    return changed


def fix_annotations(projects):
    """Find every annotation that uses a typo label and PATCH it with corrected labels."""
    touched = 0
    typo_annotations = defaultdict(list)  # ann_id -> list of typos found
    # Walk every project's tasks once
    for p in projects:
        pid = p["id"]
        page = 1
        while True:
            tasks = get(f"{BASE}/api/tasks/?project={pid}&page={page}&page_size=200&fields=all")
            tlist = tasks.get("tasks", tasks) if isinstance(tasks, dict) else tasks
            if not tlist:
                break
            for t in tlist:
                for ann in t.get("annotations", []):
                    ann_changed = False
                    new_result = []
                    for r in ann.get("result", []) or []:
                        if "value" in r:
                            if rewrite_value(r["value"]):
                                ann_changed = True
                        new_result.append(r)
                    if ann_changed:
                        ann_id = ann["id"]
                        try:
                            patch(f"{BASE}/api/annotations/{ann_id}/", {"result": new_result})
                            touched += 1
                            print(f"  patched annotation {ann_id} (project {pid}, task {t['id']})")
                        except urllib.error.HTTPError as e:
                            print(f"  FAIL annotation {ann_id}: HTTP {e.code} {e.reason}")
            if len(tlist) < 200:
                break
            page += 1
    return touched


def fix_label_configs(projects):
    """Find every project label_config that contains a typo label name and PATCH it."""
    touched = 0
    for p in projects:
        cfg = p.get("label_config", "") or ""
        new_cfg = cfg
        for typo, canonical in TYPOS.items():
            # Only replace the value attribute on Label tags
            if f'value="{typo}"' in new_cfg:
                new_cfg = new_cfg.replace(f'value="{typo}"', f'value="{canonical}"')
        if new_cfg != cfg:
            try:
                patch(f"{BASE}/api/projects/{p['id']}/", {"label_config": new_cfg})
                touched += 1
                print(f"  patched label_config on project {p['id']}: {p.get('title', '')[:40]}")
            except urllib.error.HTTPError as e:
                print(f"  FAIL project {p['id']}: HTTP {e.code} {e.reason}")
    return touched


def main():
    projs = get(f"{BASE}/api/projects/?page_size=200")
    projs = projs.get("results", projs) if isinstance(projs, dict) else projs
    print(f"Scanning {len(projs)} projects\n")

    print("== Phase A: Fix annotations using typo labels ==")
    n_ann = fix_annotations(projs)
    print(f"  → {n_ann} annotations patched\n")

    print("== Phase B: Fix project label_configs containing typo labels ==")
    # Re-fetch (label_config may have been updated by the user mid-script)
    projs = get(f"{BASE}/api/projects/?page_size=200")
    projs = projs.get("results", projs) if isinstance(projs, dict) else projs
    n_cfg = fix_label_configs(projs)
    print(f"  → {n_cfg} project configs patched\n")

    print("== Verification: searching for any remaining typo occurrences ==")
    projs = get(f"{BASE}/api/projects/?page_size=200")
    projs = projs.get("results", projs) if isinstance(projs, dict) else projs
    remaining_cfg = 0
    remaining_ann = 0
    for p in projs:
        cfg = p.get("label_config", "") or ""
        for typo in TYPOS:
            if f'value="{typo}"' in cfg:
                remaining_cfg += 1
                print(f"  config still has {typo}: project {p['id']}")
    # Re-walk tasks (we could trust the patch, but the user wanted us to be careful)
    for p in projs:
        pid = p["id"]
        page = 1
        while True:
            tasks = get(f"{BASE}/api/tasks/?project={pid}&page={page}&page_size=200&fields=all")
            tlist = tasks.get("tasks", tasks) if isinstance(tasks, dict) else tasks
            if not tlist:
                break
            for t in tlist:
                for ann in t.get("annotations", []):
                    for r in ann.get("result", []) or []:
                        for L in (r.get("value", {}).get("rectanglelabels") or []) + (r.get("value", {}).get("labels") or []):
                            if L in TYPOS:
                                remaining_ann += 1
                                print(f"  annotation {ann['id']} still has {L}")
            if len(tlist) < 200:
                break
            page += 1

    if remaining_cfg == 0 and remaining_ann == 0:
        print("  CLEAN — no remaining typo occurrences.")
    else:
        print(f"  REMAINING: {remaining_cfg} configs, {remaining_ann} annotations")
        sys.exit(2)


if __name__ == "__main__":
    main()
