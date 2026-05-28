"""E2E tests for /api/v1/admin/* JSON endpoints.

Covers role gating (super_admin only), business rules (no self-mutation,
input validation), and data-continuity (existing User/Job/Plan/Feedback
rows surface in the new endpoints).
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.auth import create_access_token, hash_password
from webapp.database import Base, get_db
from webapp import models
from webapp.main import app


# ── Test infra ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    session = S()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


def _mk_user(db, *, username, role="user", is_active=True, credits=10, tier="trial"):
    u = models.User(
        username=username,
        password_hash=hash_password("password123"),
        role=role,
        is_active=is_active,
        credits_remaining=credits,
        tier=tier,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def super_admin(db_session):
    return _mk_user(db_session, username="boss", role="super_admin")


@pytest.fixture()
def regular_user(db_session):
    return _mk_user(db_session, username="alice", role="user")


@pytest.fixture()
def auth_as(client):
    def _login_as(user):
        token = create_access_token({"sub": user.username})
        client.cookies.set("access_token", token)
        return client
    yield _login_as
    client.cookies.clear()


# ── Cross-cutting: auth gating ─────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/admin/users"),
    ("GET", "/api/v1/admin/dashboard"),
    ("GET", "/api/v1/admin/credits"),
    ("GET", "/api/v1/admin/feedback"),
    ("GET", "/api/v1/admin/plans"),
    ("GET", "/api/v1/admin/label-studio"),
])
def test_no_auth_redirects_to_login(client, method, path):
    """get_current_user raises 303 → /login when no cookie present."""
    resp = client.request(method, path, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers.get("location") == "/login"


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/admin/users"),
    ("GET", "/api/v1/admin/dashboard"),
    ("GET", "/api/v1/admin/credits"),
    ("GET", "/api/v1/admin/feedback"),
    ("GET", "/api/v1/admin/plans"),
    ("GET", "/api/v1/admin/label-studio"),
])
def test_regular_user_forbidden(auth_as, regular_user, method, path):
    """require_super_admin returns 403 for role!='super_admin'."""
    c = auth_as(regular_user)
    resp = c.request(method, path, follow_redirects=False)
    assert resp.status_code == 403


# ── Users ──────────────────────────────────────────────────────────────────────

def test_list_users(auth_as, super_admin, regular_user):
    c = auth_as(super_admin)
    resp = c.get("/api/v1/admin/users")
    assert resp.status_code == 200
    data = resp.json()
    usernames = sorted(u["username"] for u in data["users"])
    assert usernames == ["alice", "boss"]
    # data continuity: serializer exposes all fields the UI needs
    boss = next(u for u in data["users"] if u["username"] == "boss")
    assert boss["role"] == "super_admin"
    assert boss["is_active"] is True
    assert boss["credits_remaining"] == 10
    assert boss["tier"] == "trial"


def test_create_user_success(auth_as, super_admin, db_session):
    c = auth_as(super_admin)
    resp = c.post("/api/v1/admin/users", json={
        "username": "newbie",
        "email": "newbie@example.com",
        "password": "longenoughpw",
        "role": "user",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "newbie"
    assert data["role"] == "user"
    assert data["is_active"] is True
    # Persisted
    assert db_session.query(models.User).filter_by(username="newbie").first() is not None


@pytest.mark.parametrize("body,expected_substr", [
    ({"username": "ab", "password": "longenoughpw"}, "3-32 chars"),  # too short
    ({"username": "valid_name", "password": "short"}, "at least"),     # weak password
    ({"username": "has spaces!", "password": "longenoughpw"}, "3-32 chars"),
])
def test_create_user_validation(auth_as, super_admin, body, expected_substr):
    c = auth_as(super_admin)
    resp = c.post("/api/v1/admin/users", json=body)
    assert resp.status_code == 400
    assert expected_substr in resp.json()["detail"]


def test_create_user_duplicate_username(auth_as, super_admin, regular_user):
    c = auth_as(super_admin)
    resp = c.post("/api/v1/admin/users", json={
        "username": "alice",  # already exists
        "password": "longenoughpw",
    })
    assert resp.status_code == 400
    assert "already taken" in resp.json()["detail"]


def test_change_role_success(auth_as, super_admin, regular_user, db_session):
    c = auth_as(super_admin)
    resp = c.post(f"/api/v1/admin/users/{regular_user.id}/role", json={"role": "annotator"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "annotator"
    db_session.refresh(regular_user)
    assert regular_user.role == "annotator"


def test_change_role_cannot_demote_self(auth_as, super_admin):
    c = auth_as(super_admin)
    resp = c.post(f"/api/v1/admin/users/{super_admin.id}/role", json={"role": "user"})
    assert resp.status_code == 400
    assert "own role" in resp.json()["detail"]


def test_change_role_invalid(auth_as, super_admin, regular_user):
    c = auth_as(super_admin)
    resp = c.post(f"/api/v1/admin/users/{regular_user.id}/role", json={"role": "godmode"})
    assert resp.status_code == 400


def test_change_role_user_not_found(auth_as, super_admin):
    c = auth_as(super_admin)
    resp = c.post("/api/v1/admin/users/99999/role", json={"role": "user"})
    assert resp.status_code == 404


def test_activate_deactivate_cycle(auth_as, super_admin, regular_user, db_session):
    c = auth_as(super_admin)
    # Deactivate
    r1 = c.post(f"/api/v1/admin/users/{regular_user.id}/deactivate")
    assert r1.status_code == 200
    assert r1.json()["is_active"] is False
    db_session.refresh(regular_user)
    assert regular_user.is_active is False
    # Activate
    r2 = c.post(f"/api/v1/admin/users/{regular_user.id}/activate")
    assert r2.status_code == 200
    assert r2.json()["is_active"] is True


def test_deactivate_self_blocked(auth_as, super_admin):
    c = auth_as(super_admin)
    resp = c.post(f"/api/v1/admin/users/{super_admin.id}/deactivate")
    assert resp.status_code == 400


def test_delete_user(auth_as, super_admin, regular_user, db_session):
    c = auth_as(super_admin)
    resp = c.delete(f"/api/v1/admin/users/{regular_user.id}")
    assert resp.status_code == 204
    assert db_session.query(models.User).filter_by(id=regular_user.id).first() is None


def test_delete_self_blocked(auth_as, super_admin):
    c = auth_as(super_admin)
    resp = c.delete(f"/api/v1/admin/users/{super_admin.id}")
    assert resp.status_code == 400


def test_grant_credits(auth_as, super_admin, regular_user, db_session):
    c = auth_as(super_admin)
    initial = regular_user.credits_remaining
    resp = c.post(f"/api/v1/admin/users/{regular_user.id}/grant-credits", json={"amount": 50})
    assert resp.status_code == 200
    assert resp.json()["credits_remaining"] == initial + 50
    # Ledger row created
    txn = (
        db_session.query(models.CreditTransaction)
        .filter_by(user_id=regular_user.id, reason="admin_grant")
        .first()
    )
    assert txn is not None and txn.delta == 50


@pytest.mark.parametrize("amount", [0, -5, 10001])
def test_grant_credits_invalid_amount(auth_as, super_admin, regular_user, amount):
    c = auth_as(super_admin)
    resp = c.post(f"/api/v1/admin/users/{regular_user.id}/grant-credits", json={"amount": amount})
    assert resp.status_code == 422 or resp.status_code == 400


def test_change_tier(auth_as, super_admin, regular_user, db_session):
    c = auth_as(super_admin)
    resp = c.post(f"/api/v1/admin/users/{regular_user.id}/change-tier", json={"tier": "pro"})
    assert resp.status_code == 200
    assert resp.json()["tier"] == "pro"
    db_session.refresh(regular_user)
    assert regular_user.tier == "pro"


def test_change_tier_invalid(auth_as, super_admin, regular_user):
    c = auth_as(super_admin)
    resp = c.post(f"/api/v1/admin/users/{regular_user.id}/change-tier", json={"tier": "godmode"})
    assert resp.status_code == 400


# ── Dashboard ──────────────────────────────────────────────────────────────────


def test_dashboard_kpis(auth_as, super_admin, regular_user, db_session):
    # Seed a deactivated user + a done job + a new feedback
    _mk_user(db_session, username="pending_user", is_active=False)
    db_session.add(models.Job(
        user_id=regular_user.id, original_filename="x.pdf", stored_filename="y.pdf",
        status="done",
    ))
    db_session.add(models.UserFeedback(
        user_id=regular_user.id, category="bug", subject="s", message="m", status="new",
    ))
    db_session.commit()

    c = auth_as(super_admin)
    resp = c.get("/api/v1/admin/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_users"] == 3  # boss + alice + pending_user
    assert data["active_users"] == 2
    assert data["pending_users"] == 1
    assert data["total_jobs"] == 1
    assert data["done_jobs"] == 1
    assert data["open_feedback"] == 1
    assert "recent_txns" in data


# ── Credits ────────────────────────────────────────────────────────────────────


def test_credits_ledger(auth_as, super_admin, regular_user, db_session):
    # Seed a transaction
    db_session.add(models.CreditTransaction(
        user_id=regular_user.id, delta=100, balance_after=110, reason="admin_grant",
    ))
    db_session.commit()

    c = auth_as(super_admin)
    resp = c.get("/api/v1/admin/credits")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["transactions"]) == 1
    txn = data["transactions"][0]
    assert txn["delta"] == 100
    assert txn["username"] == "alice"


# ── Feedback ───────────────────────────────────────────────────────────────────


def test_feedback_list_and_filter(auth_as, super_admin, regular_user, db_session):
    db_session.add(models.UserFeedback(
        user_id=regular_user.id, category="bug", subject="a", message="x", status="new",
    ))
    db_session.add(models.UserFeedback(
        user_id=regular_user.id, category="bug", subject="b", message="y", status="resolved",
    ))
    db_session.commit()

    c = auth_as(super_admin)
    # Default filter is 'new'
    r_new = c.get("/api/v1/admin/feedback").json()
    assert len(r_new["items"]) == 1
    assert r_new["items"][0]["subject"] == "a"
    assert r_new["open_count"] == 1

    # all
    r_all = c.get("/api/v1/admin/feedback?status_filter=all").json()
    assert len(r_all["items"]) == 2

    # resolved
    r_resolved = c.get("/api/v1/admin/feedback?status_filter=resolved").json()
    assert len(r_resolved["items"]) == 1
    assert r_resolved["items"][0]["subject"] == "b"


def test_feedback_invalid_filter(auth_as, super_admin):
    c = auth_as(super_admin)
    resp = c.get("/api/v1/admin/feedback?status_filter=garbage")
    assert resp.status_code == 400


def test_feedback_update(auth_as, super_admin, regular_user, db_session):
    item = models.UserFeedback(
        user_id=regular_user.id, category="bug", subject="s", message="m", status="new",
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    c = auth_as(super_admin)
    resp = c.post(
        f"/api/v1/admin/feedback/{item.id}/update",
        json={"status": "in_progress", "admin_notes": "looking into it"},
    )
    assert resp.status_code == 200
    db_session.refresh(item)
    assert item.status == "in_progress"
    assert item.admin_notes == "looking into it"


def test_feedback_update_not_found(auth_as, super_admin):
    c = auth_as(super_admin)
    resp = c.post(
        "/api/v1/admin/feedback/99999/update",
        json={"status": "resolved", "admin_notes": ""},
    )
    assert resp.status_code == 404


# ── Plans ──────────────────────────────────────────────────────────────────────


def test_plans_list_create_toggle(auth_as, super_admin, db_session):
    c = auth_as(super_admin)
    # Initially empty
    assert c.get("/api/v1/admin/plans").json()["plans"] == []

    # Create
    r_create = c.post("/api/v1/admin/plans", json={
        "name": "Starter",
        "credits": 100,
        "price_usd_cents": 999,
    })
    assert r_create.status_code == 201
    plan_id = r_create.json()["id"]
    assert r_create.json()["is_active"] is True

    # Toggle off
    r_toggle = c.post(f"/api/v1/admin/plans/{plan_id}/toggle")
    assert r_toggle.status_code == 200
    assert r_toggle.json()["is_active"] is False

    # Toggle back on
    r_toggle2 = c.post(f"/api/v1/admin/plans/{plan_id}/toggle")
    assert r_toggle2.json()["is_active"] is True


def test_plans_toggle_not_found(auth_as, super_admin):
    c = auth_as(super_admin)
    resp = c.post("/api/v1/admin/plans/99999/toggle")
    assert resp.status_code == 404


# ── Label Studio ───────────────────────────────────────────────────────────────


def test_label_studio_list_no_jobs(auth_as, super_admin):
    """Endpoint works even when LS not configured / no done jobs exist."""
    c = auth_as(super_admin)
    resp = c.get("/api/v1/admin/label-studio")
    assert resp.status_code == 200
    data = resp.json()
    assert data["jobs"] == []
    # ls_configured may be True or False depending on env — just ensure the key is present
    assert "ls_configured" in data
    assert "ls_url" in data


def test_label_studio_sync_labels_requires_config(auth_as, super_admin, monkeypatch):
    monkeypatch.setattr("webapp.label_studio_client.is_configured", lambda: False)
    c = auth_as(super_admin)
    resp = c.post("/api/v1/admin/label-studio/sync-labels")
    assert resp.status_code == 400
    assert "not configured" in resp.json()["detail"]


def test_label_studio_sync_job_not_found(auth_as, super_admin, monkeypatch):
    monkeypatch.setattr("webapp.label_studio_client.is_configured", lambda: True)
    c = auth_as(super_admin)
    resp = c.post("/api/v1/admin/label-studio/sync/99999")
    assert resp.status_code == 404
