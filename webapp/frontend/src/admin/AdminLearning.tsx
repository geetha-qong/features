import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, CheckCircle2, Clock } from "lucide-react";
import * as api from "./api";
import type { LearningSummary } from "./api";
import { formatDateTime, useUserTimezone } from "../util/datetime";

/**
 * Admin · Self-Learning — retrain readiness + correction telemetry.
 *
 * Reads /api/v1/admin/learning/summary (single trip). Surfaces the headline
 * "are we ready to retrain?" gate, plus where the model is weakest (per-class
 * corrections) and which jobs are generating the most signal (per-job).
 *
 * Mirrors AdminEntities' layout: header strip, stat cards, and projects-list
 * tables with deep-links into the studio.
 */
export default function AdminLearning() {
  const [data, setData] = useState<LearningSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const tz = useUserTimezone();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getLearningSummary()
      .then((r) => {
        if (!cancelled) setData(r);
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
  }, [reloadKey]);

  if (loading) {
    return (
      <main className="empty-state" style={{ padding: "48px 32px" }}>
        <Activity size={28} strokeWidth={1.6} />
        <h3>Loading…</h3>
      </main>
    );
  }

  if (error) {
    return (
      <div className="empty-state" role="alert">
        <h3>Error</h3>
        <p>{error}</p>
        <button
          className="btn btn-secondary btn-sm"
          style={{ marginTop: 12 }}
          onClick={() => setReloadKey((k) => k + 1)}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const { totals, retrain_readiness: rr, by_action, by_class, by_job } = data;
  const progress = rr.threshold > 0 ? Math.min(1, rr.labeled_corrections_since_model / rr.threshold) : 0;
  const remaining = Math.max(0, rr.threshold - rr.labeled_corrections_since_model);
  const sinceModel = `since ${data.model_version}`;

  return (
    <>
      <div className="projects-header">
        <div className="titlewrap">
          <span className="overline">Admin · Operations</span>
          <h1>Self-Learning</h1>
          <p className="sub">
            Current model <strong>{data.model_version}</strong>
            {" · trained "}
            {formatDateTime(data.model_trained_at, tz)}
            {" · generated "}
            {formatDateTime(data.generated_at, tz)}
          </p>
        </div>
      </div>

      {/* Retrain readiness — the headline */}
      <div
        className="card"
        style={{
          marginTop: 8,
          padding: 20,
          border: "1px solid var(--border, rgba(255,255,255,0.08))",
          borderRadius: 12,
          background: "var(--surface-2, rgba(255,255,255,0.02))",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <h3 style={{ margin: 0 }}>Retrain readiness</h3>
            <p className="sub" style={{ margin: "4px 0 0", fontSize: 12 }}>
              Labeled corrections collected since the current model was trained.
            </p>
          </div>
          {rr.ready ? (
            <span
              className="badge"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "6px 12px",
                borderRadius: 999,
                fontWeight: 600,
                color: "#fff",
                background: "var(--ok, #1e8e3e)",
              }}
            >
              <CheckCircle2 size={14} strokeWidth={2} /> Ready to retrain
            </span>
          ) : (
            <span
              className="badge"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "6px 12px",
                borderRadius: 999,
                fontWeight: 600,
                color: "var(--fg-2, #ccc)",
                background: "var(--surface-3, rgba(255,255,255,0.06))",
              }}
            >
              <Clock size={14} strokeWidth={2} /> Collecting… {remaining} more needed
            </span>
          )}
        </div>

        <div style={{ marginTop: 16 }}>
          <div
            style={{
              height: 12,
              borderRadius: 999,
              background: "var(--surface-3, rgba(255,255,255,0.08))",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${progress * 100}%`,
                height: "100%",
                background: rr.ready ? "var(--ok, #1e8e3e)" : "var(--qong-magenta, #d6256e)",
                transition: "width 0.3s ease",
              }}
            />
          </div>
          <div style={{ marginTop: 8, fontSize: 13, color: "var(--fg-3)" }}>
            <strong>{rr.labeled_corrections_since_model.toLocaleString()}</strong>
            {" / "}
            {rr.threshold.toLocaleString()} labeled corrections
            {" · "}
            current model <span className="mono">{rr.current_model}</span>
          </div>
        </div>
      </div>

      {/* Totals grid */}
      <div className="stat-strip" data-testid="learning-stats" style={{ marginTop: 24 }}>
        <div className="stat">
          <div className="num accent">{totals.model_corrections.toLocaleString()}</div>
          <span className="lbl">Model corrections</span>
          <span className="lbl" style={{ opacity: 0.6 }}>
            {totals.model_corrections_since_model.toLocaleString()} {sinceModel}
          </span>
        </div>
        <div className="stat">
          <div className="num">{totals.tag_edits.toLocaleString()}</div>
          <span className="lbl">Tag corrections</span>
          <span className="lbl" style={{ opacity: 0.6 }}>
            {totals.tag_edits_since_model.toLocaleString()} {sinceModel}
          </span>
        </div>
        <div className="stat">
          <div className="num">{totals.user_annotations.toLocaleString()}</div>
          <span className="lbl">User annotations</span>
          <span className="lbl" style={{ opacity: 0.6 }}>
            {totals.user_annotations_labeled.toLocaleString()} labeled · {totals.user_annotations_since_model.toLocaleString()} {sinceModel}
          </span>
        </div>
        <div className="stat">
          <div className="num">{totals.entity_overrides.toLocaleString()}</div>
          <span className="lbl">Entity overrides</span>
        </div>
        <div className="stat">
          <div className="num">{totals.graph_corrections.toLocaleString()}</div>
          <span className="lbl">Graph corrections</span>
          <span className="lbl" style={{ opacity: 0.6 }}>
            {totals.graph_corrections_since_model.toLocaleString()} {sinceModel}
          </span>
        </div>
      </div>

      {/* by_action mini-breakdown */}
      <h3 style={{ marginTop: 32, marginBottom: 12 }}>Corrections by action</h3>
      <div className="stat-strip" data-testid="learning-by-action">
        <div className="stat">
          <div className="num">{(by_action.add ?? 0).toLocaleString()}</div>
          <span className="lbl">Added</span>
        </div>
        <div className="stat">
          <div className="num">{(by_action.delete ?? 0).toLocaleString()}</div>
          <span className="lbl">Deleted</span>
        </div>
        <div className="stat">
          <div className="num">{(by_action.reclassify ?? 0).toLocaleString()}</div>
          <span className="lbl">Reclassified</span>
        </div>
      </div>

      {/* Per-class weakness table */}
      <h3 style={{ marginTop: 32, marginBottom: 4 }}>Weakest classes</h3>
      <p className="sub" style={{ marginTop: 0, marginBottom: 12, fontSize: 12 }}>
        Where the model is corrected most often — sorted by total corrections. The
        top rows are the best targets for the next retrain.
      </p>
      <div className="projects-list" data-testid="learning-by-class">
        <div
          className="list-head"
          style={{ gridTemplateColumns: "1.6fr 0.7fr 0.9fr 0.7fr 0.8fr 0.7fr 0.8fr" }}
        >
          <div>Class</div>
          <div>Added</div>
          <div>Reclassified</div>
          <div>Deleted</div>
          <div>Confirmed</div>
          <div>Rejected</div>
          <div>Total</div>
        </div>
        {by_class.map((c, i) => (
          <div
            key={c.cls}
            className="list-row"
            style={{
              gridTemplateColumns: "1.6fr 0.7fr 0.9fr 0.7fr 0.8fr 0.7fr 0.8fr",
              cursor: "default",
              background: i < 3 ? "var(--surface-2, rgba(214,37,110,0.06))" : undefined,
            }}
          >
            <div className="name mono">{c.cls}</div>
            <div className="mono">{c.added}</div>
            <div className="mono">{c.reclassified}</div>
            <div className="mono">{c.deleted}</div>
            <div className="mono">{c.confirmed}</div>
            <div className="mono">{c.rejected}</div>
            <div className="mono">
              <strong>{c.total_corrections}</strong>
            </div>
          </div>
        ))}
        {by_class.length === 0 && (
          <div className="empty-state" style={{ padding: 24 }}>
            <p>No class-level corrections recorded yet.</p>
          </div>
        )}
      </div>

      {/* Per-job table */}
      <h3 style={{ marginTop: 32, marginBottom: 12 }}>By job</h3>
      <div className="projects-list" data-testid="learning-by-job">
        <div className="list-head" style={{ gridTemplateColumns: "0.6fr 1.4fr 0.8fr 0.9fr 0.8fr 0.6fr" }}>
          <div>Job</div>
          <div>P&amp;ID</div>
          <div>Corrections</div>
          <div>Annotations</div>
          <div>Tag edits</div>
          <div>Open</div>
        </div>
        {by_job.map((j) => (
          <div
            key={j.job_id}
            className="list-row"
            style={{ gridTemplateColumns: "0.6fr 1.4fr 0.8fr 0.9fr 0.8fr 0.6fr", cursor: "default" }}
          >
            <div className="mono">{j.job_id}</div>
            <div className="mono" style={{ fontSize: 11 }}>
              {j.pid_no || <em style={{ opacity: 0.6 }}>(no P&ID)</em>}
            </div>
            <div className="mono">{j.corrections}</div>
            <div className="mono">{j.annotations}</div>
            <div className="mono">{j.tag_edits}</div>
            <div>
              <Link to={`/jobs/${j.job_id}`} className="btn btn-secondary btn-sm">
                Studio →
              </Link>
            </div>
          </div>
        ))}
        {by_job.length === 0 && (
          <div className="empty-state" style={{ padding: 24 }}>
            <p>No per-job activity recorded yet.</p>
          </div>
        )}
      </div>
    </>
  );
}
