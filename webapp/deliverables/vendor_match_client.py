"""Client for the external Vendor Match API.

Calls POST /api/instrument-match with an instrument type code and optional
range parameters. Returns a dict of fields ready to merge into a canonical
entity, or None if the API is not configured / returns no matches.

Configuration (env vars):
    VENDOR_MATCH_API_URL  — base URL, e.g. https://...ngrok-free.dev
                            If empty / unset, all calls return None silently.
    VENDOR_MATCH_API_KEY  — X-API-KEY header value

Best-match strategy:
    1. Pass instType + measuring range if available → API narrows the list.
    2. If match_count == 1: use that match.
    3. If match_count > 1:  use the first match (API ranks by best fit).
    4. Results are cached per (instType, range_min, range_max, range_unit)
       so each unique instrument spec hits the API only once per process.
"""

import logging
import os
from typing import Any, Dict, Optional, Tuple

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

log = logging.getLogger(__name__)

# Process-level cache: (instType, range_min, range_max, range_unit) → fields dict
_cache: Dict[Tuple, Optional[Dict[str, Any]]] = {}


def _api_url() -> str:
    return os.environ.get("VENDOR_MATCH_API_URL", "").rstrip("/")


def _api_key() -> str:
    return os.environ.get("VENDOR_MATCH_API_KEY", "")


def _normalize_inst_type(code: str) -> str:
    """Map compound ISA codes to the base catalog type for API lookup.

    Any transmitter (ends in T) → {first_letter}T
      PZIT → PT,  FZIT → FT,  LZIT → LT,  TZIT → TT,  FZAT → FT …

    Any primary element / sensor (ends in E) → {first_letter}E
      FE → FE (unchanged),  etc.

    Anything else is returned as-is; the API will 422 if it has no catalog
    entry for that code.
    """
    if not code:
        return code
    if code.endswith("T") and len(code) > 2:
        return code[0] + "T"
    if code.endswith("E") and len(code) > 2:
        return code[0] + "E"
    return code


def fetch_vendor_fields(
    inst_type: str,
    range_min: Optional[str] = None,
    range_max: Optional[str] = None,
    range_unit: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return canonical field updates from the vendor match API, or None.

    Fields returned (all optional — only set when the API returns them):
        piping_class, calb_range_min, calb_range_max, calb_range_unit,
        measuring_range_min, measuring_range_max, measuring_range_unit,
        power_in, power_out, io_output
        _vendor_name, _model_number  (prefixed — consumed by pipeline_emitter
                                       for VendorMatch, not stored in fields)
    """
    base = _api_url()
    key = _api_key()
    if not base or not _REQUESTS_OK:
        return None

    code = _normalize_inst_type((inst_type or "").upper().strip())
    if not code:
        return None

    cache_key: Tuple = (code, range_min, range_max, range_unit)
    if cache_key in _cache:
        return _cache[cache_key]

    payload: Dict[str, Any] = {"instType": code}
    try:
        if range_min is not None:
            payload["range_min"] = float(range_min)
        if range_max is not None:
            payload["range_max"] = float(range_max)
        if range_unit:
            payload["range_unit"] = range_unit
    except (ValueError, TypeError):
        pass  # bad range values — send without them

    try:
        resp = _requests.post(
            f"{base}/api/instrument-match",
            json=payload,
            headers={
                "X-API-KEY": key,
                "Accept": "application/json",
                # ngrok free tunnels serve an interstitial page to non-browser
                # clients; this header bypasses it.
                "ngrok-skip-browser-warning": "true",
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("vendor_match_client: API call failed for %s — %s", code, exc)
        _cache[cache_key] = None
        return None

    if not data.get("success"):
        _cache[cache_key] = None
        return None

    matches = data.get("matches") or []
    if not matches:
        # qong-instrument endpoint returns data directly
        match = data.get("data") or {}
    else:
        match = matches[0]

    if not match:
        _cache[cache_key] = None
        return None

    def _str(v: Any) -> str:
        return str(v) if v is not None else ""

    result: Dict[str, Any] = {
        # Stored in fields (shown in instrument index columns)
        "piping_class":           _str(match.get("piping_class")),
        "calb_range_min":         _str(match.get("calibration_range_min")),
        "calb_range_max":         _str(match.get("calibration_range_max")),
        "calb_range_unit":        _str(match.get("calibration_range_unit")),
        "measuring_range_min":    _str(match.get("measuring_range_min")),
        "measuring_range_max":    _str(match.get("measuring_range_max")),
        "measuring_range_unit":   _str(match.get("measuring_range_unit")),
        "power_in":               _str(match.get("power_supply_input")),
        "power_out":              _str(match.get("power_supply_output")),
        "io_output":              _str(match.get("io_output")),
        # Private — used to build VendorMatch (not stored in fields)
        "_vendor_name":           _str(match.get("vendor_name")),
        "_model_number":          _str(match.get("model_number") or match.get("model")),
        "_manufacturer":          _str(match.get("manufacturer") or match.get("brand")),
        "_product_id":            _str(match.get("product_id")),
    }

    log.info(
        "vendor_match_client: %s → vendor=%s model=%s",
        code, result["_vendor_name"], result["_model_number"],
    )
    _cache[cache_key] = result
    return result
