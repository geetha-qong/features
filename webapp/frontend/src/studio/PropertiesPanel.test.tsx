import { describe, test, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PropertiesPanel from "./PropertiesPanel";
import type { CanvasElement } from "./types";

// jsdom doesn't implement scrollIntoView (used by the panel's auto-scroll effect).
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

// Node-corrections (2026-06-28): the Remove gate widened from "user-added only"
// to "any selected node", and a rejected node swaps Remove → Restore. These
// tests pin that branch logic so a regression surfaces here, not in e2e.

const ELEMENTS: Record<string, CanvasElement> = {
  "e-valve": {
    tag: "62-BV-1",
    type: "Ball Valve",
    confidence: 0.9,
    lines: [],
    entityClass: "valve",
    subClass: "BV",
  },
};

function renderPanel(props: Partial<React.ComponentProps<typeof PropertiesPanel>>) {
  return render(
    <PropertiesPanel
      elements={ELEMENTS}
      selectedId="e-valve"
      onSelect={() => {}}
      hasDatasheet={false}
      onOpenDatasheet={() => {}}
      onCollapse={() => {}}
      {...props}
    />,
  );
}

describe("PropertiesPanel remove/restore gate", () => {
  test("shows Remove for any selected node when canRemove is true", () => {
    const onRemove = vi.fn();
    renderPanel({ canRemove: true, onRemove });
    const btn = screen.getByText("Remove");
    fireEvent.click(btn);
    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Restore")).toBeNull();
  });

  test("hides Remove when canRemove is false (no real entity selected)", () => {
    renderPanel({ canRemove: false });
    expect(screen.queryByText("Remove")).toBeNull();
    expect(screen.queryByText("Restore")).toBeNull();
  });

  test("shows Restore (not Remove) for a rejected node", () => {
    const onRestore = vi.fn();
    // canRemove true is irrelevant once isRejected — Restore takes precedence.
    renderPanel({ canRemove: true, isRejected: true, onRestore });
    expect(screen.queryByText("Remove")).toBeNull();
    const btn = screen.getByText("Restore");
    fireEvent.click(btn);
    expect(onRestore).toHaveBeenCalledTimes(1);
  });
});

describe("PropertiesPanel adopt-target (type-B node)", () => {
  test("shows 'Confirm as BV' button for a type-B node (no entity_id) and calls onAdopt on click", () => {
    const onAdopt = vi.fn();
    renderPanel({
      adoptTarget: { id: "n_1", entity_id: null, class: "valve_bv", bbox: [0, 0, 10, 10], tag: null, tile: "", confidence: 0.8 },
      onAdopt,
    });
    const btn = screen.getByRole("button", { name: /confirm as bv/i });
    fireEvent.click(btn);
    expect(onAdopt).toHaveBeenCalledWith(expect.objectContaining({ id: "n_1" }));
  });

  test("does not show adopt panel when adoptTarget is absent", () => {
    renderPanel({});
    expect(screen.queryByRole("button", { name: /confirm as/i })).toBeNull();
  });
});

describe("PropertiesPanel removed-nodes section", () => {
  test("no Removed section when nothing is removed", () => {
    renderPanel({ removedNodes: [] });
    expect(screen.queryByTestId("removed-list")).toBeNull();
  });

  test("lists removed nodes and restores by entity_id", () => {
    const onRestoreNode = vi.fn();
    renderPanel({
      removedNodes: [
        { entity_id: "x1", tag: "62-CK-1" },
        { entity_id: "x2", tag: "62-DB-9" },
      ],
      onRestoreNode,
    });
    expect(screen.getByTestId("removed-list")).toBeTruthy();
    expect(screen.getByText("62-CK-1")).toBeTruthy();
    expect(screen.getByText("62-DB-9")).toBeTruthy();
    // two Restore buttons (one per removed node); clicking the first restores x1
    const restores = screen.getAllByText("Restore");
    expect(restores).toHaveLength(2);
    fireEvent.click(restores[0]);
    expect(onRestoreNode).toHaveBeenCalledWith("x1");
  });
});
