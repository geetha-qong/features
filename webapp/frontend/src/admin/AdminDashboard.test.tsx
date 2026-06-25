import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import AdminDashboard from "./AdminDashboard";
import * as api from "./api";

vi.mock("./api");

beforeEach(() => {
  vi.resetAllMocks();
});

describe("AdminDashboard", () => {
  it("renders the KPI stat strip from fetched data", async () => {
    vi.mocked(api.getKpis).mockResolvedValue({
      total_users: 42,
      active_users: 30,
      pending_users: 12,
      total_jobs: 100,
      done_jobs: 80,
      open_feedback: 3,
      mtd_consumed: 250,
      mtd_granted: 500,
      recent_txns: [
        {
          id: 1,
          user_id: 2,
          username: "alice",
          delta: 100,
          balance_after: 110,
          reason: "admin_grant",
          job_id: null,
          created_at: "2026-05-28T10:00:00",
        },
      ],
    });

    render(<AdminDashboard />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("admin-dashboard-stats")).toBeInTheDocument();
    });
    expect(screen.getByText("42")).toBeInTheDocument(); // total users
    expect(screen.getByText("30")).toBeInTheDocument(); // active
    expect(screen.getByText("12")).toBeInTheDocument(); // pending
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByText("+100")).toBeInTheDocument();
  });

  it("renders an error banner on API failure", async () => {
    vi.mocked(api.getKpis).mockRejectedValue(new Error("Network down"));
    render(<AdminDashboard />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByText("Network down")).toBeInTheDocument();
  });
});
