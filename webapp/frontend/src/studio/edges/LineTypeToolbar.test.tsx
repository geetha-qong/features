import { render, screen, fireEvent } from "@testing-library/react";
import { describe, test, expect, vi } from "vitest";
import LineTypeToolbar from "./LineTypeToolbar";
import { LINE_STYLE, LINE_TYPE_ORDER } from "./lineStyles";

describe("LineTypeToolbar", () => {
  test("renders all four line-type buttons with their labels", () => {
    render(
      <LineTypeToolbar activeLineType="process_pipe" setActiveLineType={() => {}} />,
    );
    for (const lt of LINE_TYPE_ORDER) {
      const btn = screen.getByTestId(`line-type-btn-${lt}`);
      expect(btn).toBeInTheDocument();
      // Label text comes from lineStyles.LINE_STYLE
      expect(btn).toHaveTextContent(LINE_STYLE[lt].label);
    }
    expect(screen.getAllByRole("button")).toHaveLength(4);
  });

  test("clicking a button calls setActiveLineType with the corresponding type", () => {
    const setActive = vi.fn();
    render(
      <LineTypeToolbar activeLineType="process_pipe" setActiveLineType={setActive} />,
    );
    fireEvent.click(screen.getByTestId("line-type-btn-instrument"));
    expect(setActive).toHaveBeenCalledWith("instrument");

    fireEvent.click(screen.getByTestId("line-type-btn-signal"));
    expect(setActive).toHaveBeenCalledWith("signal");

    fireEvent.click(screen.getByTestId("line-type-btn-interlock"));
    expect(setActive).toHaveBeenCalledWith("interlock");

    expect(setActive).toHaveBeenCalledTimes(3);
  });

  test("the active button is visually distinguished from inactive ones", () => {
    render(
      <LineTypeToolbar activeLineType="signal" setActiveLineType={() => {}} />,
    );
    const active = screen.getByTestId("line-type-btn-signal");
    const inactive = screen.getByTestId("line-type-btn-process_pipe");

    // aria-pressed reflects the active state for accessibility tooling.
    expect(active).toHaveAttribute("aria-pressed", "true");
    expect(inactive).toHaveAttribute("aria-pressed", "false");

    // data-active is a stable hook for E2E / CSS selectors.
    expect(active.getAttribute("data-active")).toBe("true");
    expect(inactive.getAttribute("data-active")).toBe("false");

    // Background must differ between active and inactive — the active button
    // uses the qong-pink fill (#FF4DA8 via CSS var); jsdom resolves the
    // computed style as the literal we set inline.
    expect(active.style.background).not.toBe(inactive.style.background);
  });
});
