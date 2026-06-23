# Instrument Fields Manifest — build-ready column list (all types)

**THIS is the path to reference when building the vendor-portal database.**

One row = one DB column. `snake_case` name, human label, source, suggested SQL type.
This is the *machine-readable, build-1:1* companion to
[`instrument-datasheet-fields.md`](instrument-datasheet-fields.md) (which is the
human-readable reference where fields are packed several-per-cell). Both are kept
in sync; this file is the one your portal team builds columns from, and it is also
the single source of truth Qong Studio's datasheet view is wired to (so the portal
DB and Studio never drift).

> **Covers 11 instrument types** (as of 2026-06-17): Control Valve, Pressure
> Transmitter, Flow Transmitter (= PT), Temperature Transmitter, Pressure Gauge,
> Temperature Gauge, Thermowell, Temperature Element/RTD, Flow/Sight Glass+Orifice,
> Restriction Orifice, Pressure Safety/Relief Valve. ~430 columns total.

## How to read the `Source` column — decide your portal scope

| Source | Who provides it | In the vendor portal? |
|---|---|---|
| **`VENDOR`** | The instrument vendor's catalog (model, materials, electrical, performance) | **YES — these are the portal's job.** Build every `VENDOR` column. Qong fetches them via the instrument-match API (see `vendor-portal-fields.md`). |
| **`PROCESS`** | The P&ID / line list / process engineer | Optional — captured in Qong Studio. Include only if you want the portal to be the master store for everything. |
| **`USER`** | Commercial / admin (MR/PO/MOC, certs, calibration ranges, sign-off) | Optional — captured in Qong Studio. |

- **Minimum portal build = all `VENDOR` rows (~190 columns).** That's what Qong needs the portal to expose.
- **Full master-store build = every row (~430 columns).**

## Recommended DB shape

A **base `instrument_common` table** (the Common columns below, on every instrument)
**+ one extension table per type** (`instrument_cv`, `instrument_pt`, …) keyed by the
same instrument id. PT and FT share `instrument_pt`. Alternatively one wide table with
a `type_code` discriminator — but base+extension keeps each type's columns clean.

Type codes used as table/column prefixes: `CV, PT, FT(→PT), TT, PG, TG, TW, TE, FE, RO, PSV`.

SQL types are suggestions — `TEXT` unless a value is clearly numeric (`NUMERIC`),
a flag (`BOOLEAN`), or a date (`DATE`). Range/dimension values keep a separate
`*_unit TEXT` column where the datasheet shows units.

---

## 0. Common — `instrument_common` (every instrument, ~56 cols)

| Column | Label | Source | SQL |
|---|---|---|---|
| tag_no | Tag No. | PROCESS | TEXT |
| service_description | Service / Service Description | PROCESS | TEXT |
| pid_no | P&ID No. | PROCESS | TEXT |
| location | Location (Field / CCR) | PROCESS | TEXT |
| unit_no | Unit No. | PROCESS | TEXT |
| equipment_no | Equipment No. | PROCESS | TEXT |
| equipment_system | Equipment System | PROCESS | TEXT |
| line_no | Line No. | PROCESS | TEXT |
| line_size | Line Size | PROCESS | TEXT |
| line_schedule | Schedule | PROCESS | TEXT |
| pipe_class | Pipe Class | PROCESS | TEXT |
| pipe_material | Pipe Material | PROCESS | TEXT |
| insulation | Insulation | PROCESS | TEXT |
| area_classification | Hazardous Area Classification | PROCESS | TEXT |
| temp_class | Temp Class (T3/T6) | PROCESS | TEXT |
| ignition_group | Ignition Group | PROCESS | TEXT |
| ambient_temp_min | Ambient Temp Min | PROCESS | NUMERIC |
| ambient_temp_max | Ambient Temp Max | PROCESS | NUMERIC |
| fluid_name | Fluid Name | PROCESS | TEXT |
| fluid_state | Fluid State | PROCESS | TEXT |
| fluid_phase | Fluid Phase | PROCESS | TEXT |
| operating_pressure_min | Operating Pressure Min | PROCESS | NUMERIC |
| operating_pressure_nor | Operating Pressure Normal | PROCESS | NUMERIC |
| operating_pressure_max | Operating Pressure Max | PROCESS | NUMERIC |
| operating_pressure_unit | Operating Pressure Unit | PROCESS | TEXT |
| operating_temp_min | Operating Temp Min | PROCESS | NUMERIC |
| operating_temp_nor | Operating Temp Normal | PROCESS | NUMERIC |
| operating_temp_max | Operating Temp Max | PROCESS | NUMERIC |
| operating_temp_unit | Operating Temp Unit | PROCESS | TEXT |
| design_pressure_min | Design Pressure Min | PROCESS | NUMERIC |
| design_pressure_max | Design Pressure Max | PROCESS | NUMERIC |
| design_pressure_unit | Design Pressure Unit | PROCESS | TEXT |
| design_temp_min | Design Temp Min | PROCESS | NUMERIC |
| design_temp_max | Design Temp Max | PROCESS | NUMERIC |
| design_temp_unit | Design Temp Unit | PROCESS | TEXT |
| density | Density | PROCESS | NUMERIC |
| viscosity | Viscosity | PROCESS | NUMERIC |
| molecular_weight | Molecular Weight | PROCESS | NUMERIC |
| nace_requirement | NACE Requirement | PROCESS/USER | TEXT |
| ibr_requirement | IBR Requirement | PROCESS/USER | TEXT |
| sil_level_required | SIL Level Required | PROCESS/USER | TEXT |
| certification_special_requirement | Certification / Special Requirement | USER | TEXT |
| manufacturer | Manufacturer | VENDOR | TEXT |
| model_no | Model No. | VENDOR | TEXT |
| mr_no | MR No. | USER | TEXT |
| po_no | PO No. | USER | TEXT |
| moc_no | MOC No. | USER | TEXT |
| job_id_ref | Job ID | USER | TEXT |
| requisition_no | Requisition No. | USER | TEXT |
| material_code | Material Code | USER | TEXT |
| client_reference | Client Reference | USER | TEXT |
| rev | Rev | USER | TEXT |
| prepared_by | By | USER | TEXT |
| checked_by | Chk | USER | TEXT |
| approved_by | Appr | USER | TEXT |
| doc_date | Date | USER | DATE |

---

## 1. Control Valve / Anti-Surge — `instrument_cv` (~82 cols)

| Column | Label | Source | SQL |
|---|---|---|---|
| cv_case | Case | PROCESS | TEXT |
| fluid_tending_to | Fluid Tending To | PROCESS | TEXT |
| air_fail_position | Air-Fail Position | PROCESS | TEXT |
| inlet_line_size | Inlet Line Size | PROCESS | TEXT |
| inlet_piping_class | Inlet Piping Class | PROCESS | TEXT |
| inlet_line_material | Inlet Line Material | PROCESS | TEXT |
| inlet_line_schedule | Inlet Line Schedule | PROCESS | TEXT |
| outlet_line_size | Outlet Line Size | PROCESS | TEXT |
| outlet_piping_class | Outlet Piping Class | PROCESS | TEXT |
| outlet_line_material | Outlet Line Material | PROCESS | TEXT |
| outlet_line_schedule | Outlet Line Schedule | PROCESS | TEXT |
| special_conditions | Special Conditions | PROCESS | TEXT |
| insulation_code_thickness | Insulation Code/Thickness | PROCESS | TEXT |
| operat_spec_gravity | Operating Spec Gravity | PROCESS | NUMERIC |
| cp_cv_ratio | Cp/Cv | PROCESS | NUMERIC |
| compressibility_z | Compressibility Z | PROCESS | NUMERIC |
| vapour_pressure_nom_t | Vapour Press @ Nom T | PROCESS | NUMERIC |
| viscosity_op_cond | Viscosity @ Op Cond | PROCESS | NUMERIC |
| critical_pressure | Critical Pressure | PROCESS | NUMERIC |
| critical_temperature | Critical Temperature | PROCESS | NUMERIC |
| density_min | Density Min | PROCESS | NUMERIC |
| density_norm | Density Norm | PROCESS | NUMERIC |
| density_max | Density Max | PROCESS | NUMERIC |
| density_unit | Density Unit | PROCESS | TEXT |
| flow_min | Flow Min | PROCESS | NUMERIC |
| flow_norm | Flow Norm | PROCESS | NUMERIC |
| flow_max | Flow Max | PROCESS | NUMERIC |
| flow_unit | Flow Unit | PROCESS | TEXT |
| temp_q_min | Temp Q Min | PROCESS | NUMERIC |
| temp_q_norm | Temp Q Norm | PROCESS | NUMERIC |
| temp_q_max | Temp Q Max | PROCESS | NUMERIC |
| press_q_min | Press Q Min | PROCESS | NUMERIC |
| press_q_norm | Press Q Norm | PROCESS | NUMERIC |
| press_q_max | Press Q Max | PROCESS | NUMERIC |
| dp_q_min | DP Q Min | PROCESS | NUMERIC |
| dp_q_norm | DP Q Norm | PROCESS | NUMERIC |
| dp_q_max | DP Q Max | PROCESS | NUMERIC |
| cv_min | CV Min | PROCESS | NUMERIC |
| cv_norm | CV Norm | PROCESS | NUMERIC |
| cv_max | CV Max | PROCESS | NUMERIC |
| lifting_pct_min | Lifting % Min | PROCESS | NUMERIC |
| lifting_pct_norm | Lifting % Norm | PROCESS | NUMERIC |
| lifting_pct_max | Lifting % Max | PROCESS | NUMERIC |
| noise_dba_min | Noise dBA Min | PROCESS | NUMERIC |
| noise_dba_norm | Noise dBA Norm | PROCESS | NUMERIC |
| noise_dba_max | Noise dBA Max | PROCESS | NUMERIC |
| required_cv | Required CV | PROCESS | NUMERIC |
| selected_cv | Selected CV | PROCESS | NUMERIC |
| mechanical_stop | Mechanical Stop | PROCESS | TEXT |
| fd_factor | Fd | PROCESS | NUMERIC |
| fl_cf_factor | Fl (Cf) | PROCESS | NUMERIC |
| body_type | Body Type | VENDOR | TEXT |
| body_material | Body Material | VENDOR | TEXT |
| max_dp_closed_valve | Max DP Closed Valve | VENDOR | NUMERIC |
| seat_leakage_class | Seat Leakage Class | VENDOR | TEXT |
| body_design_press_min | Body Design Press Min | PROCESS | NUMERIC |
| body_design_press_max | Body Design Press Max | PROCESS | NUMERIC |
| body_design_press_unit | Body Design Press Unit | PROCESS | TEXT |
| body_design_temp_min | Body Design Temp Min | PROCESS | NUMERIC |
| body_design_temp_max | Body Design Temp Max | PROCESS | NUMERIC |
| body_design_temp_unit | Body Design Temp Unit | PROCESS | TEXT |
| body_size | Body Size | VENDOR | TEXT |
| body_rating | Body Rating | VENDOR | TEXT |
| body_face | Body Face | VENDOR | TEXT |
| plug_type | Plug Type | VENDOR | TEXT |
| plug_material | Plug Material | VENDOR | TEXT |
| plug_dimension | Plug Dimension | VENDOR | TEXT |
| plug_form_law | Plug Form/Law | VENDOR | TEXT |
| seat_type | Seat Type | VENDOR | TEXT |
| seat_material | Seat Material | VENDOR | TEXT |
| packing_material | Packing Material | VENDOR | TEXT |
| lubricator | Lubricator | VENDOR | TEXT |
| bonnet_type | Bonnet Type | VENDOR | TEXT |
| stem_material | Stem Material | VENDOR | TEXT |
| body_area_classification | Area Classification | VENDOR | TEXT |
| req_safety_certification | Req. Safety Certification | VENDOR | TEXT |
| actuator_type | Actuator Type | VENDOR | TEXT |
| actuator_direction_of_action | Direction of Action | VENDOR | TEXT |
| actuator_spring_range | Spring Range | VENDOR | TEXT |
| actuator_supply | Actuator Supply Pressure | VENDOR | TEXT |
| positioner_type | Positioner Type | VENDOR | TEXT |
| positioner_input_signal | Positioner Input Signal | VENDOR | TEXT |
| positioner_fluid_connection | Positioner Fluid Connection | VENDOR | TEXT |
| positioner_electrical_connection | Positioner Electrical Connection | VENDOR | TEXT |
| positioner_elec_protection_class | Positioner Elec Protection Class | VENDOR | TEXT |
| positioner_enclosure_protection | Positioner Enclosure Protection | VENDOR | TEXT |
| positioner_surge_protection_device | Surge Protection Device | VENDOR | TEXT |
| positioner_action_direction | Positioner Action Direction | VENDOR | TEXT |
| handwheel | Handwheel | VENDOR | TEXT |
| handwheel_position | Handwheel Position | VENDOR | TEXT |
| booster_relay | Booster Relay | VENDOR | TEXT |
| locking_device | Locking Device | VENDOR | TEXT |
| filter | Filter | VENDOR | TEXT |
| press_reducing_valve | Press Reducing Valve | VENDOR | TEXT |
| air_set | Air Set | VENDOR | TEXT |
| pressure_gauge_acc | Pressure Gauge (accessory) | VENDOR | TEXT |
| solenoid_valve_make_model | Solenoid Valve (make/model) | VENDOR | TEXT |
| solenoid_valve_tag_no | Solenoid Valve Tag No. | PROCESS | TEXT |
| solenoid_elec_protection_class | Solenoid Elec Protection Class | VENDOR | TEXT |
| solenoid_enclosure_protection | Solenoid Enclosure Protection | VENDOR | TEXT |
| position_detector_make_model | Position Detector (make/model) | VENDOR | TEXT |
| position_detector_tag_no | Position Detector Tag No. | PROCESS | TEXT |
| position_detector_elec_protection_class | Position Detector Elec Protection Class | VENDOR | TEXT |
| position_detector_enclosure_protection | Position Detector Enclosure Protection | VENDOR | TEXT |
| position_transmitter_make_model | Position Transmitter (make/model) | VENDOR | TEXT |
| position_transmitter_tag_no | Position Transmitter Tag No. | PROCESS | TEXT |
| position_transmitter_elec_protection_class | Position Transmitter Elec Protection Class | VENDOR | TEXT |
| position_transmitter_enclosure_protection | Position Transmitter Enclosure Protection | VENDOR | TEXT |
| air_volume_tank_capacity | Air Volume Tank Capacity | VENDOR | TEXT |
| valve_weight | Valve Weight | VENDOR | NUMERIC |
| actuator_weight | Actuator Weight | VENDOR | NUMERIC |
| valve_mfr_model | Valve Mfr/Model | VENDOR | TEXT |
| actuator_mfr_model | Actuator Mfr/Model | VENDOR | TEXT |
| positioner_mfr_model | Positioner Mfr/Model | VENDOR | TEXT |

---

## 2. Pressure Transmitter — `instrument_pt` (~58 cols) · shared by Flow Transmitter

> **Flow Transmitter (FT)** uses this same table. The only FT-specific addition is
> `ft_manifold_type` (3-way vs 2-way) and the range section is read in DP units.

| Column | Label | Source | SQL |
|---|---|---|---|
| corrosive | Corrosive | PROCESS | TEXT |
| erosive | Erosive | PROCESS | TEXT |
| toxic | Toxic | PROCESS | TEXT |
| build_up | Build-up | PROCESS | TEXT |
| solidifying | Solidifying | PROCESS | TEXT |
| pulsation | Pulsation | PROCESS | TEXT |
| coagulation | Coagulation | PROCESS | TEXT |
| contains_particles | Contains Particles | PROCESS | TEXT |
| instrument_range_min | Instrument Range Min | USER | NUMERIC |
| instrument_range_max | Instrument Range Max | USER | NUMERIC |
| instrument_range_unit | Instrument Range Unit | USER | TEXT |
| calibration_range_min | Calibration Range Min | USER | NUMERIC |
| calibration_range_max | Calibration Range Max | USER | NUMERIC |
| calibration_range_unit | Calibration Range Unit | USER | TEXT |
| display_range_min | Display (Scale) Range Min | USER | NUMERIC |
| display_range_max | Display (Scale) Range Max | USER | NUMERIC |
| display_range_unit | Display (Scale) Range Unit | USER | TEXT |
| body_flange_type | Body/Flange Type | VENDOR | TEXT |
| vent_valve | Vent Valve | VENDOR | TEXT |
| drain_valve | Drain Valve | VENDOR | TEXT |
| vent_drain_size | Vent/Drain Size | VENDOR | TEXT |
| proc_conn_size | Process Conn Size | VENDOR | TEXT |
| proc_conn_rating | Process Conn Rating | VENDOR | TEXT |
| conn_type_std | Conn Type/Std | VENDOR | TEXT |
| mounting_type | Mounting Type | VENDOR | TEXT |
| body_flange_material | Body/Flange Material | VENDOR | TEXT |
| vent_drain_material | Vent/Drain Material | VENDOR | TEXT |
| bolting_material | Bolting Material | VENDOR | TEXT |
| gasket_oring_material | Gasket/O-Ring Material | VENDOR | TEXT |
| mounting_kit_material | Mounting Kit Material | VENDOR | TEXT |
| detector_type | Detector Type | VENDOR | TEXT |
| measurement_span_min | Measurement Span Min | VENDOR | NUMERIC |
| measurement_span_max | Measurement Span Max | VENDOR | NUMERIC |
| diaphragm_wetted_material | Diaphragm/Wetted Material | VENDOR | TEXT |
| fill_fluid_material | Fill Fluid Material | VENDOR | TEXT |
| output_signal_type | Output Signal Type (4-20mA) | VENDOR | TEXT |
| enclosure_ip_rating | Enclosure IP Rating | VENDOR | TEXT |
| enclosure_material | Enclosure Material | VENDOR | TEXT |
| digital_communication | Digital Communication (HART rev) | VENDOR | TEXT |
| signal_power_supply | Signal Power Supply | VENDOR | TEXT |
| integral_indicator_reqd | Integral Indicator Reqd | VENDOR | TEXT |
| integral_indicator_type | Integral Indicator Type (LCD) | VENDOR | TEXT |
| signal_termination_type | Signal Termination Type | VENDOR | TEXT |
| elect_conn_size | Elect Conn Size | VENDOR | TEXT |
| elect_conn_type | Elect Conn Type | VENDOR | TEXT |
| smart_device_type | Smart Device Type | VENDOR | TEXT |
| hardware_device_rev | Hardware Device Rev | VENDOR | TEXT |
| dd_edd_rev | DD/EDD Rev | VENDOR | TEXT |
| hart_version | HART Version | VENDOR | TEXT |
| itk_version | ITK Version (FF) | VENDOR | TEXT |
| cff_rev | CFF Rev | VENDOR | TEXT |
| pressure_accuracy | Pressure Accuracy | VENDOR | TEXT |
| zero_supply_elevation | Zero Supply/Elevation | VENDOR | TEXT |
| fill_fluid_sp_gr_temp | Fill Fluid Sp Gr @ Temp | VENDOR | TEXT |
| seal_type | Seal Type | VENDOR | TEXT |
| diaphragm_extn_length | Diaphragm Extn Length | VENDOR | TEXT |
| flush_conn_qty_size | Flush Conn Qty/Size | VENDOR | TEXT |
| seal_proc_conn_size | Seal Process Conn Size | VENDOR | TEXT |
| seal_proc_conn_rating | Seal Process Conn Rating | VENDOR | TEXT |
| seal_conn_type_std | Seal Conn Type/Std | VENDOR | TEXT |
| flushing_ring_reqd | Flushing Ring Reqd | VENDOR | TEXT |
| flushing_ring_rating | Flushing Ring Rating | VENDOR | TEXT |
| capillary_fitting_dia | Capillary Fitting Dia | VENDOR | TEXT |
| instr_conn_nom_size | Instr Conn nom Size | VENDOR | TEXT |
| diaphragm_material | Diaphragm Material | VENDOR | TEXT |
| lower_housing_material | Lower Housing Material | VENDOR | TEXT |
| upper_housing_material | Upper Housing Material | VENDOR | TEXT |
| seal_bolting_material | Seal Bolting Material | VENDOR | TEXT |
| seal_gasket_material | Seal Gasket Material | VENDOR | TEXT |
| capillary_moc | Capillary MOC | VENDOR | TEXT |
| seal_fill_fluid_material | Seal Fill Fluid Material | VENDOR | TEXT |
| ft_manifold_type | (FT only) Manifold Type (3-way/2-way) | VENDOR | TEXT |

---

## 3. Flow Transmitter — `instrument_pt` (shared)

No FT-unique table. Reuse `instrument_pt`; `ft_manifold_type` carries the manifold note,
and range columns are interpreted in DP units. **Build once, shared with PT.**

---

## 4. Temperature Transmitter — `instrument_tt` (~40 cols)

| Column | Label | Source | SQL |
|---|---|---|---|
| tt_calibration_range_min | Calibration Range Min | USER | NUMERIC |
| tt_calibration_range_max | Calibration Range Max | USER | NUMERIC |
| tt_calibration_range_unit | Calibration Range Unit | USER | TEXT |
| tt_display_range_min | Display (Scale) Range Min | USER | NUMERIC |
| tt_display_range_max | Display (Scale) Range Max | USER | NUMERIC |
| tt_display_range_unit | Display (Scale) Range Unit | USER | TEXT |
| tt_instrument_range_min | Instrument Range Min | USER | NUMERIC |
| tt_instrument_range_max | Instrument Range Max | USER | NUMERIC |
| tt_instrument_range_unit | Instrument Range Unit | USER | TEXT |
| housing_type | Housing Type | VENDOR | TEXT |
| input_sensor_type | Input Sensor Type | VENDOR | TEXT |
| input_sensor_quantity | Input Sensor Quantity | VENDOR | TEXT |
| output_signal_type | Output Signal Type | VENDOR | TEXT |
| temp_span_min | Temp Span Min | VENDOR | NUMERIC |
| temp_span_max | Temp Span Max | VENDOR | NUMERIC |
| temp_coef_tolerance_class | Temp Coef/Tolerance Class | VENDOR | TEXT |
| isolation_type | Isolation Type | VENDOR | TEXT |
| enclosure_ip_rating | Enclosure IP Rating | VENDOR | TEXT |
| characteristic_curve | Characteristic Curve | VENDOR | TEXT |
| digital_communication | Digital Communication | VENDOR | TEXT |
| signal_power_source | Signal Power Source | VENDOR | TEXT |
| configuration_of_wires | Configuration of Wires | VENDOR | TEXT |
| integral_indicator | Integral Indicator | VENDOR | TEXT |
| signal_termination_type | Signal Termination Type | VENDOR | TEXT |
| mounting_type | Mounting Type | VENDOR | TEXT |
| temp_compensation | Temp Compensation | VENDOR | TEXT |
| enclosure_material | Enclosure Material | VENDOR | TEXT |
| mounting_bracket | Mounting Bracket | VENDOR | TEXT |
| bolt_material | Bolt Material | VENDOR | TEXT |
| burnout_protection | Burnout Protection | VENDOR | TEXT |
| element_standard | Element Standard | VENDOR | TEXT |
| cable_entry_size | Cable Entry Size | VENDOR | TEXT |
| cable_quantity | Cable Quantity | VENDOR | TEXT |
| hot_backup_provided | Hot Backup Provided | VENDOR | TEXT |
| end_conn_size | End Conn Size | VENDOR | TEXT |
| end_conn_type | End Conn Type | VENDOR | TEXT |
| end_conn_qty | End Conn Qty | VENDOR | TEXT |
| smart_device_type | Smart Device Type | VENDOR | TEXT |
| hardware_device_rev | Hardware Device Rev | VENDOR | TEXT |
| dd_edd_rev | DD/EDD Rev | VENDOR | TEXT |
| hart_version | HART Version | VENDOR | TEXT |
| itk_version | ITK Version | VENDOR | TEXT |
| cff_rev | CFF Rev | VENDOR | TEXT |
| accuracy | Accuracy | VENDOR | TEXT |

---

## 5. Pressure Gauge — `instrument_pg` (~50 cols)

| Column | Label | Source | SQL |
|---|---|---|---|
| corrosive | Corrosive | PROCESS | TEXT |
| erosive | Erosive | PROCESS | TEXT |
| toxic | Toxic | PROCESS | TEXT |
| build_up | Build-up | PROCESS | TEXT |
| solidifying | Solidifying | PROCESS | TEXT |
| pulsation | Pulsation | PROCESS | TEXT |
| coagulation | Coagulation | PROCESS | TEXT |
| contains_particles | Contains Particles | PROCESS | TEXT |
| instrument_range_min | Instrument Range Min | PROCESS | NUMERIC |
| instrument_range_max | Instrument Range Max | PROCESS | NUMERIC |
| instrument_range_unit | Instrument Range Unit | PROCESS | TEXT |
| case_type | Case Type | VENDOR | TEXT |
| case_style | Case Style | VENDOR | TEXT |
| mounting_type | Mounting Type | VENDOR | TEXT |
| enclosure_ip_rating | Enclosure IP Rating | VENDOR | TEXT |
| liquid_fill_material | Liquid Fill Material | VENDOR | TEXT |
| proc_conn_size | Process Conn Size | VENDOR | TEXT |
| proc_conn_type | Process Conn Type | VENDOR | TEXT |
| proc_conn_location | Process Conn Location | VENDOR | TEXT |
| case_press_relief_type | Case Press Relief Type | VENDOR | TEXT |
| window_material | Window Material | VENDOR | TEXT |
| bolting_material | Bolting Material | VENDOR | TEXT |
| ring_material | Ring Material | VENDOR | TEXT |
| case_material | Case Material | VENDOR | TEXT |
| stem_material | Stem Material | VENDOR | TEXT |
| lower_housing_material | Lower Housing Material | VENDOR | TEXT |
| elastic_element_type | Elastic Element Type | VENDOR | TEXT |
| movement_style | Movement Style | VENDOR | TEXT |
| nom_accuracy_grade | Nom Accuracy Grade | VENDOR | TEXT |
| element_material | Element Material | VENDOR | TEXT |
| movement_material | Movement Material | VENDOR | TEXT |
| dial_scale_type | Dial Scale Type | VENDOR | TEXT |
| pointer_adjustment | Pointer Adjustment | VENDOR | TEXT |
| graduation_color | Graduation & Color | VENDOR | TEXT |
| scale_range_type | Scale Range Type | VENDOR | TEXT |
| dial_material | Dial Material | VENDOR | TEXT |
| dial_size | Dial Size | VENDOR | TEXT |
| accessory | Accessory | VENDOR | TEXT |
| accessory_code | Accessory Code | VENDOR | TEXT |
| accessory_material | Accessory Material | VENDOR | TEXT |
| seal_type | Seal Type | VENDOR | TEXT |
| diaphragm_extn_length | Diaphragm Extn Length | VENDOR | TEXT |
| flush_conn_qty_size | Flush Conn Qty/Size | VENDOR | TEXT |
| flushing_ring_assembly | Flushing Ring Assembly | VENDOR | TEXT |
| capillary_fitting_dia | Capillary Fitting Dia | VENDOR | TEXT |
| seal_proc_conn_size | Seal Process Conn Size | VENDOR | TEXT |
| seal_proc_conn_rating | Seal Process Conn Rating | VENDOR | TEXT |
| seal_proc_conn_type | Seal Process Conn Type | VENDOR | TEXT |
| gasket_oring_material | Gasket/O-ring Material | VENDOR | TEXT |
| fill_fluid_material | Fill Fluid Material | VENDOR | TEXT |
| instr_conn_nom_size | Instr Conn nom Size | VENDOR | TEXT |
| diaphragm_material | Diaphragm Material | VENDOR | TEXT |
| capillary_material | Capillary Material | VENDOR | TEXT |
| bolting_material_seal | Seal Bolting Material | VENDOR | TEXT |
| upper_housing_material | Upper Housing Material | VENDOR | TEXT |

---

## 6. Temperature Gauge — `instrument_tg` (~24 cols)

| Column | Label | Source | SQL |
|---|---|---|---|
| nozzle_stub_length | Nozzle/Stub Length | PROCESS | TEXT |
| nozzle_stub_sch | Nozzle/Stub Sch. | PROCESS | TEXT |
| corrosive | Corrosive | PROCESS | TEXT |
| erosive | Erosive | PROCESS | TEXT |
| toxic | Toxic | PROCESS | TEXT |
| vibration | Vibration | PROCESS | TEXT |
| solid_in_stream | Solid in Stream | PROCESS | TEXT |
| op_flow | Operating Flow | PROCESS | NUMERIC |
| velocity_at_max_flow | Velocity @ Max Flow | PROCESS | NUMERIC |
| instrument_range_min | Instrument Range Min | PROCESS | NUMERIC |
| instrument_range_max | Instrument Range Max | PROCESS | NUMERIC |
| accuracy | Accuracy | VENDOR | TEXT |
| case_size | Case Size | VENDOR | TEXT |
| dial_scale_type | Dial Scale Type | VENDOR | TEXT |
| pointer_adjustment | Pointer Adjustment | VENDOR | TEXT |
| graduations_color | Graduations & Color | VENDOR | TEXT |
| connection_location | Connection Location | VENDOR | TEXT |
| exterior_treatment_color | Exterior Treatment Color | VENDOR | TEXT |
| conn_nom_size | Conn nom Size | VENDOR | TEXT |
| conn_nom_type_style | Conn nom Type/Style | VENDOR | TEXT |
| element_type | Element Type | VENDOR | TEXT |
| case_type | Case Type | VENDOR | TEXT |
| case_style | Case Style | VENDOR | TEXT |
| max_fluid_vel_at_temp | Max Fluid Vel @ Temp | VENDOR | TEXT |
| min_insertion_length | Min Insertion Length | VENDOR | TEXT |
| allowable_length_at_max_flow | Allowable Length @ Max Flow | VENDOR | TEXT |
| gauge_manufacturer | Gauge Manufacturer | VENDOR | TEXT |
| gauge_model | Gauge Model | VENDOR | TEXT |

---

## 7. Thermowell — `instrument_tw` (~33 cols)

| Column | Label | Source | SQL |
|---|---|---|---|
| construction_type | Construction Type | VENDOR | TEXT |
| ring_style | Ring Style | VENDOR | TEXT |
| shank_style | Shank Style | VENDOR | TEXT |
| stem_od | Stem Outside Diameter | VENDOR | NUMERIC |
| bore_dia | Bore Dia | VENDOR | NUMERIC |
| stem_length | Stem Length | VENDOR | NUMERIC |
| od_at_support | OD at Support | VENDOR | NUMERIC |
| od_at_tip | OD at Tip | VENDOR | NUMERIC |
| stem_bulb_material | Stem/Bulb Material | VENDOR | TEXT |
| case_material | Case Material | VENDOR | TEXT |
| ring_material | Ring Material | VENDOR | TEXT |
| coating_material | Coating Material | VENDOR | TEXT |
| window_material | Window Material | VENDOR | TEXT |
| connection_material | Connection Material | VENDOR | TEXT |
| thermowell_material | Thermowell Material | VENDOR | TEXT |
| sheath_material_thickness | Sheath Material Thickness | VENDOR | TEXT |
| end_size_rating | End Size/Rating | VENDOR | TEXT |
| conn_type_std | Conn Type/Std | VENDOR | TEXT |
| ip_rating | IP Rating | VENDOR | TEXT |
| internal_conn_nom_size | Internal Conn nom Size | VENDOR | TEXT |
| insertion_length_u | Insertion Length (U) | VENDOR/PROCESS | NUMERIC |
| length_below_collar_u1 | Length below collar (U1) | VENDOR/PROCESS | NUMERIC |
| lagging_ext_length_t | Lagging Ext Length (T) | VENDOR/PROCESS | NUMERIC |
| flange_size | Flange Size | VENDOR | TEXT |
| flange_rating | Flange Rating | VENDOR | TEXT |
| flange_facing | Flange Facing | VENDOR | TEXT |
| flange_face_finish | Flange Face Finish | VENDOR | TEXT |
| well_dimension_mm | Well Dimension (mm) | VENDOR | TEXT |
| strength_calculation | Strength Calculation | VENDOR | TEXT |
| reference_dwg_no | Reference DWG No. | VENDOR | TEXT |
| standard_drawing | Standard Drawing | VENDOR | TEXT |
| pipe_nozzle_length | Pipe Nozzle Length | PROCESS | TEXT |
| thermowell_tag_no | Tag No. for Thermowell | PROCESS | TEXT |
| thermowell_manufacturer | Thermowell Manufacturer | VENDOR | TEXT |
| thermowell_model | Thermowell Model | VENDOR | TEXT |

---

## 8. Temperature Element / RTD / Thermocouple — `instrument_te` (~28 cols)

| Column | Label | Source | SQL |
|---|---|---|---|
| operating_differential_pressure | Operating Differential Pressure | PROCESS | NUMERIC |
| pulsation_vibration | Pulsation/Vibration | PROCESS | TEXT |
| element_type | Element Type | VENDOR | TEXT |
| single_double | Single/Double | VENDOR | TEXT |
| element_range | Element Range | PROCESS | TEXT |
| spec_calibration | Spec/Calibration | VENDOR | TEXT |
| tolerance_class | Tolerance Class | VENDOR | TEXT |
| sheath_material | Sheath Material | VENDOR | TEXT |
| insulator_material | Insulator Material | VENDOR | TEXT |
| wire_gauge_insul | Wire Gauge/Insul | VENDOR | TEXT |
| wire_configuration | Wire Configuration | VENDOR | TEXT |
| element_dia | Element Dia | VENDOR | NUMERIC |
| element_length | Element Length | VENDOR | NUMERIC |
| connection | Connection | VENDOR | TEXT |
| connection_size | Connection Size | VENDOR | TEXT |
| connection_material | Connection Material | VENDOR | TEXT |
| grounding_type | Grounding Type | VENDOR | TEXT |
| enclosure_class | Enclosure Class | VENDOR | TEXT |
| signal_cable_entry | Signal Cable Entry | VENDOR | TEXT |
| ex_protection | Ex Protection | VENDOR | TEXT |
| ex_approval | Ex Approval | VENDOR | TEXT |
| transmitter_mount_type | Transmitter Mount Type | VENDOR | TEXT |
| head_material | Head Material | VENDOR | TEXT |
| head_extension | Head Extension | VENDOR | TEXT |
| terminal_block | Terminal Block | VENDOR | TEXT |
| extension_length | Extension Length | VENDOR | NUMERIC |
| special_certificate | Special Certificate | USER | TEXT |
| inspection_welding_parts | Inspection for Welding Parts | USER | TEXT |
| te_manufacturer | Manufacturer | VENDOR | TEXT |
| te_model | Model | VENDOR | TEXT |
| te_option | Option | VENDOR | TEXT |

---

## 9. Flow / Sight Glass + Orifice — `instrument_fe` (~30 cols)

| Column | Label | Source | SQL |
|---|---|---|---|
| operating_differential_pressure | Operating Differential Pressure | PROCESS | NUMERIC |
| normal_flow | Normal Flow | PROCESS | NUMERIC |
| body_type | Body Type | VENDOR | TEXT |
| body_material | Body Material | VENDOR | TEXT |
| body_size_inlet | Body Size Inlet | PROCESS | TEXT |
| body_size_outlet | Body Size Outlet | PROCESS | TEXT |
| end_connections | End Connections | VENDOR | TEXT |
| press_temp_rating | Press & Temp Rating | VENDOR | TEXT |
| equalizing_conn_size | Equalizing Conn Size | VENDOR | TEXT |
| conn_orientation | Conn Orientation | VENDOR | TEXT |
| trim_material | Trim Material | VENDOR | TEXT |
| internal_check_valve | Internal Check Valve | VENDOR | TEXT |
| internal_bimetallic_vent | Internal Bimetallic Vent | VENDOR | TEXT |
| thermostatic_vent | Thermostatic Vent | VENDOR | TEXT |
| thermostatic_vent_material | Thermostatic Vent Material | VENDOR | TEXT |
| gage_glass | Gage Glass | VENDOR | TEXT |
| strainer_internal_external | Strainer Internal/External | VENDOR | TEXT |
| strainer_type_size | Strainer Type & Size | VENDOR | TEXT |
| strainer_body_material | Strainer Body Material | VENDOR | TEXT |
| strainer_press_temp_rating | Strainer Press & Temp Rating | VENDOR | TEXT |
| strainer_end_connections | Strainer End Connections | VENDOR | TEXT |
| strainer_blowoff_connections | Strainer Blowoff Connections | VENDOR | TEXT |
| strainer_mesh_size_material | Strainer Mesh Size & Material | VENDOR | TEXT |
| calc_orifice_size | Calc. Orifice Size | VENDOR | TEXT |
| selected_orifice_size | Selected Orifice Size | VENDOR | TEXT |
| view_glass_size | View Glass Size | VENDOR | TEXT |
| part_number | Part Number | VENDOR | TEXT |
| fe_manufacturer | Manufacturer | VENDOR | TEXT |
| fe_model | Model | VENDOR | TEXT |

---

## 10. Restriction Orifice — `instrument_ro` (~28 cols)

| Column | Label | Source | SQL |
|---|---|---|---|
| flow_rate | Flow Rate | PROCESS | NUMERIC |
| specific_heats_ratio_cp_cv | Specific Heats Ratio Cp/Cv | PROCESS | NUMERIC |
| compressibility_z | Compressibility Z | PROCESS | NUMERIC |
| velocity | Velocity | PROCESS | NUMERIC |
| quality_pct_superheat | Quality%/Superheat | PROCESS | TEXT |
| permanent_pressure_loss | Permanent Pressure Loss | PROCESS | NUMERIC |
| base_pressure | Base Pressure | PROCESS | NUMERIC |
| base_temperature | Base Temperature | PROCESS | NUMERIC |
| ro_type | Type | VENDOR | TEXT |
| bore_calculation | Bore Calculation | VENDOR | TEXT |
| mating_flange_size | Mating Flange Size | VENDOR | TEXT |
| mating_flange_rating | Mating Flange Rating | VENDOR | TEXT |
| mating_flange_facing | Mating Flange Facing | VENDOR | TEXT |
| bore_diameter_d | Bore Diameter (d) | VENDOR | NUMERIC |
| diameter_ratio_beta | Diameter Ratio (β=d/D) | VENDOR | NUMERIC |
| plate_material | Plate Material | VENDOR | TEXT |
| plate_thickness | Plate Thickness | VENDOR | NUMERIC |
| ring_material_type | Ring Material & Type | VENDOR | TEXT |
| ms_type | Multistage Type | VENDOR | TEXT |
| ms_number_of_stages | Multistage Number of Stages | VENDOR | NUMERIC |
| ms_end_connection | Multistage End Connection | VENDOR | TEXT |
| ms_flange_facing_finish | Multistage Flange Facing Finish | VENDOR | TEXT |
| ms_plate_material | Multistage Plate Material | VENDOR | TEXT |
| ms_body_material | Multistage Body Material | VENDOR | TEXT |
| ms_flange_material | Multistage Flange Material | VENDOR | TEXT |
| ms_bore_diameter | Multistage Bore Diameter | VENDOR | NUMERIC |
| ms_thickness | Multistage Thickness | VENDOR | NUMERIC |
| ro_manufacturer | Manufacturer | VENDOR | TEXT |
| ro_model | Model | VENDOR | TEXT |

---

## 11. Pressure Safety / Relief Valve — `instrument_psv` (~57 cols)

| Column | Label | Source | SQL |
|---|---|---|---|
| quantity | Quantity (No. of PSVs, e.g. 1W+1S) | PROCESS | TEXT |
| line_equipment_no | Line/Equipment No. | PROCESS | TEXT |
| nozzle_full_semi | Nozzle (Full / Semi) | PROCESS | TEXT |
| safety_relief | Safety / Relief | PROCESS | TEXT |
| conv_bellows_pilot | Conv. / Bellows / Pilot Operated | PROCESS | TEXT |
| sour_services | Sour Services | PROCESS | TEXT |
| bonnet_type | Bonnet Type | VENDOR | TEXT |
| painting_system | Painting System | VENDOR | TEXT |
| total_weight | Total Weight | VENDOR | NUMERIC |
| fluid | Fluid | PROCESS | TEXT |
| state | State | PROCESS | TEXT |
| corrosive_component | Corrosive Component | PROCESS | TEXT |
| multi_phase | Multi-phase | PROCESS | TEXT |
| required_capacity | Required Capacity (kg/h) | PROCESS | NUMERIC |
| accumulation_pct | Accumulation % | PROCESS | NUMERIC |
| molecular_weight | Molecular Weight | PROCESS | NUMERIC |
| specific_gravity | Specific Gravity | PROCESS | NUMERIC |
| pressure_operating | Pressure Operating (bar-g) | PROCESS | NUMERIC |
| pressure_max | Pressure Max (bar-g) | PROCESS | NUMERIC |
| pressure_design | Pressure Design (bar-g) | PROCESS | NUMERIC |
| cold_diff_test_pressure | Cold Differential Test Pressure | PROCESS | NUMERIC |
| temp_operating | Temperature Operating (°C) | PROCESS | NUMERIC |
| temp_max | Temperature Max (°C) | PROCESS | NUMERIC |
| temp_design | Temperature Design (°C) | PROCESS | NUMERIC |
| back_pressure_superimposed_constant | Back Pressure Superimposed (Constant) | PROCESS | NUMERIC |
| back_pressure_superimposed_variable | Back Pressure Superimposed (Variable) | PROCESS | NUMERIC |
| back_pressure_builtup | Back Pressure Built-up | PROCESS | NUMERIC |
| back_pressure_total | Back Pressure Total (bar-g) | PROCESS | NUMERIC |
| allowable_overpressure_pct | % Allowable Overpressure | PROCESS | NUMERIC |
| set_pressure | Set Pressure | PROCESS | NUMERIC |
| relieving_temperature | Relieving Temperature | PROCESS | NUMERIC |
| overpressure_factor | Overpressure Factor | PROCESS | NUMERIC |
| compr_factor_z | Compr. Factor (Z) | PROCESS | NUMERIC |
| cp_cv_ratio | Ratio of Specific Heats Cp/Cv | PROCESS | NUMERIC |
| relief_density | Relief Density (kg/m³) | PROCESS | NUMERIC |
| relief_viscosity | Relief Viscosity (cP) | PROCESS | NUMERIC |
| blowdown | Blowdown | PROCESS | NUMERIC |
| vapor_mass_fraction | Vapor Mass Fraction | PROCESS | NUMERIC |
| latent_heat_vaporisation | Latent Heat of Vaporisation | PROCESS | NUMERIC |
| liq_spec_heat_at_prv | Liq. Spec. Heat @ PRV | PROCESS | NUMERIC |
| system_spec_vol_at_prv_inlet | System Spec. Vol @ PRV inlet | PROCESS | NUMERIC |
| spec_vol_at_90pct_prv_inlet | Spec. Vol @ 90% PRV inlet | PROCESS | NUMERIC |
| design_code | Design Code (e.g. API STD 520 Pt 1) | PROCESS | TEXT |
| valve_discharge_to | Valve discharge to | PROCESS | TEXT |
| sizing_basis | Sizing Basis | PROCESS | TEXT |
| process_cal_capacity | Process Cal. Capacity | PROCESS | NUMERIC |
| calculated_area_mm2 | Calculated Area (mm²) | PROCESS | NUMERIC |
| vendor_cal_capacity | Vendor Cal. Capacity | VENDOR | NUMERIC |
| selected_area_mm2 | Selected Area (mm²) | VENDOR | NUMERIC |
| selected_capacity | Selected Capacity (kg/h) | VENDOR | NUMERIC |
| orifice_designation | Orifice Designation (API letter, e.g. Q) | VENDOR | TEXT |
| certified_relieving_capacity | Certified Relieving Capacity | VENDOR | NUMERIC |
| rupture_disc_other | Rupture Disc / Other | PROCESS/VENDOR | TEXT |
| size_inlet | Size Inlet (in) | PROCESS | TEXT |
| size_outlet | Size Outlet (in) | PROCESS | TEXT |
| rating_facing_inlet | Rating & Facing Inlet | VENDOR | TEXT |
| rating_facing_outlet | Rating & Facing Outlet | VENDOR | TEXT |
| flange_dim_finish | Flange Dim/Finish | VENDOR | TEXT |
| nuts_bolts_material | Nuts/Bolts Material | VENDOR | TEXT |
| body_bonnet_material | Body & Bonnet Material | VENDOR | TEXT |
| nozzle_disc_material | Nozzle & Disc Material | VENDOR | TEXT |
| spring_material | Spring Material | VENDOR | TEXT |
| resilient_seat_seal_material | Resilient Seat Seal Material | VENDOR | TEXT |
| bellows_material | Bellows Material | VENDOR | TEXT |
| external_paint | External Paint | VENDOR | TEXT |
| pilot_tubing_fitting_material | Pilot Tubing/Fitting Material | VENDOR | TEXT |
| pilot_type | Pilot Type (Flowing/Nonflowing) | VENDOR | TEXT |
| reaction_force | Reaction Force (kN) | VENDOR | NUMERIC |
| sound_pressure_level_30m | Calculated Sound Pressure Level @ 30m (dB) | VENDOR | NUMERIC |
| cap_screwed_bolted | Cap (Screwed/Bolted) | VENDOR | TEXT |
| lever_plain_packed | Lever (Plain/Packed) | VENDOR | TEXT |
| asme_code_stamping | ASME Code Stamping | VENDOR | TEXT |
| test_gag | Test Gag | VENDOR | TEXT |
| bug_screen | Bug Screen | VENDOR | TEXT |
| nace_mr0175 | NACE MR0175/ISO 15156 | USER | TEXT |
| test_cert | Test Cert | USER | TEXT |
| tag_number_nameplate | Tag Number Nameplate | USER | TEXT |

---

## Summary counts

| Table | Type | Total cols | of which VENDOR |
|---|---|---|---|
| instrument_common | all | 56 | 2 |
| instrument_cv | Control Valve | 82 | 53 |
| instrument_pt | Pressure / Flow Transmitter | 58 | 47 |
| instrument_tt | Temperature Transmitter | 43 | 34 |
| instrument_pg | Pressure Gauge | 54 | 43 |
| instrument_tg | Temperature Gauge | 28 | 17 |
| instrument_tw | Thermowell | 35 | 31 |
| instrument_te | Temperature Element/RTD | 31 | 24 |
| instrument_fe | Flow/Sight Glass + Orifice | 29 | 24 |
| instrument_ro | Restriction Orifice | 29 | 21 |
| instrument_psv | Pressure Safety Valve | 76 | 28 |
| **Total** | | **~521 rows** (≈430 distinct columns; some labels repeat across types) | **~324 VENDOR** |

> **Living document.** Same as `instrument-datasheet-fields.md`: when a new datasheet
> type arrives, add its `## N` table here AND its `## N` section there, then bump the
> counts. The two files are a matched pair.

*Generated 2026-06-17 from `instrument-datasheet-fields.md` (sources: ASV_IDS.xlsx,
Main Skid IDS.pdf, TNB-2 PT_FT_TT.pdf, Block-5 PSV). For the fetch API contract see
`vendor-portal-fields.md`.*
