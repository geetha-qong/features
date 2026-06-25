/**
 * Admin · Training Feedback Metrics — FEATURES #38 P6.
 *
 * Hits GET /api/v1/admin/annotations/metrics and renders:
 *   - Top-line stats (total model detections vs user annotations vs ratio).
 *   - Stacked bar of by_status counts (status token colors).
 *   - Last-30-days line chart (inline SVG — recharts isn't installed).
 *
 * Mount: NOT wired into App.tsx; the main session does the integration pass.
 */
import { useEffect, useState } from "react";
import { Activity, AlertTriangle, BarChart3, CheckCircle2, UserPlus } from "lucide-react";

export interface AnnotationMetrics {
  total_model_detections: number;
  total_user_annotations: number;
  by_status: {
    user_added: number;
    user_confirmed: number;
    user_rejected: number;
    model_found: number;
    [k: string]: number;
  };
  per_day_last_30: Array<{ date: string; model: number; user: number }>;
}

const STATUS_COLOR: Record<string, string> = {
  model_found: "var(--info)",
  user_added: "var(--qong-pink)",
  user_confirmed: "var(--ok)",
  user_rejected: "var(--error)",
};

const STATUS_LABEL: Record<string, string> = {
  model_found: "Model found",
  user_added: "User added",
  user_confirmed: "User confirmed",
  user_rejected: "User rejected",
};

async function fetchMetrics(): Promise<AnnotationMetrics> {
  const res = await fetch("/api/v1/admin/annotations/metrics", {
    credentials: "include",
    redirect: "manual",
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return (await res.json()) as AnnotationMetrics;
}

export default function AdminAnnotationMetrics() {
  const [data, setData] = useState<AnnotationMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchMetrics()
      .then((m) => { if (!cancelled) setData(m); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return <div style={{ padding: "var(--s-6)" }} data-testid="metrics-loading">Loading metrics…</div>;
  }
  if (error || !data) {
    return (
      <div style={{ padding: "var(--s-6)", color: "var(--error)" }} data-testid="metrics-error">
        <AlertTriangle size={14} strokeWidth={1.6} /> {error ?? "No data"}
      </div>
    );
  }

  const ratio =
    data.total_model_detections > 0
      ? (data.total_user_annotations / data.total_model_detections).toFixed(2)
      : "—";

  // Stacked bar — normalize segment widths to total
  const statusKeys = ["model_found", "user_added", "user_confirmed", "user_rejected"];
  const totalForBar = statusKeys.reduce(
    (acc, k) => acc + (data.by_status[k] || 0),
    0,
  );

  return (
    <div style={{ padding: "var(--s-6)" }} data-testid="metrics-root">
      <div style={{ marginBottom: "var(--s-6)" }}>
        <span className="overline">Admin · Training</span>
        <h1 style={{ margin: 0, display: "flex", alignItems: "center", gap: 10 }}>
          <BarChart3 size={22} strokeWidth={1.6} />
          Annotation Metrics
        </h1>
        <p className="sub">Model-vs-user volume and last-30-day breakdown.</p>
      </div>

      {/* Top stats */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: "var(--s-4)",
          marginBottom: "var(--s-6)",
        }}
        data-testid="metrics-topstats"
      >
        <StatCard
          icon={<Activity size={18} strokeWidth={1.6} />}
          label="Model detections"
          value={data.total_model_detections}
          tint="var(--info)"
          testId="stat-model"
        />
        <StatCard
          icon={<UserPlus size={18} strokeWidth={1.6} />}
          label="User annotations"
          value={data.total_user_annotations}
          tint="var(--qong-pink)"
          testId="stat-user"
        />
        <StatCard
          icon={<CheckCircle2 size={18} strokeWidth={1.6} />}
          label="User / model ratio"
          value={ratio}
          tint="var(--qong-purple)"
          testId="stat-ratio"
        />
      </div>

      {/* Stacked bar */}
      <section style={{ marginBottom: "var(--s-6)" }} data-testid="metrics-status-bar">
        <h3 style={{ margin: "0 0 var(--s-3)", fontSize: 14 }}>By status</h3>
        {totalForBar === 0 ? (
          <div style={{ color: "var(--ink-500)", fontSize: 12 }} data-testid="status-bar-empty">
            No annotations yet.
          </div>
        ) : (
          <div
            style={{
              display: "flex",
              width: "100%",
              height: 22,
              borderRadius: "var(--r-2)",
              overflow: "hidden",
              border: "1px solid var(--ink-200)",
            }}
          >
            {statusKeys.map((k) => {
              const n = data.by_status[k] || 0;
              const pct = totalForBar > 0 ? (n / totalForBar) * 100 : 0;
              if (pct === 0) return null;
              return (
                <div
                  key={k}
                  title={`${STATUS_LABEL[k]}: ${n}`}
                  style={{
                    width: `${pct}%`,
                    background: STATUS_COLOR[k],
                  }}
                  data-testid={`status-seg-${k}`}
                />
              );
            })}
          </div>
        )}
        <div
          style={{
            display: "flex",
            gap: "var(--s-4)",
            marginTop: "var(--s-2)",
            flexWrap: "wrap",
            fontSize: 12,
            color: "var(--ink-700)",
          }}
        >
          {statusKeys.map((k) => (
            <span key={k} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <span
                style={{
                  display: "inline-block",
                  width: 10,
                  height: 10,
                  borderRadius: "var(--r-2)",
                  background: STATUS_COLOR[k],
                }}
              />
              {STATUS_LABEL[k]} <strong data-testid={`status-count-${k}`}>{data.by_status[k] || 0}</strong>
            </span>
          ))}
        </div>
      </section>

      {/* Per-day chart */}
      <section data-testid="metrics-perday">
        <h3 style={{ margin: "0 0 var(--s-3)", fontSize: 14 }}>Last 30 days</h3>
        <PerDayChart series={data.per_day_last_30} />
      </section>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  tint,
  testId,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  tint: string;
  testId?: string;
}) {
  return (
    <div
      data-testid={testId}
      style={{
        border: "1px solid var(--ink-200)",
        borderRadius: "var(--r-3)",
        padding: "var(--s-4)",
        background: "var(--ink-0)",
        boxShadow: "var(--shadow-sm)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: tint }}>
        {icon}
        <span style={{ fontSize: 12, color: "var(--ink-700)" }}>{label}</span>
      </div>
      <div style={{ fontSize: 28, fontWeight: 600, marginTop: 6, color: tint }}>{value}</div>
    </div>
  );
}

function PerDayChart({
  series,
}: {
  series: Array<{ date: string; model: number; user: number }>;
}) {
  const W = 640;
  const H = 180;
  const PAD = 32;
  const innerW = W - PAD * 2;
  const innerH = H - PAD * 2;

  const max = Math.max(
    1,
    ...series.map((d) => Math.max(d.model, d.user)),
  );
  const xStep = series.length > 1 ? innerW / (series.length - 1) : innerW;

  const path = (key: "model" | "user") =>
    series
      .map((d, i) => {
        const x = PAD + i * xStep;
        const y = PAD + innerH - (d[key] / max) * innerH;
        return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(" ");

  return (
    <div data-testid="perday-chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        style={{ background: "var(--ink-50)", borderRadius: "var(--r-3)" }}
        role="img"
        aria-label="Annotations per day, last 30 days"
      >
        {/* Axis baseline */}
        <line
          x1={PAD}
          y1={PAD + innerH}
          x2={PAD + innerW}
          y2={PAD + innerH}
          stroke="var(--ink-300)"
          strokeWidth={1}
        />
        {/* Model line */}
        <path
          d={path("model")}
          stroke="var(--info)"
          strokeWidth={1.8}
          fill="none"
          data-testid="perday-line-model"
        />
        {/* User line */}
        <path
          d={path("user")}
          stroke="var(--qong-pink)"
          strokeWidth={1.8}
          fill="none"
          data-testid="perday-line-user"
        />
        {/* Endpoint labels */}
        <text
          x={PAD}
          y={PAD - 6}
          fontSize="10"
          fill="var(--ink-700)"
        >
          max {max}
        </text>
      </svg>
      <div
        style={{
          display: "flex",
          gap: "var(--s-4)",
          marginTop: "var(--s-2)",
          fontSize: 12,
          color: "var(--ink-700)",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 14,
              height: 2,
              background: "var(--info)",
              display: "inline-block",
            }}
          />
          Model detections
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 14,
              height: 2,
              background: "var(--qong-pink)",
              display: "inline-block",
            }}
          />
          User annotations
        </span>
      </div>
    </div>
  );
}
