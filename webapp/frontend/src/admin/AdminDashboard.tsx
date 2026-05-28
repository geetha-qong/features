import { useEffect, useState } from "react";
import * as api from "./api";
import type { DashboardKpis } from "./types";

export default function AdminDashboard() {
  const [data, setData] = useState<DashboardKpis | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getKpis()
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="empty-state" role="alert">
        <h3>Error</h3>
        <p>{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="empty-state">
        <h3>Loading…</h3>
      </div>
    );
  }

  return (
    <>
      <div className="projects-header">
        <div className="titlewrap">
          <span className="overline">Admin · Operations</span>
          <h1>Dashboard</h1>
          <p className="sub">Operational KPIs across all tenants.</p>
        </div>
      </div>

      <div className="stat-strip" data-testid="admin-dashboard-stats">
        <div className="stat">
          <div className="num accent">{data.total_users}</div>
          <span className="lbl">Total users</span>
        </div>
        <div className="stat">
          <div className="num">{data.active_users}</div>
          <span className="lbl">Active</span>
        </div>
        <div className="stat">
          <div className="num">{data.pending_users}</div>
          <span className="lbl">Pending / inactive</span>
        </div>
        <div className="stat">
          <div className="num">{data.total_jobs}</div>
          <span className="lbl">Total jobs</span>
        </div>
        <div className="stat">
          <div className="num">{data.done_jobs}</div>
          <span className="lbl">Jobs done</span>
        </div>
        <div className="stat">
          <div className="num">{data.open_feedback}</div>
          <span className="lbl">Open feedback</span>
        </div>
        <div className="stat">
          <div className="num">{data.mtd_granted}</div>
          <span className="lbl">Credits granted</span>
        </div>
        <div className="stat">
          <div className="num">{data.mtd_consumed}</div>
          <span className="lbl">Credits consumed</span>
        </div>
      </div>

      <h3 style={{ marginTop: 32, marginBottom: 12 }}>Recent transactions</h3>
      {data.recent_txns.length === 0 ? (
        <div className="empty-state">
          <p>No transactions yet.</p>
        </div>
      ) : (
        <div className="projects-list" data-testid="admin-dashboard-txns">
          <div className="list-head" style={{ gridTemplateColumns: "1.2fr 1fr 0.8fr 1.2fr 1fr" }}>
            <div>User</div>
            <div>Reason</div>
            <div>Delta</div>
            <div>Balance after</div>
            <div>When</div>
          </div>
          {data.recent_txns.map((t) => (
            <div
              key={t.id}
              className="list-row"
              style={{ gridTemplateColumns: "1.2fr 1fr 0.8fr 1.2fr 1fr", cursor: "default" }}
            >
              <div className="name">{t.username || `user#${t.user_id}`}</div>
              <div className="cell-client">{t.reason}</div>
              <div className="mono" style={{ color: t.delta > 0 ? "var(--ok)" : "var(--error)" }}>
                {t.delta > 0 ? "+" : ""}
                {t.delta}
              </div>
              <div className="mono">{t.balance_after}</div>
              <div className="cell-date">{t.created_at ? new Date(t.created_at).toLocaleString() : ""}</div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
