import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import RequireAuth from "./RequireAuth";
import { AuthProvider } from "./AuthContext";

function setupFetch(opts: { status: number; body?: object }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/v1/account")) {
        return new Response(JSON.stringify(opts.body ?? {}), {
          status: opts.status,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response("{}", { status: 200 });
    }),
  );
}

function renderAtPath(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AuthProvider>
        <Routes>
          <Route element={<RequireAuth />}>
            <Route path="/dashboard" element={<div data-testid="protected">PROTECTED</div>} />
            <Route path="/admin/users" element={<div data-testid="protected">PROTECTED</div>} />
          </Route>
          <Route path="/signin" element={<div data-testid="signin">SIGN IN PAGE</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("RequireAuth", () => {
  it("redirects to /signin when no user is authenticated", async () => {
    setupFetch({ status: 401 });
    renderAtPath("/dashboard");
    await waitFor(() => {
      expect(screen.getByTestId("signin")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
  });

  it("renders the protected child when authenticated", async () => {
    setupFetch({
      status: 200,
      body: { id: 1, username: "admin", email: "a@b", role: "super_admin" },
    });
    renderAtPath("/dashboard");
    await waitFor(() => {
      expect(screen.getByTestId("protected")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("signin")).not.toBeInTheDocument();
  });

  it("redirects deep admin paths to /signin when unauthenticated", async () => {
    setupFetch({ status: 401 });
    renderAtPath("/admin/users");
    await waitFor(() => {
      expect(screen.getByTestId("signin")).toBeInTheDocument();
    });
  });
});
