import { describe, test, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import Shortcuts from "./Shortcuts";
import * as shortcutsApi from "../studio/shortcuts/api";
import { ThemeProvider } from "../theme/ThemeContext";

vi.mock("../studio/shortcuts/api");

const DEFAULTS: shortcutsApi.ShortcutMap = {
  v: { action: "select-class", entity_class: "valve", sub_class: "BV" },
  g: { action: "select-class", entity_class: "valve", sub_class: "GT" },
  "1": { action: "mode", mode: "select" },
  Escape: { action: "cancel" },
};

function renderShortcuts() {
  return render(
    <ThemeProvider>
      <Shortcuts />
    </ThemeProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(shortcutsApi.getShortcuts).mockResolvedValue({ ...DEFAULTS });
  vi.mocked(shortcutsApi.patchShortcuts).mockImplementation(async (m) => m);
  vi.mocked(shortcutsApi.resetShortcuts).mockResolvedValue({ ...DEFAULTS });
});

describe("Shortcuts page", () => {
  test("renders default shortcuts on mount", async () => {
    renderShortcuts();
    await waitFor(() => {
      expect(screen.getByTestId("shortcuts-row-v")).toBeInTheDocument();
    });
    expect(screen.getByTestId("shortcuts-row-g")).toBeInTheDocument();
    expect(screen.getByTestId("shortcuts-row-1")).toBeInTheDocument();
    expect(screen.getByTestId("shortcuts-row-Escape")).toBeInTheDocument();
    expect(shortcutsApi.getShortcuts).toHaveBeenCalled();
  });

  test("pressing a key in the capture input registers it", async () => {
    renderShortcuts();
    await waitFor(() => screen.getByTestId("shortcuts-row-v"));

    const capture = screen.getByTestId("shortcuts-new-key") as HTMLInputElement;
    fireEvent.keyDown(capture, { key: "x" });

    expect(capture.value).toBe("x");
  });

  test("modifier-held key in the capture input is ignored", async () => {
    renderShortcuts();
    await waitFor(() => screen.getByTestId("shortcuts-row-v"));

    const capture = screen.getByTestId("shortcuts-new-key") as HTMLInputElement;
    fireEvent.keyDown(capture, { key: "s", ctrlKey: true });

    expect(capture.value).toBe("");
  });

  test("selecting action=select-class shows sub_class picker", async () => {
    renderShortcuts();
    await waitFor(() => screen.getByTestId("shortcuts-row-v"));

    // select-class is the default action — pickers should already be present.
    expect(screen.getByTestId("shortcuts-new-entity-class")).toBeInTheDocument();
    expect(screen.getByTestId("shortcuts-new-sub-class")).toBeInTheDocument();

    // Switch to "mode" — sub_class picker should disappear, mode picker shows.
    fireEvent.change(screen.getByTestId("shortcuts-new-action"), {
      target: { value: "mode" },
    });
    expect(screen.queryByTestId("shortcuts-new-sub-class")).not.toBeInTheDocument();
    expect(screen.getByTestId("shortcuts-new-mode")).toBeInTheDocument();

    // Switch back to select-class — sub_class picker should be back.
    fireEvent.change(screen.getByTestId("shortcuts-new-action"), {
      target: { value: "select-class" },
    });
    expect(screen.getByTestId("shortcuts-new-sub-class")).toBeInTheDocument();
  });

  test("clicking save calls PATCH with the merged map", async () => {
    renderShortcuts();
    await waitFor(() => screen.getByTestId("shortcuts-row-v"));

    // Add a new binding for key "x".
    const capture = screen.getByTestId("shortcuts-new-key") as HTMLInputElement;
    fireEvent.keyDown(capture, { key: "x" });
    fireEvent.click(screen.getByTestId("shortcuts-add"));

    // Save.
    await act(async () => {
      fireEvent.click(screen.getByTestId("shortcuts-save"));
    });

    await waitFor(() => {
      expect(shortcutsApi.patchShortcuts).toHaveBeenCalled();
    });
    const sent = vi.mocked(shortcutsApi.patchShortcuts).mock.calls[0][0];
    expect(sent.x).toBeDefined();
    expect(sent.x.action).toBe("select-class");
    expect(sent.v).toBeDefined(); // existing bindings preserved (merged map)
    expect(sent.Escape).toBeDefined();
  });

  test("conflict on existing key requires a confirm-overwrite click", async () => {
    renderShortcuts();
    await waitFor(() => screen.getByTestId("shortcuts-row-v"));

    const capture = screen.getByTestId("shortcuts-new-key") as HTMLInputElement;
    fireEvent.keyDown(capture, { key: "v" });

    expect(screen.getByTestId("shortcuts-conflict")).toBeInTheDocument();

    // First click flips to "pending overwrite" mode; doesn't apply yet.
    fireEvent.click(screen.getByTestId("shortcuts-add"));
    // Capture input still has the pending key — overwrite hasn't been confirmed.
    expect((screen.getByTestId("shortcuts-new-key") as HTMLInputElement).value).toBe("v");

    // Second click commits the overwrite — capture should clear.
    fireEvent.click(screen.getByTestId("shortcuts-add"));
    expect((screen.getByTestId("shortcuts-new-key") as HTMLInputElement).value).toBe("");
  });

  test("reset button calls reset endpoint + reloads defaults", async () => {
    renderShortcuts();
    await waitFor(() => screen.getByTestId("shortcuts-row-v"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("shortcuts-reset"));
    });

    await waitFor(() => {
      expect(shortcutsApi.resetShortcuts).toHaveBeenCalled();
    });
    // After reset the map should still show defaults.
    expect(screen.getByTestId("shortcuts-row-v")).toBeInTheDocument();
  });

  test("delete button removes a binding from the local draft", async () => {
    renderShortcuts();
    await waitFor(() => screen.getByTestId("shortcuts-row-v"));

    fireEvent.click(screen.getByTestId("shortcuts-delete-v"));

    expect(screen.queryByTestId("shortcuts-row-v")).not.toBeInTheDocument();
    // Other bindings still present.
    expect(screen.getByTestId("shortcuts-row-g")).toBeInTheDocument();
  });
});
