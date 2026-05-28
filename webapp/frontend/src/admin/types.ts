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
