"""Vendor-match proxy (FEATURES #124).

The Studio "Select Vendor" dropdown needs the external vendor catalog, but the
vendor API requires an `X-API-KEY`. Calling it directly from the browser would
ship that live key in the SPA bundle (a real leak — it once was hardcoded in
the frontend). Instead the browser hits this same-origin, cookie-authenticated
proxy, which calls the vendor API server-side with the key from env
(`VENDOR_MATCH_API_URL` / `VENDOR_MATCH_API_KEY`).
"""
import logging
from urllib.parse import urlparse

import requests as _requests
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from webapp import models
from webapp.auth import get_current_user
from webapp.deliverables.vendor_match_client import (
    fetch_vendor_catalog,
    fetch_vendor_datasheet,
    vendor_api_configured,
    _api_key,
    _api_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["vendor"])


class VendorMatchRequest(BaseModel):
    instType: str


@router.post("/vendor-match")
def vendor_match(
    req: VendorMatchRequest,
    current_user: models.User = Depends(get_current_user),
):
    """Proxy a vendor-catalog lookup. Returns the raw vendor API response
    (`{success, instType, data:[...]}`) so the dropdown can list every product.

    503 if the vendor API isn't configured for this environment; 502 if it is
    configured but the upstream call failed.
    """
    code = (req.instType or "").strip()
    if not code:
        raise HTTPException(status_code=422, detail="instType is required")
    if not vendor_api_configured():
        raise HTTPException(status_code=503, detail="Vendor match API not configured for this environment")
    data = fetch_vendor_catalog(code)
    if data is None:
        raise HTTPException(status_code=502, detail="Vendor match API call failed")
    return data


def _to_path_keys(raw: dict) -> dict:
    """Convert fetch_vendor_datasheet() OLD-format keys to dotted IDS schema paths
    suitable for patchEntity (EntityOverride).

    OLD format produced by fetch_vendor_datasheet:
      "ids_*"      → entity.fields
      "_vendor_name" / "_model_number" / "_product_id"  → vendor identity
      everything else  → entity.vendor_match.catalog_fields

    Converted to:
      "fields.ids_*"
      "vendor_match.vendor_name" / "vendor_match.product_name" / "vendor_match.part_number"
      "vendor_match.catalog_fields.<key>"
    """
    _IDENTITY = {
        "_vendor_name":  "vendor_match.vendor_name",
        "_model_number": "vendor_match.product_name",
        "_product_id":   "vendor_match.part_number",
    }
    result = {}
    for k, v in raw.items():
        if k in _IDENTITY:
            result[_IDENTITY[k]] = v
        elif k.startswith("ids_"):
            result[f"fields.{k}"] = v
        else:
            result[f"vendor_match.catalog_fields.{k}"] = v
    return result


@router.get("/vendor-datasheet")
def vendor_datasheet(
    url: str = Query(None, description="PDF datasheet URL to proxy"),
    instType: str = Query(None, description="Instrument type for field population"),
    current_user: models.User = Depends(get_current_user),
):
    """Unified vendor datasheet endpoint: proxy PDF or return entity fields.

    **PDF Proxy mode** (url parameter):
    Proxy the vendor PDF datasheet to the browser. The vendor's datasheet endpoint
    requires `X-API-KEY`. The browser can't set that header in a fetch/iframe src,
    so the SPA passes the raw `datasheet_url` here and we fetch it server-side,
    streaming the bytes back as `application/pdf`.

    Security: only URLs whose hostname exactly matches the configured
    VENDOR_MATCH_API_URL host are accepted. This prevents SSRF and stops the
    API key from being forwarded to an attacker-controlled host. Redirects are
    disabled so a 302 cannot move the request (and the key) elsewhere.

    **Field Population mode** (instType parameter):
    Return vendor datasheet fields as dotted IDS schema paths for patchEntity.
    Keys are dotted paths (fields.ids_*, vendor_match.vendor_name,
    vendor_match.catalog_fields.*), values are strings ready to pass to patchEntity.
    """
    # URL proxy mode
    if url:
        parsed = urlparse(url)
        allowed = urlparse(_api_url())
        if parsed.scheme != "https" or parsed.hostname != allowed.hostname or not allowed.hostname:
            raise HTTPException(status_code=422, detail="Datasheet URL not from configured vendor host")

        try:
            resp = _requests.get(
                url,
                headers={
                    "X-API-KEY": _api_key(),
                    "Accept": "application/pdf,*/*",
                    "ngrok-skip-browser-warning": "true",
                },
                timeout=15,
                allow_redirects=False,
            )
            if resp.is_redirect:
                raise HTTPException(status_code=502, detail="Vendor redirect rejected")
            resp.raise_for_status()
            return Response(content=resp.content, media_type="application/pdf")
        except _requests.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Vendor datasheet fetch failed: {exc}") from exc
        except Exception as exc:
            logger.warning("vendor_datasheet proxy error: %s", exc)
            raise HTTPException(status_code=502, detail="Vendor datasheet fetch failed") from exc

    # Field population mode
    elif instType:
        code = (instType or "").strip().upper()
        if not code:
            raise HTTPException(status_code=422, detail="instType is required")
        if not vendor_api_configured():
            raise HTTPException(status_code=503, detail="Vendor API not configured for this environment")
        data = fetch_vendor_datasheet(code)
        if data is None:
            raise HTTPException(status_code=502, detail="Vendor datasheet fetch failed")
        return {"success": True, "instType": code, "data": _to_path_keys(data)}

    else:
        raise HTTPException(status_code=422, detail="Either 'url' or 'instType' parameter is required")
