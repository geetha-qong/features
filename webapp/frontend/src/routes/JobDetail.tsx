import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import Studio from "../studio/Studio";

/**
 * /jobs/:jobId route — wraps the new Studio component with a real Job fetch.
 *
 * Production-continuity rule: this route replaces the prior JobDetail
 * placeholder. The FastAPI Jinja-rendered /jobs/{id} HTML route in
 * webapp/routers/jobs.py:111 is untouched and continues to serve any
 * direct-URL access outside the SPA (legacy customers, email links, etc).
 *
 * Phase 2b will move the deliverable export links into the Studio top bar's
 * "More menu → Export". For now, they remain reachable at
 * /api/v1/jobs/{id}/export/{type}/{format}.
 */
interface JobResponse {
  job_id: number;
  status: string;
  pid_no: string;
  original_filename: string;
  valve_count: number;
}

export default function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [job, setJob] = useState<JobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!jobId) return;
    fetch(`/api/v1/jobs/${jobId}`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: JobResponse) => {
        if (cancelled) return;
        setJob(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  if (error) {
    return (
      <main style={{ padding: "48px 32px", maxWidth: 720, margin: "0 auto" }}>
        <h1 className="qs-display" style={{ fontSize: 32 }}>
          Couldn't load job
        </h1>
        <p style={{ color: "var(--fg-2)", marginTop: 12 }}>{error}</p>
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => navigate("/dashboard")}
          style={{ marginTop: 24 }}
        >
          Back to Dashboard
        </button>
      </main>
    );
  }

  if (!job) {
    return (
      <main style={{ padding: "48px 32px", textAlign: "center", color: "var(--fg-3)" }}>
        Loading…
      </main>
    );
  }

  return (
    <Studio
      project={{
        id: job.job_id,
        name: (job.original_filename || `Job ${job.job_id}`).replace(/\.pdf$/i, ""),
        pidCount: 1,
      }}
      userName={user?.username || "guest"}
      onBack={() => navigate("/dashboard")}
    />
  );
}
