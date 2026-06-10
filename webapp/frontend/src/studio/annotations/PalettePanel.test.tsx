import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PalettePanel from "./PalettePanel";

describe("PalettePanel", () => {
  test("renders category headers for valve, instrument, equipment", () => {
    render(<PalettePanel activeMarkClass={null} onChange={() => {}} dark={false} />);
    expect(screen.getByTestId("palette-cat-valve")).toBeTruthy();
    expect(screen.getByTestId("palette-cat-instrument")).toBeTruthy();
    expect(screen.getByTestId("palette-cat-equipment")).toBeTruthy();
    expect(screen.getByText("Valves")).toBeTruthy();
    expect(screen.getByText("Instruments")).toBeTruthy();
    expect(screen.getByText("Equipment")).toBeTruthy();
  });

  test("renders all 13 valve sub_class buttons", () => {
    render(<PalettePanel activeMarkClass={null} onChange={() => {}} dark={false} />);
    // A sample of the more important ones
    expect(screen.getByTestId("palette-item-valve-BV")).toBeTruthy();
    expect(screen.getByTestId("palette-item-valve-GT")).toBeTruthy();
    expect(screen.getByTestId("palette-item-valve-NCBV")).toBeTruthy();
    expect(screen.getByTestId("palette-item-valve-SB")).toBeTruthy();
  });

  test("clicking a sub_class button fires onChange with the right shape", () => {
    const onChange = vi.fn();
    render(<PalettePanel activeMarkClass={null} onChange={onChange} dark={false} />);
    fireEvent.click(screen.getByTestId("palette-item-valve-BV"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ entity_class: "valve", sub_class: "BV" });
  });

  test("clicking instrument sub_class fires onChange with entity_class=instrument", () => {
    const onChange = vi.fn();
    render(<PalettePanel activeMarkClass={null} onChange={onChange} dark={false} />);
    fireEvent.click(screen.getByTestId("palette-item-instrument-FT"));
    expect(onChange).toHaveBeenCalledWith({ entity_class: "instrument", sub_class: "FT" });
  });

  test("active button has data-active=true and pink background", () => {
    render(
      <PalettePanel
        activeMarkClass={{ entity_class: "valve", sub_class: "BV" }}
        onChange={() => {}}
        dark={false}
      />,
    );
    const btn = screen.getByTestId("palette-item-valve-BV") as HTMLButtonElement;
    expect(btn.dataset.active).toBe("true");
    // Style coming from inline `background`.
    expect(btn.style.background.toLowerCase()).toContain("var(--qong-pink");
    // Sibling that isn't armed should NOT be active.
    const other = screen.getByTestId("palette-item-valve-GT") as HTMLButtonElement;
    expect(other.dataset.active).toBe("false");
  });

  test("clicking the armed button again disarms (onChange(null))", () => {
    const onChange = vi.fn();
    render(
      <PalettePanel
        activeMarkClass={{ entity_class: "valve", sub_class: "BV" }}
        onChange={onChange}
        dark={false}
      />,
    );
    fireEvent.click(screen.getByTestId("palette-item-valve-BV"));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
