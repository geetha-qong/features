"""
Graph node enrichment — runs after extract_graph() writes canonical_graph.json.

Populates 8 fields on every node using deterministic rules + OCR:
  wet_dry, state_0, state_1, interlock,
  alarm_hh, alarm_h, alarm_l, alarm_ll

Rules:
- Wet/Dry  : from instrument type code extracted from tag, fallback to class/io_type
- State 0/1: from device category (all binary devices → "0 = OFF / Open" / "1 = ON / Closed")
- Interlock: inst_sis node → Yes; node connected_to an inst_sis tag → Yes
- Alarms   : OCR expanded bbox on full-page image (inst_* nodes only)

canonical.json is READ ONLY — never modified here.
Neo4j is not touched.
"""
from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── IO output cleanup ─────────────────────────────────────────────────────────

_MA_RE = re.compile(r'4[-–]20\s*mA', re.IGNORECASE)

def _clean_io_output(raw: str) -> str:
    """Strip bus-protocol prefixes: "RS485 + 4-20mA" → "4-20mA"."""
    if _MA_RE.search(raw):
        return "4-20mA"
    return raw


# ── Type-code buckets ─────────────────────────────────────────────────────────

_WET_CODES = {
    "FT","FI","FIT","FIC","FM","FC","FQ","FQI",
    "PT","PI","PIT","PIC","PG","PGI",
    "TT","TI","TIT","TIC","TE",
    "LT","LI","LIT","LIC",
    "AT","AI","AIT","AIC",
    "PDT","PDI","PDIT","PDIC",
    "PZT","PZI","PZIT","PZIC",
    "WT","WI","WIT",
    "FE",
}

_DRY_CODES = {
    "PSH","PSL","PS","PAH","PAL","PAHL",
    "LSH","LSL","LS","LAH","LAL","LAHL",
    "FSH","FSL","FS","FAH","FAL","FAHL",
    "TSH","TSL","TS","TAH","TAL","TAHL",
    "HSH","HSL","HS","HV",
    "BV","CV","MOV","SOV","ZV","XV",
    "FCV","LCV","PCV","TCV","PV",
    "DB","CK",
}

_ALARM_CODES = {
    "PZA","PZAL","PZAH","PAH","PAL","FAH","FAL",
    "LAH","LAL","TAH","TAL","AAH","AAL",
}

_SWITCH_CODES = {
    "PSH","PSL","PS","LSH","LSL","LS","FSH","FSL","FS",
    "TSH","TSL","TS","HS","PAH","PAL","FAH","FAL",
    "LAH","LAL","TAH","TAL","PZA","PZAL","PZAH",
}

_VALVE_CLASSES = {"valve_bv","valve_db","valve_ck","valve_gl","valve_cv","valve_mov"}
_VALVE_CODES   = {"BV","CV","MOV","SOV","ZV","XV","FCV","LCV","PCV","TCV","PV","DB","CK","GL"}

# ── Instrument service description + location (pump/motor template) ────────────
# Based on oil & gas Motor & Pump Instrumentation standard:
# suction/discharge PG/PT → PUMP PRESS; PDI → STRAINER DIFF PRESS; etc.
_INST_SERVICE_DESC: Dict[str, str] = {
    # Pressure
    "PG":   "PUMP PRESS",
    "PI":   "PUMP PRESS",
    "PT":   "PUMP PRESS",
    "PIT":  "PUMP PRESS",
    "PDI":  "STRAINER DIFF PRESS",
    "PDT":  "STRAINER DIFF PRESS",
    "PDIT": "STRAINER DIFF PRESS",
    # Flow
    "FT":   "FLOW",
    "FIT":  "FLOW",
    "FI":   "FLOW",
    "FM":   "FLOW",
    # Level
    "LT":   "LEVEL",
    "LIT":  "LEVEL",
    "LG":   "SEAL FLUID LEVEL",
    "LI":   "LEVEL",
    "LS":   "LEVEL SWITCH",
    "LSH":  "LEVEL SWITCH HIGH",
    "LSL":  "LEVEL SWITCH LOW",
    # Temperature
    "TI":   "BEARING TEMP",
    "TE":   "BEARING TEMP",
    "TIT":  "BEARING TEMP",
    "TT":   "TEMP",
    # Vibration
    "XT":   "VIBRATION",
    "XIT":  "VIBRATION",
    # Position / valve
    "ZI":   "CHECK VALVE STATUS",
    "ZT":   "VALVE POSITION",
    "ZIT":  "VALVE POSITION",
    # Current
    "II":   "MOTOR CURRENT",
    "IIT":  "MOTOR CURRENT",
}

# Local = read on-site (gauge/glass); Field = transmits signal; Panel = control room
_INST_LOCATION: Dict[str, str] = {
    "PG": "LOCAL",  "PI": "LOCAL",  "PDI": "LOCAL",
    "LG": "LOCAL",  "LI": "LOCAL",
    "TG": "LOCAL",  "TI": "LOCAL",
    "ZI": "LOCAL",
    "PT": "FIELD",  "PIT": "FIELD", "PDT": "FIELD", "PDIT": "FIELD",
    "FT": "FIELD",  "FIT": "FIELD", "FM":  "FIELD",
    "LT": "FIELD",  "LIT": "FIELD",
    "TT": "FIELD",  "TIT": "FIELD", "TE":  "FIELD",
    "XT": "FIELD",  "XIT": "FIELD",
    "ZT": "FIELD",  "ZIT": "FIELD",
    "LS": "FIELD",  "LSH": "FIELD", "LSL": "FIELD",
    "II": "PANEL",  "IIT": "PANEL",
}

# YOLO detection class → control-system classification (authoritative)
_YOLO_SYSTEM_MAP: Dict[str, str] = {
    "inst_sis":         "SIS",
    "SIS-R":            "SIS",
    "interlock":        "SIS",
    "inst_bpcs":        "BPCS",
    "inst_field":       "FIELD",
    "inst_local_panel": "FIELD",
}


def _type_code(tag: Optional[str]) -> str:
    if not tag:
        return ""
    tag = tag.upper()
    # With area code prefix: "62-FIT-8025" → "FIT"
    m = re.match(r"^\d+[-_]([A-Z]+)[-_]\d+", tag)
    if m:
        return m.group(1)
    # Without area code: "FIT-8025", "LS-8050", "LS-8057A" → "FIT", "LS"
    m = re.match(r"^([A-Z]+)[-_]\d+", tag)
    return m.group(1) if m else ""


# ── Wet / Dry ─────────────────────────────────────────────────────────────────

def _wet_dry(node: Dict[str, Any]) -> str:
    cls    = node.get("class", "")
    tag    = node.get("tag") or ""
    code   = _type_code(tag)
    iotype = node.get("io_type", "")

    if cls in ("Motor", "Pump/Dwg Pump"):
        return "Wet"
    # Sight glass on an inst_* node → no electrical output
    if code == "GL" and cls.startswith("inst_"):
        return ""
    if code in _WET_CODES:
        return "Wet"
    if code in _DRY_CODES:
        return "Dry"
    if code in _ALARM_CODES:
        return "Wet" if iotype in ("AI", "AO") else "Dry"
    if cls in _VALVE_CLASSES:
        return "Dry"
    if cls.startswith("inst_"):
        if iotype in ("AI", "AO"):
            return "Wet"
        if iotype in ("DI", "DO"):
            return "Dry"
    return ""


# ── State 0 / State 1 ─────────────────────────────────────────────────────────

def _states(node: Dict[str, Any]) -> Tuple[str, str]:
    cls  = node.get("class", "")
    tag  = node.get("tag") or ""
    code = _type_code(tag)

    if cls in _VALVE_CLASSES or code in _VALVE_CODES:
        return "OFF / Open", "ON / Closed"
    if cls in ("Motor", "Pump/Dwg Pump"):
        return "OFF / Open", "ON / Closed"
    if code in _SWITCH_CODES:
        return "OFF / Open", "ON / Closed"
    # Transmitters / elements → analog, no binary state
    if code in _WET_CODES:
        return "", ""
    if cls.startswith("inst_"):
        iotype = node.get("io_type", "")
        if iotype == "AI":
            return "", ""
        if iotype == "DO":
            return "OFF / Open", "ON / Closed"
        if iotype == "DI":
            return "OFF / Open", "ON / Closed"
    return "", ""


# ── Interlock ─────────────────────────────────────────────────────────────────

def _build_interlock_index(nodes: List[Dict[str, Any]]) -> set:
    """Return the set of tags that belong to inst_sis nodes."""
    return {n["tag"] for n in nodes if n.get("class") == "inst_sis" and n.get("tag")}


def _interlock(node: Dict[str, Any], sis_tags: set) -> str:
    if node.get("class") == "inst_sis":
        return "Yes"
    for t in node.get("connected_to", []):
        if t in sis_tags:
            return "Yes"
    return ""


# ── OCR alarm detection ───────────────────────────────────────────────────────

_HH_RE  = re.compile(r'\bHH\b', re.IGNORECASE)
_LL_RE  = re.compile(r'\bLL\b', re.IGNORECASE)
_H_RE   = re.compile(r'\bH\b',  re.IGNORECASE)
_L_RE   = re.compile(r'\bL\b',  re.IGNORECASE)
_SET_RE = re.compile(r'SET\s*@?\s*[\d.,]+[^\s]*', re.IGNORECASE)


def _ocr_alarms(
    node: Dict[str, Any],
    page_img,           # PIL Image, already loaded
    ocr_fn,            # callable(np.ndarray) → rapidocr result
    img_w: int,
    img_h: int,
    pad: int = 80,
) -> Tuple[str, str, str, str, str]:
    """Return (alarm_hh, alarm_h, alarm_l, alarm_ll, remark) from OCR."""
    import numpy as np
    from PIL import ImageFilter

    bbox = node.get("bbox", [])
    if not bbox or len(bbox) < 4:
        return "", "", "", "", ""

    x1 = max(0, int(bbox[0]) - pad)
    y1 = max(0, int(bbox[1]) - pad)
    x2 = min(img_w, int(bbox[2]) + pad)
    y2 = min(img_h, int(bbox[3]) + pad)
    if x2 - x1 < 5 or y2 - y1 < 5:
        return "", "", "", "", ""

    crop = page_img.crop((x1, y1, x2, y2))
    crop = crop.filter(ImageFilter.SHARPEN)
    crop = crop.resize((crop.width * 2, crop.height * 2))
    arr  = np.array(crop)

    try:
        result = ocr_fn(arr)
    except Exception:
        return "", "", "", "", ""

    texts = []
    if result and result[0]:
        for line in result[0]:
            if line and len(line) >= 2:
                texts.append(str(line[1]))

    hh = h = l = ll = remark = ""
    for t in texts:
        if _HH_RE.search(t):
            hh = "Yes"
        elif _LL_RE.search(t):
            ll = "Yes"
        elif _H_RE.search(t):
            h  = "Yes"
        elif _L_RE.search(t):
            l  = "Yes"
        m = _SET_RE.search(t)
        if m:
            remark = m.group(0).strip()
    return hh, h, l, ll, remark


# ── Canonical.json enrichment (cyan dots) ─────────────────────────────────────

# Graph node key → canonical.json entity.fields key
_NODE_TO_CANON_FIELD: Dict[str, str] = {
    "wet_dry":   "wet_dry",
    "state_0":   "state_0",
    "state_1":   "state_1",
    "interlock": "interlock",
    "alarm_hh":  "alarm_high_high",
    "alarm_h":   "alarm_high",
    "alarm_l":   "alarm_low",
    "alarm_ll":  "alarm_low_low",
}

# entity_overrides field_names for the above — deleted when we write natively
_ENRICHED_OVERRIDE_FIELDS = {
    "fields.wet_dry", "fields.state_0", "fields.state_1", "fields.interlock",
    "fields.alarm_high_high", "fields.alarm_high", "fields.alarm_low", "fields.alarm_low_low",
    "fields.io_output",
}


def apply_enrichment_to_canonical(job_dir: str, job_id: int, db: Any) -> Dict[str, Any]:
    """
    Write enriched fields from canonical_graph.json directly into canonical.json
    so they appear as cyan (pipeline-native) in the Bulk Review UI.

    Also cleans io_output ("RS485 + 4-20mA" → "4-20mA") in place.

    Then deletes any previously-pushed entity_overrides for these fields so
    old pink dots don't linger after a re-run.
    """
    from webapp.models import EntityOverride

    graph_path = Path(job_dir) / "canonical_graph.json"
    canon_path = Path(job_dir) / "canonical.json"

    if not graph_path.exists() or not canon_path.exists():
        return {"skipped": 1}

    with open(graph_path) as f:
        graph = json.load(f)
    with open(canon_path) as f:
        canon = json.load(f)

    # entity_id → first graph node for that entity
    node_by_eid: Dict[str, Dict] = {}
    for node in graph.get("nodes", []):
        eid = node.get("entity_id")
        if eid and eid not in node_by_eid:
            node_by_eid[eid] = node

    updated = 0
    for entity in canon.get("entities", []):
        if entity.get("entity_class") != "instrument":
            continue
        eid = str(entity.get("entity_id", ""))
        if not eid:
            continue

        fields = entity.setdefault("fields", {})
        changed = False

        node = node_by_eid.get(eid)
        if node:
            for node_key, canon_key in _NODE_TO_CANON_FIELD.items():
                val = str(node.get(node_key) or "").strip()
                if val and val.lower() not in ("null", "none"):
                    fields[canon_key] = val
                    changed = True
            # Map YOLO class → system (authoritative, overrides _classify_system heuristic)
            sys_val = _YOLO_SYSTEM_MAP.get(node.get("class", ""))
            if sys_val:
                fields["system"] = sys_val
                changed = True

        # Clean io_output in-place
        raw_io = str(fields.get("io_output") or "").strip()
        cleaned = _clean_io_output(raw_io)
        if cleaned != raw_io:
            fields["io_output"] = cleaned
            changed = True

        if changed:
            updated += 1

    # Fallback: system from YOLO class for instrument entities not matched via entity_id.
    # Uses tag → graph node lookup for nodes that lack entity_id linkage.
    _tag_to_inst_node: Dict[str, Dict] = {}
    for node in graph.get("nodes", []):
        cls = node.get("class", "")
        if cls in _YOLO_SYSTEM_MAP and node.get("tag") and not node.get("entity_id"):
            _tag_to_inst_node[node["tag"]] = node
    for entity in canon.get("entities", []):
        if entity.get("entity_class") != "instrument":
            continue
        if entity.get("fields", {}).get("system"):
            continue  # already set in primary pass above
        node = _tag_to_inst_node.get(entity.get("tag") or "")
        if node:
            sys_val = _YOLO_SYSTEM_MAP.get(node.get("class", ""))
            if sys_val:
                entity.setdefault("fields", {})["system"] = sys_val

    # Instrument service_description + location from pump/motor template.
    # Runs on every entity regardless of graph linkage — uses type code only.
    # Only overwrites if:
    #   - service_description is empty or contains " on NA" (generic pipeline placeholder)
    #   - location is not yet set
    for entity in canon.get("entities", []):
        if entity.get("entity_class") != "instrument":
            continue
        fields = entity.setdefault("fields", {})
        tag = entity.get("tag") or ""
        code = _type_code(tag)

        # Fix "on NA" or missing service_description
        existing_sd = str(fields.get("service_description") or "")
        if (not existing_sd or " on NA" in existing_sd) and code:
            template_desc = _INST_SERVICE_DESC.get(code)
            if template_desc:
                fields["service_description"] = template_desc
                updated += 1

        # Set location if not already present
        if not fields.get("location"):
            fields["location"] = _INST_LOCATION.get(code, "FIELD")
            updated += 1

    # Propagate tags + parsed fields from Pass 3 graph nodes into equipment entities.
    # Pass 3 writes tag + oil-gas fields → canonical_graph.json node; copy into canonical.json.
    # Parsed fields go into entity["fields"] so the equipment list CSV/XLSX can render them.
    _GRAPH_TO_FIELDS = (
        "unit_number", "area_code", "train_suffix",
        "is_duty", "is_standby", "parallel_tag",
        "parallel_node_id", "related_instruments",
        "service_description",
    )

    def _normalise_graph_field(field: str, val):
        """Normalise a value copied from a graph node before writing to entity.fields."""
        if field == "service_description" and isinstance(val, str):
            return " ".join(val.split()).upper()
        return val
    equip_tags_applied = 0
    for entity in canon.get("entities", []):
        if entity.get("entity_class") != "equipment":
            continue
        eid = str(entity.get("entity_id", ""))
        if not eid:
            continue
        node = node_by_eid.get(eid)
        if not node:
            continue
        # Set tag only if not already present
        if not entity.get("tag") and node.get("tag"):
            entity["tag"] = node["tag"]
            equip_tags_applied += 1
        # Always sync parsed fields — even if tag was already set on a prior run
        if "fields" not in entity or not isinstance(entity["fields"], dict):
            entity["fields"] = {}
        for field in _GRAPH_TO_FIELDS:
            val = node.get(field)
            if val is not None:
                entity["fields"][field] = _normalise_graph_field(field, val)

    # Fallback 1: tag-based sync for graph nodes whose entity_id wasn't linked.
    # Build best-node-per-tag index (highest confidence wins for duplicates).
    tagged_nodes_by_tag: Dict[str, Dict] = {}
    for node in graph.get("nodes", []):
        if not node.get("entity_id") and node.get("tag"):
            tag = node["tag"]
            existing = tagged_nodes_by_tag.get(tag)
            if not existing or float(node.get("confidence", 0)) > float(existing.get("confidence", 0)):
                tagged_nodes_by_tag[tag] = node

    for entity in canon.get("entities", []):
        if entity.get("entity_class") != "equipment":
            continue
        etag = entity.get("tag")
        if not etag:
            continue
        node = tagged_nodes_by_tag.get(etag)
        if not node:
            continue
        if "fields" not in entity or not isinstance(entity["fields"], dict):
            entity["fields"] = {}
        for field in _GRAPH_TO_FIELDS:
            val = node.get(field)
            if val is not None:
                entity["fields"][field] = _normalise_graph_field(field, val)

    # Fallback 2: bbox-proximity match for untagged canonical entities.
    # Graph nodes with tags but no entity_id may correspond to canonical entities
    # whose entity_id wasn't wired during graph extraction (happens on older jobs).
    # Match by centroid distance; assign tag + fields if within 80px (page coords).
    _CLASS_MAP = {"Pump/Dwg Pump": "pump", "Motor": "motor"}
    unmatched_tagged_nodes = [
        n for n in graph.get("nodes", [])
        if not n.get("entity_id") and n.get("tag") and n.get("bbox")
        and n.get("class") in _CLASS_MAP
    ]
    if unmatched_tagged_nodes:
        def _centroid(bbox):
            x1, y1, x2, y2 = bbox
            return ((x1 + x2) / 2, (y1 + y2) / 2)

        for entity in canon.get("entities", []):
            if entity.get("entity_class") != "equipment" or entity.get("tag"):
                continue
            ebbox = entity.get("bbox")
            if not ebbox:
                continue
            ecx, ecy = _centroid(ebbox)
            best_node, best_dist = None, float("inf")
            for node in unmatched_tagged_nodes:
                ncx, ncy = _centroid(node["bbox"])
                dist = ((ecx - ncx) ** 2 + (ecy - ncy) ** 2) ** 0.5
                if dist < best_dist:
                    best_node, best_dist = node, dist
            if best_node and best_dist < 80:
                entity["tag"] = best_node["tag"]
                equip_tags_applied += 1
                if "fields" not in entity or not isinstance(entity["fields"], dict):
                    entity["fields"] = {}
                for field in _GRAPH_TO_FIELDS:
                    val = best_node.get(field)
                    if val is not None:
                        entity["fields"][field] = _normalise_graph_field(field, val)

    # Augment canonical.json with YOLO-detected equipment that has no tag/entity_id.
    # Motors and pumps are detected by YOLO but often lack tag numbers in the P&ID,
    # so they never appear in equipment_list.csv. Add them here so the Equipment List
    # deliverable shows them.
    _YOLO_EQUIP_LABELS: Dict[str, str] = {"Motor": "motor", "Pump/Dwg Pump": "pump"}

    existing_equip_bboxes: set = set()
    for entity in canon.get("entities", []):
        if entity.get("entity_class") == "equipment":
            bbox = entity.get("bbox")
            if bbox:
                existing_equip_bboxes.add(tuple(round(float(v), 1) for v in bbox))

    equip_added = 0
    for node in graph.get("nodes", []):
        cls = node.get("class", "")
        sub = _YOLO_EQUIP_LABELS.get(cls)
        if not sub:
            continue
        if node.get("entity_id"):
            continue  # already matched to an existing equipment entity
        bbox = node.get("bbox") or [0.0, 0.0, 0.0, 0.0]
        bbox_key = tuple(round(float(v), 1) for v in bbox)
        if bbox_key in existing_equip_bboxes:
            continue  # de-duplicate across re-runs
        existing_equip_bboxes.add(bbox_key)
        det_key = f"{job_id}:yolo-equip:{cls}:{bbox}"
        eid = str(uuid.uuid5(uuid.NAMESPACE_DNS, det_key))
        canon.setdefault("entities", []).append({
            "entity_id": eid,
            "entity_class": "equipment",
            "sub_class": sub,
            "tag": None,
            "pid_number": "",
            "sheet_number": 1,
            "bbox": [float(v) for v in bbox],
            "fields": {"equipment_type": sub, "service_duty": ""},
            "vendor_match": None,
        })
        equip_added += 1

    # Deduplicate equipment entities sharing the same tag (tile-overlap YOLO detections
    # can produce the same physical pump/motor twice with the same Pass 3 tag). Keep the
    # one with highest YOLO confidence from the graph node. Never touch null-tag entities.
    equip_deduped = 0
    tag_to_equip_indices: Dict[str, list] = {}
    for i, entity in enumerate(canon.get("entities", [])):
        if entity.get("entity_class") != "equipment":
            continue
        tag = entity.get("tag")
        if not tag:
            continue  # do not deduplicate untagged entities
        tag_to_equip_indices.setdefault(tag, []).append(i)

    remove_indices: set = set()
    for tag, indices in tag_to_equip_indices.items():
        if len(indices) <= 1:
            continue
        def _conf(idx: int, _canon=canon, _nbe=node_by_eid) -> float:
            eid = str(_canon["entities"][idx].get("entity_id", ""))
            node = _nbe.get(eid)
            return float(node.get("confidence", 0)) if node else 0.0
        best = max(indices, key=_conf)
        for idx in indices:
            if idx != best:
                remove_indices.add(idx)

    if remove_indices:
        canon["entities"] = [
            e for i, e in enumerate(canon["entities"])
            if i not in remove_indices
        ]
        equip_deduped = len(remove_indices)
        print(f"  dedup: removed {equip_deduped} duplicate equipment entities "
              f"(same tag, kept highest confidence)")

    # General equipment tag parser: extract unit_number and area_code for ANY
    # equipment class (strainer, heat_exchanger, vessel, etc.) whose tag wasn't
    # handled by parse_equipment_tag() which only covers P/M.
    # Format: [AA-]X[-]NNNNNN  e.g. 62-S-151000, HE-101, V-2001A
    _EQUIP_TAG_RE = re.compile(
        r'^(?:(?P<area>\d{2,4})-)?[A-Z]+-(?P<unit>\d{3,6})[A-Z]?$'
    )
    for entity in canon.get("entities", []):
        if entity.get("entity_class") != "equipment":
            continue
        fields = entity.setdefault("fields", {})
        if not fields.get("unit_number"):
            tag = entity.get("tag") or ""
            m = _EQUIP_TAG_RE.match(tag.strip())
            if m:
                fields["unit_number"] = m.group("unit")[:2]
                if m.group("area") and not fields.get("area_code"):
                    fields["area_code"] = m.group("area")

    # Truncate unit_number to first 2 digits for all equipment (covers values
    # set by both the _EQUIP_TAG_RE fallback above and Pass 3 graph node sync).
    for entity in canon.get("entities", []):
        if entity.get("entity_class") != "equipment":
            continue
        fields = entity.setdefault("fields", {})
        u = fields.get("unit_number")
        if u and str(u).strip():
            fields["unit_number"] = str(u).strip()[:2]

    # Post-process equipment entities: set service_description from service_duty
    # if not already set by Pass 3. Location always defaults to FIELD.
    for entity in canon.get("entities", []):
        if entity.get("entity_class") != "equipment":
            continue
        fields = entity.setdefault("fields", {})
        # Promote legacy service_duty text to service_description if it looks like real text
        # (not the generic "Pump"/"Motor" YOLO class name injected by enrichment)
        if not fields.get("service_description"):
            sd = str(fields.get("service_duty") or "")
            if sd and sd.lower() not in ("", "pump", "motor"):
                fields["service_description"] = " ".join(sd.split()).upper()
        # Duty/standby-aware fallback for equipment with no specific description
        if not fields.get("service_description") or fields.get("service_description") in ("PUMP", "MOTOR"):
            sub    = str(entity.get("sub_class") or "").upper()  # "PUMP" or "MOTOR"
            is_duty    = fields.get("is_duty")
            is_standby = fields.get("is_standby")
            if sub:
                if is_duty:
                    fields["service_description"] = f"DUTY {sub}"
                elif is_standby:
                    fields["service_description"] = f"STANDBY {sub}"
                else:
                    fields["service_description"] = f"PROCESS {sub}"

        # Location: default to FIELD for all equipment without an explicit location
        if not fields.get("location"):
            fields["location"] = "FIELD"

    # Cross-propagate service_description between pump↔motor pairs sharing unit_number.
    # When a motor has "PW TRANSFER PUMPS" but the matched pump only has "PROCESS PUMP",
    # set both to the more informative description.
    _GENERIC = {"PROCESS PUMP", "PROCESS MOTOR", "DUTY PUMP", "STANDBY PUMP", "DUTY MOTOR", "STANDBY MOTOR"}
    equip_by_unit: Dict[str, list] = {}
    for entity in canon.get("entities", []):
        if entity.get("entity_class") != "equipment":
            continue
        unit = entity.get("fields", {}).get("unit_number") or ""
        if unit:
            equip_by_unit.setdefault(unit, []).append(entity)
    for unit, group in equip_by_unit.items():
        if len(group) < 2:
            continue
        real_desc = next(
            (e["fields"].get("service_description") for e in group
             if e["fields"].get("service_description") not in _GENERIC and e["fields"].get("service_description")),
            None,
        )
        if real_desc:
            for entity in group:
                if entity["fields"].get("service_description") in _GENERIC:
                    entity["fields"]["service_description"] = real_desc

    # Backfill missing pid_number for equipment entities from the most common
    # non-empty pid_number among equipment peers. Graph-extracted pump/motor nodes
    # are added without a pid_number; fill them in so the equipment list shows the
    # same drawing reference on every row.
    from collections import Counter as _Counter
    equip_pid_counts = _Counter(
        e.get("pid_number") for e in canon.get("entities", [])
        if e.get("entity_class") == "equipment" and e.get("pid_number")
    )
    if not equip_pid_counts:
        # Fallback: use most common pid across all entities
        equip_pid_counts = _Counter(
            e.get("pid_number") for e in canon.get("entities", [])
            if e.get("pid_number")
        )
    if equip_pid_counts:
        dominant_pid = equip_pid_counts.most_common(1)[0][0]
        for entity in canon.get("entities", []):
            if entity.get("entity_class") == "equipment" and not entity.get("pid_number"):
                entity["pid_number"] = dominant_pid

    # Backfill entity bboxes from YOLO detections for entities that still have
    # the placeholder [0,0,0,0] bbox. Detections carry real pixel coordinates;
    # canonical entities from the LLM extraction always start with zeros.
    # This enables spatial features (jump-to, search highlight) for pumps/motors
    # that were matched via class-compatibility (FIFO) in _attach_entity_ids.
    try:
        from webapp.models import Job as _Job
        from webapp.routers.api_v1 import _attach_entity_ids as _aei, _normalize_detection_shape as _nds
        import json as _json
        _job = db.query(_Job).filter(_Job.id == job_id).first()
        if _job and _job.gpu_detections:
            _raw = _json.loads(_job.gpu_detections) if isinstance(_job.gpu_detections, str) else list(_job.gpu_detections)
            if _raw:
                _nds(_raw)
                # Build lightweight entity proxies for matching
                class _E:
                    def __init__(self, e):
                        self.entity_id = e["entity_id"]
                        self.entity_class = e.get("entity_class")
                        self.sub_class = e.get("sub_class")
                        self.tag = e.get("tag")
                _proxies = [_E(e) for e in canon.get("entities", []) if e.get("entity_id")]
                _aei(_raw, _proxies)
                # Map entity_id → first detection bbox
                _eid_to_bbox = {}
                for _d in _raw:
                    _eid = _d.get("entity_id")
                    _bb = _d.get("bbox")
                    if _eid and _bb and _eid not in _eid_to_bbox:
                        _eid_to_bbox[_eid] = _bb
                # Copy bbox into canonical entity when it's still zeros
                _bbox_backfilled = 0
                for _entity in canon.get("entities", []):
                    _eid = str(_entity.get("entity_id", ""))
                    if not _eid:
                        continue
                    _curr = _entity.get("bbox")
                    if _curr and _curr != [0.0, 0.0, 0.0, 0.0] and _curr != [0, 0, 0, 0]:
                        continue
                    _det_bbox = _eid_to_bbox.get(_eid)
                    if _det_bbox:
                        _entity["bbox"] = _det_bbox
                        _bbox_backfilled += 1
                if _bbox_backfilled:
                    print(f"  bbox_backfill: updated {_bbox_backfilled} entities from YOLO detections")
    except Exception as _bbox_err:
        print(f"  bbox_backfill: skipped ({_bbox_err})")

    with open(canon_path, "w") as f:
        json.dump(canon, f, indent=2)

    # Delete old entity_overrides for enriched fields — they're now in canonical.json
    # natively, so overrides would just add redundant pink dots.
    deleted = (
        db.query(EntityOverride)
        .filter(
            EntityOverride.job_id == job_id,
            EntityOverride.field_name.in_(_ENRICHED_OVERRIDE_FIELDS),
        )
        .delete(synchronize_session=False)
    )
    db.commit()

    return {"updated_entities": updated, "overrides_cleared": deleted, "yolo_equipment_added": equip_added, "equip_tags_applied": equip_tags_applied, "equip_deduped": equip_deduped}


# ── Public entry point ────────────────────────────────────────────────────────

def enrich_graph(job_dir: str) -> Dict[str, Any]:
    """
    Read canonical_graph.json from job_dir, enrich all nodes with the 8 fields,
    write back, and return a stats dict.

    canonical.json is read for existing alarm/remark data (read-only).
    Neo4j is not touched.
    """
    job_path   = Path(job_dir)
    graph_path = job_path / "canonical_graph.json"
    canon_path = job_path / "canonical.json"
    page_path  = job_path / "tmp" / "page_0_full.png"

    if not graph_path.exists():
        return {"skipped": "canonical_graph.json not found"}

    with open(graph_path) as f:
        graph = json.load(f)

    # Read canonical.json for existing alarm data (read-only)
    canon_alarms_by_tag: Dict[str, Dict] = {}
    if canon_path.exists():
        with open(canon_path) as f:
            canon = json.load(f)
        for e in canon.get("entities", []):
            tag = e.get("tag")
            if tag:
                canon_alarms_by_tag[tag] = e.get("fields", {})

    nodes    = graph.get("nodes", [])
    sis_tags = _build_interlock_index(nodes)

    # Set up OCR (optional — graceful degradation if unavailable)
    ocr_fn    = None
    page_img  = None
    img_w = img_h = 0
    if page_path.exists():
        try:
            from rapidocr_onnxruntime import RapidOCR
            from PIL import Image
            import PIL.Image
            PIL.Image.MAX_IMAGE_PIXELS = None  # suppress decompression bomb warning
            _ocr = RapidOCR()
            ocr_fn   = _ocr
            page_img = Image.open(page_path).convert("RGB")
            img_w, img_h = page_img.size
        except Exception as _e:
            pass  # OCR unavailable — alarms will be blank

    stats = {"wet": 0, "dry": 0, "interlock": 0,
             "alarm_hh": 0, "alarm_h": 0, "alarm_l": 0, "alarm_ll": 0,
             "ocr_available": ocr_fn is not None}

    for node in nodes:
        # ── Wet / Dry ──
        wd = _wet_dry(node)
        node["wet_dry"] = wd
        if wd == "Wet":   stats["wet"] += 1
        elif wd == "Dry": stats["dry"] += 1

        # ── State 0 / 1 ──
        s0, s1 = _states(node)
        node["state_0"] = s0
        node["state_1"] = s1

        # ── Interlock ──
        il = _interlock(node, sis_tags)
        node["interlock"] = il
        if il == "Yes":
            stats["interlock"] += 1

        # ── Alarms — OCR (instruments only) + canonical fallback ──
        is_inst = (not node.get("class", "").startswith("valve_")
                   and node.get("class") not in ("Motor", "Pump/Dwg Pump"))

        hh_o = h_o = l_o = ll_o = rem_o = ""
        if is_inst and ocr_fn and page_img:
            hh_o, h_o, l_o, ll_o, rem_o = _ocr_alarms(
                node, page_img, ocr_fn, img_w, img_h
            )

        # Canonical fields (read-only source of truth if present)
        cf = canon_alarms_by_tag.get(node.get("tag") or "", {})
        def _yn(v: Any) -> str:
            if not v or str(v).strip().upper() in ("", "NULL", "NONE", "-", "—", "NO", "N", "0", "FALSE"):
                return ""
            return "Yes"

        node["alarm_hh"] = _yn(cf.get("alarm_high_high")) or hh_o
        node["alarm_h"]  = _yn(cf.get("alarm_high"))      or h_o
        node["alarm_l"]  = _yn(cf.get("alarm_low"))       or l_o
        node["alarm_ll"] = _yn(cf.get("alarm_low_low"))   or ll_o

        existing_remark = node.get("remark") or ""
        new_remark = cf.get("remark") or rem_o
        if new_remark and new_remark not in existing_remark:
            node["remark"] = (existing_remark + " " + new_remark).strip() if existing_remark else new_remark
        elif not existing_remark:
            node["remark"] = new_remark or ""

        if node["alarm_hh"] == "Yes": stats["alarm_hh"] += 1
        if node["alarm_h"]  == "Yes": stats["alarm_h"]  += 1
        if node["alarm_l"]  == "Yes": stats["alarm_l"]  += 1
        if node["alarm_ll"] == "Yes": stats["alarm_ll"] += 1

    with open(graph_path, "w") as f:
        json.dump(graph, f, indent=2)

    stats["nodes"] = len(nodes)
    return stats
