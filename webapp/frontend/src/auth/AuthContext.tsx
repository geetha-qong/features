import { createContext, useContext, useEffect, useState, ReactNode } from "react";

export interface CurrentUser {
  id: number;
  username: string;
  email: string;
  role: string;
  /** IANA name or null. Null → callers should fall back to browser-detected. */
  timezone: string | null;
}

/** Browser-detected IANA timezone, with a safe fallback. */
export function detectBrowserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  login: (username: string, password: string, keepSignedIn: boolean) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      // GET /api/v1/account — returns { username, credits_remaining, tier }
      // when a valid JWT cookie is set. Returns 401 when not authenticated.
      // NOTE: the backend does not expose id or email via this endpoint, so
      // we synthesise defaults; they're sufficient for nav display.
      const res = await fetch("/api/v1/account", { credentials: "include" });
      if (res.ok) {
        const data = await res.json();
        setUser({
          id: data.id ?? 0,
          username: data.username,
          email: data.email ?? data.username,
          // role MUST come from the server explicitly — never fall back to
          // data.tier (was a bug; would render super_admin as "trial").
          role: typeof data.role === "string" ? data.role : "user",
          timezone: typeof data.timezone === "string" ? data.timezone : null,
        });
        // Auto-set TZ on first login: if server has no preference yet,
        // POST the browser-detected zone once silently. Subsequent logins
        // see the persisted value and skip this. Failures are ignored —
        // we don't want a TZ POST error to break login.
        if (!data.timezone) {
          const detected = detectBrowserTimezone();
          if (detected) {
            void fetch("/api/v1/account/timezone", {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ timezone: detected }),
              credentials: "include",
            }).catch(() => { /* best-effort */ });
          }
        }
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  async function login(
    username: string,
    password: string,
    _keepSignedIn: boolean,
  ): Promise<void> {
    // The existing webapp/routers/auth.py uses:
    //   POST /login
    //   Content-Type: application/x-www-form-urlencoded
    //   Body: username=<value>&password=<value>
    // On success → 303 redirect to /dashboard + Set-Cookie: access_token=<JWT>
    // On failure → 400/403 HTML response (Jinja template with error text)
    const form = new URLSearchParams();
    form.set("username", username);
    form.set("password", password);
    const res = await fetch("/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
      credentials: "include",
      redirect: "manual", // don't auto-follow the 303; we handle navigation ourselves
    });
    // fetch with redirect:"manual" gives status 0 + type "opaqueredirect" for a 3xx.
    // 4xx → JSON body `{ detail: "..." }` from FastAPI HTTPException.
    // (Pre-2026-06-02 the backend returned a Jinja-rendered HTML error page;
    // login.html was removed alongside GET /login, so the error is now JSON.)
    if (res.status >= 400) {
      let message = `Login failed (${res.status})`;
      try {
        const data = await res.json();
        if (data && typeof data.detail === "string" && data.detail.trim()) {
          message = data.detail.trim();
        }
      } catch {
        // ignore parse failures — fall back to the generic message above
      }
      throw new Error(message);
    }
    // Status 0 (opaqueredirect) = success; the cookie is now set.
    await refresh();
  }

  async function logout() {
    // GET /logout deletes the cookie and returns 303 → /signin
    await fetch("/logout", { credentials: "include" }).catch(() => {});
    setUser(null);
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}
