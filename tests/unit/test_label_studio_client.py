"""Tests for `webapp.label_studio_client.get_or_create_project`.

Locks in two behaviours:
  1. **Existing project found** → return its id, NEVER hit `/api/projects/` POST
     and NEVER hit `/api/webhooks/` POST.
  2. **New project created** → hit `/api/webhooks/` POST exactly once with the
     correct payload (project id, secret header, TASKS_CREATED action).

Also covers two failure modes that must not bubble out of
`get_or_create_project`:
  - webhook POST returns 5xx → project_id still returned.
  - `LS_WEBHOOK_SECRET` unset → webhook registration skipped silently, project
    still returned.

Mocks `requests` at module scope; no live LS needed.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def _reload_ls_client(monkeypatch, *, secret: str = "test-secret", api_key: str = "qk_dummy"):
    """Re-import the module after env overrides so module-level constants pick
    up the test values. Returns the freshly-imported module."""
    monkeypatch.setenv("LS_API_KEY", api_key)
    monkeypatch.setenv("LS_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://test.example.com")
    if "webapp.label_studio_client" in sys.modules:
        del sys.modules["webapp.label_studio_client"]
    import importlib
    import webapp.label_studio_client as ls
    importlib.reload(ls)
    return ls


def _mk_response(status: int, json_body=None, text: str = "") -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_body if json_body is not None else {}
    m.text = text or (str(json_body) if json_body is not None else "")
    m.headers = {"content-type": "application/json"}
    return m


def test_existing_project_short_circuits(monkeypatch):
    """When the project already exists, we MUST NOT call any POST endpoint."""
    ls = _reload_ls_client(monkeypatch)

    with patch.object(ls.requests, "get") as mock_get, \
         patch.object(ls.requests, "post") as mock_post:
        mock_get.return_value = _mk_response(200, {"results": [
            {"id": 7, "title": "EXISTING-PID"},
            {"id": 8, "title": "OTHER-PID"},
        ]})

        result = ls.get_or_create_project("EXISTING-PID")

        assert result == 7
        mock_get.assert_called_once()
        mock_post.assert_not_called()  # no project create, no webhook register


def test_new_project_registers_webhook(monkeypatch):
    """Create → webhook POST with correct body + headers."""
    ls = _reload_ls_client(monkeypatch)

    with patch.object(ls.requests, "get") as mock_get, \
         patch.object(ls.requests, "post") as mock_post:
        mock_get.return_value = _mk_response(200, {"results": []})
        # First POST is project creation; second is webhook registration.
        mock_post.side_effect = [
            _mk_response(201, {"id": 42, "title": "NEW-PID"}),
            _mk_response(201, {"id": 99}),
        ]

        result = ls.get_or_create_project("NEW-PID")

        assert result == 42
        assert mock_post.call_count == 2

        # Project creation
        proj_call = mock_post.call_args_list[0]
        assert proj_call.args[0].endswith("/api/projects/")
        assert proj_call.kwargs["json"]["title"] == "NEW-PID"

        # Webhook registration
        wh_call = mock_post.call_args_list[1]
        assert wh_call.args[0].endswith("/api/webhooks/")
        wh_body = wh_call.kwargs["json"]
        assert wh_body["project"] == 42
        assert wh_body["actions"] == ["TASKS_CREATED"]
        assert wh_body["is_active"] is True
        assert wh_body["url"] == "https://test.example.com/api/v1/webhooks/label-studio/tasks-created"
        assert wh_body["headers"] == {"X-LS-Webhook-Secret": "test-secret"}


def test_new_project_returns_id_even_when_webhook_fails(monkeypatch):
    """5xx on webhook → log + continue. The project_id is still returned so the
    pipeline's auto-sync can push tiles. The auto-tile (PDF-import) path is the
    only thing that degrades, and that's acceptable as best-effort."""
    ls = _reload_ls_client(monkeypatch)

    with patch.object(ls.requests, "get") as mock_get, \
         patch.object(ls.requests, "post") as mock_post:
        mock_get.return_value = _mk_response(200, {"results": []})
        mock_post.side_effect = [
            _mk_response(201, {"id": 42}),
            _mk_response(500, text="boom"),
        ]

        result = ls.get_or_create_project("NEW-PID")

        assert result == 42  # project creation still wins
        assert mock_post.call_count == 2


def test_new_project_webhook_skipped_without_secret(monkeypatch):
    """If LS_WEBHOOK_SECRET is empty, do NOT register a hook (it would only
    401 anything LS posts to it). Project creation succeeds; webhook step is a
    no-op with a clear log line."""
    ls = _reload_ls_client(monkeypatch, secret="")

    with patch.object(ls.requests, "get") as mock_get, \
         patch.object(ls.requests, "post") as mock_post:
        mock_get.return_value = _mk_response(200, {"results": []})
        mock_post.side_effect = [_mk_response(201, {"id": 42})]

        result = ls.get_or_create_project("NEW-PID")

        assert result == 42
        # Only project creation called — webhook registration short-circuited.
        assert mock_post.call_count == 1
        assert mock_post.call_args_list[0].args[0].endswith("/api/projects/")


def test_get_or_create_project_unconfigured_returns_none(monkeypatch):
    """LS_API_KEY empty → is_configured() false → return None immediately, no
    HTTP calls. Defends the local-dev / CI path where no LS is wired up."""
    ls = _reload_ls_client(monkeypatch, api_key="")

    with patch.object(ls.requests, "get") as mock_get, \
         patch.object(ls.requests, "post") as mock_post:
        result = ls.get_or_create_project("ANYTHING")
        assert result is None
        mock_get.assert_not_called()


# ── extract_pdf_path_from_task_data — covers LS's `$undefined$` quirk ─────────


def test_extract_pdf_path_finds_image_key(monkeypatch):
    ls = _reload_ls_client(monkeypatch)
    assert ls.extract_pdf_path_from_task_data(
        {"image": "/data/upload/35/abc-foo.pdf"}
    ) == "/data/upload/35/abc-foo.pdf"


def test_extract_pdf_path_finds_undefined_key(monkeypatch):
    """LS Import UI stashes non-image uploads under `$undefined$`. The receiver
    used to look at `data.image` only and miss every PDF uploaded via LS UI."""
    ls = _reload_ls_client(monkeypatch)
    assert ls.extract_pdf_path_from_task_data(
        {"$undefined$": "/data/upload/38/xyz.PDF"}
    ) == "/data/upload/38/xyz.PDF"


def test_extract_pdf_path_returns_none_for_png(monkeypatch):
    """Tile tasks (post-auto-tile) carry a PNG — must NOT match, otherwise we'd
    re-tile our own outputs in an infinite loop."""
    ls = _reload_ls_client(monkeypatch)
    assert ls.extract_pdf_path_from_task_data(
        {"image": "/data/upload/35/abc-tile_p0_r1_c2.png"}
    ) is None


def test_extract_pdf_path_returns_none_for_empty_or_garbage(monkeypatch):
    ls = _reload_ls_client(monkeypatch)
    assert ls.extract_pdf_path_from_task_data({}) is None
    assert ls.extract_pdf_path_from_task_data({"image": ""}) is None
    assert ls.extract_pdf_path_from_task_data({"image": None}) is None
    assert ls.extract_pdf_path_from_task_data(None) is None  # type: ignore[arg-type]


# ── reconcile_project_webhooks — startup self-heal ───────────────────────────


def test_reconcile_adds_webhook_to_project_missing_one(monkeypatch):
    """A project with zero webhooks must get our auto-tile webhook attached.
    The webhook list probe + POST register must both fire."""
    ls = _reload_ls_client(monkeypatch)

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/api/projects/?page_size=500"):
            return _mk_response(200, {"results": [{"id": 38}]})
        if "/api/webhooks/?project=38" in url:
            return _mk_response(200, [])  # no webhooks yet
        if "/api/projects/38/tasks" in url:
            return _mk_response(200, {"tasks": []})  # no backlog
        return _mk_response(404)

    posts = []
    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append({"url": url, "json": json})
        if url.endswith("/api/webhooks/"):
            return _mk_response(201, {"id": 99})
        return _mk_response(404)

    with patch.object(ls.requests, "get", side_effect=fake_get), \
         patch.object(ls.requests, "post", side_effect=fake_post), \
         patch("webapp.queue.get_cpu_queue"):
        out = ls.reconcile_project_webhooks(enqueue_pdf_backlog=True)

    assert out["status"] == "ok"
    assert out["webhooks_added"] == 1
    # One POST to /api/webhooks/ — and it MUST target proj 38 with our secret
    webhook_posts = [p for p in posts if p["url"].endswith("/api/webhooks/")]
    assert len(webhook_posts) == 1
    assert webhook_posts[0]["json"]["project"] == 38
    assert webhook_posts[0]["json"]["actions"] == ["TASKS_CREATED"]
    assert webhook_posts[0]["json"]["headers"]["X-LS-Webhook-Secret"] == "test-secret"


def test_reconcile_skips_project_that_already_has_webhook(monkeypatch):
    """Idempotent on rerun — if our webhook is already there, don't double-add."""
    ls = _reload_ls_client(monkeypatch)
    existing = [{
        "id": 50,
        "is_active": True,
        "actions": ["TASKS_CREATED"],
        "url": "https://test.example.com/api/v1/webhooks/label-studio/tasks-created",
    }]

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/api/projects/?page_size=500"):
            return _mk_response(200, {"results": [{"id": 35}]})
        if "/api/webhooks/?project=35" in url:
            return _mk_response(200, existing)
        if "/api/projects/35/tasks" in url:
            return _mk_response(200, {"tasks": []})
        return _mk_response(404)

    posts = []
    with patch.object(ls.requests, "get", side_effect=fake_get), \
         patch.object(ls.requests, "post", side_effect=lambda *a, **k: posts.append(k) or _mk_response(201, {"id": 1})), \
         patch("webapp.queue.get_cpu_queue"):
        out = ls.reconcile_project_webhooks(enqueue_pdf_backlog=True)

    assert out["status"] == "ok"
    assert out["webhooks_added"] == 0
    # No registration POST should have been issued.
    assert not any(p.get("json", {}).get("actions") == ["TASKS_CREATED"] for p in posts)


def test_reconcile_enqueues_pdf_backlog(monkeypatch):
    """Existing PDF tasks (from LS-UI uploads predating the webhook) get tiling
    jobs queued on the cpu-worker. Without this, every new LS-UI project leaves
    a stale PDF sitting in LS forever."""
    ls = _reload_ls_client(monkeypatch)

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/api/projects/?page_size=500"):
            return _mk_response(200, {"results": [{"id": 38}]})
        if "/api/webhooks/?project=38" in url:
            return _mk_response(200, [])
        if "/api/projects/38/tasks" in url:
            return _mk_response(200, {"tasks": [
                {"id": 1246, "data": {"$undefined$": "/data/upload/38/foo.pdf"}},
                {"id": 1247, "data": {"image": "/data/upload/38/tile_p0_r0_c0.png"}},  # skip
            ]})
        return _mk_response(404)

    fake_queue = MagicMock()
    with patch.object(ls.requests, "get", side_effect=fake_get), \
         patch.object(ls.requests, "post", return_value=_mk_response(201, {"id": 99})), \
         patch("webapp.queue.get_cpu_queue", return_value=fake_queue):
        out = ls.reconcile_project_webhooks(enqueue_pdf_backlog=True)

    assert out["pdf_backlog_enqueued"] == 1
    fake_queue.enqueue.assert_called_once()
    call_kwargs = fake_queue.enqueue.call_args.kwargs["kwargs"]
    assert call_kwargs == {
        "project_id": 38,
        "task_id": 1246,
        "image_path": "/data/upload/38/foo.pdf",
    }


def test_reconcile_skipped_when_secret_unset(monkeypatch):
    """No LS_WEBHOOK_SECRET → can't auth callbacks → don't register anything."""
    ls = _reload_ls_client(monkeypatch, secret="")
    with patch.object(ls.requests, "get") as mock_get, \
         patch.object(ls.requests, "post") as mock_post:
        out = ls.reconcile_project_webhooks(enqueue_pdf_backlog=True)
    assert out["status"] == "skipped"
    mock_get.assert_not_called()
    mock_post.assert_not_called()
