import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminPlans from "./AdminPlans";
import * as api from "./api";

vi.mock("./api");

const plan = {
  id: 1,
  name: "Starter",
  credits: 100,
  price_usd_cents: 999,
  is_active: true,
  stripe_price_id: null,
  created_at: "2026-05-28T10:00:00",
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.listPlans).mockResolvedValue({ plans: [plan] });
});

describe("AdminPlans", () => {
  it("renders the plans list", async () => {
    render(<AdminPlans />);
    await waitFor(() => screen.getByTestId("plans-table"));
    expect(screen.getByText("Starter")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("$9.99")).toBeInTheDocument();
  });

  it("calls api.togglePlan when the toggle button is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(api.togglePlan).mockResolvedValue({ ...plan, is_active: false });
    render(<AdminPlans />);
    await waitFor(() => screen.getByTestId("plans-table"));

    await user.click(screen.getByTestId("plan-toggle-1"));
    await waitFor(() => {
      expect(api.togglePlan).toHaveBeenCalledWith(1);
    });
  });
});
