import { describe, test, expect } from "vitest";
import { render } from "@testing-library/react";
import PidSymbol, { subClassToSymKind } from "./PidSymbol";

describe("PidSymbol", () => {
  test("renders an svg for a known kind", () => {
    const { container } = render(<PidSymbol kind="valve_bv" />);
    const svg = container.querySelector("svg");
    expect(svg).toBeTruthy();
    expect(svg?.getAttribute("viewBox")).toBe("0 0 30 26");
    // Ball valve = bowtie (2 polygons) + a centre circle.
    expect(container.querySelectorAll("polygon").length).toBe(2);
    expect(container.querySelector("circle")).toBeTruthy();
  });

  test("falls back to the generic valve glyph for an unknown kind", () => {
    const { container: known } = render(<PidSymbol kind="valve_gen" />);
    const { container: unknown } = render(<PidSymbol kind="totally_unknown_kind" />);
    // Same shape output as valve_gen (lead lines + bowtie polygons).
    expect(unknown.querySelectorAll("polygon").length).toBe(
      known.querySelectorAll("polygon").length,
    );
    expect(unknown.querySelector("svg")).toBeTruthy();
  });

  test("uses the sym-* shape classes so it themes via currentColor", () => {
    const { container } = render(<PidSymbol kind="valve_bf" />);
    expect(container.querySelector(".sym-line")).toBeTruthy();
    expect(container.querySelector(".sym-acc")).toBeTruthy();
  });
});

describe("subClassToSymKind", () => {
  test("maps known valve sub_classes", () => {
    expect(subClassToSymKind("valve", "BV")).toBe("valve_bv");
    expect(subClassToSymKind("valve", "BF")).toBe("valve_bf");
    expect(subClassToSymKind("valve", "PV")).toBe("valve_pneuctrl");
  });

  test("collapses unmapped valve codes onto valve_gen", () => {
    expect(subClassToSymKind("valve", "VB")).toBe("valve_gen");
    expect(subClassToSymKind("valve", "SB")).toBe("valve_gen");
  });

  test("instruments map to inst_field", () => {
    expect(subClassToSymKind("instrument", "FT")).toBe("inst_field");
    expect(subClassToSymKind("instrument", "LT")).toBe("inst_field");
  });

  test("equipment maps pump and motor, else inst_field", () => {
    expect(subClassToSymKind("equipment", "Pump")).toBe("pump");
    expect(subClassToSymKind("equipment", "Motor")).toBe("Motor");
    expect(subClassToSymKind("equipment", "Vessel")).toBe("inst_field");
  });

  test("unknown class falls back to valve_gen", () => {
    expect(subClassToSymKind(undefined, undefined)).toBe("valve_gen");
  });
});
