import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminFeedback from "./AdminFeedback";
import * as api from "./api";

vi.mock("./api");

const newItem = {
  id: 1,
  user_id: 2,
  username: "alice",
  category: "bug",
  subject: "Dashboard slow",
  message: "It takes 10 seconds to load.",
  page_url: "https://dev.qongsystems.com/dashboard",
  status: "new" as const,
  admin_notes: null,
  created_at: "2026-05-28T10:00:00",
};

const resolvedItem = {
  ...newItem,
  id: 2,
  subject: "Login fixed",
  status: "resolved" as const,
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.listFeedback).mockImplementation(async (filter) => {
    if (filter === "resolved") {
      return { items: [resolvedItem], status_filter: "resolved", open_count: 1 };
    }
    if (filter === "all") {
      return { items: [newItem, resolvedItem], status_filter: "all", open_count: 1 };
    }
    return { items: [newItem], status_filter: "new", open_count: 1 };
  });
});

describe("AdminFeedback", () => {
  it("loads with status_filter=new by default", async () => {
    render(<AdminFeedback />);
    await waitFor(() => screen.getByTestId("feedback-item-1"));
    expect(api.listFeedback).toHaveBeenCalledWith("new");
    expect(screen.getByText("Dashboard slow")).toBeInTheDocument();
    expect(screen.queryByText("Login fixed")).not.toBeInTheDocument();
  });

  it("re-fetches when filter changes", async () => {
    const user = userEvent.setup();
    render(<AdminFeedback />);
    await waitFor(() => screen.getByTestId("feedback-item-1"));

    await user.click(screen.getByTestId("feedback-filter-resolved"));
    await waitFor(() => {
      expect(api.listFeedback).toHaveBeenCalledWith("resolved");
    });
    expect(screen.getByText("Login fixed")).toBeInTheDocument();
  });

  it("renders page_url as a safe link (defense-in-depth render-side guard)", async () => {
    render(<AdminFeedback />);
    await waitFor(() => screen.getByTestId("feedback-item-1"));
    const link = screen.getByText("https://dev.qongsystems.com/dashboard").closest("a");
    expect(link).not.toBeNull();
    expect(link?.getAttribute("rel")).toContain("noopener");
    expect(link?.getAttribute("rel")).toContain("noreferrer");
  });

  it("does NOT render an href for non-http(s) page_url", async () => {
    vi.mocked(api.listFeedback).mockResolvedValueOnce({
      items: [{ ...newItem, page_url: "javascript:alert(1)" }],
      status_filter: "new",
      open_count: 1,
    });
    render(<AdminFeedback />);
    await waitFor(() => screen.getByTestId("feedback-item-1"));
    expect(screen.queryByText("javascript:alert(1)")).not.toBeInTheDocument();
  });
});
