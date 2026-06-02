export interface AccountInfo {
  id: number;
  username: string;
  email: string | null;
  credits_remaining: number;
  tier: string;
  role: string;
}

export interface Transaction {
  id: number;
  delta: number;
  balance_after: number;
  reason: string;
  job_id: number | null;
  created_at: string | null;
}

export interface ApiKey {
  id: number;
  name: string;
  key_prefix: string;
  created_at: string | null;
  last_used_at: string | null;
}

export interface CreatedApiKey extends ApiKey {
  key: string; // one-time plaintext reveal
}

export interface BillingPlan {
  id: number;
  name: string;
  credits: number;
  price_usd_cents: number;
  stripe_price_id: string | null;
}

export interface BillingResponse {
  balance: number;
  tier: string;
  plans: BillingPlan[];
}

export type FeedbackCategory = "bug" | "feature" | "pricing" | "other";

export interface FeedbackSubmission {
  category: FeedbackCategory;
  subject: string;
  message: string;
  page_url?: string | null;
}
