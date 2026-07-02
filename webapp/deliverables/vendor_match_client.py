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


def fetch_vendor_datasheet(inst_type: str) -> Optional[Dict[str, Any]]:
    """Fetch full datasheet (40+ fields) from /api/instrument-datasheet.

    Returns a dict in the format expected by entities.py and datasheet.py:
      - ``ids_*`` keys  → go into entity.fields  (e.g. "ids_calibration_range_min")
      - ``_vendor_name``, ``_model_number``, ``_product_id``  → private, used to
        build entity.vendor_match identity
      - all other keys  → go into entity.vendor_match.catalog_fields; keys are
        the IDS catalog_fields sub-keys  (e.g. "output_signal_type",
        "enclosure_ip_rating", "proc_conn_size")

    Returns None if API not configured or call fails.
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

    # ── IDS direct fields (entity.fields["ids_*"]) ────────────────────────
    # Prefer instrument_range_* if present, fall back to measurement_*_value.
    inst_min  = _s(raw.get("instrument_range_min"))  or _s(raw.get("measurement_min_value"))
    inst_max  = _s(raw.get("instrument_range_max"))  or _s(raw.get("measurement_max_value"))
    inst_unit = _s(raw.get("instrument_range_unit")) or _s(raw.get("measurement_unit"))

    result: Dict[str, Any] = {
        # Vendor identity (consumed by entities.py / datasheet.py to build VendorMatch)
        "_vendor_name":   _s(raw.get("manufacturer")),
        "_model_number":  _s(raw.get("model_number")),
        "_product_id":    _s(raw.get("product_id")),
        # IDS entity.fields keys
        "ids_pipe_class":                        _s(raw.get("piping_class")),
        "ids_calibration_range_min":             _s(raw.get("calibration_range_min")),
        "ids_calibration_range_max":             _s(raw.get("calibration_range_max")),
        "ids_calibration_range_unit":            _s(raw.get("calibration_range_unit")),
        "ids_instrument_range_min":              inst_min,
        "ids_instrument_range_max":              inst_max,
        "ids_instrument_range_unit":             inst_unit,
        "ids_display_range_min":                 _s(raw.get("display_range_min")),
        "ids_display_range_max":                 _s(raw.get("display_range_max")),
        "ids_display_range_unit":                _s(raw.get("display_range_unit")),
        "ids_certification_special_requirement": _s(raw.get("hazardous_area_certification")),
        "ids_ambient_temp_min":                  _s(raw.get("ambient_temp_min")),
        "ids_ambient_temp_max":                  _s(raw.get("ambient_temp_max")),
        # Catalog fields — keys match IDS vendor_match.catalog_fields sub-keys exactly
        "body_flange_type":          _s(raw.get("body_flange_type")),
        "vent_valve":                _s(raw.get("vent_valve")),
        "drain_valve":               _s(raw.get("drain_valve")),
        "vent_drain_size":           _s(raw.get("vent_drain_size")),
        "proc_conn_size":            _s(raw.get("process_connection")) or _s(raw.get("connection_size")),
        "proc_conn_rating":          _s(raw.get("proc_conn_rating")),
        "mounting_type":             _s(raw.get("mounting_type")),
        "body_flange_material":      _s(raw.get("body_flange_material")),
        "vent_drain_material":       _s(raw.get("vent_drain_material")),
        "bolting_material":          _s(raw.get("bolting_material")),
        "gasket_oring_material":     _s(raw.get("gasket_oring_material")),
        "mounting_kit_material":     _s(raw.get("mounting_kit_material")),
        "detector_type":             _s(raw.get("detector_type")),
        "measurement_span_min":      _s(raw.get("measurement_span_min")),
        "measurement_span_max":      _s(raw.get("measurement_span_max")),
        "diaphragm_wetted_material": _s(raw.get("wetted_material")),
        "diaphragm_material":        _s(raw.get("diaphragm_material")),
        "fill_fluid_material":       _s(raw.get("fill_fluid")),
        "output_signal_type":        _s(raw.get("output_signal")),
        "enclosure_ip_rating":       _s(raw.get("ip_rating")),
        "enclosure_material":        _s(raw.get("enclosure_material")),
        "digital_communication":     _s(raw.get("communication_protocol")),
        "signal_power_supply":       _s(raw.get("power_supply")),
        "external_power_supply":     _s(raw.get("external_power_supply")),
        "integral_indicator_reqd":   _s(raw.get("integral_indicator_reqd")),
        "integral_indicator_type":   _s(raw.get("integral_indicator_type")),
        "signal_termination_type":   _s(raw.get("signal_termination_type")),
        "elect_conn_size":           _s(raw.get("elect_conn_size")),
        "elect_conn_type":           _s(raw.get("electrical_interface")),
        "smart_device_type":         _s(raw.get("smart_device_type")),
        "hardware_device_rev":       _s(raw.get("hardware_device_rev")),
        "dd_edd_rev":                _s(raw.get("dd_edd_rev")),
        "hart_version":              _s(raw.get("hart_version")),
        "itk_version":               _s(raw.get("itk_version")),
        "cff_rev":                   _s(raw.get("cff_rev")),
        "pressure_accuracy":         _s(raw.get("accuracy")),
        "zero_supply_elevation":     _s(raw.get("zero_supply_elevation")),
        "fill_fluid_sp_gr_temp":     _s(raw.get("fill_fluid_sp_gr_temp")),
        "seal_type":                 _s(raw.get("seal_type")),
        "diaphragm_extn_length":     _s(raw.get("diaphragm_extn_length")),
        "flush_conn_qty_size":       _s(raw.get("flush_conn_qty_size")),
        "seal_proc_conn_size":       _s(raw.get("seal_proc_conn_size")),
        "seal_proc_conn_rating":     _s(raw.get("seal_proc_conn_rating")),
        "seal_conn_type_std":        _s(raw.get("seal_conn_type_std")),
        "flushing_ring_reqd":        _s(raw.get("flushing_ring_reqd")),
        "flushing_ring_rating":      _s(raw.get("flushing_ring_rating")),
        "capillary_fitting_dia":     _s(raw.get("capillary_fitting_dia")),
        "instr_conn_nom_size":       _s(raw.get("instr_conn_nom_size")),
        "lower_housing_material":    _s(raw.get("lower_housing_material")),
        "upper_housing_material":    _s(raw.get("upper_housing_material")),
        "seal_bolting_material":     _s(raw.get("seal_bolting_material")),
        "seal_gasket_material":      _s(raw.get("seal_gasket_material")),
        "capillary_moc":             _s(raw.get("capillary_moc")),
        "seal_fill_fluid_material":  _s(raw.get("seal_fill_fluid_material")),
    }

    # Drop empty strings so callers can do a simple truthiness check
    result = {k: v for k, v in result.items() if v}

    if not result:
        _datasheet_cache[code] = None
        return None

    log.info("vendor_match_client: datasheet %s → %d fields, vendor=%s model=%s",
             code, len(result),
             result.get("_vendor_name", ""),
             result.get("_model_number", ""))
    _datasheet_cache[code] = result
    return result

