import { useCallback, useEffect, useState } from "react";
import * as api from "./api";
import type { FeedbackItem, FeedbackStatus } from "./types";

const STATUSES: Array<FeedbackStatus | "all"> = ["all", "new", "in_progress", "resolved", "wontfix"];

const STATUS_BADGE: Record<FeedbackStatus, string> = {
  new: "fail",
  in_progress: "run",
  resolved: "ok",
  wontfix: "draft",
};

export default function AdminFeedback() {
  const [filter, setFilter] = useState<FeedbackStatus | "all">("new");
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [openCount, setOpenCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [editingNotes, setEditingNotes] = useState<Record<number, string>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listFeedback(filter);
      setItems(data.items);
      setOpenCount(data.open_count);
      setEditingNotes(
        Object.fromEntries(data.items.map((i) => [i.id, i.admin_notes || ""])),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function update(item: FeedbackItem, status: FeedbackStatus) {
    setBusyId(item.id);
    try {
      await api.updateFeedback(item.id, status, editingNotes[item.id] ?? "");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <div className="projects-header">
        <div className="titlewrap">
          <span className="overline">Admin · Inbox</span>
          <h1>
            Feedback{openCount > 0 ? <span style={{ marginLeft: 12, color: "var(--qong-magenta)", fontSize: 24 }}>{openCount} new</span> : null}
          </h1>
          <p className="sub">Triage user-submitted feedback. URLs sanitised at submission per the security fix.</p>
        </div>
      </div>

      <div className="toolbar">
        <div className="filters" data-testid="feedback-filters">
          {STATUSES.map((s) => (
            <button
              key={s}
              className={`chip ${filter === s ? "active" : ""}`}
              onClick={() => setFilter(s)}
              data-testid={`feedback-filter-${s}`}
            >
              {s.replace("_", " ")}
            </button>
          ))}
        </div>
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
      ) : items.length === 0 ? (
        <div className="empty-state">
          <h3>No feedback{filter !== "all" ? ` with status "${filter}"` : ""}.</h3>
        </div>
      ) : (
        <div data-testid="feedback-items">
          {items.map((f) => (
            <div
              key={f.id}
              className="prop-card"
              style={{ marginBottom: 12 }}
              data-testid={`feedback-item-${f.id}`}
            >
              <div className="prop-head">
                <span className="prop-tag">{f.category}</span>
                <span className={`status-pill ${STATUS_BADGE[f.status]}`} style={{ position: "static" }}>
                  <span className="dot"></span>
                  {f.status.replace("_", " ")}
                </span>
              </div>
              <h3 style={{ marginTop: 8 }}>{f.subject}</h3>
              <div className="caption" style={{ color: "var(--fg-3)" }}>
                {f.username || "Anonymous"} · {f.created_at ? new Date(f.created_at).toLocaleString() : ""}
                {f.page_url &&
                  (f.page_url.startsWith("http://") || f.page_url.startsWith("https://")) && (
                    <>
                      {" · "}
                      <a
                        href={f.page_url}
                        target="_blank"
                        rel="noopener noreferrer nofollow"
                        style={{ color: "var(--fg-3)" }}
                      >
                        {f.page_url}
                      </a>
                    </>
                  )}
              </div>
              <p style={{ marginTop: 12 }}>{f.message}</p>
              <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "flex-end" }}>
                <div className="field" style={{ flex: 1 }}>
                  <label className="field-label">Admin notes</label>
                  <input
                    className="input"
                    style={{ height: 36 }}
                    value={editingNotes[f.id] ?? ""}
                    onChange={(e) =>
                      setEditingNotes({ ...editingNotes, [f.id]: e.target.value })
                    }
                  />
                </div>
                <select
                  className="input"
                  style={{ height: 36, maxWidth: 180 }}
                  value={f.status}
                  onChange={(e) => update(f, e.target.value as FeedbackStatus)}
                  disabled={busyId === f.id}
                  data-testid={`feedback-status-${f.id}`}
                >
                  <option value="new">new</option>
                  <option value="in_progress">in_progress</option>
                  <option value="resolved">resolved</option>
                  <option value="wontfix">wontfix</option>
                </select>
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={busyId === f.id}
                  onClick={() => update(f, f.status)}
                >
                  Save notes
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
