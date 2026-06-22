import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import DatasheetPanel from "./DatasheetPanel";
import * as api from "../api";
import type { EntityDatasheetResponse } from "../api";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    getEntityDatasheet: vi.fn(),
    patchEntity: vi.fn(),
  };
});

function datasheet(): EntityDatasheetResponse {
  return {
    entity_id: "e1",
    sub_class: "CV",
    type_label: "Control Valve",
    type_supported: true,
    tag: "PV-203",
    pid_number: "PID-1",
    sheet_number: 1,
    sections: [
      {
        name: "Identity",
        fields: [
          { field: "tag", header: "Tag No.", source: "process", editable: true, value: "PV-203", is_override: false },
          { field: "fields.service_description", header: "Service", source: "process", editable: true, value: null, is_override: false },
        ],
      },
      {
        name: "Valve Body",
        fields: [
          { field: "vendor_match.catalog_fields.body_material", header: "Body Material", source: "vendor", editable: false, value: "WCC", is_override: false },
          { field: "fields.ids_body_size", header: "Body Size", source: "process", editable: true, value: null, is_override: false },
        ],
      },
    ],
  };
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("DatasheetPanel", () => {
  it("renders every section and field for the selected instrument", async () => {
    vi.mocked(api.getEntityDatasheet).mockResolvedValue(datasheet());
    render(<DatasheetPanel jobId={55} entityId="e1" />);

    // All section names and field headers appear — not just the few list columns.
    expect(await screen.findByText("Identity")).toBeInTheDocument();
    expect(screen.getByText("Valve Body")).toBeInTheDocument();
    expect(screen.getByText("Tag No.")).toBeInTheDocument();
    expect(screen.getByText("Service")).toBeInTheDocument();
    expect(screen.getByText("Body Material")).toBeInTheDocument(); // vendor, read-only
    expect(screen.getByText("Body Size")).toBeInTheDocument();
    // Field-count summary in the save bar.
    expect(screen.getByText(/Control Valve · 4 fields/)).toBeInTheDocument();
  });

  it("saves only the edited field via patchEntity, then refetches", async () => {
    vi.mocked(api.getEntityDatasheet).mockResolvedValue(datasheet());
    vi.mocked(api.patchEntity).mockResolvedValue({ entity_id: "e1", applied: 1 });
    const onSaved = vi.fn();
    render(<DatasheetPanel jobId={55} entityId="e1" onSaved={onSaved} />);

    await screen.findByText("Identity");

    // Edit the Service field. Editable inputs render in DOM order:
    // Tag (0), Service (1), Body Size (2) — Body Material is vendor/read-only.
    const inputs = screen.getAllByRole("textbox");
    fireEvent.change(inputs[1], { target: { value: "Crude inlet" } });

    const saveBtn = screen.getByTitle(/Save 1 change/);
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(api.patchEntity).toHaveBeenCalledWith(55, "e1", {
        "fields.service_description": "Crude inlet",
      });
    });
    // Refetch (getEntityDatasheet called twice: initial + post-save) and onSaved fired.
    await waitFor(() => expect(api.getEntityDatasheet).toHaveBeenCalledTimes(2));
    expect(onSaved).toHaveBeenCalled();
  });
});
