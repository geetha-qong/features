import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminLabelStudio from "./AdminLabelStudio";
import * as api from "./api";

vi.mock("./api");

beforeEach(() => {
  vi.resetAllMocks();
});

describe("AdminLabelStudio", () => {
  it("shows the 'not configured' banner when ls_configured is false", async () => {
    vi.mocked(api.listLsJobs).mockResolvedValue({
      jobs: [],
      ls_url: "http://localhost:9001",
      ls_configured: false,
    });
    render(<AdminLabelStudio />);
    await waitFor(() => {
      expect(screen.getByText(/not configured/i)).toBeInTheDocument();
    });
  });

  it("renders job rows and calls syncJobToLs on click", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listLsJobs).mockResolvedValue({
      jobs: [
        {
          id: 42,
          pid_no: "PID-001",
          original_filename: "drawing.pdf",
          status: "done",
          ls_project_id: null,
          ls_synced: false,
          valve_count: 7,
          created_at: "2026-05-28T10:00:00",
          ls_stats: {},
        },
      ],
      ls_url: "http://localhost:9001",
      ls_configured: true,
    });
    vi.mocked(api.syncJobToLs).mockResolvedValue({ job_id: 42, ls_project_id: 1, tiles_pushed: 5 });

    render(<AdminLabelStudio />);
    await waitFor(() => screen.getByTestId("ls-jobs-table"));

    expect(screen.getByText("drawing.pdf")).toBeInTheDocument();
    expect(screen.getByText("PID-001")).toBeInTheDocument();

    await user.click(screen.getByTestId("ls-sync-job-42"));
    await waitFor(() => {
      expect(api.syncJobToLs).toHaveBeenCalledWith(42);
    });
  });
});
