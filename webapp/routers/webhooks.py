"""Inbound webhooks from external services (currently: Label Studio).

Each handler does the minimum amount of work synchronously (signature check,
payload parse, enqueue) and returns 200 quickly. Long-running work (PDF
tiling, multipart uploads) is dispatched onto the cpu-worker RQ queue so
the webhook response stays under typical 10-second sender timeouts.

See FEATURES #30 for the auto-tile motivation.
"""
from __future__ import annotations

import hmac
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from webapp.queue import get_cpu_queue

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

# Shared secret sent by LS on every webhook hit. The LS webhook UI doesn't
# expose a "secret" field directly, so we stash this value into a custom
# header on the webhook's request config. Required — without it the endpoint
# is open to anyone who can reach our network.
_LS_WEBHOOK_SECRET = os.environ.get("LS_WEBHOOK_SECRET", "")


def _verify_secret(authorization: Optional[str], x_ls_webhook_secret: Optional[str]) -> None:
    """Reject requests that don't carry the expected shared secret.

    LS lets you set a custom Authorization header on a webhook. Some teams
    prefer a discrete header instead — we accept either:
      - `Authorization: Bearer <secret>` (LS "Authorization" field), or
      - `X-LS-Webhook-Secret: <secret>` (custom header — recommended)
    """
    if not _LS_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="webhook secret not configured server-side")
    expected = _LS_WEBHOOK_SECRET
    # hmac.compare_digest avoids byte-by-byte timing leaks. Both candidate
    # branches use compare_digest so a slow-equal compare can't be used to
    # probe one branch via the other.
    if x_ls_webhook_secret and hmac.compare_digest(x_ls_webhook_secret, expected):
        return
    if authorization and hmac.compare_digest(authorization, f"Bearer {expected}"):
        return
    raise HTTPException(status_code=401, detail="invalid webhook secret")


@router.post("/label-studio/tasks-created")
async def ls_tasks_created(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_ls_webhook_secret: Optional[str] = Header(default=None, alias="X-LS-Webhook-Secret"),
) -> Dict[str, Any]:
    """Handle LS `TASKS_CREATED` event.

    Payload shape (LS 1.23):
      {
        "action": "TASKS_CREATED",
        "project": { "id": 32, ... },
        "tasks":   [ { "id": 877, "data": {"image": "/data/upload/32/<uuid>.pdf"}, ... }, ... ]
      }

    For each task whose `data.image` ends in `.pdf`, enqueue an auto-tile job.
    PNG tasks are no-ops (most common case after our own upload step succeeds —
    we keep responding 200 so LS doesn't disable the webhook).
    """
    _verify_secret(authorization, x_ls_webhook_secret)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    if (payload.get("action") or "").upper() != "TASKS_CREATED":
        # Webhook may be subscribed to multiple events; ignore non-matching.
        return {"status": "ignored", "reason": "non-task-created-event"}

    project = payload.get("project") or {}
    project_id = project.get("id")
    tasks: List[Dict[str, Any]] = payload.get("tasks") or []
    if not project_id or not tasks:
        return {"status": "ignored", "reason": "missing project or tasks"}

    queue = get_cpu_queue()
    enqueued: List[int] = []
    for task in tasks:
        image_path = (task.get("data") or {}).get("image")
        task_id = task.get("id")
        if not image_path or not task_id:
            continue
        if not image_path.lower().endswith(".pdf"):
            continue
        queue.enqueue(
            "webapp.auto_tile.auto_tile_ls_task_rq",
            kwargs={
                "project_id": project_id,
                "task_id": task_id,
                "image_path": image_path,
            },
            job_timeout=300,  # 5 min — PDF download + tile + 9 uploads
        )
        enqueued.append(task_id)

    return {
        "status": "ok",
        "project_id": project_id,
        "tasks_received": len(tasks),
        "enqueued_for_tiling": len(enqueued),
        "task_ids": enqueued,
    }
