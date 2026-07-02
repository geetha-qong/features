"""Instrument-datasheet (IDS) field schema — single source of truth.

This module defines, per instrument type, the exact set of datasheet fields
(label + canonical path + provenance) used by BOTH:

  * the datasheet API surface (what fields are shown/editable in Qong Studio), and
  * the XLSX datasheet export.

Keeping one definition here means the API and the export can never drift.

The field names (snake_case columns), human labels, and provenance ("source")
are derived 1:1 from ``docs/instrument-fields-manifest.md`` (the column source of
truth). The grouping into readable sections follows
``docs/instrument-datasheet-fields.md``.

------------------------------------------------------------------------------
Canonical path rules (how a manifest column maps to a CanonicalEntity path)
------------------------------------------------------------------------------
A ``CanonicalEntity`` (see ``webapp/deliverables/canonical.py``) has:
  - ``tag``           (str)
  - ``pid_number``    (str)
  - ``sub_class``     (str)
  - ``fields``        (dict[str, Any])   -- process/user captured values
  - ``vendor_match``  (VendorMatch | None) with ``vendor_name``, ``product_name``,
                       ``part_number`` and a ``catalog_fields`` dict.

For each manifest column ``<col>`` with a given ``source``:

PROCESS / USER  -> editable=True
  Common-identity special cases that map onto EXISTING canonical fields:
    tag_no              -> "tag"
    service_description -> "fields.service_description"
    pid_no              -> "pid_number"
    location            -> "fields.location"
    unit_no             -> "fields.unit_number"
    equipment_no        -> "fields.equipment_no"
    line_no             -> "fields.line_no"
  All other process/user columns:
    <col>               -> "fields.ids_<col>"

VENDOR  -> editable=False
    manufacturer        -> "vendor_match.vendor_name"
    model_no            -> "vendor_match.product_name"
    all other vendor    -> "vendor_match.catalog_fields.<col>"

Slash sources in the manifest (e.g. ``PROCESS/USER``, ``VENDOR/PROCESS``,
``PROCESS/VENDOR``): the FIRST tag wins for both ``source`` and ``editable``
(process/user => editable True; vendor => editable False).

------------------------------------------------------------------------------
Implemented types (all 11 from the manifest): Common + CV, PT (shared by FT),
TT, PG, TG, TW, TE, FE, RO, PSV. Unknown sub_classes fall back to Common-only.
------------------------------------------------------------------------------
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


# --------------------------------------------------------------------------- #
# Public dataclasses
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class IdsField:
    header: str                        # human label, e.g. "Body Material"
    path: str                          # dot-notation canonical path (see module docstring)
    source: str                        # "process" | "user" | "vendor"
    editable: bool                     # True for process/user, False for vendor
    options: Optional[List[str]] = None  # if set, render as a dropdown select
    group: Optional[str] = None          # consecutive fields sharing the same group key render as one unified container


@dataclass(frozen=True)
class IdsSection:
    name: str
    fields: List[IdsField]


# Display labels keyed by normalized type key.
TYPE_LABELS: Dict[str, str] = {
    "CV": "Control Valve",
    "PT": "Pressure Transmitter",
    "TT": "Temperature Transmitter",
    "PG": "Pressure Gauge",
    "TG": "Temperature Gauge",
    "TW": "Thermowell",
    "TE": "Temperature Element / RTD",
    "FE": "Flow / Sight Glass",
    "RO": "Restriction Orifice",
    "PSV": "Pressure Safety Valve",
}

# Type keys that currently have a per-type schema implemented here.
SUPPORTED_SUBCLASSES = set(TYPE_LABELS.keys())


# --------------------------------------------------------------------------- #
# Normalization: canonical sub_class / ISA code -> datasheet type key
# --------------------------------------------------------------------------- #
# FT reuses the PT schema (DP-cell flow transmitter shares the PT form).
_SUBCLASS_ALIASES: Dict[str, str] = {
    # Control Valve
    "cv": "CV",
    "control": "CV",
    "control valve": "CV",
    # Pressure / Flow transmitter family (FT reuses PT)
    "pt": "PT",
    "pit": "PT",
    "pzit": "PT",
    "pzt": "PT",
    "ft": "PT",
    "fit": "PT",
    "fzit": "PT",
    # Differential-pressure transmitter family also shares the PT form
    # (DP cell + sensing element + transmitter sections all apply).
    "pdit": "PT",
    "pdt": "PT",
    "fdit": "PT",
    # Temperature transmitter
    "tt": "TT",
    "tit": "TT",
    "tzit": "TT",
    # Pressure gauge (PG / PI); differential-pressure indicator shares the form
    "pg": "PG",
    "pi": "PG",
    "pdi": "PG",
    # Temperature gauge (TG / TI)
    "tg": "TG",
    "ti": "TG",
    # Thermowell
    "tw": "TW",
    "thermowell": "TW",
    # Temperature element / RTD / thermocouple
    "te": "TE",
    "rtd": "TE",
    "tc": "TE",
    # Flow / sight glass + orifice element
    "fe": "FE",
    "fg": "FE",
    # Restriction orifice
    "ro": "RO",
    # Pressure Safety / Relief Valve
    "psv": "PSV",
    "rv": "PSV",
    "prv": "PSV",
    "relief_safety": "PSV",
    "3way_relief": "PSV",
    "safety": "PSV",
    "relief": "PSV",
}


def _match_descriptive(k: str) -> Optional[str]:
    """Keyword classifier for descriptive sub_class names.

    The pipeline writes human-readable sub_classes ("FLOW TRANSMITTER",
    "PRESSURE GAUGE", "DIFFERENTIAL PRESSURE INDICATING TRANSMITTER") rather
    than ISA codes, so the exact-match alias table misses them. We classify by
    keyword instead. Order matters — most specific first. Returns None for
    genuinely ambiguous names (analyzer, alarm, hand switch, level, generic
    valve/controller) so they get the Common datasheet rather than wrong
    type-specific fields.
    """
    has = lambda *words: any(w in k for w in words)

    # Mechanical / fixed types (check before the transmitter/gauge families).
    if "thermowell" in k:
        return "TW"
    if "restriction orifice" in k:
        return "RO"
    if ("safety" in k or "relief" in k) and "valve" in k:
        return "PSV"
    if "control valve" in k:
        return "CV"
    if has("thermocouple", "rtd", "resistance temperature") or (
        "temperature" in k and "element" in k
    ):
        return "TE"

    # Transmitters (a transmitter wins even if the name also says "indicating").
    if "transmitter" in k:
        if "temperature" in k:
            return "TT"
        if has("pressure", "flow", "differential"):
            return "PT"  # pressure / DP / flow transmitters share the PT form
        return None  # level / other transmitter — no matching datasheet type

    # Local gauges / indicators (no transmitter).
    if has("gauge", "indicator", "indicating"):
        if "temperature" in k:
            return "TG"
        if "pressure" in k:
            return "PG"
        if "flow" in k:
            return "FE"

    # Flow / sight-glass elements + measurement orifices.
    if has("flow element", "orifice", "sight glass", "flow gauge"):
        return "FE"

    return None


def normalize_subclass(sub_class: Optional[str]) -> Optional[str]:
    """Map a canonical sub_class / ISA code / descriptive name to a datasheet key.

    Returns one of the keys in ``TYPE_LABELS`` (CV/PT/TT/PG/TG/TW/TE/FE/RO/PSV),
    or None if unknown. Case-insensitive. FT maps to PT (shared form).

    Resolution order: (1) exact alias table (ISA codes like ``ft``/``pdit`` plus
    a few canonical phrases), then (2) a keyword classifier for the descriptive
    names the pipeline actually emits ("PRESSURE TRANSMITTER", ...).
    """
    if not sub_class:
        return None
    key = sub_class.strip().lower()
    if key in _SUBCLASS_ALIASES:
        return _SUBCLASS_ALIASES[key]
    return _match_descriptive(key)


# --------------------------------------------------------------------------- #
# Field constructor — applies the path rules from the module docstring
# --------------------------------------------------------------------------- #
# Common-identity columns that map onto EXISTING canonical fields rather than
# the generic ``fields.ids_<col>`` namespace.
_IDENTITY_PATHS: Dict[str, str] = {
    "tag_no": "tag",
    "service_description": "fields.service_description",
    "pid_no": "pid_number",
    "location": "fields.location",
    "unit_no": "fields.unit_number",
    "equipment_no": "fields.equipment_no",
    "line_no": "fields.line_no",
}


def _f(header: str, col: str, source: str, group: Optional[str] = None) -> IdsField:
    """Build an IdsField for manifest column ``col``, applying path rules.

    ``source`` accepts manifest tags including slash forms ("PROCESS/USER",
    "VENDOR/PROCESS", ...). The FIRST tag wins.
    """
    primary = source.split("/", 1)[0].strip().lower()  # "process" | "user" | "vendor"

    if primary == "vendor":
        if col == "manufacturer":
            path = "vendor_match.vendor_name"
        elif col == "model_no":
            path = "vendor_match.product_name"
        elif col == "part_number":
            path = "vendor_match.part_number"
        else:
            path = "vendor_match.catalog_fields." + col
        return IdsField(header=header, path=path, source="vendor", editable=False, group=group)

    # process / user
    if col in _IDENTITY_PATHS:
        path = _IDENTITY_PATHS[col]
    else:
        path = "fields.ids_" + col
    return IdsField(header=header, path=path, source=primary, editable=True, group=group)


# --------------------------------------------------------------------------- #
# 0. Common sections (manifest "## 0. Common" — ~56 columns, regrouped)
# --------------------------------------------------------------------------- #
COMMON_SECTIONS: List[IdsSection] = [
    IdsSection("General", [
        _f("Tag No.", "tag_no", "PROCESS"),
        _f("Service / Service Description", "service_description", "PROCESS"),
        _f("P&ID No.", "pid_no", "PROCESS"),
        _f("Location (Field / CCR)", "location", "PROCESS"),
        _f("Unit No.", "unit_no", "PROCESS"),
        # Equipment Information — 2-column group
        _f("Equipment No.", "equipment_no", "PROCESS", group="equip_info"),
        _f("Line No.", "line_no", "PROCESS", group="equip_info"),
        # Line Information — 2-column group
        _f("Line Size", "line_size", "PROCESS", group="line_info"),
        _f("Schedule", "line_schedule", "PROCESS", group="line_info"),
        # Pipe Information — 3-column group
        _f("Pipe Class", "pipe_class", "PROCESS", group="pipe_info"),
        _f("Pipe Material", "pipe_material", "PROCESS", group="pipe_info"),
        _f("Pipe Insulation", "insulation", "PROCESS", group="pipe_info"),
        # Ambient Temperature — 2-column group
        _f("Ambient Temp Min", "ambient_temp_min", "PROCESS", group="ambient_temp"),
        _f("Ambient Temp Max", "ambient_temp_max", "PROCESS", group="ambient_temp"),
    ]),
    IdsSection("Area Classification", [
        IdsField(
            header="Hazardous Area Classification",
            path="fields.ids_area_classification",
            source="process",
            editable=True,
            options=["Zone 0", "Zone 1", "Zone 2"],
        ),
        IdsField(
            header="Temp Class",
            path="fields.ids_temp_class",
            source="process",
            editable=True,
            options=["T1", "T2", "T3", "T4", "T5", "T6"],
        ),
        IdsField(
            header="Category",
            path="fields.ids_ignition_group",
            source="process",
            editable=True,
            options=["IA", "IIA", "IB", "IIB", "IIIB", "IC", "IIC"],
        ),
        _f("IP Rating", "ip_rating", "PROCESS"),
    ]),
    IdsSection("Process", [
        # Fluid group — 3-column
        _f("Fluid Name", "fluid_name", "PROCESS", group="fluid_info"),
        _f("Fluid State", "fluid_state", "PROCESS", group="fluid_info"),
        _f("Fluid Phase", "fluid_phase", "PROCESS", group="fluid_info"),
        _f("Density", "density", "PROCESS"),
        _f("Viscosity", "viscosity", "PROCESS"),
        _f("Molecular Weight", "molecular_weight", "PROCESS"),
        # Operating Pressure — 3-column group
        _f("Operating Pressure Min", "operating_pressure_min", "PROCESS", group="op_pressure"),
        _f("Operating Pressure Normal", "operating_pressure_nor", "PROCESS", group="op_pressure"),
        _f("Operating Pressure Max", "operating_pressure_max", "PROCESS", group="op_pressure"),
        _f("Operating Pressure Unit", "operating_pressure_unit", "PROCESS"),
        # Operating Temperature — 3-column group
        _f("Operating Temp Min", "operating_temp_min", "PROCESS", group="op_temp"),
        _f("Operating Temp Normal", "operating_temp_nor", "PROCESS", group="op_temp"),
        _f("Operating Temp Max", "operating_temp_max", "PROCESS", group="op_temp"),
        _f("Operating Temp Unit", "operating_temp_unit", "PROCESS"),
        # Design Pressure — 2-column group
        _f("Design Pressure Min", "design_pressure_min", "PROCESS", group="design_pressure"),
        _f("Design Pressure Max", "design_pressure_max", "PROCESS", group="design_pressure"),
        _f("Design Pressure Unit", "design_pressure_unit", "PROCESS"),
        # Design Temperature — 2-column group
        _f("Design Temp Min", "design_temp_min", "PROCESS", group="design_temp"),
        _f("Design Temp Max", "design_temp_max", "PROCESS", group="design_temp"),
        _f("Design Temp Unit", "design_temp_unit", "PROCESS"),
    ]),
    IdsSection("Requirements & Certification", [
        # Key Requirements — 2-column group
        IdsField(
            header="NACE Requirement",
            path="fields.ids_nace_requirement",
            source="process", editable=True,
            options=["Yes", "No", "Define"],
            group="key_requirements",
        ),
        IdsField(
            header="SIL Level Required",
            path="fields.ids_sil_level_required",
            source="process", editable=True,
            options=["SIL 1", "SIL 2", "SIL 3", "Yes", "No", "Define"],
            group="key_requirements",
        ),
        _f("IBR Requirement", "ibr_requirement", "PROCESS/USER"),
        _f("Certification / Special Requirement", "certification_special_requirement", "USER"),
    ]),
    IdsSection("Commercial / Sign-off", [
        _f("Manufacturer", "manufacturer", "VENDOR"),
        _f("Model No.", "model_no", "VENDOR"),
        _f("MR No.", "mr_no", "USER"),
        _f("PO No.", "po_no", "USER"),
        _f("Client Reference", "client_reference", "USER"),
        _f("Rev", "rev", "USER"),
        _f("By", "prepared_by", "USER"),
        _f("Chk", "checked_by", "USER"),
        _f("Appr", "approved_by", "USER"),
        _f("Date", "doc_date", "USER"),
    ]),
]


# --------------------------------------------------------------------------- #
# 1. Control Valve / Anti-Surge (manifest "## 1", sections per fields doc "## 1")
# --------------------------------------------------------------------------- #
_CV_SECTIONS: List[IdsSection] = [
    IdsSection("General", [
        _f("Case", "cv_case", "PROCESS"),
        _f("Fluid Tending To", "fluid_tending_to", "PROCESS"),
        _f("Air-Fail Position", "air_fail_position", "PROCESS"),
    ]),
    IdsSection("Inlet Line", [
        _f("Inlet Line Size", "inlet_line_size", "PROCESS"),
        _f("Inlet Piping Class", "inlet_piping_class", "PROCESS"),
        _f("Inlet Line Material", "inlet_line_material", "PROCESS"),
        _f("Inlet Line Schedule", "inlet_line_schedule", "PROCESS"),
    ]),
    IdsSection("Outlet Line", [
        _f("Outlet Line Size", "outlet_line_size", "PROCESS"),
        _f("Outlet Piping Class", "outlet_piping_class", "PROCESS"),
        _f("Outlet Line Material", "outlet_line_material", "PROCESS"),
        _f("Outlet Line Schedule", "outlet_line_schedule", "PROCESS"),
    ]),
    IdsSection("Operating", [
        _f("Special Conditions", "special_conditions", "PROCESS"),
        _f("Insulation Code/Thickness", "insulation_code_thickness", "PROCESS"),
        _f("Operating Spec Gravity", "operat_spec_gravity", "PROCESS"),
        _f("Cp/Cv", "cp_cv_ratio", "PROCESS"),
        _f("Compressibility Z", "compressibility_z", "PROCESS"),
        _f("Vapour Press @ Nom T", "vapour_pressure_nom_t", "PROCESS"),
        _f("Viscosity @ Op Cond", "viscosity_op_cond", "PROCESS"),
        _f("Critical Pressure", "critical_pressure", "PROCESS"),
        _f("Critical Temperature", "critical_temperature", "PROCESS"),
        _f("Density Min", "density_min", "PROCESS"),
        _f("Density Norm", "density_norm", "PROCESS"),
        _f("Density Max", "density_max", "PROCESS"),
        _f("Density Unit", "density_unit", "PROCESS"),
        _f("Flow Min", "flow_min", "PROCESS"),
        _f("Flow Norm", "flow_norm", "PROCESS"),
        _f("Flow Max", "flow_max", "PROCESS"),
        _f("Flow Unit", "flow_unit", "PROCESS"),
        _f("Temp Q Min", "temp_q_min", "PROCESS"),
        _f("Temp Q Norm", "temp_q_norm", "PROCESS"),
        _f("Temp Q Max", "temp_q_max", "PROCESS"),
        _f("Press Q Min", "press_q_min", "PROCESS"),
        _f("Press Q Norm", "press_q_norm", "PROCESS"),
        _f("Press Q Max", "press_q_max", "PROCESS"),
        _f("DP Q Min", "dp_q_min", "PROCESS"),
        _f("DP Q Norm", "dp_q_norm", "PROCESS"),
        _f("DP Q Max", "dp_q_max", "PROCESS"),
    ]),
    IdsSection("Calculation", [
        _f("CV Min", "cv_min", "PROCESS"),
        _f("CV Norm", "cv_norm", "PROCESS"),
        _f("CV Max", "cv_max", "PROCESS"),
        _f("Lifting % Min", "lifting_pct_min", "PROCESS"),
        _f("Lifting % Norm", "lifting_pct_norm", "PROCESS"),
        _f("Lifting % Max", "lifting_pct_max", "PROCESS"),
        _f("Noise dBA Min", "noise_dba_min", "PROCESS"),
        _f("Noise dBA Norm", "noise_dba_norm", "PROCESS"),
        _f("Noise dBA Max", "noise_dba_max", "PROCESS"),
        _f("Required CV", "required_cv", "PROCESS"),
        _f("Selected CV", "selected_cv", "PROCESS"),
        _f("Mechanical Stop", "mechanical_stop", "PROCESS"),
        _f("Fd", "fd_factor", "PROCESS"),
        _f("Fl (Cf)", "fl_cf_factor", "PROCESS"),
    ]),
    IdsSection("Valve Body", [
        _f("Body Type", "body_type", "VENDOR"),
        _f("Body Material", "body_material", "VENDOR"),
        _f("Max DP Closed Valve", "max_dp_closed_valve", "VENDOR"),
        _f("Seat Leakage Class", "seat_leakage_class", "VENDOR"),
        _f("Body Design Press Min", "body_design_press_min", "PROCESS"),
        _f("Body Design Press Max", "body_design_press_max", "PROCESS"),
        _f("Body Design Press Unit", "body_design_press_unit", "PROCESS"),
        _f("Body Design Temp Min", "body_design_temp_min", "PROCESS"),
        _f("Body Design Temp Max", "body_design_temp_max", "PROCESS"),
        _f("Body Design Temp Unit", "body_design_temp_unit", "PROCESS"),
        _f("Body Size", "body_size", "VENDOR"),
        _f("Body Rating", "body_rating", "VENDOR"),
        _f("Body Face", "body_face", "VENDOR"),
        _f("Plug Type", "plug_type", "VENDOR"),
        _f("Plug Material", "plug_material", "VENDOR"),
        _f("Plug Dimension", "plug_dimension", "VENDOR"),
        _f("Plug Form/Law", "plug_form_law", "VENDOR"),
        _f("Seat Type", "seat_type", "VENDOR"),
        _f("Seat Material", "seat_material", "VENDOR"),
        _f("Packing Material", "packing_material", "VENDOR"),
        _f("Lubricator", "lubricator", "VENDOR"),
        _f("Bonnet Type", "bonnet_type", "VENDOR"),
        _f("Stem Material", "stem_material", "VENDOR"),
        _f("Area Classification", "body_area_classification", "VENDOR"),
        _f("Req. Safety Certification", "req_safety_certification", "VENDOR"),
    ]),
    IdsSection("Actuator", [
        _f("Actuator Type", "actuator_type", "VENDOR"),
        _f("Direction of Action", "actuator_direction_of_action", "VENDOR"),
        _f("Spring Range", "actuator_spring_range", "VENDOR"),
        _f("Actuator Supply Pressure", "actuator_supply", "VENDOR"),
    ]),
    IdsSection("Positioner", [
        _f("Positioner Type", "positioner_type", "VENDOR"),
        _f("Positioner Input Signal", "positioner_input_signal", "VENDOR"),
        _f("Positioner Fluid Connection", "positioner_fluid_connection", "VENDOR"),
        _f("Positioner Electrical Connection", "positioner_electrical_connection", "VENDOR"),
        _f("Positioner Elec Protection Class", "positioner_elec_protection_class", "VENDOR"),
        _f("Positioner Enclosure Protection", "positioner_enclosure_protection", "VENDOR"),
        _f("Surge Protection Device", "positioner_surge_protection_device", "VENDOR"),
        _f("Positioner Action Direction", "positioner_action_direction", "VENDOR"),
    ]),
    IdsSection("Accessories", [
        _f("Handwheel", "handwheel", "VENDOR"),
        _f("Handwheel Position", "handwheel_position", "VENDOR"),
        _f("Booster Relay", "booster_relay", "VENDOR"),
        _f("Locking Device", "locking_device", "VENDOR"),
        _f("Filter", "filter", "VENDOR"),
        _f("Press Reducing Valve", "press_reducing_valve", "VENDOR"),
        _f("Air Set", "air_set", "VENDOR"),
        _f("Pressure Gauge (accessory)", "pressure_gauge_acc", "VENDOR"),
    ]),
    IdsSection("Solenoid Valve", [
        _f("Solenoid Valve (make/model)", "solenoid_valve_make_model", "VENDOR"),
        _f("Solenoid Valve Tag No.", "solenoid_valve_tag_no", "PROCESS"),
        _f("Solenoid Elec Protection Class", "solenoid_elec_protection_class", "VENDOR"),
        _f("Solenoid Enclosure Protection", "solenoid_enclosure_protection", "VENDOR"),
    ]),
    IdsSection("Position Detector", [
        _f("Position Detector (make/model)", "position_detector_make_model", "VENDOR"),
        _f("Position Detector Tag No.", "position_detector_tag_no", "PROCESS"),
        _f("Position Detector Elec Protection Class", "position_detector_elec_protection_class", "VENDOR"),
        _f("Position Detector Enclosure Protection", "position_detector_enclosure_protection", "VENDOR"),
    ]),
    IdsSection("Position Transmitter", [
        _f("Position Transmitter (make/model)", "position_transmitter_make_model", "VENDOR"),
        _f("Position Transmitter Tag No.", "position_transmitter_tag_no", "PROCESS"),
        _f("Position Transmitter Elec Protection Class", "position_transmitter_elec_protection_class", "VENDOR"),
        _f("Position Transmitter Enclosure Protection", "position_transmitter_enclosure_protection", "VENDOR"),
    ]),
    IdsSection("Air Volume Tank & Purchase", [
        _f("Air Volume Tank Capacity", "air_volume_tank_capacity", "VENDOR"),
        _f("Valve Weight", "valve_weight", "VENDOR"),
        _f("Actuator Weight", "actuator_weight", "VENDOR"),
        _f("Valve Mfr/Model", "valve_mfr_model", "VENDOR"),
        _f("Actuator Mfr/Model", "actuator_mfr_model", "VENDOR"),
        _f("Positioner Mfr/Model", "positioner_mfr_model", "VENDOR"),
    ]),
]


# --------------------------------------------------------------------------- #
# 2. Pressure Transmitter (manifest "## 2"; shared by Flow Transmitter)
#    Section grouping per fields doc "## 2".
# --------------------------------------------------------------------------- #
_PT_SECTIONS: List[IdsSection] = [
    IdsSection("Element", [
        _f("Corrosive", "corrosive", "PROCESS"),
        _f("Erosive", "erosive", "PROCESS"),
        _f("Toxic", "toxic", "PROCESS"),
        _f("Build-up", "build_up", "PROCESS"),
        _f("Solidifying", "solidifying", "PROCESS"),
        _f("Pulsation", "pulsation", "PROCESS"),
        _f("Coagulation", "coagulation", "PROCESS"),
        _f("Contains Particles", "contains_particles", "PROCESS"),
    ]),
    IdsSection("Range", [
        _f("Inst Range Min", "instrument_range_min", "USER", group="inst_range"),
        _f("Inst Range Max", "instrument_range_max", "USER", group="inst_range"),
        _f("Inst Range Unit", "instrument_range_unit", "USER", group="inst_range"),
        _f("Calibration Range Min", "calibration_range_min", "USER"),
        _f("Calibration Range Max", "calibration_range_max", "USER"),
        _f("Calibration Range Unit", "calibration_range_unit", "USER"),
        _f("Display (Scale) Range Min", "display_range_min", "USER"),
        _f("Display (Scale) Range Max", "display_range_max", "USER"),
        _f("Display (Scale) Range Unit", "display_range_unit", "USER"),
    ]),
    IdsSection("Transmitter Body", [
        _f("Body/Flange Type", "body_flange_type", "VENDOR"),
        _f("Vent Valve", "vent_valve", "VENDOR"),
        _f("Drain Valve", "drain_valve", "VENDOR"),
        _f("Vent/Drain Size", "vent_drain_size", "VENDOR"),
        _f("Process Conn Size", "proc_conn_size", "VENDOR"),
        _f("Process Conn Rating", "proc_conn_rating", "VENDOR"),
        _f("Conn Type/Std", "conn_type_std", "VENDOR"),
        _f("Mounting Type", "mounting_type", "VENDOR"),
    ]),
    IdsSection("Body Materials", [
        _f("Body/Flange Material", "body_flange_material", "VENDOR"),
        _f("Vent/Drain Material", "vent_drain_material", "VENDOR"),
        _f("Bolting Material", "bolting_material", "VENDOR"),
        _f("Gasket/O-Ring Material", "gasket_oring_material", "VENDOR"),
        _f("Mounting Kit Material", "mounting_kit_material", "VENDOR"),
    ]),
    IdsSection("Sensing Element", [
        _f("Detector Type", "detector_type", "VENDOR"),
        _f("Measurement Span Min", "measurement_span_min", "VENDOR"),
        _f("Measurement Span Max", "measurement_span_max", "VENDOR"),
        _f("Diaphragm/Wetted Material", "diaphragm_wetted_material", "VENDOR"),
        _f("Fill Fluid Material", "fill_fluid_material", "VENDOR"),
    ]),
    IdsSection("Transmitter", [
        _f("Output Signal Type (4-20mA)", "output_signal_type", "VENDOR"),
        _f("Enclosure IP Rating", "enclosure_ip_rating", "VENDOR"),
        _f("Enclosure Material", "enclosure_material", "VENDOR"),
        _f("Digital Communication (HART rev)", "digital_communication", "VENDOR"),
        _f("Signal Power Supply", "signal_power_supply", "VENDOR"),
        _f("Integral Indicator Reqd", "integral_indicator_reqd", "VENDOR"),
        _f("Integral Indicator Type (LCD)", "integral_indicator_type", "VENDOR"),
        _f("Signal Termination Type", "signal_termination_type", "VENDOR"),
        _f("Elect Conn Size", "elect_conn_size", "VENDOR"),
        _f("Elect Conn Type", "elect_conn_type", "VENDOR"),
    ]),
    IdsSection("Smart Device", [
        _f("Smart Device Type", "smart_device_type", "VENDOR"),
        _f("Hardware Device Rev", "hardware_device_rev", "VENDOR"),
        _f("DD/EDD Rev", "dd_edd_rev", "VENDOR"),
        _f("HART Version", "hart_version", "VENDOR"),
        _f("ITK Version (FF)", "itk_version", "VENDOR"),
        _f("CFF Rev", "cff_rev", "VENDOR"),
    ]),
    IdsSection("Performance", [
        _f("Pressure Accuracy", "pressure_accuracy", "VENDOR"),
        _f("Zero Supply/Elevation", "zero_supply_elevation", "VENDOR"),
        _f("Fill Fluid Sp Gr @ Temp", "fill_fluid_sp_gr_temp", "VENDOR"),
    ]),
    IdsSection("Diaphragm Seal (if fitted)", [
        _f("Seal Type", "seal_type", "VENDOR"),
        _f("Diaphragm Extn Length", "diaphragm_extn_length", "VENDOR"),
        _f("Flush Conn Qty/Size", "flush_conn_qty_size", "VENDOR"),
        _f("Seal Process Conn Size", "seal_proc_conn_size", "VENDOR"),
        _f("Seal Process Conn Rating", "seal_proc_conn_rating", "VENDOR"),
        _f("Seal Conn Type/Std", "seal_conn_type_std", "VENDOR"),
        _f("Flushing Ring Reqd", "flushing_ring_reqd", "VENDOR"),
        _f("Flushing Ring Rating", "flushing_ring_rating", "VENDOR"),
        _f("Capillary Fitting Dia", "capillary_fitting_dia", "VENDOR"),
        _f("Instr Conn nom Size", "instr_conn_nom_size", "VENDOR"),
        _f("Diaphragm Material", "diaphragm_material", "VENDOR"),
        _f("Lower Housing Material", "lower_housing_material", "VENDOR"),
        _f("Upper Housing Material", "upper_housing_material", "VENDOR"),
        _f("Seal Bolting Material", "seal_bolting_material", "VENDOR"),
        _f("Seal Gasket Material", "seal_gasket_material", "VENDOR"),
        _f("Capillary MOC", "capillary_moc", "VENDOR"),
        _f("Seal Fill Fluid Material", "seal_fill_fluid_material", "VENDOR"),
    ]),
    IdsSection("Flow Transmitter (FT)", [
        _f("Manifold Type (3-way/2-way)", "ft_manifold_type", "VENDOR"),
    ]),
]


# --------------------------------------------------------------------------- #
# 11. Pressure Safety / Relief Valve (manifest "## 11")
#     Section grouping per fields doc "## 11".
# --------------------------------------------------------------------------- #
_PSV_SECTIONS: List[IdsSection] = [
    IdsSection("General", [
        _f("Quantity (No. of PSVs, e.g. 1W+1S)", "quantity", "PROCESS"),
        _f("Line/Equipment No.", "line_equipment_no", "PROCESS"),
        _f("Nozzle (Full / Semi)", "nozzle_full_semi", "PROCESS"),
        _f("Safety / Relief", "safety_relief", "PROCESS"),
        _f("Conv. / Bellows / Pilot Operated", "conv_bellows_pilot", "PROCESS"),
        _f("Sour Services", "sour_services", "PROCESS"),
        _f("Bonnet Type", "bonnet_type", "VENDOR"),
        _f("Painting System", "painting_system", "VENDOR"),
        _f("Total Weight", "total_weight", "VENDOR"),
    ]),
    IdsSection("Process Conditions", [
        _f("Fluid", "fluid", "PROCESS"),
        _f("State", "state", "PROCESS"),
        _f("Corrosive Component", "corrosive_component", "PROCESS"),
        _f("Multi-phase", "multi_phase", "PROCESS"),
        _f("Required Capacity (kg/h)", "required_capacity", "PROCESS"),
        _f("Accumulation %", "accumulation_pct", "PROCESS"),
        # Molecular Weight intentionally omitted here — it's a Common field
        # (Process Fluid section); duplicating its path would collide.
        _f("Specific Gravity", "specific_gravity", "PROCESS"),
        _f("Pressure Operating (bar-g)", "pressure_operating", "PROCESS"),
        _f("Pressure Max (bar-g)", "pressure_max", "PROCESS"),
        _f("Pressure Design (bar-g)", "pressure_design", "PROCESS"),
        _f("Cold Differential Test Pressure", "cold_diff_test_pressure", "PROCESS"),
        _f("Temperature Operating (C)", "temp_operating", "PROCESS"),
        _f("Temperature Max (C)", "temp_max", "PROCESS"),
        _f("Temperature Design (C)", "temp_design", "PROCESS"),
        _f("Back Pressure Superimposed (Constant)", "back_pressure_superimposed_constant", "PROCESS"),
        _f("Back Pressure Superimposed (Variable)", "back_pressure_superimposed_variable", "PROCESS"),
        _f("Back Pressure Built-up", "back_pressure_builtup", "PROCESS"),
        _f("Back Pressure Total (bar-g)", "back_pressure_total", "PROCESS"),
        _f("% Allowable Overpressure", "allowable_overpressure_pct", "PROCESS"),
        _f("Set Pressure", "set_pressure", "PROCESS"),
        _f("Relieving Temperature", "relieving_temperature", "PROCESS"),
        _f("Overpressure Factor", "overpressure_factor", "PROCESS"),
        _f("Compr. Factor (Z)", "compr_factor_z", "PROCESS"),
        _f("Ratio of Specific Heats Cp/Cv", "cp_cv_ratio", "PROCESS"),
        _f("Relief Density (kg/m3)", "relief_density", "PROCESS"),
        _f("Relief Viscosity (cP)", "relief_viscosity", "PROCESS"),
        _f("Blowdown", "blowdown", "PROCESS"),
        _f("Vapor Mass Fraction", "vapor_mass_fraction", "PROCESS"),
        _f("Latent Heat of Vaporisation", "latent_heat_vaporisation", "PROCESS"),
        _f("Liq. Spec. Heat @ PRV", "liq_spec_heat_at_prv", "PROCESS"),
        _f("System Spec. Vol @ PRV inlet", "system_spec_vol_at_prv_inlet", "PROCESS"),
        _f("Spec. Vol @ 90% PRV inlet", "spec_vol_at_90pct_prv_inlet", "PROCESS"),
    ]),
    IdsSection("Basis & Selection", [
        _f("Design Code (e.g. API STD 520 Pt 1)", "design_code", "PROCESS"),
        _f("Valve discharge to", "valve_discharge_to", "PROCESS"),
        _f("Sizing Basis", "sizing_basis", "PROCESS"),
        _f("Process Cal. Capacity", "process_cal_capacity", "PROCESS"),
        _f("Calculated Area (mm2)", "calculated_area_mm2", "PROCESS"),
        _f("Vendor Cal. Capacity", "vendor_cal_capacity", "VENDOR"),
        _f("Selected Area (mm2)", "selected_area_mm2", "VENDOR"),
        _f("Selected Capacity (kg/h)", "selected_capacity", "VENDOR"),
        _f("Orifice Designation (API letter, e.g. Q)", "orifice_designation", "VENDOR"),
        _f("Certified Relieving Capacity", "certified_relieving_capacity", "VENDOR"),
        _f("Rupture Disc / Other", "rupture_disc_other", "PROCESS/VENDOR"),
    ]),
    IdsSection("Connections / Materials", [
        _f("Size Inlet (in)", "size_inlet", "PROCESS"),
        _f("Size Outlet (in)", "size_outlet", "PROCESS"),
        _f("Rating & Facing Inlet", "rating_facing_inlet", "VENDOR"),
        _f("Rating & Facing Outlet", "rating_facing_outlet", "VENDOR"),
        _f("Flange Dim/Finish", "flange_dim_finish", "VENDOR"),
        _f("Nuts/Bolts Material", "nuts_bolts_material", "VENDOR"),
        _f("Body & Bonnet Material", "body_bonnet_material", "VENDOR"),
        _f("Nozzle & Disc Material", "nozzle_disc_material", "VENDOR"),
        _f("Spring Material", "spring_material", "VENDOR"),
        _f("Resilient Seat Seal Material", "resilient_seat_seal_material", "VENDOR"),
        _f("Bellows Material", "bellows_material", "VENDOR"),
        _f("External Paint", "external_paint", "VENDOR"),
        _f("Pilot Tubing/Fitting Material", "pilot_tubing_fitting_material", "VENDOR"),
        _f("Pilot Type (Flowing/Nonflowing)", "pilot_type", "VENDOR"),
        _f("Reaction Force (kN)", "reaction_force", "VENDOR"),
        _f("Calculated Sound Pressure Level @ 30m (dB)", "sound_pressure_level_30m", "VENDOR"),
    ]),
    IdsSection("Options", [
        _f("Cap (Screwed/Bolted)", "cap_screwed_bolted", "VENDOR"),
        _f("Lever (Plain/Packed)", "lever_plain_packed", "VENDOR"),
        _f("ASME Code Stamping", "asme_code_stamping", "VENDOR"),
        _f("Test Gag", "test_gag", "VENDOR"),
        _f("Bug Screen", "bug_screen", "VENDOR"),
        _f("NACE MR0175/ISO 15156", "nace_mr0175", "USER"),
        _f("Test Cert", "test_cert", "USER"),
        _f("Tag Number Nameplate", "tag_number_nameplate", "USER"),
    ]),
]


# --------------------------------------------------------------------------- #
# 4. Temperature Transmitter (manifest "## 4")
# --------------------------------------------------------------------------- #
_TT_SECTIONS: List[IdsSection] = [
    IdsSection("Range", [
        _f("Inst Range Min", "tt_instrument_range_min", "USER", group="inst_range"),
        _f("Inst Range Max", "tt_instrument_range_max", "USER", group="inst_range"),
        _f("Inst Range Unit", "tt_instrument_range_unit", "USER", group="inst_range"),
        _f("Calibration Range Min", "tt_calibration_range_min", "USER"),
        _f("Calibration Range Max", "tt_calibration_range_max", "USER"),
        _f("Calibration Range Unit", "tt_calibration_range_unit", "USER"),
        _f("Display (Scale) Range Min", "tt_display_range_min", "USER"),
        _f("Display (Scale) Range Max", "tt_display_range_max", "USER"),
        _f("Display (Scale) Range Unit", "tt_display_range_unit", "USER"),
    ]),
    IdsSection("Transmitter", [
        _f("Housing Type", "housing_type", "VENDOR"),
        _f("Input Sensor Type", "input_sensor_type", "VENDOR"),
        _f("Input Sensor Quantity", "input_sensor_quantity", "VENDOR"),
        _f("Output Signal Type", "output_signal_type", "VENDOR"),
        _f("Temp Span Min", "temp_span_min", "VENDOR"),
        _f("Temp Span Max", "temp_span_max", "VENDOR"),
        _f("Temp Coef/Tolerance Class", "temp_coef_tolerance_class", "VENDOR"),
        _f("Isolation Type", "isolation_type", "VENDOR"),
        _f("Enclosure IP Rating", "enclosure_ip_rating", "VENDOR"),
        _f("Characteristic Curve", "characteristic_curve", "VENDOR"),
        _f("Digital Communication", "digital_communication", "VENDOR"),
        _f("Signal Power Source", "signal_power_source", "VENDOR"),
        _f("Configuration of Wires", "configuration_of_wires", "VENDOR"),
        _f("Integral Indicator", "integral_indicator", "VENDOR"),
        _f("Signal Termination Type", "signal_termination_type", "VENDOR"),
        _f("Mounting Type", "mounting_type", "VENDOR"),
        _f("Temp Compensation", "temp_compensation", "VENDOR"),
        _f("Enclosure Material", "enclosure_material", "VENDOR"),
        _f("Mounting Bracket", "mounting_bracket", "VENDOR"),
        _f("Bolt Material", "bolt_material", "VENDOR"),
        _f("Burnout Protection", "burnout_protection", "VENDOR"),
        _f("Element Standard", "element_standard", "VENDOR"),
        _f("Cable Entry Size", "cable_entry_size", "VENDOR"),
        _f("Cable Quantity", "cable_quantity", "VENDOR"),
        _f("Hot Backup Provided", "hot_backup_provided", "VENDOR"),
        _f("End Conn Size", "end_conn_size", "VENDOR"),
        _f("End Conn Type", "end_conn_type", "VENDOR"),
        _f("End Conn Qty", "end_conn_qty", "VENDOR"),
    ]),
    IdsSection("Smart Device", [
        _f("Smart Device Type", "smart_device_type", "VENDOR"),
        _f("Hardware Device Rev", "hardware_device_rev", "VENDOR"),
        _f("DD/EDD Rev", "dd_edd_rev", "VENDOR"),
        _f("HART Version", "hart_version", "VENDOR"),
        _f("ITK Version", "itk_version", "VENDOR"),
        _f("CFF Rev", "cff_rev", "VENDOR"),
    ]),
    IdsSection("Performance", [
        _f("Accuracy", "accuracy", "VENDOR"),
    ]),
]


# --------------------------------------------------------------------------- #
# 5. Pressure Gauge (manifest "## 5")
# --------------------------------------------------------------------------- #
_PG_SECTIONS: List[IdsSection] = [
    IdsSection("Element", [
        _f("Corrosive", "corrosive", "PROCESS"),
        _f("Erosive", "erosive", "PROCESS"),
        _f("Toxic", "toxic", "PROCESS"),
        _f("Build-up", "build_up", "PROCESS"),
        _f("Solidifying", "solidifying", "PROCESS"),
        _f("Pulsation", "pulsation", "PROCESS"),
        _f("Coagulation", "coagulation", "PROCESS"),
        _f("Contains Particles", "contains_particles", "PROCESS"),
        _f("Elastic Element Type", "elastic_element_type", "VENDOR"),
        _f("Movement Style", "movement_style", "VENDOR"),
        _f("Nom Accuracy Grade", "nom_accuracy_grade", "VENDOR"),
        _f("Element Material", "element_material", "VENDOR"),
        _f("Movement Material", "movement_material", "VENDOR"),
    ]),
    IdsSection("Range", [
        _f("Inst Range Min", "instrument_range_min", "PROCESS", group="inst_range"),
        _f("Inst Range Max", "instrument_range_max", "PROCESS", group="inst_range"),
        _f("Inst Range Unit", "instrument_range_unit", "PROCESS", group="inst_range"),
    ]),
    IdsSection("Connection & Case", [
        _f("Case Type", "case_type", "VENDOR"),
        _f("Case Style", "case_style", "VENDOR"),
        _f("Mounting Type", "mounting_type", "VENDOR"),
        _f("Enclosure IP Rating", "enclosure_ip_rating", "VENDOR"),
        _f("Liquid Fill Material", "liquid_fill_material", "VENDOR"),
        _f("Process Conn Size", "proc_conn_size", "VENDOR"),
        _f("Process Conn Type", "proc_conn_type", "VENDOR"),
        _f("Process Conn Location", "proc_conn_location", "VENDOR"),
        _f("Case Press Relief Type", "case_press_relief_type", "VENDOR"),
        _f("Window Material", "window_material", "VENDOR"),
        _f("Bolting Material", "bolting_material", "VENDOR"),
        _f("Ring Material", "ring_material", "VENDOR"),
        _f("Case Material", "case_material", "VENDOR"),
        _f("Stem Material", "stem_material", "VENDOR"),
        _f("Lower Housing Material", "lower_housing_material", "VENDOR"),
    ]),
    IdsSection("Dial & Pointer", [
        _f("Dial Scale Type", "dial_scale_type", "VENDOR"),
        _f("Pointer Adjustment", "pointer_adjustment", "VENDOR"),
        _f("Graduation & Color", "graduation_color", "VENDOR"),
        _f("Scale Range Type", "scale_range_type", "VENDOR"),
        _f("Dial Material", "dial_material", "VENDOR"),
        _f("Dial Size", "dial_size", "VENDOR"),
    ]),
    IdsSection("Accessory", [
        _f("Accessory", "accessory", "VENDOR"),
        _f("Accessory Code", "accessory_code", "VENDOR"),
        _f("Accessory Material", "accessory_material", "VENDOR"),
    ]),
    IdsSection("Diaphragm Seal", [
        _f("Seal Type", "seal_type", "VENDOR"),
        _f("Diaphragm Extn Length", "diaphragm_extn_length", "VENDOR"),
        _f("Flush Conn Qty/Size", "flush_conn_qty_size", "VENDOR"),
        _f("Flushing Ring Assembly", "flushing_ring_assembly", "VENDOR"),
        _f("Capillary Fitting Dia", "capillary_fitting_dia", "VENDOR"),
        _f("Seal Process Conn Size", "seal_proc_conn_size", "VENDOR"),
        _f("Seal Process Conn Rating", "seal_proc_conn_rating", "VENDOR"),
        _f("Seal Process Conn Type", "seal_proc_conn_type", "VENDOR"),
        _f("Gasket/O-ring Material", "gasket_oring_material", "VENDOR"),
        _f("Fill Fluid Material", "fill_fluid_material", "VENDOR"),
        _f("Instr Conn nom Size", "instr_conn_nom_size", "VENDOR"),
        _f("Diaphragm Material", "diaphragm_material", "VENDOR"),
        _f("Capillary Material", "capillary_material", "VENDOR"),
        _f("Seal Bolting Material", "bolting_material_seal", "VENDOR"),
        _f("Upper Housing Material", "upper_housing_material", "VENDOR"),
    ]),
]


# --------------------------------------------------------------------------- #
# 6. Temperature Gauge (manifest "## 6")
# --------------------------------------------------------------------------- #
_TG_SECTIONS: List[IdsSection] = [
    IdsSection("Pipe / Nozzle", [
        _f("Nozzle/Stub Length", "nozzle_stub_length", "PROCESS"),
        _f("Nozzle/Stub Sch.", "nozzle_stub_sch", "PROCESS"),
    ]),
    IdsSection("Element", [
        _f("Corrosive", "corrosive", "PROCESS"),
        _f("Erosive", "erosive", "PROCESS"),
        _f("Toxic", "toxic", "PROCESS"),
        _f("Vibration", "vibration", "PROCESS"),
        _f("Solid in Stream", "solid_in_stream", "PROCESS"),
    ]),
    IdsSection("Operating", [
        _f("Operating Flow", "op_flow", "PROCESS"),
        _f("Velocity @ Max Flow", "velocity_at_max_flow", "PROCESS"),
    ]),
    IdsSection("Range", [
        _f("Inst Range Min", "instrument_range_min", "PROCESS", group="inst_range"),
        _f("Inst Range Max", "instrument_range_max", "PROCESS", group="inst_range"),
        _f("Accuracy", "accuracy", "VENDOR"),
    ]),
    IdsSection("Dial & Pointer", [
        _f("Case Size", "case_size", "VENDOR"),
        _f("Dial Scale Type", "dial_scale_type", "VENDOR"),
        _f("Pointer Adjustment", "pointer_adjustment", "VENDOR"),
        _f("Graduations & Color", "graduations_color", "VENDOR"),
        _f("Connection Location", "connection_location", "VENDOR"),
        _f("Exterior Treatment Color", "exterior_treatment_color", "VENDOR"),
        _f("Conn nom Size", "conn_nom_size", "VENDOR"),
        _f("Conn nom Type/Style", "conn_nom_type_style", "VENDOR"),
    ]),
    IdsSection("Sensing Element", [
        _f("Element Type", "element_type", "VENDOR"),
    ]),
    IdsSection("Case", [
        _f("Case Type", "case_type", "VENDOR"),
        _f("Case Style", "case_style", "VENDOR"),
    ]),
    IdsSection("Performance", [
        _f("Max Fluid Vel @ Temp", "max_fluid_vel_at_temp", "VENDOR"),
        _f("Min Insertion Length", "min_insertion_length", "VENDOR"),
        _f("Allowable Length @ Max Flow", "allowable_length_at_max_flow", "VENDOR"),
    ]),
    IdsSection("Purchase", [
        _f("Gauge Manufacturer", "gauge_manufacturer", "VENDOR"),
        _f("Gauge Model", "gauge_model", "VENDOR"),
    ]),
]


# --------------------------------------------------------------------------- #
# 7. Thermowell (manifest "## 7")
# --------------------------------------------------------------------------- #
_TW_SECTIONS: List[IdsSection] = [
    IdsSection("Construction", [
        _f("Construction Type", "construction_type", "VENDOR"),
        _f("Ring Style", "ring_style", "VENDOR"),
        _f("Shank Style", "shank_style", "VENDOR"),
    ]),
    IdsSection("Dimensions", [
        _f("Stem Outside Diameter", "stem_od", "VENDOR"),
        _f("Bore Dia", "bore_dia", "VENDOR"),
        _f("Stem Length", "stem_length", "VENDOR"),
        _f("OD at Support", "od_at_support", "VENDOR"),
        _f("OD at Tip", "od_at_tip", "VENDOR"),
    ]),
    IdsSection("Materials", [
        _f("Stem/Bulb Material", "stem_bulb_material", "VENDOR"),
        _f("Case Material", "case_material", "VENDOR"),
        _f("Ring Material", "ring_material", "VENDOR"),
        _f("Coating Material", "coating_material", "VENDOR"),
        _f("Window Material", "window_material", "VENDOR"),
        _f("Connection Material", "connection_material", "VENDOR"),
        _f("Thermowell Material", "thermowell_material", "VENDOR"),
        _f("Sheath Material Thickness", "sheath_material_thickness", "VENDOR"),
    ]),
    IdsSection("Connection", [
        _f("End Size/Rating", "end_size_rating", "VENDOR"),
        _f("Conn Type/Std", "conn_type_std", "VENDOR"),
        _f("IP Rating", "ip_rating", "VENDOR"),
        _f("Internal Conn nom Size", "internal_conn_nom_size", "VENDOR"),
    ]),
    IdsSection("Insertion", [
        _f("Insertion Length (U)", "insertion_length_u", "VENDOR/PROCESS"),
        _f("Length below collar (U1)", "length_below_collar_u1", "VENDOR/PROCESS"),
        _f("Lagging Ext Length (T)", "lagging_ext_length_t", "VENDOR/PROCESS"),
    ]),
    IdsSection("Flange & Reference", [
        _f("Flange Size", "flange_size", "VENDOR"),
        _f("Flange Rating", "flange_rating", "VENDOR"),
        _f("Flange Facing", "flange_facing", "VENDOR"),
        _f("Flange Face Finish", "flange_face_finish", "VENDOR"),
        _f("Well Dimension (mm)", "well_dimension_mm", "VENDOR"),
        _f("Strength Calculation", "strength_calculation", "VENDOR"),
        _f("Reference DWG No.", "reference_dwg_no", "VENDOR"),
        _f("Standard Drawing", "standard_drawing", "VENDOR"),
    ]),
    IdsSection("Process & Tag", [
        _f("Pipe Nozzle Length", "pipe_nozzle_length", "PROCESS"),
        _f("Tag No. for Thermowell", "thermowell_tag_no", "PROCESS"),
    ]),
    IdsSection("Purchase", [
        _f("Thermowell Manufacturer", "thermowell_manufacturer", "VENDOR"),
        _f("Thermowell Model", "thermowell_model", "VENDOR"),
    ]),
]


# --------------------------------------------------------------------------- #
# 8. Temperature Element / RTD / Thermocouple (manifest "## 8")
# --------------------------------------------------------------------------- #
_TE_SECTIONS: List[IdsSection] = [
    IdsSection("Element", [
        _f("Operating Differential Pressure", "operating_differential_pressure", "PROCESS"),
        _f("Pulsation/Vibration", "pulsation_vibration", "PROCESS"),
        _f("Element Type", "element_type", "VENDOR"),
        _f("Single/Double", "single_double", "VENDOR"),
        _f("Element Range", "element_range", "PROCESS"),
        _f("Spec/Calibration", "spec_calibration", "VENDOR"),
        _f("Tolerance Class", "tolerance_class", "VENDOR"),
        _f("Sheath Material", "sheath_material", "VENDOR"),
        _f("Insulator Material", "insulator_material", "VENDOR"),
        _f("Wire Gauge/Insul", "wire_gauge_insul", "VENDOR"),
        _f("Wire Configuration", "wire_configuration", "VENDOR"),
        _f("Element Dia", "element_dia", "VENDOR"),
        _f("Element Length", "element_length", "VENDOR"),
    ]),
    IdsSection("Connection", [
        _f("Connection", "connection", "VENDOR"),
        _f("Connection Size", "connection_size", "VENDOR"),
        _f("Connection Material", "connection_material", "VENDOR"),
        _f("Grounding Type", "grounding_type", "VENDOR"),
    ]),
    IdsSection("Enclosure / Ex", [
        _f("Enclosure Class", "enclosure_class", "VENDOR"),
        _f("Signal Cable Entry", "signal_cable_entry", "VENDOR"),
        _f("Ex Protection", "ex_protection", "VENDOR"),
        _f("Ex Approval", "ex_approval", "VENDOR"),
    ]),
    IdsSection("Head", [
        _f("Transmitter Mount Type", "transmitter_mount_type", "VENDOR"),
        _f("Head Material", "head_material", "VENDOR"),
        _f("Head Extension", "head_extension", "VENDOR"),
        _f("Terminal Block", "terminal_block", "VENDOR"),
        _f("Extension Length", "extension_length", "VENDOR"),
    ]),
    IdsSection("Certification", [
        _f("Special Certificate", "special_certificate", "USER"),
        _f("Inspection for Welding Parts", "inspection_welding_parts", "USER"),
    ]),
    IdsSection("Purchase", [
        _f("Manufacturer", "te_manufacturer", "VENDOR"),
        _f("Model", "te_model", "VENDOR"),
        _f("Option", "te_option", "VENDOR"),
    ]),
]


# --------------------------------------------------------------------------- #
# 9. Flow / Sight Glass + Orifice (manifest "## 9")
# --------------------------------------------------------------------------- #
_FE_SECTIONS: List[IdsSection] = [
    IdsSection("Service", [
        _f("Operating Differential Pressure", "operating_differential_pressure", "PROCESS"),
        _f("Normal Flow", "normal_flow", "PROCESS"),
    ]),
    IdsSection("Body", [
        _f("Body Type", "body_type", "VENDOR"),
        _f("Body Material", "body_material", "VENDOR"),
        _f("Body Size Inlet", "body_size_inlet", "PROCESS"),
        _f("Body Size Outlet", "body_size_outlet", "PROCESS"),
        _f("End Connections", "end_connections", "VENDOR"),
        _f("Press & Temp Rating", "press_temp_rating", "VENDOR"),
        _f("Equalizing Conn Size", "equalizing_conn_size", "VENDOR"),
        _f("Conn Orientation", "conn_orientation", "VENDOR"),
    ]),
    IdsSection("Trim", [
        _f("Trim Material", "trim_material", "VENDOR"),
    ]),
    IdsSection("Options", [
        _f("Internal Check Valve", "internal_check_valve", "VENDOR"),
        _f("Internal Bimetallic Vent", "internal_bimetallic_vent", "VENDOR"),
        _f("Thermostatic Vent", "thermostatic_vent", "VENDOR"),
        _f("Thermostatic Vent Material", "thermostatic_vent_material", "VENDOR"),
        _f("Gage Glass", "gage_glass", "VENDOR"),
    ]),
    IdsSection("Strainer", [
        _f("Strainer Internal/External", "strainer_internal_external", "VENDOR"),
        _f("Strainer Type & Size", "strainer_type_size", "VENDOR"),
        _f("Strainer Body Material", "strainer_body_material", "VENDOR"),
        _f("Strainer Press & Temp Rating", "strainer_press_temp_rating", "VENDOR"),
        _f("Strainer End Connections", "strainer_end_connections", "VENDOR"),
        _f("Strainer Blowoff Connections", "strainer_blowoff_connections", "VENDOR"),
        _f("Strainer Mesh Size & Material", "strainer_mesh_size_material", "VENDOR"),
    ]),
    IdsSection("Purchase", [
        _f("Calc. Orifice Size", "calc_orifice_size", "VENDOR"),
        _f("Selected Orifice Size", "selected_orifice_size", "VENDOR"),
        _f("View Glass Size", "view_glass_size", "VENDOR"),
        _f("Manufacturer", "fe_manufacturer", "VENDOR"),
        _f("Model", "fe_model", "VENDOR"),
    ]),
]


# --------------------------------------------------------------------------- #
# 10. Restriction Orifice (manifest "## 10")
# --------------------------------------------------------------------------- #
_RO_SECTIONS: List[IdsSection] = [
    IdsSection("Service", [
        _f("Flow Rate", "flow_rate", "PROCESS"),
        _f("Specific Heats Ratio Cp/Cv", "specific_heats_ratio_cp_cv", "PROCESS"),
        _f("Compressibility Z", "compressibility_z", "PROCESS"),
        _f("Velocity", "velocity", "PROCESS"),
        _f("Quality%/Superheat", "quality_pct_superheat", "PROCESS"),
        _f("Permanent Pressure Loss", "permanent_pressure_loss", "PROCESS"),
        _f("Base Pressure", "base_pressure", "PROCESS"),
        _f("Base Temperature", "base_temperature", "PROCESS"),
    ]),
    IdsSection("Basis", [
        _f("Type", "ro_type", "VENDOR"),
        _f("Bore Calculation", "bore_calculation", "VENDOR"),
    ]),
    IdsSection("Orifice Plate", [
        _f("Mating Flange Size", "mating_flange_size", "VENDOR"),
        _f("Mating Flange Rating", "mating_flange_rating", "VENDOR"),
        _f("Mating Flange Facing", "mating_flange_facing", "VENDOR"),
        _f("Bore Diameter (d)", "bore_diameter_d", "VENDOR"),
        _f("Diameter Ratio (b=d/D)", "diameter_ratio_beta", "VENDOR"),
        _f("Material", "plate_material", "VENDOR"),
        _f("Thickness", "plate_thickness", "VENDOR"),
        _f("Ring Material & Type", "ring_material_type", "VENDOR"),
    ]),
    IdsSection("Multistage Orifice", [
        _f("Type", "ms_type", "VENDOR"),
        _f("Number of Stages", "ms_number_of_stages", "VENDOR"),
        _f("End Connection", "ms_end_connection", "VENDOR"),
        _f("Flange Facing Finish", "ms_flange_facing_finish", "VENDOR"),
        _f("Plate Material", "ms_plate_material", "VENDOR"),
        _f("Body Material", "ms_body_material", "VENDOR"),
        _f("Flange Material", "ms_flange_material", "VENDOR"),
        _f("Bore Diameter", "ms_bore_diameter", "VENDOR"),
        _f("Thickness", "ms_thickness", "VENDOR"),
    ]),
    IdsSection("Purchase", [
        _f("Manufacturer", "ro_manufacturer", "VENDOR"),
        _f("Model", "ro_model", "VENDOR"),
    ]),
]


_TYPE_SECTIONS: Dict[str, List[IdsSection]] = {
    "CV": _CV_SECTIONS,
    "PT": _PT_SECTIONS,
    "TT": _TT_SECTIONS,
    "PG": _PG_SECTIONS,
    "TG": _TG_SECTIONS,
    "TW": _TW_SECTIONS,
    "TE": _TE_SECTIONS,
    "FE": _FE_SECTIONS,
    "RO": _RO_SECTIONS,
    "PSV": _PSV_SECTIONS,
}


def get_ids_sections_for_type(sub_class: Optional[str]) -> List[IdsSection]:
    """Return [COMMON section(s)] + type-specific sections for ``sub_class``.

    Unknown / None type -> COMMON sections only (never raises).
    """
    type_key = normalize_subclass(sub_class)
    type_sections = _TYPE_SECTIONS.get(type_key, []) if type_key else []
    return COMMON_SECTIONS + type_sections
