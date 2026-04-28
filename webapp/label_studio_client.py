"""Label Studio API client — push P&ID tiles as annotation tasks."""
import os
from typing import Optional
import requests

LS_URL = os.environ.get("LS_URL", "http://localhost:8080").rstrip("/")
LS_API_KEY = os.environ.get("LS_API_KEY", "")

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
  </RectangleLabels>
</View>"""


def _headers() -> dict:
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
        if resp.status_code == 201:
            return len(resp.json())
    except Exception as e:
        print(f"[label_studio] push_tiles error: {e}")
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
                "url": f"{LS_URL}/projects/{project_id}/",
            }
    except Exception as e:
        print(f"[label_studio] get_project_stats error: {e}")
    return {}
