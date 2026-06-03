import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Key, Receipt, CreditCard, ArrowRight } from "lucide-react";
import { detectBrowserTimezone, useAuth } from "../auth/AuthContext";
import {
  getAccount,
  getBilling,
  listTransactions,
  setTimezone,
} from "../account/api";
import type {
  AccountInfo,
  BillingResponse,
  Transaction,
} from "../account/types";

/** Curated short list — enough for ~95% of our user base. Users can also
 *  click "Use browser detection" to clear and fall back to Intl auto-detect. */
const TZ_OPTIONS: { value: string; label: string }[] = [
  { value: "Asia/Kolkata", label: "India — IST (Asia/Kolkata)" },
  { value: "Asia/Dubai", label: "Gulf — GST (Asia/Dubai)" },
  { value: "Europe/Istanbul", label: "Türkiye — TRT (Europe/Istanbul)" },
  { value: "Europe/London", label: "UK — GMT/BST (Europe/London)" },
  { value: "Europe/Berlin", label: "Central Europe — CET/CEST (Europe/Berlin)" },
  { value: "America/New_York", label: "US East — ET (America/New_York)" },
  { value: "America/Los_Angeles", label: "US West — PT (America/Los_Angeles)" },
  { value: "Asia/Singapore", label: "Singapore — SGT (Asia/Singapore)" },
  { value: "Asia/Tokyo", label: "Japan — JST (Asia/Tokyo)" },
  { value: "Australia/Sydney", label: "Sydney — AEST/AEDT (Australia/Sydney)" },
  { value: "UTC", label: "UTC (no offset)" },
];

function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function Account() {
  const { user, refresh: refreshAuth } = useAuth();
  const [info, setInfo] = useState<AccountInfo | null>(null);
  const [txns, setTxns] = useState<Transaction[]>([]);
  const [billing, setBilling] = useState<BillingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tzSaving, setTzSaving] = useState(false);
  const [tzError, setTzError] = useState<string | null>(null);
  const browserTz = detectBrowserTimezone();

  async function handleTimezoneChange(value: string) {
    // "" sentinel = clear (revert to browser auto-detect)
    const next = value === "" ? null : value;
    setTzSaving(true);
    setTzError(null);
    try {
      await setTimezone(next);
      setInfo((cur) => (cur ? { ...cur, timezone: next } : cur));
      // Push the new value into AuthContext so anywhere else in the SPA
      // that reads user.timezone updates immediately.
      void refreshAuth();
    } catch (e) {
      setTzError((e as Error).message);
    } finally {
      setTzSaving(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([getAccount(), listTransactions(10), getBilling()])
      .then(([acc, txnRes, bill]) => {
        if (cancelled) return;
        setInfo(acc);
        setTxns(txnRes.transactions);
        setBilling(bill);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return <div style={{ padding: 32 }}>Loading account…</div>;
  }
  if (error) {
    return <div style={{ padding: 32, color: "crimson" }}>Failed to load account: {error}</div>;
  }

  return (
    <div style={{ padding: 32, maxWidth: 1100, margin: "0 auto" }}>
      <h1 style={{ marginBottom: 24 }}>Account</h1>

      <section style={{ marginBottom: 32 }}>
        <h2 style={{ fontSize: 18, marginBottom: 12 }}>Profile</h2>
        <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", rowGap: 8, alignItems: "center" }}>
          <div style={{ color: "#666" }}>Username</div><div>{info?.username ?? user?.username}</div>
          <div style={{ color: "#666" }}>Email</div><div>{info?.email ?? "—"}</div>
          <div style={{ color: "#666" }}>Role</div><div>{info?.role}</div>
          <div style={{ color: "#666" }}>Tier</div><div>{info?.tier}</div>
          <div style={{ color: "#666" }}>Credits remaining</div>
          <div style={{ fontWeight: 600 }}>{info?.credits_remaining ?? 0}</div>
          <div style={{ color: "#666" }}>Time zone</div>
          <div>
            <select
              value={info?.timezone ?? ""}
              onChange={(e) => void handleTimezoneChange(e.target.value)}
              disabled={tzSaving}
              style={{ padding: "6px 10px", minWidth: 320 }}
            >
              <option value="">Auto-detect from browser ({browserTz})</option>
              {TZ_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            {tzSaving && <span style={{ marginLeft: 12, color: "#666" }}>Saving…</span>}
            {tzError && <span style={{ marginLeft: 12, color: "crimson" }}>{tzError}</span>}
            <div style={{ color: "#888", fontSize: 12, marginTop: 4 }}>
              All timestamps in Studio, Dashboard, and Admin display in this zone.
            </div>
          </div>
        </div>
      </section>

      <section style={{ marginBottom: 32 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h2 style={{ fontSize: 18, margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
            <Key size={18} /> API Keys
          </h2>
          <Link to="/account/api-keys" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            Manage keys <ArrowRight size={14} />
          </Link>
        </div>
        <p style={{ color: "#666", margin: 0 }}>
          Programmatic access via <code>Authorization: Bearer qk_…</code>.
        </p>
      </section>

      <section style={{ marginBottom: 32 }}>
        <h2 style={{ fontSize: 18, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
          <Receipt size={18} /> Recent Transactions
        </h2>
        {txns.length === 0 ? (
          <p style={{ color: "#666" }}>No transactions yet.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>
                <th style={{ padding: 8 }}>When</th>
                <th style={{ padding: 8 }}>Reason</th>
                <th style={{ padding: 8, textAlign: "right" }}>Delta</th>
                <th style={{ padding: 8, textAlign: "right" }}>Balance</th>
                <th style={{ padding: 8 }}>Job</th>
              </tr>
            </thead>
            <tbody>
              {txns.map((t) => (
                <tr key={t.id} style={{ borderBottom: "1px solid #f0f0f0" }}>
                  <td style={{ padding: 8 }}>{formatDate(t.created_at)}</td>
                  <td style={{ padding: 8 }}>{t.reason}</td>
                  <td style={{ padding: 8, textAlign: "right", color: t.delta < 0 ? "crimson" : "green" }}>
                    {t.delta > 0 ? "+" : ""}{t.delta}
                  </td>
                  <td style={{ padding: 8, textAlign: "right" }}>{t.balance_after}</td>
                  <td style={{ padding: 8 }}>
                    {t.job_id ? <Link to={`/jobs/${t.job_id}`}>#{t.job_id}</Link> : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2 style={{ fontSize: 18, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
          <CreditCard size={18} /> Billing
        </h2>
        <p style={{ color: "#666", marginTop: 0 }}>
          Current balance: <strong>{billing?.balance ?? 0}</strong> credits ({billing?.tier} tier).
        </p>
        {billing && billing.plans.length > 0 ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 }}>
            {billing.plans.map((p) => (
              <div key={p.id} style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16 }}>
                <h3 style={{ marginTop: 0 }}>{p.name}</h3>
                <p style={{ fontSize: 22, fontWeight: 600, margin: "8px 0" }}>{formatCents(p.price_usd_cents)}</p>
                <p style={{ color: "#666", margin: 0 }}>{p.credits} credits</p>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ color: "#666" }}>No plans available — contact sales for enterprise pricing.</p>
        )}
      </section>
    </div>
  );
}
