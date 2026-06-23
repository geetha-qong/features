import { render, screen, fireEvent } from "@testing-library/react";
import { describe, test, expect, vi } from "vitest";
import EdgeMetadataDrawer from "./EdgeMetadataDrawer";
import type { EdgeLite } from "../PidCanvas";

const baseEdge: EdgeLite = {
  edge_id: "edge-1",
  source: "user",
  status: "user_added",
  line_type: "instrument",
  relation_type: null,
  source_entity_id: "ent-a",
  target_entity_id: "ent-b",
  polyline: [
    [10, 10],
    [100, 100],
  ],
  sheet_number: 1,
  group_id: null,
};

describe("EdgeMetadataDrawer", () => {
  test("renders with the passed edge — surfaces line_type and accepts inputs", () => {
    render(
      <EdgeMetadataDrawer edge={baseEdge} onSave={() => {}} onClose={() => {}} />,
    );
    const drawer = screen.getByTestId("edge-metadata-drawer");
    expect(drawer).toBeInTheDocument();
    // The drawer header shows the edge's line_type for context.
    expect(drawer).toHaveTextContent("instrument");
    expect(screen.getByTestId("edge-relation-select")).toBeInTheDocument();
    expect(screen.getByTestId("edge-group-input")).toBeInTheDocument();
    // Three metadata KV rows.
    expect(screen.getByTestId("edge-meta-key-0")).toBeInTheDocument();
    expect(screen.getByTestId("edge-meta-key-1")).toBeInTheDocument();
    expect(screen.getByTestId("edge-meta-key-2")).toBeInTheDocument();
  });

  test("Save calls onSave with the user-entered metadata", () => {
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(<EdgeMetadataDrawer edge={baseEdge} onSave={onSave} onClose={onClose} />);

    fireEvent.change(screen.getByTestId("edge-relation-select"), {
      target: { value: "measures" },
    });
    fireEvent.change(screen.getByTestId("edge-group-input"), {
      target: { value: "LOOP-101" },
    });
    fireEvent.change(screen.getByTestId("edge-meta-key-0"), {
      target: { value: "signal" },
    });
    fireEvent.change(screen.getByTestId("edge-meta-value-0"), {
      target: { value: "4-20mA" },
    });

    fireEvent.click(screen.getByTestId("edge-drawer-save"));

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith({
      relation_type: "measures",
      group_id: "LOOP-101",
      metadata_json: { signal: "4-20mA" },
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  test("Skip calls onClose and does NOT call onSave", () => {
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(<EdgeMetadataDrawer edge={baseEdge} onSave={onSave} onClose={onClose} />);

    // Even if the user typed something, Skip should discard it.
    fireEvent.change(screen.getByTestId("edge-group-input"), {
      target: { value: "LOOP-999" },
    });

    fireEvent.click(screen.getByTestId("edge-drawer-skip"));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });

  test("Save with an empty group_id and empty metadata rows emits nulls", () => {
    const onSave = vi.fn();
    render(<EdgeMetadataDrawer edge={baseEdge} onSave={onSave} onClose={() => {}} />);
    fireEvent.click(screen.getByTestId("edge-drawer-save"));
    expect(onSave).toHaveBeenCalledWith({
      relation_type: null,
      group_id: null,
      metadata_json: null,
    });
  });
});
