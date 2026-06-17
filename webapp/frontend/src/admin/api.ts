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
  CustomerTemplateOverridePayload,
  CustomerTemplateResponse,
  DashboardKpis,
  EntityAggregates,
  EntitySearchResp,
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

// Customer templates (D5)
export const getCustomerTemplate = (slug: string) =>
  call<CustomerTemplateResponse>("GET", `/api/v1/admin/customer-templates/${encodeURIComponent(slug)}`);
export const putCustomerTemplate = (
  slug: string,
  overrides: CustomerTemplateOverridePayload[],
) =>
  call<CustomerTemplateResponse>(
    "PUT",
    `/api/v1/admin/customer-templates/${encodeURIComponent(slug)}`,
    { overrides },
  );
export const resetCustomerTemplate = (slug: string) =>
  call<CustomerTemplateResponse>(
    "DELETE",
    `/api/v1/admin/customer-templates/${encodeURIComponent(slug)}/overrides`,
  );

// Entities (FEATURES #35 — cross-job canonical_entities index)
export interface EntitySearchFilters {
  entity_class?: string;
  sub_class?: string;
  tag_contains?: string;
  job_id?: number;
  limit?: number;
  offset?: number;
}
export const getEntityAggregates = () =>
  call<EntityAggregates>("GET", "/api/v1/admin/entities/aggregates");
export const searchEntities = (f: EntitySearchFilters = {}) => {
  const qs = new URLSearchParams();
  if (f.entity_class) qs.set("entity_class", f.entity_class);
  if (f.sub_class) qs.set("sub_class", f.sub_class);
  if (f.tag_contains) qs.set("tag_contains", f.tag_contains);
  if (f.job_id !== undefined) qs.set("job_id", String(f.job_id));
  if (f.limit !== undefined) qs.set("limit", String(f.limit));
  if (f.offset !== undefined) qs.set("offset", String(f.offset));
  const q = qs.toString();
  return call<EntitySearchResp>("GET", `/api/v1/admin/entities${q ? "?" + q : ""}`);
};

// Taxonomy + label triage (Phase 4c — unified-taxonomy track)
export interface TaxonomyClass {
  order?: number;
  yolo_label: string | null;
  entity_class: string | null;
  sub_class: string | null;
  display_name: string;
  color: string;
  glyph_kind: string;
}
export interface TaxonomyResp {
  schema_version: number;
  classes: TaxonomyClass[];
  yolo_routing: Array<Record<string, unknown>>;
}
export interface LabelTriageItem {
  id: number;
  label_value: string;
  source: string | null;
  discovered_at: string | null;
  status: string;
  assigned_entity_class: string | null;
  assigned_sub_class: string | null;
  assigned_display_name: string | null;
  assigned_color: string | null;
  assigned_glyph_kind: string | null;
  decided_by_user_id: number | null;
  decided_at: string | null;
  notes: string | null;
}
export interface ClassifyTriagePayload {
  action: "approve" | "ignore" | "reject";
  entity_class?: string;
  sub_class?: string;
  display_name?: string;
  color?: string;
  glyph_kind?: string;
}

export const getTaxonomy = () =>
  call<TaxonomyResp>("GET", "/api/v1/admin/taxonomy");
export const listLabelTriage = (status = "pending") =>
  call<{ items: LabelTriageItem[]; status: string }>(
    "GET",
    `/api/v1/admin/label-triage?status=${encodeURIComponent(status)}`,
  );
export const classifyLabelTriage = (id: number, payload: ClassifyTriagePayload) =>
  call<LabelTriageItem>("POST", `/api/v1/admin/label-triage/${id}/classify`, payload);

// Self-Learning (retrain readiness + correction telemetry)
export interface LearningSummary {
  model_version: string;
  model_trained_at: string | null; // ISO Z
  generated_at: string; // ISO Z
  totals: {
    model_corrections: number;
    model_corrections_since_model: number;
    user_annotations: number;
    user_annotations_labeled: number;
    user_annotations_since_model: number;
    tag_edits: number;
    tag_edits_since_model: number;
    entity_overrides: number;
    graph_corrections: number;
    graph_corrections_since_model: number;
  };
  retrain_readiness: {
    labeled_corrections_since_model: number;
    threshold: number;
    ready: boolean;
    current_model: string;
  };
  by_action: { add?: number; delete?: number; reclassify?: number };
  by_class: Array<{
    cls: string;
    entity_class: string | null;
    sub_class: string | null;
    added: number;
    reclassified: number;
    deleted: number;
    confirmed: number;
    rejected: number;
    total_corrections: number;
  }>;
  by_job: Array<{
    job_id: number;
    pid_no: string | null;
    corrections: number;
    annotations: number;
    tag_edits: number;
  }>;
}

export const getLearningSummary = () =>
  call<LearningSummary>("GET", "/api/v1/admin/learning/summary");

export { HttpError };
