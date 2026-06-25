import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import AdminAnnotationMetrics from "./AdminAnnotationMetrics";

const mockMetrics = {
  total_model_detections: 12,
  total_user_annotations: 7,
  by_status: {
    user_added: 4,
    user_confirmed: 2,
    user_rejected: 1,
    model_found: 0,
  },
  per_day_last_30: Array.from({ length: 30 }, (_, i) => ({
    date: `2026-06-${String(i + 1).padStart(2, "0")}`,
    model: i,
    user: 30 - i,
  })),
};

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => mockMetrics,
  } as Response);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AdminAnnotationMetrics", () => {
  test("renders top-line stats from API", async () => {
    render(<AdminAnnotationMetrics />);
    await waitFor(() => screen.getByTestId("metrics-root"));
    expect(screen.getByTestId("stat-model")).toHaveTextContent("12");
    expect(screen.getByTestId("stat-user")).toHaveTextContent("7");
    // ratio = 7/12 ≈ 0.58
    expect(screen.getByTestId("stat-ratio")).toHaveTextContent("0.58");
  });

  test("renders by-status counts", async () => {
    render(<AdminAnnotationMetrics />);
    await waitFor(() => screen.getByTestId("metrics-root"));
    expect(screen.getByTestId("status-count-user_added")).toHaveTextContent("4");
    expect(screen.getByTestId("status-count-user_confirmed")).toHaveTextContent("2");
    expect(screen.getByTestId("status-count-user_rejected")).toHaveTextContent("1");
  });

  test("renders 30-day chart with both series paths", async () => {
    render(<AdminAnnotationMetrics />);
    await waitFor(() => screen.getByTestId("perday-chart"));
    expect(screen.getByTestId("perday-line-model")).toBeInTheDocument();
    expect(screen.getByTestId("perday-line-user")).toBeInTheDocument();
  });

  test("shows error when fetch fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({}),
    } as Response);
    render(<AdminAnnotationMetrics />);
    await waitFor(() => screen.getByTestId("metrics-error"));
  });
});
