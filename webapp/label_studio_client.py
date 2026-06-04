"""Label Studio API client — push P&ID tiles as annotation tasks."""
import base64
import json
import os
import re
import time
import threading
from collections import defaultdict
from pathlib import Path
from typing import List, Optional
import requests

LS_URL = os.environ.get("LS_URL", "http://localhost:8080").rstrip("/")
LS_API_KEY = os.environ.get("LS_API_KEY", "")
# Browser-accessible LS URL (for links shown to users). Default: direct port access.
LS_EXTERNAL_URL = os.environ.get("LS_EXTERNAL_URL", "http://localhost:9001").rstrip("/")

LABEL_CONFIG = """<View>
  <Image name="image" value="$image"/>
  <RectangleLabels name="label" toName="image">
    <Label value="valve_bf"            background="#FF6B6B"/>
    <Label value="valve_bv"            background="#4ECDC4"/>
    <Label value="valve_db"            background="#45B7D1"/>
    <Label value="valve_ck"            background="#96CEB4"/>
    <Label value="valve_gl"            background="#FFEAA7"/>
    <Label value="valve_cv"            background="#DDA0DD"/>
    <Label value="valve_gen"           background="#98D8C8"/>
    <Label value="actuator_motor"      background="#FFB347"/>
    <Label value="actuator_pneumatic"  background="#87CEEB"/>
    <Label value="actuator_solenoid"   background="#F0E68C"/>
    <Label value="inst_field"          background="#FFA39E"/>
    <Label value="interlock"           background="#D4380D"/>
    <Label value="DCS"                 background="#FFC069"/>
    <Label value="PLC"                 background="#AD8B00"/>
    <Label value="Motor"               background="#D3F261"/>
    <Label value="Pump/Dwg Pump"       background="#389E0D"/>
    <Label value="inst_field-R"        background="#5CDBD3"/>
    <Label value="interlock-R"         background="#096DD9"/>
  </RectangleLabels>
</View>"""


def _looks_like_jwt(s: str) -> bool:
    return s.startswith("eyJ") and s.count(".") == 2


# LS 1.23+ replaced the legacy "Token <key>" auth with JWT. The Personal Access
# Token shown in the LS UI is a *refresh* token — you have to POST it to
# /api/token/refresh/ to get a short-lived (~5 min) access token, then send
# THAT as `Bearer …` to the real API. We cache the access token until ~60s
# before its iat-derived expiry to avoid a round-trip on every call.
#
# If LS_API_KEY is a non-JWT string (legacy LS deployments < 1.23), we send it
# as `Token <key>` directly — no exchange.
_access_token: Optional[str] = None
_access_token_exp: float = 0.0
_access_lock = threading.Lock()


def _refresh_access_token() -> Optional[str]:
    """Exchange the refresh-JWT in LS_API_KEY for a short-lived access JWT.
    Caches the result in module globals; subsequent calls inside the validity
    window are O(1). Returns None on any failure (caller falls back to no-op)."""
    global _access_token, _access_token_exp
    try:
        resp = requests.post(
            f"{LS_URL}/api/token/refresh/",
            json={"refresh": LS_API_KEY},
            timeout=5,
        )
        if resp.status_code != 200:
            print(f"[label_studio] token-refresh failed {resp.status_code}: {resp.text[:200]}")
            return None
        access = resp.json().get("access")
        if not access:
            return None
        # Decode the access JWT's payload for `exp`; tolerate missing exp.
        try:
            payload_b64 = access.split(".")[1] + "==="  # pad for safety
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            exp = float(payload.get("exp", time.time() + 240))
        except Exception:
            exp = time.time() + 240  # 4-min default if decode fails
        _access_token = access
        _access_token_exp = exp - 60  # refresh 60s before real expiry
        return access
    except Exception as e:
        print(f"[label_studio] token-refresh error: {e!r}")
        return None


def _headers() -> dict:
    if _looks_like_jwt(LS_API_KEY):
        with _access_lock:
            now = time.time()
            tok = _access_token if _access_token and now < _access_token_exp else _refresh_access_token()
        if not tok:
            # Send the refresh as Bearer anyway — some LS endpoints accept it.
            tok = LS_API_KEY
        return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    # Legacy LS or non-JWT API key — send as Token header.
    return {"Authorization": f"Token {LS_API_KEY}", "Content-Type": "application/json"}


def is_configured() -> bool:
    return bool(LS_API_KEY)


def get_or_create_project(pid_no: str) -> Optional[int]:
    """Return existing Label Studio project id for this P&ID or create a new one."""
    if not is_configured():
        return None
    try:
        resp = requests.get(f"{LS_URL}/api/projects/", headers=_headers(), timeout=5)
        if resp.status_code == 200:
            for proj in resp.json().get("results", []):
                if proj["title"] == pid_no:
                    return proj["id"]
        # Create new project
        resp = requests.post(
            f"{LS_URL}/api/projects/",
            headers=_headers(),
            json={"title": pid_no, "label_config": LABEL_CONFIG},
            timeout=10,
        )
        if resp.status_code == 201:
            return resp.json()["id"]
    except Exception as e:
        print(f"[label_studio] get_or_create_project error: {e}")
    return None


def delete_all_tasks(project_id: int) -> bool:
    """Delete all tasks in a project (so re-sync replaces stale image URLs)."""
    if not is_configured():
        return False
    try:
        resp = requests.delete(
            f"{LS_URL}/api/projects/{project_id}/tasks/",
            headers=_headers(),
            timeout=15,
        )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[label_studio] delete_all_tasks error: {e}")
    return False


def push_tiles(project_id: int, tile_urls: list) -> int:
    """Push tile image URLs as tasks. Returns count of tasks created."""
    if not is_configured():
        return 0
    try:
        tasks = [{"data": {"image": url}} for url in tile_urls]
        resp = requests.post(
            f"{LS_URL}/api/projects/{project_id}/import",
            headers=_headers(),
            json=tasks,
            timeout=30,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            # LS returns a dict like {"task_count": N, ...}, not a list
            return data.get("task_count", len(tile_urls)) if isinstance(data, dict) else len(data)
    except Exception as e:
        print(f"[label_studio] push_tiles error: {e}")
    return 0


def sync_all_label_configs(source_project_id: int = 1) -> dict:
    """Copy the label config from source_project_id to every other project.

    Returns {"updated": [...], "skipped": [...], "failed": [...]}
    """
    if not is_configured():
        return {"updated": [], "skipped": [], "failed": []}
    try:
        src = requests.get(f"{LS_URL}/api/projects/{source_project_id}/", headers=_headers(), timeout=10)
        if src.status_code != 200:
            return {"updated": [], "skipped": [], "failed": [f"source project {source_project_id} not found"]}
        label_config = src.json()["label_config"]

        all_projects = []
        url = f"{LS_URL}/api/projects/?page_size=100"
        while url:
            r = requests.get(url, headers=_headers(), timeout=10)
            data = r.json()
            all_projects.extend(data.get("results", []))
            url = data.get("next")

        updated, skipped, failed = [], [], []
        for p in all_projects:
            if p["id"] == source_project_id or p.get("label_config") == label_config:
                skipped.append(p["id"])
                continue
            r = requests.patch(
                f"{LS_URL}/api/projects/{p['id']}/",
                headers=_headers(),
                json={"label_config": label_config},
                timeout=10,
            )
            (updated if r.status_code in (200, 201) else failed).append(p["id"])
        return {"updated": updated, "skipped": skipped, "failed": failed}
    except Exception as e:
        print(f"[label_studio] sync_all_label_configs error: {e}")
        return {"updated": [], "skipped": [], "failed": [str(e)]}


_TILE_RE = re.compile(r'tile_p(\d+)_r(\d+)_c(\d+)')


def push_predictions(project_id: int, detections: List[dict], job_dir: Path) -> int:
    """Push GPU worker detections as pre-annotation predictions to LS tasks.

    Matches each detection to the correct task by parsing tile coordinates from the
    task image URL, then POSTs a prediction with percentage-based bbox coordinates.
    Returns the number of predictions successfully posted.
    """
    if not is_configured() or not project_id:
        return 0
    try:
        resp = requests.get(
            f"{LS_URL}/api/tasks/?project={project_id}&page_size=500",
            headers=_headers(), timeout=15,
        )
        if resp.status_code != 200:
            return 0
        payload = resp.json()
        tasks = payload.get("tasks", payload) if isinstance(payload, dict) else payload

        # (page, row, col) → task_id
        task_map: dict = {}
        for task in tasks:
            url = task.get("data", {}).get("image", "")
            m = _TILE_RE.search(url)
            if m:
                task_map[(int(m.group(1)), int(m.group(2)), int(m.group(3)))] = task["id"]

        # Group detections by tile
        by_tile: dict = defaultdict(list)
        for det in detections:
            key = (det.get("tile_page", 0), det.get("tile_row", 0), det.get("tile_col", 0))
            by_tile[key].append(det)

        posted = 0
        for (page, row, col), tile_dets in by_tile.items():
            task_id = task_map.get((page, row, col))
            if not task_id:
                continue

            tile_path = job_dir / "tmp" / f"tile_p{page}_r{row}_c{col}.png"
            if tile_path.exists():
                from PIL import Image as _Image
                with _Image.open(tile_path) as im:
                    img_w, img_h = im.size
            else:
                img_w, img_h = 2000, 2000  # fallback; percentages still valid

            result = []
            for det in tile_dets:
                bbox = det.get("bbox_tile", [])
                if len(bbox) < 4:
                    continue
                x1, y1, x2, y2 = bbox
                result.append({
                    "type": "rectanglelabels",
                    "from_name": "label",
                    "to_name": "image",
                    "original_width": img_w,
                    "original_height": img_h,
                    "value": {
                        "x": x1 / img_w * 100,
                        "y": y1 / img_h * 100,
                        "width": (x2 - x1) / img_w * 100,
                        "height": (y2 - y1) / img_h * 100,
                        "rotation": 0,
                        "rectanglelabels": [det.get("yolo_class", "valve_gen")],
                    },
                })

            if not result:
                continue

            pred = requests.post(
                f"{LS_URL}/api/predictions/",
                headers=_headers(),
                json={"task": task_id, "model_version": "gpu-worker-v1", "result": result},
                timeout=15,
            )
            if pred.status_code in (200, 201):
                posted += 1
        return posted
    except Exception as e:
        print(f"[label_studio] push_predictions error: {e}")
    return 0


def get_project_stats(project_id: int) -> dict:
    """Return task count and annotation completion stats for a project."""
    if not is_configured():
        return {}
    try:
        resp = requests.get(f"{LS_URL}/api/projects/{project_id}/", headers=_headers(), timeout=5)
        if resp.status_code == 200:
            d = resp.json()
            return {
                "total_tasks": d.get("task_number", 0),
                "annotated": d.get("num_tasks_with_annotations", 0),
                "url": f"{LS_EXTERNAL_URL}/projects/{project_id}/",
            }
    except Exception as e:
        print(f"[label_studio] get_project_stats error: {e}")
    return {}
