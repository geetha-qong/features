import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminLabelTriage from "./AdminLabelTriage";
import * as api from "./api";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    getTaxonomy: vi.fn(),
    listLabelTriage: vi.fn(),
    classifyLabelTriage: vi.fn(),
  };
});

const taxonomy = {
  schema_version: 1,
  classes: [
    {
      order: 0,
      yolo_label: "valve_bv",
      entity_class: "valve",
      sub_class: "BV",
      display_name: "Ball Valve",
      color: "#86D8C4",
      glyph_kind: "valve_bv",
    },
  ],
  yolo_routing: [],
};

const pendingItem = {
  id: 7,
  label_value: "XYZ-99",
  source: "ocr",
  discovered_at: "2026-06-15T10:00:00Z",
  status: "pending",
  assigned_entity_class: null,
  assigned_sub_class: null,
  assigned_display_name: null,
  assigned_color: null,
  assigned_glyph_kind: null,
  decided_by_user_id: null,
  decided_at: null,
  notes: null,
};

beforeEach(() => {
  vi.mocked(api.getTaxonomy).mockResolvedValue(taxonomy);
  vi.mocked(api.listLabelTriage).mockResolvedValue({ items: [pendingItem], status: "pending" });
  vi.mocked(api.classifyLabelTriage).mockResolvedValue({ ...pendingItem, status: "approved" });
});

describe("AdminLabelTriage", () => {
  it("loads pending triage rows + taxonomy reference by default", async () => {
    render(<AdminLabelTriage />);
    await waitFor(() => screen.getByTestId("triage-item-7"));
    expect(api.listLabelTriage).toHaveBeenCalledWith("pending");
    expect(screen.getByText("XYZ-99")).toBeInTheDocument();
    // Taxonomy reference panel
    expect(screen.getByText("Ball Valve")).toBeInTheDocument();
  });

  it("re-fetches when the status filter changes", async () => {
    const user = userEvent.setup();
    render(<AdminLabelTriage />);
    await waitFor(() => screen.getByTestId("triage-item-7"));

    await user.click(screen.getByTestId("triage-filter-approved"));
    await waitFor(() => {
      expect(api.listLabelTriage).toHaveBeenCalledWith("approved");
    });
  });

  it("posts an approve classify with the row draft", async () => {
    const user = userEvent.setup();
    render(<AdminLabelTriage />);
    await waitFor(() => screen.getByTestId("triage-item-7"));

    await user.click(screen.getByTestId("triage-approve-7"));
    await waitFor(() => {
      expect(api.classifyLabelTriage).toHaveBeenCalledWith(
        7,
        expect.objectContaining({ action: "approve", entity_class: "valve", display_name: "XYZ-99" }),
      );
    });
  });

  it("posts an ignore classify without taxonomy fields", async () => {
    const user = userEvent.setup();
    render(<AdminLabelTriage />);
    await waitFor(() => screen.getByTestId("triage-item-7"));

    await user.click(screen.getByTestId("triage-ignore-7"));
    await waitFor(() => {
      expect(api.classifyLabelTriage).toHaveBeenCalledWith(7, { action: "ignore" });
    });
  });
});
