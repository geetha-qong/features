export type Role = "user" | "annotator" | "super_admin";
export type Tier = "trial" | "starter" | "pro" | "enterprise";
export type FeedbackStatus = "new" | "in_progress" | "resolved" | "wontfix";

export interface AdminUser {
  id: number;
  username: string;
  email: string | null;
  role: Role;
  is_active: boolean;
  credits_remaining: number;
  tier: Tier;
  organization: string | null;
  created_at: string | null;
}

export interface CreditTxn {
  id: number;
  user_id: number;
  username: string | null;
  delta: number;
  balance_after: number;
  reason: string;
  job_id: number | null;
  created_at: string | null;
}

export interface FeedbackItem {
  id: number;
  user_id: number | null;
  username: string | null;
  category: string;
  subject: string;
  message: string;
  page_url: string | null;
  status: FeedbackStatus;
  admin_notes: string | null;
  created_at: string | null;
}

export interface BillingPlan {
  id: number;
  name: string;
  credits: number;
  price_usd_cents: number;
  is_active: boolean;
  stripe_price_id: string | null;
  created_at: string | null;
}

export interface DashboardKpis {
  total_users: number;
  active_users: number;
  pending_users: number;
  total_jobs: number;
  done_jobs: number;
  open_feedback: number;
  mtd_consumed: number;
  mtd_granted: number;
  recent_txns: CreditTxn[];
}

export interface LsJob {
  id: number;
  pid_no: string;
  original_filename: string;
  status: string;
  ls_project_id: number | null;
  ls_synced: boolean;
  valve_count: number;
  created_at: string | null;
  ls_stats: Record<string, number | string>;
}

export interface LabelStudioResponse {
  jobs: LsJob[];
  ls_url: string;
  ls_configured: boolean;
}

// Customer template overrides (D5 — admin-editable column labels)

export type DeliverableType = "valve_list" | "instrument_index" | "datasheet" | "equipment_list" | "io_list";

export interface CustomerTemplateColumn {
  key: string;                  // the JSON template's `field` value, e.g. "fields.size"
  label: string;                // current label (override if set, else JSON header)
  hidden: boolean;
  order_in_template: number | null;
  is_overridden: boolean;
}

export interface CustomerTemplateResponse {
  slug: string;
  customer_name: string | null;
  available_slugs: string[];
  deliverables: Record<DeliverableType, CustomerTemplateColumn[]>;
  last_updated_at: string | null;
}

export interface CustomerTemplateOverridePayload {
  deliverable_type: DeliverableType;
  column_key: string;
  label_override: string | null;
  column_order: number | null;
  hidden: boolean;
}

// Cross-job entity index (FEATURES #34/#35).
export interface CanonicalEntityRowResp {
  job_id: number;
  entity_id: string;
  entity_class: string;            // 'valve' | 'instrument' | 'equipment'
  sub_class: string | null;
  tag: string | null;
  pid_number: string;
  sheet_number: number;
  fields: Record<string, unknown>;
  updated_at: string | null;       // ISO8601 UTC
}

export interface EntitySearchResp {
  total: number;
  returned: number;
  offset: number;
  limit: number;
  rows: CanonicalEntityRowResp[];
}

export interface EntityAggregates {
  total_rows: number;
  by_class: Record<string, number>;
  top_valve_sub_classes: Array<{ sub_class: string; count: number }>;
  top_jobs_by_valve_count: Array<{ job_id: number; count: number }>;
  // Tags appearing in ≥2 distinct jobs — audit signal for re-extractions
  // (same drawing, two runs) or legitimate same-tag-on-two-drawings cases.
  // Optional because older deploys don't include it (FEATURES #37+).
  duplicate_tags_across_jobs?: Array<{ tag: string; job_count: number; row_count: number }>;
}
