import { describe, it, expect } from "vitest";
import { colorForSubClass, colorForKind, NEUTRAL_COLOR, PALETTE } from "../paletteColors";

// Digits reserved for canvas mode-switching in routers/shortcuts.py
// DEFAULT_SHORTCUTS ("1"→select, "2"→mark-symbol, "3"→draw-edge). A palette
// entry must never advertise one of these as its class-select hint.
const RESERVED_MODE_KEYS = new Set(["1", "2", "3"]);

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

  it("no palette entry hard-codes a hotkey hint colliding with mode keys", () => {
    // Regression: static digit hints (BF='1', BV='2', DB='3') used to shadow
    // the mode-switch keys. Hints now come solely from the live shortcut map,
    // so PALETTE entries must carry no `key` at all.
    for (const entries of Object.values(PALETTE)) {
      for (const e of entries) {
        if (e.key !== undefined) {
          expect(RESERVED_MODE_KEYS.has(e.key)).toBe(false);
        }
        // Stronger guarantee: no static hints remain anywhere.
        expect(e.key).toBeUndefined();
      }
    }
  });
});
