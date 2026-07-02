/**
 * Per-user Studio keyboard shortcuts — typed fetch helpers.
 *
 * Mirrors the contract in webapp/routers/shortcuts.py:
 *   GET   /api/v1/users/me/shortcuts       → returns merged-with-defaults map
 *   PATCH /api/v1/users/me/shortcuts       → whole-object replace; returns stored value (NOT merged)
 *   POST  /api/v1/users/me/shortcuts/reset → clears stored; returns defaults
 *
 * The PATCH semantics are "send the full desired state"; backend writes it
 * verbatim and only merges with defaults on the way out of GET.
 */

/** A single key → action binding. Field set varies by action; the union is
 *  accepted by the backend (extra="allow") so adding metadata later is safe. */
export interface ShortcutBinding {
  /** One of "select-class" | "mode" | "cancel" | "delete-selected". */
  action: string;
  /** Required when action === "select-class". */
  entity_class?: string;
  /** Required when action === "select-class". */
  sub_class?: string;
  /** Required when action === "mode" — one of "select" | "mark-symbol" | "draw-edge". */
  mode?: string;
  /** Forward-compat: extra metadata is allowed by the backend. */
  [k: string]: unknown;
}

/** Keymap: key string ("v", "Escape", …) → binding. */
export type ShortcutMap = Record<string, ShortcutBinding>;

interface ShortcutsResponse {
  shortcuts: ShortcutMap;
}

export class ShortcutsHttpError extends Error {
  status: number;
  detail?: string;
  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "include",
    redirect: "manual",
  });
  if (res.status === 0 || res.type === "opaqueredirect") {
    throw new ShortcutsHttpError(401, "Not authenticated");
  }
  let payload: unknown = null;
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("application/json")) {
    try {
      payload = await res.json();
    } catch {
      /* ignore */
    }
  }
  if (!res.ok) {
    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : `HTTP ${res.status}`;
    throw new ShortcutsHttpError(res.status, detail, detail);
  }
  return payload as T;
}

/** GET the user's effective keymap (user-set merged on top of system defaults). */
export const getShortcuts = (): Promise<ShortcutMap> =>
  call<ShortcutsResponse>("GET", "/api/v1/users/me/shortcuts").then((r) => r.shortcuts);

/** PATCH the user's keymap. Whole-object replace — caller sends full desired state.
 *  Returns the stored value (NOT merged with defaults). */
export const patchShortcuts = (map: ShortcutMap): Promise<ShortcutMap> =>
  call<ShortcutsResponse>("PATCH", "/api/v1/users/me/shortcuts", { shortcuts: map }).then(
    (r) => r.shortcuts,
  );

/** POST reset — clear stored overrides, return defaults. */
export const resetShortcuts = (): Promise<ShortcutMap> =>
  call<ShortcutsResponse>("POST", "/api/v1/users/me/shortcuts/reset").then((r) => r.shortcuts);
