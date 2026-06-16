/**
 * Parity gate for the generated-taxonomy switch (taxonomy phase 3).
 *
 * paletteColors / labelMap / PidSymbol now SOURCE their data from
 * taxonomy.generated.ts (regenerated from webapp/taxonomy.json). This test
 * pins the public outputs against the values frozen BEFORE the switch, so a
 * future taxonomy.json edit that would change a rendered color / display name /
 * glyph can't slip through silently. If one of these fails, fix taxonomy.json
 * (or the documented frontend override), do not edit the consumers blindly.
 */
import { describe, it, expect } from "vitest";
import { colorForSubClass, colorForKind, NEUTRAL_COLOR, PALETTE } from "../paletteColors";
import { displayNameForSubClass, SUB_CLASS_NAMES } from "../labelMap";
import { subClassToSymKind } from "../PidSymbol";

// ── Frozen values (captured from the pre-switch hard-coded tables) ───────────

// colorForSubClass(entity_class, sub) for every current palette sub.
const FROZEN_SUB_COLORS: Record<string, string> = {
  "valve|BV": "#86D8C4",
  "valve|BF": "#FF6B6B",
  "valve|GT": "#7EC9C2",
  "valve|CK": "#D8C794",
  "valve|DB": "#7FD4D2",
  "valve|GL": "#A8DD92",
  "valve|CV": "#C49AE2",
  "valve|NCBV": "#86A8E8",
  "valve|VB": "#8EE0CE",
  "valve|VF": "#92B4E8",
  "valve|VD": "#EBA6C6",
  "valve|PV": "#EB8070",
  "valve|SB": "#C3B4EC",
  "instrument|FT": "#E5CBA0",
  "instrument|PT": "#C5BCEC",
  "instrument|TT": "#8585D6",
  "instrument|LT": "#B4ACE6",
  "instrument|AT": "#EC9696",
  "instrument|PIC": "#C6C6CE",
  "instrument|FIC": "#ACDC90",
  "instrument|TIC": "#ECA666",
  "instrument|LIC": "#EC8698",
  "equipment|Pump": "#8CCC76",
  "equipment|Vessel": "#B496DC",
  "equipment|Exchanger": "#DCD486",
  "equipment|Tank": "#DCC68C",
};

// displayNameForSubClass(sub) for every current SUB_CLASS_NAMES entry.
const FROZEN_SUB_NAMES: Record<string, string> = {
  BV: "Ball Valve",
  BF: "Butterfly Valve",
  GT: "Gate Valve",
  CK: "Check Valve",
  DB: "Diaphragm Valve",
  GL: "Globe Valve",
  CV: "Control Valve",
  NCBV: "NC Ball Valve",
  PNEUCTRL: "Pneumatic Valve",
  RELIEF_SAFETY: "Relief / Safety Valve",
  "3WAY_RELIEF": "3-Way Relief Valve",
  VB: "Block Valve",
  VF: "Flow Valve",
  VD: "Drain Valve",
  PV: "Pressure Valve",
  SB: "Sample/Bleed Valve",
  FT: "Flow Tx",
  PT: "Pressure Tx",
  TT: "Temperature Tx",
  LT: "Level Tx",
  AT: "Analytic Tx",
  PIC: "Pressure Ctrl",
  FIC: "Flow Ctrl",
  TIC: "Temperature Ctrl",
  LIC: "Level Ctrl",
  Pump: "Pump",
  Vessel: "Vessel",
  Exchanger: "Exchanger",
  Tank: "Tank",
};

// subClassToSymKind(entity_class, sub) for every current palette sub + the two
// frontend-override valves (NCBV/DB) + class-level fallbacks.
const FROZEN_GLYPH_KINDS: [string | undefined, string | undefined, string][] = [
  ["valve", "BV", "valve_bv"],
  ["valve", "BF", "valve_bf"],
  ["valve", "GT", "valve_gt"],
  ["valve", "CK", "valve_ck"],
  ["valve", "DB", "valve_db"],
  ["valve", "GL", "valve_gl"],
  ["valve", "CV", "valve_cv"],
  ["valve", "NCBV", "valve_ncbv"],
  ["valve", "PV", "valve_pneuctrl"],
  ["valve", "VB", "valve_gen"],
  ["valve", "VF", "valve_gen"],
  ["valve", "VD", "valve_gen"],
  ["valve", "SB", "valve_gen"],
  ["valve", "ZZZ", "valve_gen"],
  ["instrument", "FT", "inst_field"],
  ["instrument", "PT", "inst_field"],
  ["instrument", "LIC", "inst_field"],
  ["instrument", "XYZ", "inst_field"],
  ["equipment", "Pump", "pump"],
  ["equipment", "PUMP", "pump"],
  ["equipment", "Motor", "Motor"],
  ["equipment", "MOTOR", "Motor"],
  ["equipment", "Vessel", "inst_field"],
  ["equipment", "Tank", "inst_field"],
  [undefined, undefined, "valve_gen"],
  ["weird", "THING", "valve_gen"],
];

describe("taxonomy parity — generated module preserves pre-switch outputs", () => {
  it("colorForSubClass matches frozen palette colors", () => {
    for (const [key, hex] of Object.entries(FROZEN_SUB_COLORS)) {
      const [ec, sub] = key.split("|");
      expect(colorForSubClass(ec, sub)).toBe(hex);
    }
  });

  it("colorForSubClass falls back to neutral for unknowns", () => {
    expect(colorForSubClass("valve", "NOPE")).toBe(NEUTRAL_COLOR);
    expect(colorForSubClass(undefined, undefined)).toBe(NEUTRAL_COLOR);
  });

  it("colorForKind matches frozen kind colors", () => {
    expect(colorForKind("valve_bv")).toBe("#86D8C4");
    expect(colorForKind("valve_bf")).toBe("#FF6B6B");
    expect(colorForKind("inst_field")).toBe("#E5CBA0"); // first instrument sub (FT)
    expect(colorForKind("pump")).toBe("#8CCC76");
    expect(colorForKind("totally_unknown")).toBe(NEUTRAL_COLOR);
  });

  it("displayNameForSubClass matches frozen sub-class names", () => {
    for (const [sub, name] of Object.entries(FROZEN_SUB_NAMES)) {
      expect(displayNameForSubClass(sub)).toBe(name);
    }
  });

  it("SUB_CLASS_NAMES has no extra/missing keys vs frozen set", () => {
    expect(Object.keys(SUB_CLASS_NAMES).sort()).toEqual(
      Object.keys(FROZEN_SUB_NAMES).sort(),
    );
  });

  it("subClassToSymKind matches frozen glyph kinds", () => {
    for (const [ec, sub, kind] of FROZEN_GLYPH_KINDS) {
      expect(subClassToSymKind(ec, sub)).toBe(kind);
    }
  });

  it("PALETTE membership + order preserved", () => {
    expect(PALETTE.valve.map((e) => e.sub)).toEqual([
      "BV", "BF", "GT", "CK", "DB", "GL", "CV", "NCBV", "VB", "VF", "VD", "PV", "SB",
    ]);
    expect(PALETTE.instrument.map((e) => e.sub)).toEqual([
      "FT", "PT", "TT", "LT", "AT", "PIC", "FIC", "TIC", "LIC",
    ]);
    expect(PALETTE.equipment.map((e) => e.sub)).toEqual([
      "Pump", "Vessel", "Exchanger", "Tank",
    ]);
    // colors come through correctly on the assembled PALETTE entries.
    expect(PALETTE.valve.find((e) => e.sub === "BV")?.color).toBe("#86D8C4");
    expect(PALETTE.equipment.find((e) => e.sub === "Tank")?.color).toBe("#DCC68C");
  });
});
