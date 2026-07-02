"""Unit tests for the vendor-match proxy (FEATURES #124).

The proxy keeps the vendor API key server-side; the browser only ever hits the
same-origin /api/v1/vendor-match. These cover the configuration guard and the
route's status-code contract.
"""
import types

import pytest

from webapp.deliverables import vendor_match_client as vmc
from webapp.routers import vendor as vendor_router


def _user():
    return types.SimpleNamespace(id=1, role="user")


# ── vendor_api_configured ────────────────────────────────────────────────────────

def test_configured_false_when_url_unset(monkeypatch):
    monkeypatch.delenv("VENDOR_MATCH_API_URL", raising=False)
    assert vmc.vendor_api_configured() is False


def test_configured_true_when_url_set(monkeypatch):
    monkeypatch.setenv("VENDOR_MATCH_API_URL", "https://dev-vendors.qongsystems.com")
    assert vmc.vendor_api_configured() is True


# ── route contract ──────────────────────────────────────────────────────────────

def test_route_422_on_blank_insttype():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        vendor_router.vendor_match(vendor_router.VendorMatchRequest(instType="  "), current_user=_user())
    assert ei.value.status_code == 422


def test_route_503_when_unconfigured(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(vendor_router, "vendor_api_configured", lambda: False)
    with pytest.raises(HTTPException) as ei:
        vendor_router.vendor_match(vendor_router.VendorMatchRequest(instType="PT"), current_user=_user())
    assert ei.value.status_code == 503


def test_route_502_when_upstream_fails(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(vendor_router, "vendor_api_configured", lambda: True)
    monkeypatch.setattr(vendor_router, "fetch_vendor_catalog", lambda code: None)
    with pytest.raises(HTTPException) as ei:
        vendor_router.vendor_match(vendor_router.VendorMatchRequest(instType="PT"), current_user=_user())
    assert ei.value.status_code == 502


def test_route_returns_catalog_on_success(monkeypatch):
    monkeypatch.setattr(vendor_router, "vendor_api_configured", lambda: True)
    payload = {"success": True, "instType": "PT", "data": [{"product_id": 1, "manufacturer": "Emerson"}]}
    monkeypatch.setattr(vendor_router, "fetch_vendor_catalog", lambda code: payload)
    out = vendor_router.vendor_match(vendor_router.VendorMatchRequest(instType="PT"), current_user=_user())
    assert out == payload
