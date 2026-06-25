# Instrument Datasheet Fields — full column reference

**Purpose:** the complete set of columns Qong Studio should capture per instrument
type, extracted from real project datasheets, with each column tagged by where the
value comes from. Use this to build the **vendor-portal DB columns** (the
`[VENDOR]` rows) and the Qong Studio capture schema (all rows).

> **Living document** — instrument types are added as new datasheets arrive.
> To add a type: append a new `## N. <Type>` section (sections by source above),
> tag each field `[VENDOR]/[PROCESS]/[USER]`, and add its `[VENDOR]` columns to the
> consolidated build list at the end. **Types covered so far:** Control Valve,
> Pressure Transmitter, Flow Transmitter, Temperature Transmitter, Pressure Gauge,
> Temperature Gauge, Thermowell, Temperature Element/RTD, Flow/Sight Glass+Orifice,
> Restriction Orifice, Pressure Safety/Relief Valve.

**Sources (read 2026-06-17):**
- `23E065AJ01_ASV_IDS.xlsx` — Control Valve / Anti-Surge Valve (Masoneilan), 2 sheets.
- `Main Skid IDS.pdf` (58 pp, TechnipEnergies) — Pressure Gauge, Pressure Transmitter, Temperature Gauge, Thermowell, RTD element, Flow/Sight Glass, Restriction Orifice.
- `TNB-2-Process Instruments_PT_FT_TT.pdf` — Pressure / Flow / Temperature transmitters (full 82/67-field Technip forms).
- Block 5 Al-Shaheen PSV data sheet (Trillium Flow Technologies) — Pressure Safety Valve (added 2026-06-17 from a shared screenshot).

**Legend:** `[VENDOR]` supplied by the vendor portal (build these columns) ·
`[PROCESS]` from the P&ID / line list / process engineer (Qong extracts or a
reviewer enters) · `[USER]` commercial/admin (MR/PO/MOC, calibration ranges,
special requirements).

> Note: the **current** Qong datasheet generator (`webapp/deliverables/datasheet.py`)
> implements a much thinner subset of these. This doc is the **target** field set
> the real datasheets require — it's what the columns "that are gone" should be.

---

## 0. Common fields (every instrument — capture once)

| Field | Source |
|---|---|
| Tag No. | [PROCESS] |
| Service / Service Description | [PROCESS] |
| P&ID No. | [PROCESS] |
| Location (Field / CCR) | [PROCESS] |
| Unit / Equipment No. / Equipment System | [PROCESS] |
| Line No. · Line Size · Schedule · Pipe Class · Pipe Material · Insulation | [PROCESS] |
| Area / Hazardous Area Classification · Temp Class (T3/T6) · Ignition group | [PROCESS] |
| Ambient Temperature Min / Max | [PROCESS] |
| Fluid: Name · State · Phase | [PROCESS] |
| Operating Pressure / Temperature (Min · Nor · Max + unit) | [PROCESS] |
| Design Pressure / Temperature (Min · Max + unit) | [PROCESS] |
| Density · Viscosity · Molecular Weight | [PROCESS] |
| NACE Requirement · IBR Requirement · SIL Level Required | [PROCESS]/[USER] |
| Certification / Special Requirement (calib cert, MTC EN10204 3.1, PMI, hydrotest, dye-pen) | [USER] |
| Manufacturer · Model No. | **[VENDOR]** |
| MR No. · PO No. · MOC No. · Job ID · Requisition No. · Material Code · Client Reference | [USER] |
| Rev / By / Chk / Appr / Date | [USER] |

Per-type tables below list the fields **beyond** these common ones.

---

## 1. Control Valve / Anti-Surge Valve (CV) — `valve_cv`, `valve_*`
Source: `23E065AJ01_ASV_IDS.xlsx` (Masoneilan 51-series). ~61 fields, 14 sections.

| Section | Field | Source |
|---|---|---|
| General | Case · Fluid Tending To · Air-Fail Position | [PROCESS] |
| Inlet line | Line Size · Piping Class · Line Material · Line Schedule | [PROCESS] |
| Outlet line | Line Size · Piping Class · Line Material · Line Schedule | [PROCESS] |
| Operating | Special Conditions · Insulation Code/Thickness · Molecular Weight · Operat. Spec Gravity · Cp/Cv · Compressibility Z · Vapour Press @ Nom T · Viscosity @ Op Cond · Critical Pressure · Critical Temperature | [PROCESS] |
| Operating | Density (Min/Norm/Max/Unit) · Flow (Min/Norm/Max/Unit) · Temp (Q Min/Norm/Max) · Press (Q Min/Norm/Max) · DP (Q Min/Norm/Max) | [PROCESS] |
| Calculation | CV (Min/Norm/Max) · Lifting % (Min/Norm/Max) · Noise dBA (Min/Norm/Max) · Required CV · Selected CV · Mechanical Stop · Fd · Fl (Cf) | [PROCESS] |
| Valve Body | Body Type · Body Material · Max DP Closed Valve · Seat Leakage Class | **[VENDOR]** |
| Valve Body | Design Press Min/Max + Unit · Design Temp Min/Max + Unit | [PROCESS] |
| Valve Body | Size · Rating · Face · Plug Type · Plug Material · Plug Dimension · Plug Form/Law · Seat Type · Seat Material · Packing Material · Lubricator · Bonnet Type · Stem Material · Area Classification · Req. Safety Certification | **[VENDOR]** |
| Actuator | Actuator Type · Direction of Action · Spring Range · Supply (pressure) | **[VENDOR]** |
| Positioner | Type · Input Signal · Fluid Connection · Electrical Connection · Elec Protection Class · Enclosure Protection · Surge Protection Device · Action Direction | **[VENDOR]** |
| Accessories | Handwheel · Position · Booster Relay · Locking Device · Filter · Press Reduc Valve · Air Set · Pressure Gauge | **[VENDOR]** |
| Solenoid Valve | Solenoid Valve (make/model) · Tag No. · Elec Protection Class · Enclosure Protection | **[VENDOR]** + tag [PROCESS] |
| Position Detector | Position Detector (make/model) · Tag No. · Elec Protection Class · Enclosure Protection | **[VENDOR]** + tag [PROCESS] |
| Position Transmitter | Position Transmitter · Tag No. · Elec Protection Class · Enclosure Protection | **[VENDOR]** + tag [PROCESS] |
| Air Volume Tank | Capacity | **[VENDOR]** |
| Purchase | Weight (body/actuator) · Valve Mfr/Model · Actuator Mfr/Model · Positioner Mfr/Model | **[VENDOR]** |

---

## 2. Pressure Transmitter (PT) — `inst_*` / ISA `PT/PIT`
Source: `TNB-2…PT_FT_TT.pdf` p1 + `Main Skid IDS.pdf` p11–15. 82-field Technip form (incl. remote/diaphragm-seal column).

| Section | Field | Source |
|---|---|---|
| Process | Corrosive · Erosive · Toxic · Build-up · Solidifying · Pulsation · Coagulation · Contains Particles | [PROCESS] |
| Range | Instrument Range · Calibration Range · Display (Scale) Range (Min/Max + unit) | [USER] |
| Transmitter Body | Body/Flange Type · Vent Valve · Drain Valve · Vent/Drain Size · Proc Conn Size/Rating · Conn Type/Std · Mounting Type | **[VENDOR]** |
| Body Materials | Body/Flange Material · Vent/Drain Material · Bolting Material · Gasket/O-Ring Material · Mounting Kit Material | **[VENDOR]** |
| Sensing Element | Detector Type · Measurement Span Min/Max · Diaphragm/Wetted Material · Fill Fluid Material | **[VENDOR]** |
| Transmitter | Output Signal Type (4-20mA) · Enclosure IP Rating · Enclosure Material · Digital Communication (HART rev) · Signal Power Supply · Integral Indicator Reqd · Integral Indicator Type (LCD) · Signal Termination Type · Elect Conn Size · Elect Conn Type | **[VENDOR]** |
| Smart Device | Smart Device Type · Hardware Device Rev · DD/EDD Rev · HART Version · ITK Version (FF) · CFF Rev | **[VENDOR]** |
| Performance | Pressure Accuracy · Zero Supply/Elevation · Fill Fluid Sp Gr @ Temp | **[VENDOR]** |
| Diaphragm Seal (if fitted) | Seal Type · Diaphragm Extn Length · Flush Conn Qty/Size · Proc Conn Size/Rating · Conn Type/Std · Flushing Ring Reqd/Rating · Capillary Fitting Dia · Instr Conn nom Size · Diaphragm Material · Lower/Upper Housing Material · Bolting Material · Gasket Material · Capillary MOC · Fill Fluid Material | **[VENDOR]** |

---

## 3. Flow Transmitter (FT) — ISA `FT/FIT` (DP type)
Source: `TNB-2…PT_FT_TT.pdf` p2. **Uses the identical 82-field form as the Pressure
Transmitter** (DP-cell flow). No FT-unique columns — reuse the PT schema; only the
range section is in DP units and the manifold note differs (3-way vs 2-way).
→ **Build once, shared with PT.**

---

## 4. Temperature Transmitter (TT) — ISA `TT/TIT`
Source: `TNB-2…PT_FT_TT.pdf` p3 (Technip code 04004, 67 fields).

| Section | Field | Source |
|---|---|---|
| Range | Calibration Range · Display (Scale) Range · Instrument Range | [USER] |
| Transmitter | Housing Type · Input Sensor Type · Input Sensor Quantity · Output Signal Type · Temp Span Min/Max · Temp Coef/Tolerance Class · Isolation Type · Enclosure IP Rating · Characteristic Curve · Digital Communication · Signal Power Source · Configuration of Wires · Integral Indicator · Signal Termination Type · Mounting Type · Temp Compensation · Enclosure Material · Mounting Bracket · Bolt Material · Burnout Protection · Element Standard · Cable Entry Size · Cable Quantity · Hot Backup Provided · End Conn Size/Type/Qty | **[VENDOR]** |
| Smart Device | Smart Device Type · Hardware Device Rev · DD/EDD Rev · HART Version · ITK Version · CFF Rev | **[VENDOR]** |
| Performance | Accuracy | **[VENDOR]** |

---

## 5. Pressure Gauge (PG) — ISA `PG/PI`
Source: `Main Skid IDS.pdf` p5–10 (WIKA, code 03003, 52 fields + diaphragm-seal column).

| Section | Field | Source |
|---|---|---|
| Process | Corrosive · Erosive · Toxic · Build-up · Solidifying · Pulsation · Coagulation · Contains Particles | [PROCESS] |
| Range | Instrument Range (Min–Max + unit) | [PROCESS] |
| Conn & Case | Case Type · Case Style · Mounting Type · Enclosure IP Rating · Liquid Fill Material · Proc Conn Size/Type · Proc Conn Location · Case Press Relief Type · Window Material · Bolting Material · Ring Material · Case Material · Stem Material · Lower Housing Material | **[VENDOR]** |
| Element & Movement | Elastic Element Type · Movement Style · Nom Accuracy Grade · Element Material · Movement Material | **[VENDOR]** |
| Dial & Pointer | Dial Scale Type · Pointer Adjustment · Graduation & Color · Scale Range Type · Dial Material · Dial Size | **[VENDOR]** |
| Accessory | Accessory + Code + Material (Restrictor, Pulse Damper, Siphon, Gauge Saver, Snubber, Vacuum Protection, …) | **[VENDOR]** |
| Diaphragm Seal (if fitted) | Seal Type · Diaphragm Extn Length · Flush Conn Qty/Size · Flushing Ring Assembly · Capillary Fitting Dia · Proc Conn Size/Rating/Type · Gasket/O-ring Material · Fill Fluid Material · Instr Conn nom Size · Diaphragm/Capillary/Bolting/Upper-Housing Material | **[VENDOR]** |

---

## 6. Temperature Gauge (TG) — ISA `TG/TI`
Source: `Main Skid IDS.pdf` p16–20 (WIKA bimetallic).

| Section | Field | Source |
|---|---|---|
| Pipe/Nozzle | Nozzle/Stub Length · Nozzle/Stub Sch. | [PROCESS] |
| Process | Corrosive · Erosive · Toxic · Vibration · Solid in Stream | [PROCESS] |
| Operating | Op. Flow · Velocity @ Max Flow | [PROCESS] |
| Range | Instrument Range Min/Max · Accuracy | [PROCESS] / **[VENDOR]** (accuracy) |
| Dial & Pointer | Case Size · Dial Scale Type · Pointer Adjustment · Graduations & Color · Connection Location · Exterior Treatment Color · Conn nom Size · Conn nom Type/Style | **[VENDOR]** |
| Sensing Element | Element Type | **[VENDOR]** |
| Case | Case Type · Case Style | **[VENDOR]** |
| Performance | Max Fluid Vel @ Temp · Min Insertion Length · Allowable Length @ Max Flow | **[VENDOR]** |
| Purchase | Gauge Manufacturer · Gauge Model | **[VENDOR]** |

---

## 7. Thermowell (TW)
Source: `Main Skid IDS.pdf` (TG sheets + TE "Well" block). Often paired with TG/TE.

| Field | Source |
|---|---|
| Construction Type · Ring Style · Shank Style | **[VENDOR]** |
| Stem Outside Diameter · Bore Dia · Stem Length · OD at Support · OD at Tip | **[VENDOR]** |
| Stem/Bulb Material · Case Material · Ring Material · Coating Material · Window Material · Connection Material · Thermowell Material · Sheath Material thickness | **[VENDOR]** |
| End Size/Rating · Conn Type/Std · IP Rating · Internal Conn nom Size | **[VENDOR]** |
| Insertion Length (U) · Length below collar (U1) · Lagging Ext Length (T) | **[VENDOR]** / [PROCESS] |
| Flange Size/Rating/Facing · Flange Face Finish · Well Dimension (mm) · Strength Calculation · Reference DWG No. · Standard Drawing | **[VENDOR]** |
| Pipe Nozzle Length · Tag No. for Thermowell | [PROCESS] |
| Thermowell Manufacturer · Model | **[VENDOR]** |

---

## 8. Temperature Element / RTD / Thermocouple (TE)
Source: `Main Skid IDS.pdf` p30–47 (MINCO Pt100 RTD).

| Section | Field | Source |
|---|---|---|
| Process | Operating Differential Pressure · Pulsation/Vibration | [PROCESS] |
| Element | Type · Single/Double · Range · Spec/Calibration · Tolerance Class · Sheath Material · Insulator Material · Wire Gauge/Insul · Wire Configuration · Element Dia · Element Length | **[VENDOR]** (Range = [PROCESS]) |
| Connection | Connection · Connection Size · Material · Grounding Type | **[VENDOR]** |
| Enclosure/Ex | Enclosure Class · Signal Cable Entry · Ex Protection · Ex Approval | **[VENDOR]** |
| Head | Transmitter Mount Type · Head Material · Head Extension · Terminal Block · Extension Length | **[VENDOR]** |
| Cert | Special Certificate · Inspection for welding parts | [USER] |
| Purchase | Manufacturer · Model · Option | **[VENDOR]** |

---

## 9. Flow / Sight Glass + Orifice (FG/FE) — ISA `FG/FE`
Source: `Main Skid IDS.pdf` p48–55 (Elliott flow/sight glass; note: these are
sight-glass forms carrying orifice + strainer sub-sections, not classic orifice-plate metering sheets).

| Section | Field | Source |
|---|---|---|
| Service | Operating Differential Pressure · Normal Flow | [PROCESS] |
| Body | Type · Material · Size Inlet/Outlet · End Connections · Press & Temp Rating · Equalizing Conn Size · Conn Orientation | **[VENDOR]** (sizes [PROCESS]) |
| Trim | Material | **[VENDOR]** |
| Options | Internal Check Valve · Internal Bimetallic Vent · Thermostatic Vent/Material · Gage Glass | **[VENDOR]** |
| Strainer | Internal/External · Type & Size · Body Material · Press & Temp Rating · End Connections · Blowoff Connections · Mesh Size & Material | **[VENDOR]** |
| Purchase | Calc. Orifice Size · Selected Orifice Size · View Glass Size · Part Number · Manufacturer · Model | **[VENDOR]** |

---

## 10. Restriction Orifice (RO) — ISA `RO`
Source: `Main Skid IDS.pdf` p56–57.

| Section | Field | Source |
|---|---|---|
| Service | Flow Rate · Specific Heats Ratio Cp/Cv · Compressibility Z · Velocity · Quality%/Superheat · Permanent Pressure Loss · Base Pressure · Base Temperature | [PROCESS] |
| Basis | Type · Bore Calculation | **[VENDOR]** |
| Orifice Plate | Mating Flange Size/Rating/Facing · Bore Diameter (d) · Diameter Ratio (β=d/D) · Material · Thickness · Ring Material & Type | **[VENDOR]** |
| Multistage Orifice | Type · Number of Stages · End Connection · Flange Facing Finish · Plate/Body/Flange Material · Bore Diameter · Thickness | **[VENDOR]** |
| Purchase | Manufacturer · Model | **[VENDOR]** |

---

## 11. Pressure Safety / Relief Valve (PSV / PRV) — ISA `PSV/RV`, Qong `valve_relief_safety`
Source: Block 5 Al-Shaheen "Data Sheet for Pressure Safety Valves" (Trillium Flow
Technologies), `DTS` form. ~57 fields, 6 sections.

| Section | Field | Source |
|---|---|---|
| General | Tag No. · Quantity (No. of PSVs, e.g. 1W+1S) · Service · P&ID No. · Line/Equipment No. | [PROCESS] |
| General | Nozzle (Full / Semi) · Safety / Relief · Conv. / Bellows / Pilot Operated · Sour Services | [PROCESS] |
| General | Bonnet Type · Painting System · Total Weight | **[VENDOR]** |
| Process Conditions | Fluid · State · Corrosive Component · Multi-phase flag | [PROCESS] |
| Process Conditions | Required Capacity (kg/h) · Accumulation % · Molecular Weight · Specific Gravity | [PROCESS] |
| Process Conditions | Pressure: Operating / Max / Design (bar-g) · Cold Differential Test Pressure | [PROCESS] |
| Process Conditions | Temperature: Operating / Max / Design (°C) | [PROCESS] |
| Process Conditions | Back Pressure: Superimposed (Constant/Variable) · Built-up · Total (bar-g) | [PROCESS] |
| Process Conditions | % Allowable Overpressure · Set Pressure · Relieving Temperature · Overpres. Factor / Compr. Factor (Z) | [PROCESS] |
| Process Conditions | Ratio of Specific Heats Cp/Cv · Relief Density (kg/m³) · Relief Viscosity (cP) · Blowdown | [PROCESS] |
| Process Conditions | Vapor Mass Fraction · Latent Heat of Vaporisation · Liq. Spec. Heat @ PRV · System Spec. Vol @ PRV inlet · Spec. Vol @ 90% PRV inlet | [PROCESS] |
| Basis & Selection | Design Code (e.g. API STD 520 Pt 1) · Valve discharge to · Sizing Basis · Process Cal. Capacity · Calculated Area (mm²) | [PROCESS] |
| Basis & Selection | Vendor Cal. Capacity · Selected Area (mm²) · Selected Capacity (kg/h) · Orifice Designation (API letter, e.g. Q) · Certified Relieving Capacity | **[VENDOR]** |
| Basis & Selection | Rupture Disc / Other | [PROCESS]/[VENDOR] |
| Connections/Materials | Size Inlet/Outlet (in) · Rating & Facing Inlet/Outlet · Flange Dim/Finish | **[VENDOR]** (sizes [PROCESS]) |
| Connections/Materials | Nuts/Bolts Material · Body & Bonnet Material · Nozzle & Disc Material · Spring Material · Resilient Seat Seal Material · Bellows Material · External Paint · Pilot Tubing/Fitting Material | **[VENDOR]** |
| Connections/Materials | Pilot Type (Flowing/Nonflowing) · Reaction Force (kN) · Calculated Sound Pressure Level @ 30m (dB) | **[VENDOR]** |
| Options | Cap (Screwed/Bolted) · Lever (Plain/Packed) · ASME Code Stamping · Test Gag · Bug Screen | **[VENDOR]** |
| Options | NACE MR0175/ISO 15156 · Test Cert · Tag Number Nameplate | [USER] |
| Manufacturer & Model | Manufacturer · Model | **[VENDOR]** |

---

## 12. Vendor Portal — columns to build (consolidated)

Group the `[VENDOR]` columns into vendor catalog tables. Most are shared across
types; build a base + per-type extension.

**Identity (all types):** `manufacturer`, `model_number`, `part_number`, `product_id`

**Electrical / signal (transmitters, smart instruments):**
`output_signal_type`, `signal_power_supply`, `enclosure_ip_rating`,
`enclosure_material`, `digital_communication`, `elect_conn_size`,
`elect_conn_type`, `integral_indicator_reqd`, `integral_indicator_type`,
`signal_termination_type`, `cable_entry_size`, `cable_quantity`

**Smart device data (HART/FF):** `smart_device_type`, `hardware_device_rev`,
`dd_edd_rev`, `hart_version`, `itk_version`, `cff_rev`

**Performance:** `accuracy`, `measurement_span_min/max`, `temp_span_min/max`,
`tolerance_class`, `burnout_protection`, `zero_supply_elevation`, `fill_fluid_sp_gr`

**Process connection / body / materials:** `body_flange_type`, `body_flange_material`,
`proc_conn_size`, `proc_conn_rating`, `proc_conn_type`, `mounting_type`,
`bolting_material`, `gasket_oring_material`, `wetted_material`, `fill_fluid_material`,
`vent_drain_valve`, `vent_drain_size`

**Diaphragm/remote seal:** `seal_type`, `diaphragm_extn_length`, `flush_conn_qty_size`,
`flushing_ring_reqd`, `capillary_fitting_dia`, `capillary_moc`, `diaphragm_material`,
`upper_lower_housing_material`

**Control valve:** `body_type`, `body_material`, `seat_leakage_class`, `plug_type`,
`plug_material`, `seat_type`, `seat_material`, `packing_material`, `bonnet_type`,
`stem_material`, `trim_size_rating_face`, `actuator_type`, `actuator_supply`,
`spring_range`, `positioner_type`, `positioner_input_signal`,
`positioner_enclosure_protection`, `handwheel`, `air_set`, `solenoid_make_model`,
`position_detector_make_model`, `position_transmitter_make_model`, `air_volume_tank_capacity`,
`valve_weight`, `actuator_weight`

**Gauge (PG/TG):** `case_type`, `case_style`, `case_size`, `dial_size`, `dial_material`,
`dial_scale_type`, `pointer_adjustment`, `graduations_color`, `nom_accuracy_grade`,
`elastic_element_type`, `element_material`, `movement_style`, `movement_material`,
`window_material`, `liquid_fill_material`, `case_press_relief_type`, `min_insertion_length`

**Thermowell:** `construction_type`, `shank_style`, `stem_od`, `bore_dia`, `stem_length`,
`od_at_support`, `od_at_tip`, `stem_bulb_material`, `thermowell_material`,
`sheath_material_thickness`, `insertion_length_u`, `length_below_collar_u1`,
`lagging_ext_length_t`, `flange_size_rating_facing`, `well_dimension`, `ref_dwg_no`

**Temperature element (TE/RTD/TC):** `element_type`, `single_double`, `spec_calibration`,
`sheath_material`, `insulator_material`, `wire_gauge_insul`, `wire_configuration`,
`element_dia`, `element_length`, `connection_size`, `grounding_type`, `ex_protection`,
`ex_approval`, `head_material`, `head_extension`, `terminal_block`, `transmitter_mount_type`

**Orifice / flow element (FE/RO/FG):** `bore_diameter`, `diameter_ratio_beta`,
`plate_material`, `plate_thickness`, `ring_material_type`, `flange_size_rating_facing`,
`flange_facing_finish`, `number_of_stages`, `bore_calculation`, `selected_orifice_size`,
`view_glass_size`, `strainer_type_size`, `strainer_mesh_material`

**Pressure safety / relief valve (PSV/PRV):** `bonnet_type`, `total_weight`,
`orifice_designation` (API letter), `selected_area_mm2`, `selected_capacity`,
`vendor_cal_capacity`, `certified_relieving_capacity`, `rating_facing_inlet`,
`rating_facing_outlet`, `flange_dim_finish`, `nuts_bolts_material`,
`body_bonnet_material`, `nozzle_disc_material`, `spring_material`,
`resilient_seat_seal_material`, `bellows_material`, `pilot_tubing_material`,
`pilot_type`, `reaction_force`, `sound_pressure_level`, `cap_screwed_bolted`,
`lever_plain_packed`, `test_gag`, `bug_screen`, `asme_code_stamping`

---

*Generated 2026-06-17 from the datasheets listed above + the live Qong field
definitions. `[PROCESS]`/`[USER]` columns are captured in Qong Studio; `[VENDOR]`
columns are what the vendor portal must expose for Qong to fetch via the
instrument-match API (see `docs/vendor-portal-fields.md` for the API contract).*
