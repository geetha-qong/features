import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminCredits from "./AdminCredits";
import * as api from "./api";

vi.mock("./api");

const txns = [
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
  {
    id: 2,
    user_id: 3,
    username: "bob",
    delta: -5,
    balance_after: 5,
    reason: "job_consumed",
    job_id: 1,
    created_at: "2026-05-28T11:00:00",
  },
];

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.listCredits).mockResolvedValue({ transactions: txns });
});

describe("AdminCredits", () => {
  it("renders all transactions", async () => {
    render(<AdminCredits />);
    await waitFor(() => screen.getByTestId("credits-table"));
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByText("bob")).toBeInTheDocument();
    expect(screen.getByText("+100")).toBeInTheDocument();
    expect(screen.getByText("-5")).toBeInTheDocument();
  });

  it("filters by 'granted' sign", async () => {
    const user = userEvent.setup();
    render(<AdminCredits />);
    await waitFor(() => screen.getByTestId("credits-table"));

    await user.click(screen.getByText("granted"));
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.queryByText("bob")).not.toBeInTheDocument();
  });

  it("filters by username search", async () => {
    const user = userEvent.setup();
    render(<AdminCredits />);
    await waitFor(() => screen.getByTestId("credits-table"));

    await user.type(screen.getByPlaceholderText(/Search by username/), "bob");
    expect(screen.queryByText("alice")).not.toBeInTheDocument();
    expect(screen.getByText("bob")).toBeInTheDocument();
  });
});
