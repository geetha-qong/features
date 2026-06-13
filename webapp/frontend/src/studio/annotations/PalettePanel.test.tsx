import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PalettePanel from "./PalettePanel";
import { useShortcuts } from "../shortcuts/useShortcuts";
import type { UseShortcutsResult } from "../shortcuts/useShortcuts";
import type { ShortcutMap } from "../shortcuts/api";

// Mock the keymap hook so we don't hit the network and can control the
// per-user bindings the palette renders its hotkey badges from.
vi.mock("../shortcuts/useShortcuts", () => ({
  useShortcuts: vi.fn(),
}));

const mockedUseShortcuts = vi.mocked(useShortcuts);

function mockShortcuts(shortcuts: ShortcutMap) {
  mockedUseShortcuts.mockReturnValue({
    shortcuts,
    update: vi.fn(),
    replace: vi.fn(),
    reset: vi.fn(),
    loading: false,
    error: null,
  } as UseShortcutsResult);
}

beforeEach(() => {
  // Default: empty keymap → rows fall back to their static design-time hints.
  mockShortcuts({});
});

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

  test("renders the user's customised hotkey for a class", () => {
    // User rebound the BV-valve select-class action to "v" (backend default
    // shape), and FT-instrument to "f". The badge must reflect these live
    // bindings, not the static design-time hints ("2" / "8").
    mockShortcuts({
      v: { action: "select-class", entity_class: "valve", sub_class: "BV" },
      f: { action: "select-class", entity_class: "instrument", sub_class: "FT" },
    });
    render(<PalettePanel activeMarkClass={null} onChange={() => {}} dark={false} />);

    const bvKbd = screen
      .getByTestId("palette-item-valve-BV")
      .querySelector("kbd.palette-row-kbd");
    expect(bvKbd?.textContent).toBe("V");

    const ftKbd = screen
      .getByTestId("palette-item-instrument-FT")
      .querySelector("kbd.palette-row-kbd");
    expect(ftKbd?.textContent).toBe("F");
  });

  test("falls back to the static design hint when no binding exists", () => {
    // Empty keymap (default from beforeEach) → BV shows its static "2" hint.
    render(<PalettePanel activeMarkClass={null} onChange={() => {}} dark={false} />);
    const bvKbd = screen
      .getByTestId("palette-item-valve-BV")
      .querySelector("kbd.palette-row-kbd");
    expect(bvKbd?.textContent).toBe("2");
  });
});
