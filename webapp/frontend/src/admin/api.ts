/**
 * Typed fetch helpers for /api/v1/admin/* endpoints.
 *
 * All calls go through the Vite proxy → FastAPI. Cookie auth is included
 * automatically because the SPA + backend share an origin in dev (and we'll
 * use same-origin in prod too).
 */
import type {
  AdminUser,
  BillingPlan,
  DashboardKpis,
  FeedbackItem,
  FeedbackStatus,
  LabelStudioResponse,
  Role,
  Tier,
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

// Users
export const listUsers = () => call<{ users: AdminUser[] }>("GET", "/api/v1/admin/users");
export const createUser = (data: {
  username: string;
  email?: string;
  password: string;
  role?: Role;
}) => call<AdminUser>("POST", "/api/v1/admin/users", data);
export const changeRole = (id: number, role: Role) =>
  call<AdminUser>("POST", `/api/v1/admin/users/${id}/role`, { role });
export const activateUser = (id: number) =>
  call<AdminUser>("POST", `/api/v1/admin/users/${id}/activate`);
export const deactivateUser = (id: number) =>
  call<AdminUser>("POST", `/api/v1/admin/users/${id}/deactivate`);
export const deleteUser = (id: number) => call<void>("DELETE", `/api/v1/admin/users/${id}`);
export const grantCredits = (id: number, amount: number) =>
  call<AdminUser>("POST", `/api/v1/admin/users/${id}/grant-credits`, { amount });
export const changeTier = (id: number, tier: Tier) =>
  call<AdminUser>("POST", `/api/v1/admin/users/${id}/change-tier`, { tier });

// Dashboard
export const getKpis = () => call<DashboardKpis>("GET", "/api/v1/admin/dashboard");

// Credits
export const listCredits = (limit = 200) =>
  call<{ transactions: Array<import("./types").CreditTxn> }>(
    "GET",
    `/api/v1/admin/credits?limit=${limit}`,
  );

// Feedback
export const listFeedback = (statusFilter: FeedbackStatus | "all" = "new") =>
  call<{ items: FeedbackItem[]; status_filter: string; open_count: number }>(
    "GET",
    `/api/v1/admin/feedback?status_filter=${statusFilter}`,
  );
export const updateFeedback = (id: number, status: FeedbackStatus, adminNotes: string) =>
  call<FeedbackItem>("POST", `/api/v1/admin/feedback/${id}/update`, {
    status,
    admin_notes: adminNotes,
  });

// Plans
export const listPlans = () => call<{ plans: BillingPlan[] }>("GET", "/api/v1/admin/plans");
export const createPlan = (data: {
  name: string;
  credits: number;
  price_usd_cents: number;
}) => call<BillingPlan>("POST", "/api/v1/admin/plans", data);
export const togglePlan = (id: number) =>
  call<BillingPlan>("POST", `/api/v1/admin/plans/${id}/toggle`);

// Label Studio
export const listLsJobs = () =>
  call<LabelStudioResponse>("GET", "/api/v1/admin/label-studio");
export const syncLabelConfigs = () =>
  call<{ updated: number[]; count: number }>(
    "POST",
    "/api/v1/admin/label-studio/sync-labels",
  );
export const syncJobToLs = (jobId: number) =>
  call<{ job_id: number; ls_project_id: number; tiles_pushed: number }>(
    "POST",
    `/api/v1/admin/label-studio/sync/${jobId}`,
  );

export { HttpError };
