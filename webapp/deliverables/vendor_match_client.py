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
import re
from typing import Any, Dict, Optional, Tuple

# Strip bus-protocol prefixes so io_output only shows the signal spec.
# "RS485 + 4-20mA" → "4-20mA",  "HART 4-20mA" → "4-20mA"
_MA_RE = re.compile(r'4[-–]20\s*mA', re.IGNORECASE)

def _clean_io_output(raw: str) -> str:
    if _MA_RE.search(raw):
        return "4-20mA"
    return raw

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

log = logging.getLogger(__name__)

# Process-level caches
_cache: Dict[Tuple, Optional[Dict[str, Any]]] = {}  # fetch_vendor_fields cache
_datasheet_cache: Dict[str, Optional[Dict[str, Any]]] = {}  # fetch_vendor_datasheet cache


def _api_url() -> str:
    return os.environ.get("VENDOR_MATCH_API_URL", "").rstrip("/")


def _api_key() -> str:
    return os.environ.get("VENDOR_MATCH_API_KEY", "")


def _normalize_inst_type(code: str) -> str:
    """Map compound ISA codes to the base catalog type for API lookup.

    Transmitter (last letter T) → {first_letter}T
      PZIT → PT,  FZIT → FT,  LZIT → LT,  TZIT → TT …

    Primary element (last letter E) → {first_letter}E
      FE → FE (unchanged), etc.

    Switch / manual-hand (last letter S, or trip suffixes HH/LL/SH/SL) → PBS
      HS → PBS,  LIS → PBS,  PSHH → PBS,  FSLL → PBS …
      All switches use the same PBS (Push Button Switch) vendor catalog entry.

    Anything else is returned as-is; the API will 422 if it has no catalog
    entry for that code.
    """
    if not code:
        return code
    # Transmitter
    if code.endswith("T") and len(code) > 2:
        return code[0] + "T"
    # Primary element
    if code.endswith("E") and len(code) > 2:
        return code[0] + "E"
    # Switch / manual-hand — all map to PBS
    if code.endswith("S"):
        return "PBS"
    if code.endswith(("HH", "LL", "SH", "SL")):
        return "PBS"
    return code


def vendor_api_configured() -> bool:
    """True iff the vendor-match API URL is set (key may be required by the API)."""
    return bool(_api_url()) and _REQUESTS_OK


def fetch_vendor_catalog(inst_type: str) -> Optional[Dict[str, Any]]:
    """Return the RAW vendor-API response (``{success, instType, data:[...]}``)
    for an instrument type, or None if unconfigured / failed.

    Unlike :func:`fetch_vendor_fields` (which maps the single best match to
    canonical fields for the pipeline), this returns the full product list so
    the Studio "Select Vendor" dropdown can offer every option. It exists so the
    browser never has to hold the API key — the ``/api/v1/vendor-match`` proxy
    calls this server-side (FEATURES #124).
    """
    base = _api_url()
    key = _api_key()
    code = (inst_type or "").upper().strip()
    if not base or not _REQUESTS_OK or not code:
        return None
    try:
        # Use full URL if it ends with /api/qong-instrument, otherwise append it
        url = base if base.endswith("/api/qong-instrument") else f"{base}/api/qong-instrument"
        resp = _requests.post(
            url,
            json={"instType": code},
            headers={
                "X-API-KEY": key,
                "Accept": "application/json",
                "ngrok-skip-browser-warning": "true",
            },
            timeout=8,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("vendor_match_client: catalog fetch failed for %s — %s", code, exc)
        return None


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
        # Use full URL if it ends with /api/qong-instrument, otherwise append it
        url = base if base.endswith("/api/qong-instrument") else f"{base}/api/qong-instrument"
        resp = _requests.post(
            url,
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

    raw = data.get("data") or data.get("matches") or []
    if isinstance(raw, list):
        match = raw[0] if raw else {}
    else:
        match = raw  # single-product response: data is already a dict

    if not match or not isinstance(match, dict):
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
        "io_output":              _clean_io_output(_str(match.get("io_output"))),
        "external_power_supply":  _str(match.get("external_power_supply")),
        "certificate":            _str(match.get("certificate")),
        # Private — used to build VendorMatch (not stored in fields)
        "_vendor_name":           _str(match.get("manufacturer") or match.get("vendor_name")),
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


# API field-name -> existing IDS-schema column-name aliases, for the handful
# of columns where the vendor API's snake_case name differs from the name
# already used in webapp/deliverables/ids_schema.py. The schema/UI field
# names are NOT changed — this table is the only translation layer.
_DATASHEET_FIELD_ALIASES: Dict[str, str] = {
    "schedule":                      "line_schedule",
    "pipe_insulation":               "insulation",
    "hazardous_area_classification": "area_classification",
    "category":                      "ignition_group",
    "process_conn_size":             "proc_conn_size",
    "process_conn_type":             "proc_conn_type",
    "process_conn_location":         "proc_conn_location",
    "seal_bolting_material":         "bolting_material_seal",
}

# The API splits dial size into two fields; the schema has one "dial_size"
# column, so they're combined ("100 mm") before matching.
_DIAL_SIZE_VALUE_KEY = "dial_size_value"
_DIAL_SIZE_UNIT_KEY = "dial_size_unit"
_DIAL_SIZE_COL = "dial_size"

# Vendor-identity keys: never stored as a plain field, consumed separately to
# build entity.vendor_match.
_IDENTITY_API_KEYS = {"manufacturer", "model_number", "product_id"}


def _schema_col_index(sub_class: str) -> Tuple[set, set]:
    """(process_cols, vendor_cols) column names for this datasheet type.

    process_cols -> destined for entity.fields["ids_<col>"]
    vendor_cols  -> destined for entity.vendor_match.catalog_fields[<col>]

    Built by walking ``get_ids_sections_for_type`` (the schema module) itself,
    so every field already defined there — for every instrument type — is
    picked up automatically. Nothing here needs updating when the schema
    changes or a new type is added.
    """
    from webapp.deliverables.ids_schema import get_ids_sections_for_type

    process_cols: set = set()
    vendor_cols: set = set()
    for section in get_ids_sections_for_type(sub_class):
        for field in section.fields:
            if field.path.startswith("fields.ids_"):
                process_cols.add(field.path[len("fields.ids_"):])
            elif field.path.startswith("vendor_match.catalog_fields."):
                vendor_cols.add(field.path[len("vendor_match.catalog_fields."):])
    return process_cols, vendor_cols


def fetch_vendor_datasheet(inst_type: str) -> Optional[Dict[str, Any]]:
    """Fetch the full datasheet from /api/instrument-datasheet and map every
    field it returns onto the existing IDS schema for ``inst_type`` (e.g.
    "PG", "PT") — schema-driven, so any field the API returns is displayed
    automatically as long as a matching schema column already exists; no
    per-type field list to maintain here.

    Returns a dict in the format expected by entities.py and datasheet.py:
      - ``ids_*`` keys  → go into entity.fields  (e.g. "ids_ambient_temp_min")
      - ``_vendor_name``, ``_model_number``, ``_product_id``  → private, used to
        build entity.vendor_match identity
      - all other keys  → go into entity.vendor_match.catalog_fields; keys
        match the IDS schema's vendor catalog sub-keys exactly

    Returns None if API not configured, call fails, or no fields matched.
    """
    base = _api_url()
    key = _api_key()
    code = (inst_type or "").upper().strip()
    if not base or not _REQUESTS_OK or not code:
        return None

    if code in _datasheet_cache:
        return _datasheet_cache[code]

    try:
        resp = _requests.post(
            f"{base}/api/instrument-datasheet",
            json={"instType": code},
            headers={
                "X-API-KEY": key,
                "Accept": "application/json",
                "ngrok-skip-browser-warning": "true",
            },
            timeout=8,
        )
        resp.raise_for_status()
        api_data = resp.json()
    except Exception as exc:
        log.warning("vendor_match_client: datasheet fetch failed for %s — %s", code, exc)
        _datasheet_cache[code] = None
        return None

    if not api_data.get("success"):
        _datasheet_cache[code] = None
        return None

    raw = api_data.get("data") or {}
    if not isinstance(raw, dict):
        _datasheet_cache[code] = None
        return None

    def _s(v: Any) -> str:
        return str(v).strip() if v is not None else ""

    process_cols, vendor_cols = _schema_col_index(code)

    result: Dict[str, Any] = {}

    if raw.get("manufacturer"):
        result["_vendor_name"] = _s(raw.get("manufacturer"))
    if raw.get("model_number"):
        result["_model_number"] = _s(raw.get("model_number"))
    if raw.get("product_id") is not None and raw.get("product_id") != "":
        result["_product_id"] = _s(raw.get("product_id"))

    # dial_size_value + dial_size_unit -> single "dial_size" schema field.
    if _DIAL_SIZE_COL in vendor_cols and (
        raw.get(_DIAL_SIZE_VALUE_KEY) is not None or raw.get(_DIAL_SIZE_UNIT_KEY)
    ):
        combined = " ".join(
            p for p in (_s(raw.get(_DIAL_SIZE_VALUE_KEY)), _s(raw.get(_DIAL_SIZE_UNIT_KEY))) if p
        )
        if combined:
            result[_DIAL_SIZE_COL] = combined

    skip_keys = _IDENTITY_API_KEYS | {_DIAL_SIZE_VALUE_KEY, _DIAL_SIZE_UNIT_KEY}
    for api_key_name, value in raw.items():
        if api_key_name in skip_keys or value is None or value == "":
            continue
        col = _DATASHEET_FIELD_ALIASES.get(api_key_name, api_key_name)
        if col in process_cols:
            result[f"ids_{col}"] = _s(value)
        elif col in vendor_cols:
            result[col] = _s(value)
        # else: API returned a field with no matching schema column — skip.

    if not result:
        _datasheet_cache[code] = None
        return None

    log.info(
        "vendor_match_client: datasheet %s → %d fields mapped, vendor=%s model=%s",
        code, len(result), result.get("_vendor_name", ""), result.get("_model_number", ""),
    )
    _datasheet_cache[code] = result
    return result

