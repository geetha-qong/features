# Vendor Portal — Instrument Fields Reference

**Purpose:** the complete set of fields Qong Studio expects per instrument, so the
vendor portal can expose matching DB columns. Qong fetches these via the
**instrument-match API** to fill the Instrument Index and Instrument Datasheet.

> Every field below is taken from the live code — sources cited per section.
> Tags: **[PID]** extracted from the drawing · **[VENDOR]** supplied by the vendor
> portal (this is what you build) · **[USER]** filled by a reviewer · **[DERIVED]**
> computed by Qong from the tag.

---

## 1. How Qong fetches from the vendor portal

Source: `webapp/deliverables/vendor_match_client.py`

**Request** — Qong calls `POST {VENDOR_PORTAL}/api/instrument-match` with:
| field | meaning |
|---|---|
| `instType` | normalized instrument type code (see §2) |
| `range_min` | analog range low (optional, from PID) |
| `range_max` | analog range high (optional) |
| `range_unit` | engineering unit (optional) |

Header: `X-API-KEY: <key>`. Response must be `{"success": true, "data": {...}}`
(or `{"success": true, "matches": [{...}]}`).

**Response fields Qong reads** (→ where they land in Qong):
| vendor portal column (response key) | → Qong field |
|---|---|
| `vendor_name` | Manufacturer |
| `manufacturer` / `brand` | Manufacturer (fallback) |
| `model_number` / `model` | Model No |
| `product_id` | vendor product id |
| `piping_class` | Piping Class |
| `calibration_range_min` | CALB Range Min |
| `calibration_range_max` | CALB Range Max |
| `calibration_range_unit` | CALB Range Unit |
| `measuring_range_min` | Measuring Range Min |
| `measuring_range_max` | Measuring Range Max |
| `measuring_range_unit` | Measuring Range Unit |
| `power_supply_input` | Power In |
| `power_supply_output` | Power Out |
| `io_output` | IO Output |

These are the **minimum vendor-portal columns** for the Instrument Index. For the
Datasheet, also expose the catalog fields in §4.

---

## 2. Instrument type codes (what the vendor catalog keys on)

Source: `vendor_match_client._normalize_inst_type`. Qong normalizes the ISA tag
code before lookup, so your catalog only needs the **base** codes:

| Catalog code | Covers (ISA tag codes) | Description |
|---|---|---|
| `PT` | PT, PIT, PZIT, PZT … | Pressure transmitter |
| `FT` | FT, FIT, FZIT … | Flow transmitter |
| `LT` | LT, LIT, LZIT … | Level transmitter |
| `TT` | TT, TIT, TZIT … | Temperature transmitter |
| `AT` | AT, AIT … | Analyser transmitter |
| `FE` | FE | Flow primary element (orifice etc.) |
| `PBS` | HS, LIS, PSHH, FSLL, any switch/trip | Switch / push-button (all switches share one catalog entry) |

Rule of thumb: transmitter (code ends in **T**) → `{first letter}T`; primary
element (ends in **E**) → `{first letter}E`; switch/trip (ends in **S** or HH/LL/
SH/SL) → `PBS`. Define a catalog row per base code, per range band you support.

---

## 3. Instrument Index — full column set (35)

Source: `webapp/deliverables/customer_templates/default.json` (deliverable
`instrument_index`). Canonical field paths from `webapp/deliverables/pipeline_emitter.py`.

| # | Column | Canonical path | Source |
|---|---|---|---|
| 1 | Rev. No | `fields.rev_no` | [USER] |
| 2 | Unit Number | `fields.unit_number` | [DERIVED] (1st tag segment) |
| 3 | Loop. No | `fields.loop_name` | [DERIVED] (tag, type-code→1 letter, instance suffix dropped) |
| 4 | Instrument Type | `fields.tag_type_code` | [DERIVED] (alpha tag segment) |
| 5 | Service Description | `fields.service_description` | [PID] |
| 6 | P&ID No. | `pid_number` | [PID] |
| 7 | Line No. | `fields.line_no` | [PID] |
| 8 | Equipment No. | `fields.equipment_no` | [PID] |
| 9 | Location | `fields.location` | [PID] |
| 10 | System | `fields.system` | [DERIVED] (BPCS/SIS classify) |
| 11 | Sub System | `fields.technical_room` | [USER] |
| 12 | IO Type | `fields.io_type` | [DERIVED] (AI/AO/DI/DO) |
| 13 | IO Output | `fields.io_output` | **[VENDOR]** |
| 14 | Power In | `fields.power_in` | **[VENDOR]** |
| 15 | Power Out | `fields.power_out` | **[VENDOR]** |
| 16 | High High Alarm Limit | `fields.alarm_high_high` | [USER] |
| 17 | High Alarm Limit | `fields.alarm_high` | [USER] |
| 18 | Low Alarm Limit | `fields.alarm_low` | [USER] |
| 19 | Low Low Alarm Limit | `fields.alarm_low_low` | [USER] |
| 20 | Junction Box / Panel | `fields.junction_box_panel` | [USER] |
| 21 | Multi-Cable Type | `fields.multi_cable_type` | [USER] |
| 22 | Pair No. | `fields.pair_no` | [USER] |
| 23 | Manufacturer | `vendor_match.vendor_name` | **[VENDOR]** |
| 24 | Model No | `vendor_match.product_name` | **[VENDOR]** |
| 25 | Inst. Datasheet | `fields.datasheet_ref` | [PID]/[USER] |
| 26 | Piping Class | `fields.piping_class` | **[VENDOR]** |
| 27 | CALB Range Min | `fields.calb_range_min` | **[VENDOR]** |
| 28 | CALB Range Max | `fields.calb_range_max` | **[VENDOR]** |
| 29 | CALB Range Unit | `fields.calb_range_unit` | **[VENDOR]** |
| 30 | Measuring Range Min | `fields.measuring_range_min` | **[VENDOR]** |
| 31 | Measuring Range Max | `fields.measuring_range_max` | **[VENDOR]** |
| 32 | Measuring Range Unit | `fields.measuring_range_unit` | **[VENDOR]** |
| 33 | Certification | `fields.certification` | **[VENDOR]**/[USER] |
| 34 | Explosion Proof | `fields.explosion_proof` | **[VENDOR]**/[USER] |
| 35 | Remark | `fields.remark` | [PID]/[USER] |

Also captured on every instrument (not all shown as columns): `signal_type`,
`signal_level`, `external_power_supply`, `analog_range_low_scale`,
`analog_range_high_scale`, `analog_range_eu`.

---

## 4. Instrument Datasheet (IDS) — sectioned fields

Source: `webapp/deliverables/datasheet.py` (`IDS_SECTIONS`). This is the
control-valve / final-element datasheet. **[VENDOR]** rows resolve from
`vendor_match.catalog_fields.*` — i.e. extra vendor-portal columns beyond §1.

| Section | Field | Canonical path | Source |
|---|---|---|---|
| General Data | Tag Number | `tag` | [PID] |
| | Service | `fields.service_description` | [PID] |
| | P&ID No. | `pid_number` | [PID] |
| | Line Number | `fields.line_no` | [PID] |
| | SIL Level Required | `fields.ids_sil_level_required` | [USER] |
| | Nace Applicable | `fields.ids_nace_applicable` | [USER] |
| Inlet line | Line Size | `fields.ids_inlet_line_size` | [USER] |
| | Line Material | `fields.ids_inlet_line_material` | [USER] |
| | Piping Class | `fields.ids_inlet_line_class` | [USER] |
| Outlet line | Line Size | `fields.ids_outlet_line_size` | [USER] |
| | Line Material | `fields.ids_outlet_line_material` | [USER] |
| | Piping Class | `fields.ids_outlet_line_class` | [USER] |
| Operating Conditions | Fluid | `fields.ids_fluid` | [USER] |
| | Phase | `fields.ids_phase` | [USER] |
| Calculation Results | Required CV | `fields.ids_required_cv` | [USER] |
| | Selected CV | `fields.ids_selected_cv` | [USER] |
| Valve Body | Body Type | `vendor_match.catalog_fields.ids_body_type` | **[VENDOR]** |
| | Body Material | `vendor_match.catalog_fields.body_material` | **[VENDOR]** |
| | Design Pressure Max | `fields.ids_design_pressure_max` | [USER] |
| | Design Pressure Unit | `fields.ids_design_pressure_unit` | [USER] |
| | Design Temperature Max | `fields.ids_design_temperature_max` | [USER] |
| | Design Temperature Unit | `fields.ids_design_temperature_unit` | [USER] |
| Actuator | Actuator Type | `vendor_match.catalog_fields.ids_actuator_type` | **[VENDOR]** |
| | Supply Pressure | `vendor_match.catalog_fields.ids_actuator_supply` | **[VENDOR]** |
| Positioner | Input Signal | `vendor_match.catalog_fields.ids_input_signal` | **[VENDOR]** |
| | Electrical Connection | `vendor_match.catalog_fields.ids_electrical_connection` | **[VENDOR]** |
| | Enclosure Protection | `vendor_match.catalog_fields.ids_enclosure_protection` | **[VENDOR]** |
| Accessories | Handwheel | `vendor_match.catalog_fields.ids_handwheel` | **[VENDOR]** |
| | Solenoid Valve | `vendor_match.catalog_fields.ids_solenoid_valve` | **[VENDOR]** |
| Position Transmitter | Position Transmitter Tag | `fields.ids_position_transmitter_tag` | [USER] |
| | Air Volume Tank | `fields.ids_air_volume_tank` | [USER] |
| Purchase | Manufacturer | `vendor_match.vendor_name` | **[VENDOR]** |
| | Model No. | `vendor_match.product_name` | **[VENDOR]** |
| | Part Number | `vendor_match.part_number` | **[VENDOR]** |

---

## 5. What to build in the vendor portal (summary)

Per **catalog entry** = (instType base code from §2) × (range band), expose columns:

**Identity:** `vendor_name`, `manufacturer`/`brand`, `model_number`/`model`, `product_id`
**Electrical/IO:** `power_supply_input`, `power_supply_output`, `io_output`
**Ranges:** `calibration_range_min/max/unit`, `measuring_range_min/max/unit`
**Process:** `piping_class`, `certification`, `explosion_proof`
**Datasheet catalog_fields** (final elements / control valves): `ids_body_type`,
`body_material`, `ids_actuator_type`, `ids_actuator_supply`, `ids_input_signal`,
`ids_electrical_connection`, `ids_enclosure_protection`, `ids_handwheel`,
`ids_solenoid_valve`

Return these in the `data` (or `matches[0]`) object of `POST /api/instrument-match`
with `{"success": true, ...}`, keyed by `instType` (+ range). Qong merges them onto
the matched instrument and they flow into the Index + Datasheet automatically.

---

*Generated 2026-06-17 from: `vendor_match_client.py`, `datasheet.py`,
`pipeline_emitter.py`, `customer_templates/default.json`. If these change,
regenerate this doc.*
