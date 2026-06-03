/**
 * Typed fetch helpers for /api/v1/account/* and /api/v1/feedback.
 * Mirrors the admin/api.ts pattern (same call<T>() shape).
 */
import type {
  AccountInfo,
  ApiKey,
  BillingResponse,
  CreatedApiKey,
  FeedbackSubmission,
  Transaction,
} from "./types";

class HttpError extends Error {
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
    throw new HttpError(401, "Not authenticated");
  }
  if (res.status === 204) {
    return undefined as T;
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
    throw new HttpError(res.status, detail, detail);
  }
  return payload as T;
}

export const getAccount = () => call<AccountInfo>("GET", "/api/v1/account");

/**
 * Set or clear the user's preferred display timezone.
 * Pass `null` to clear (frontend then auto-detects via Intl.DateTimeFormat).
 */
export const setTimezone = (tz: string | null) =>
  call<{ timezone: string | null }>("PATCH", "/api/v1/account/timezone", { timezone: tz });

export const listTransactions = (limit = 20) =>
  call<{ transactions: Transaction[] }>("GET", `/api/v1/account/transactions?limit=${limit}`);

export const listApiKeys = () =>
  call<{ keys: ApiKey[] }>("GET", "/api/v1/account/api-keys");

export const createApiKey = (name: string) =>
  call<CreatedApiKey>("POST", "/api/v1/account/api-keys", { name });

export const revokeApiKey = (id: number) =>
  call<void>("DELETE", `/api/v1/account/api-keys/${id}`);

export const getBilling = () =>
  call<BillingResponse>("GET", "/api/v1/account/billing");

export const submitFeedback = (data: FeedbackSubmission) =>
  call<{ id: number; category: string; subject: string; created_at: string | null }>(
    "POST",
    "/api/v1/feedback",
    data,
  );
