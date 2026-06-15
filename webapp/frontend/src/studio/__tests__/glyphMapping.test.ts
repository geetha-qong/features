// __tests__/glyphMapping.test.ts
import { describe, it, expect } from "vitest";
import { labelToSymKind } from "../PidSymbol";

describe("labelToSymKind (YOLO label -> glyph kind)", () => {
  it("passes through labels that already are glyph kinds", () => {
    expect(labelToSymKind("valve_bf")).toBe("valve_bf");
    expect(labelToSymKind("inst_field")).toBe("inst_field");
    expect(labelToSymKind("arrow_up")).toBe("arrow_up");
    expect(labelToSymKind("Motor")).toBe("Motor");
  });
  it("normalizes the slash/space pump label", () => {
    expect(labelToSymKind("Pump/Dwg Pump")).toBe("pump");
  });
  it("falls back to valve_gen for unknown labels", () => {
    expect(labelToSymKind("nonsense_label")).toBe("valve_gen");
    expect(labelToSymKind(undefined)).toBe("valve_gen");
  });
});
