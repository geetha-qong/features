import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import * as api from "./api";
import type { CreditTxn } from "./types";
import { formatDateTime, useUserTimezone } from "../util/datetime";

type SignFilter = "all" | "granted" | "consumed";

export default function AdminCredits() {
  const tz = useUserTimezone();
  const [txns, setTxns] = useState<CreditTxn[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [signFilter, setSignFilter] = useState<SignFilter>("all");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .listCredits(200)
      .then((d) => {
        if (!cancelled) setTxns(d.transactions);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    let list = txns;
    if (signFilter === "granted") list = list.filter((t) => t.delta > 0);
    else if (signFilter === "consumed") list = list.filter((t) => t.delta < 0);
    if (query) {
      const q = query.toLowerCase();
      list = list.filter(
        (t) =>
          (t.username || "").toLowerCase().includes(q) || t.reason.toLowerCase().includes(q),
      );
    }
    return list;
  }, [txns, signFilter, query]);

  return (
    <>
      <div className="projects-header">
        <div className="titlewrap">
          <span className="overline">Admin · Ledger</span>
          <h1>Credit transactions</h1>
          <p className="sub">Last 200 credit changes across all users.</p>
        </div>
      </div>

      <div className="toolbar">
        <div className="input-with-icon search">
          <span className="ic" style={{ color: "var(--fg-3)" }}>
            <Search size={16} strokeWidth={1.6} />
          </span>
          <input
            className="input"
            placeholder="Search by username or reason…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ height: 40 }}
          />
        </div>
        <div className="filters">
          {(["all", "granted", "consumed"] as SignFilter[]).map((f) => (
            <button
              key={f}
              className={`chip ${signFilter === f ? "active" : ""}`}
              onClick={() => setSignFilter(f)}
            >
              {f}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <span className="props-sub">
          {filtered.length} of {txns.length}
        </span>
      </div>

      {error && (
        <div
          style={{ background: "var(--error-soft)", color: "var(--error)", padding: 12, borderRadius: 8, marginBottom: 16 }}
          role="alert"
        >
          {error}
        </div>
      )}

      {loading ? (
        <div className="empty-state">
          <h3>Loading…</h3>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <h3>No transactions{txns.length > 0 ? " match" : " yet"}</h3>
        </div>
      ) : (
        <div className="projects-list" data-testid="credits-table">
          <div className="list-head" style={{ gridTemplateColumns: "1.2fr 1fr 0.8fr 1fr 1fr 0.8fr" }}>
            <div>User</div>
            <div>Reason</div>
            <div>Delta</div>
            <div>Balance after</div>
            <div>When</div>
            <div>Job</div>
          </div>
          {filtered.map((t) => (
            <div
              key={t.id}
              className="list-row"
              style={{ gridTemplateColumns: "1.2fr 1fr 0.8fr 1fr 1fr 0.8fr", cursor: "default" }}
            >
              <div className="name">{t.username || `user#${t.user_id}`}</div>
              <div className="cell-client">{t.reason}</div>
              <div className="mono" style={{ color: t.delta > 0 ? "var(--ok)" : "var(--error)" }}>
                {t.delta > 0 ? "+" : ""}
                {t.delta}
              </div>
              <div className="mono">{t.balance_after}</div>
              <div className="cell-date">{t.created_at ? formatDateTime(t.created_at, tz) : ""}</div>
              <div className="mono">{t.job_id ?? "—"}</div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
