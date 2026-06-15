import { describe, it, expect } from "vitest";
import { colorForSubClass, colorForKind, NEUTRAL_COLOR } from "../paletteColors";

describe("paletteColors", () => {
  it("returns the palette color for a known sub-class", () => {
    expect(colorForSubClass("valve", "BV")).toBe("#86D8C4");
    expect(colorForSubClass("valve", "BF")).toBe("#FF6B6B");
    expect(colorForSubClass("instrument", "FT")).toBe("#E5CBA0");
  });
  it("falls back to a neutral color for unknown sub-class", () => {
    expect(colorForSubClass("valve", "ZZZ")).toBe(NEUTRAL_COLOR);
    expect(colorForSubClass(undefined, undefined)).toBe(NEUTRAL_COLOR);
  });
  it("maps a glyph kind to the same palette color", () => {
    // valve_bv shares BV's color; inst_field shares an instrument color
    expect(colorForKind("valve_bv")).toBe("#86D8C4");
    expect(colorForKind("valve_bf")).toBe("#FF6B6B");
  });
  it("falls back to neutral for an unknown kind", () => {
    expect(colorForKind("totally_unknown")).toBe(NEUTRAL_COLOR);
  });
});
