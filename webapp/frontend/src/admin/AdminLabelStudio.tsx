import { useCallback, useEffect, useState } from "react";
import { ExternalLink, GitBranch, RefreshCw } from "lucide-react";
import * as api from "./api";
import type { LabelStudioResponse } from "./types";

export default function AdminLabelStudio() {
  const [data, setData] = useState<LabelStudioResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyJobId, setBusyJobId] = useState<number | null>(null);
  const [syncingLabels, setSyncingLabels] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await api.listLsJobs();
      setData(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function syncLabels() {
    setSyncingLabels(true);
    try {
      await api.syncLabelConfigs();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSyncingLabels(false);
    }
  }

  async function syncJob(jobId: number) {
    setBusyJobId(jobId);
    try {
      await api.syncJobToLs(jobId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyJobId(null);
    }
  }

  return (
    <>
      <div className="projects-header">
        <div className="titlewrap">
          <span className="overline">Admin · Annotation</span>
          <h1>Label Studio</h1>
          <p className="sub">Sync completed P&ID jobs into Label Studio for annotation.</p>
        </div>
        {data?.ls_configured && (
          <button
            className="btn btn-secondary btn-sm"
            disabled={syncingLabels}
            onClick={syncLabels}
            data-testid="ls-sync-labels"
          >
            <RefreshCw size={13} strokeWidth={1.6} /> Sync label configs
          </button>
        )}
      </div>

      {data && !data.ls_configured && (
        <div
          style={{
            background: "var(--warn-soft)",
            color: "var(--warn)",
            padding: 16,
            borderRadius: 8,
            marginBottom: 16,
          }}
        >
          <strong>Label Studio not configured.</strong> Set <code>LS_API_KEY</code> in
          environment to enable sync actions.
        </div>
      )}

      {data?.ls_url && (
        <div className="caption" style={{ marginBottom: 16, color: "var(--fg-3)" }}>
          External URL:{" "}
          <a href={data.ls_url} target="_blank" rel="noopener noreferrer">
            {data.ls_url}
          </a>
        </div>
      )}

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
      ) : !data || data.jobs.length === 0 ? (
        <div className="empty-state">
          <h3>No completed jobs to sync</h3>
        </div>
      ) : (
        <div className="projects-list" data-testid="ls-jobs-table">
          <div className="list-head" style={{ gridTemplateColumns: "0.6fr 2fr 1fr 0.8fr 1.2fr 1fr" }}>
            <div>Job</div>
            <div>PDF</div>
            <div>P&ID</div>
            <div>Valves</div>
            <div>LS project</div>
            <div></div>
          </div>
          {data.jobs.map((j) => (
            <div
              key={j.id}
              className="list-row"
              style={{ gridTemplateColumns: "0.6fr 2fr 1fr 0.8fr 1.2fr 1fr", cursor: "default" }}
              data-testid={`ls-job-row-${j.id}`}
            >
              <div className="mono">#{j.id}</div>
              <div>
                <div className="name">{j.original_filename}</div>
                <div className="sub">
                  {j.created_at ? new Date(j.created_at).toLocaleDateString() : ""}
                </div>
              </div>
              <div className="mono">{j.pid_no}</div>
              <div className="mono">{j.valve_count}</div>
              <div>
                {j.ls_project_id ? (
                  <a
                    href={`${data.ls_url}/projects/${j.ls_project_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: "var(--qong-magenta)" }}
                  >
                    <GitBranch size={12} strokeWidth={1.6} /> project {j.ls_project_id}
                    <ExternalLink size={11} strokeWidth={1.6} style={{ marginLeft: 4 }} />
                  </a>
                ) : (
                  <span className="caption">—</span>
                )}
              </div>
              <div>
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={busyJobId === j.id || !data.ls_configured}
                  onClick={() => syncJob(j.id)}
                  data-testid={`ls-sync-job-${j.id}`}
                >
                  {busyJobId === j.id ? "Syncing…" : j.ls_synced ? "Re-sync tiles" : "Sync tiles"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
