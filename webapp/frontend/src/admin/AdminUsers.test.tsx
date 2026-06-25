import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import AdminUsers from "./AdminUsers";
import * as api from "./api";
import { AuthProvider } from "../auth/AuthContext";

vi.mock("./api");

const seed = [
  {
    id: 1,
    username: "boss",
    email: null,
    role: "super_admin" as const,
    is_active: true,
    credits_remaining: 100,
    tier: "enterprise" as const,
    organization: null,
    created_at: "2026-01-01T00:00:00",
  },
  {
    id: 2,
    username: "alice",
    email: "alice@example.com",
    role: "user" as const,
    is_active: true,
    credits_remaining: 10,
    tier: "trial" as const,
    organization: null,
    created_at: "2026-01-02T00:00:00",
  },
];

beforeEach(() => {
  vi.resetAllMocks();
  // Mock the global fetch that AuthProvider uses on mount
  // AuthProvider calls GET /api/v1/account; we return a logged-in super_admin
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/v1/account")) {
        return new Response(
          JSON.stringify({ id: 1, username: "boss", email: "boss@x", role: "super_admin" }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      return new Response("{}", { status: 200 });
    }),
  );
  // api.* are typed mocks
  vi.mocked(api.listUsers).mockResolvedValue({ users: seed });
});

function renderUsers() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <AdminUsers />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("AdminUsers", () => {
  it("renders the user table from API data", async () => {
    renderUsers();
    expect(screen.getByText("Loading users…")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("admin-user-row-boss")).toBeInTheDocument();
    });
    expect(screen.getByTestId("admin-user-row-alice")).toBeInTheDocument();
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
  });

  it("filters by username when typing in the search box", async () => {
    const user = userEvent.setup();
    renderUsers();
    await waitFor(() => screen.getByTestId("admin-user-row-boss"));

    await user.type(screen.getByTestId("admin-users-search"), "alice");
    expect(screen.queryByTestId("admin-user-row-boss")).not.toBeInTheDocument();
    expect(screen.getByTestId("admin-user-row-alice")).toBeInTheDocument();
  });

  it("opens the edit modal when a row is clicked", async () => {
    const user = userEvent.setup();
    renderUsers();
    await waitFor(() => screen.getByTestId("admin-user-row-alice"));

    await user.click(screen.getByTestId("admin-user-row-alice"));
    expect(await screen.findByTestId("edit-user-modal")).toBeInTheDocument();
  });

  it("calls api.changeRole when 'Apply' clicked after selecting a different role", async () => {
    const user = userEvent.setup();
    vi.mocked(api.changeRole).mockResolvedValue({ ...seed[1], role: "annotator" });
    renderUsers();
    await waitFor(() => screen.getByTestId("admin-user-row-alice"));

    await user.click(screen.getByTestId("admin-user-row-alice"));
    await screen.findByTestId("edit-user-modal");

    // The select defaults to alice's current role "user"; change to "annotator"
    const select = screen.getByTestId("edit-user-role") as HTMLSelectElement;
    await user.selectOptions(select, "annotator");
    // Then click the Apply button for the role row
    const applyButtons = screen.getAllByText("Apply");
    await user.click(applyButtons[0]); // first Apply = role row
    await waitFor(() => {
      expect(api.changeRole).toHaveBeenCalledWith(2, "annotator");
    });
  });
});
