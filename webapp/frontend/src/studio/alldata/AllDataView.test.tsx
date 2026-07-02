import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import AllDataView from "./AllDataView";
import * as api from "../api";
import type { EntitiesResponse, EntityRow, JobDetectionsResp } from "../api";

vi.mock("../api", async (importOriginal) => {
  // Keep HttpError (a real class the component does `instanceof` against);
  // stub the network helpers.
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    getEntities: vi.fn(),
    getJobDetections: vi.fn(),
  };
});

function entity(
  id: string,
  entityClass: string,
  subClass: string,
  tag: string,
): EntityRow {
  return {
    entity_id: id,
    entity_class: entityClass,
    sub_class: subClass,
    tag,
    pid_number: "PID-001",
    sheet_number: 1,
    values: { "fields.size": { value: "8", source: "pid", is_override: false } },
  };
}

function entitiesResp(rows: EntityRow[]): EntitiesResponse {
  return {
    deliverable_type: "x",
    customer_template_slug: "default",
    schema: [],
    entities: rows,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("AllDataView", () => {
  it("renders entity rows and detections in one table, deduped by entity_id", async () => {
    const valve = entity("v1", "valve", "Ball Valve", "BV-101");
    // Same entity_id appears again via the datasheet fetch — must dedupe.
    vi.mocked(api.getEntities).mockImplementation((_jobId: number, type: string) => {
      if (type === "valve_list") return Promise.resolve(entitiesResp([valve]));
      if (type === "instrument_index")
        return Promise.resolve(
          entitiesResp([entity("i1", "instrument", "Transmitter", "PT-200")]),
        );
      if (type === "equipment_list") return Promise.resolve(entitiesResp([]));
      if (type === "datasheet") return Promise.resolve(entitiesResp([valve]));
      return Promise.resolve(entitiesResp([]));
    });
    const det: JobDetectionsResp = {
      job_id: 7,
      status: "done",
      valve_count: 1,
      detection_count: 1,
      valves: [],
      detections: [
        { label: "gate_valve", confidence: 0.91, tile: "r0c1", bbox: [10, 20, 30, 40] },
      ],
    };
    vi.mocked(api.getJobDetections).mockResolvedValue(det);

    render(<AllDataView jobId={7} projectName="Test Job" onBack={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("BV-101")).toBeInTheDocument();
    });
    expect(screen.getByText("PT-200")).toBeInTheDocument();
    expect(screen.getByText("gate_valve")).toBeInTheDocument();

    // 2 entities (valve deduped) + 1 detection = 3 total.
    const summary = screen.getByTestId("alldata-summary");
    expect(summary).toHaveTextContent("3");
    // Detection confidence rendered as a percentage.
    expect(screen.getByText("91%")).toBeInTheDocument();
  });

  it("filters by type chip (Detections shows only YOLO rows)", async () => {
    vi.mocked(api.getEntities).mockImplementation((_jobId: number, type: string) => {
      if (type === "valve_list")
        return Promise.resolve(entitiesResp([entity("v1", "valve", "Ball", "BV-101")]));
      return Promise.resolve(entitiesResp([]));
    });
    vi.mocked(api.getJobDetections).mockResolvedValue({
      job_id: 7,
      status: "done",
      valve_count: 0,
      detection_count: 1,
      valves: [],
      detections: [{ label: "gate_valve", confidence: 0.5, tile: "r0c0" }],
    });

    render(<AllDataView jobId={7} projectName="Test Job" onBack={() => {}} />);

    await waitFor(() => expect(screen.getByText("BV-101")).toBeInTheDocument());

    // Click the "Detections" chip → entity row disappears, detection remains.
    fireEvent.click(screen.getByRole("tab", { name: /Detections/ }));
    expect(screen.queryByText("BV-101")).not.toBeInTheDocument();
    expect(screen.getByText("gate_valve")).toBeInTheDocument();
  });

  it("shows a graceful empty state when there is no extracted data", async () => {
    vi.mocked(api.getEntities).mockRejectedValue(new api.HttpError("HTTP 404", 404));
    vi.mocked(api.getJobDetections).mockRejectedValue(new api.HttpError("HTTP 404", 404));

    render(<AllDataView jobId={9} projectName="Empty Job" onBack={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText(/No extracted data for job #9 yet/)).toBeInTheDocument();
    });
  });
});
