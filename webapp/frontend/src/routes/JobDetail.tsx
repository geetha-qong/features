import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Activity, ArrowLeft } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import Studio from "../studio/Studio";

/**
 * /jobs/:jobId route — wraps the new Studio component with a real Job fetch.
 *
 * FEATURES #41: backstop the route so a job that hasn't finished extracting
 * renders a "Still processing" panel instead of dropping the user into the
 * Studio with prototype fallback data. The Dashboard already gates the
 * normal click path; this guard covers the direct-URL / bookmark / refresh
 * cases. While processing, we poll every 3s and seamlessly upgrade to the
 * Studio the moment the backend flips to `done`.
 *
 * The FastAPI Jinja-rendered /jobs/{id} HTML route in webapp/routers/jobs.py
 * is untouched and continues to serve any direct-URL access outside the SPA
 * (legacy customers, email links, etc).
 */
interface JobResponse {
  job_id: number;
  status: string;
  pid_no: string;
  original_filename: string;
  valve_count: number;
}

const TERMINAL_STATUSES = new Set(["done", "failed"]);

export default function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [job, setJob] = useState<JobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!jobId) return;

    function fetchOnce() {
      return fetch(`/api/v1/jobs/${jobId}`, { credentials: "include" })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((data: JobResponse) => {
          if (cancelled) return;
          setJob(data);
          return data;
        })
        .catch((err) => {
          if (cancelled) return;
          setError(err instanceof Error ? err.message : String(err));
        });
    }

    fetchOnce();
    // Poll only while the job is in flight — terminal states stop the timer
    // so a finished or failed job costs no recurring traffic.
    const id = window.setInterval(async () => {
      const d = await fetchOnce();
      if (d && TERMINAL_STATUSES.has(d.status)) {
        window.clearInterval(id);
      }
    }, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
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

  if (job.status === "failed") {
    return (
      <main style={{ padding: "48px 32px", maxWidth: 720, margin: "0 auto" }}>
        <h1 className="qs-display" style={{ fontSize: 32 }}>
          Extraction failed
        </h1>
        <p style={{ color: "var(--fg-2)", marginTop: 12 }}>
          We couldn't process <strong>{job.original_filename || `Job ${job.job_id}`}</strong>.
          Try re-uploading the PDF — large or scanned drawings sometimes need a
          second pass.
        </p>
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => navigate("/dashboard")}
          style={{ marginTop: 24, display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <ArrowLeft size={13} strokeWidth={1.6} /> Back to Dashboard
        </button>
      </main>
    );
  }

  if (job.status !== "done") {
    // Pending or processing — render a calm progress panel and keep polling.
    // No Studio mounts so the user never sees demo data masquerading as their
    // upload.
    return (
      <main
        style={{
          padding: "64px 32px",
          maxWidth: 560,
          margin: "0 auto",
          textAlign: "center",
        }}
      >
        <div
          style={{
            display: "inline-grid",
            placeItems: "center",
            width: 72,
            height: 72,
            borderRadius: 999,
            background: "rgba(139,63,206,0.12)",
            border: "1px solid rgba(139,63,206,0.3)",
            color: "var(--qong-purple)",
            marginBottom: 22,
          }}
        >
          <Activity size={28} strokeWidth={1.7} className="dashboard-toast-pulse" />
        </div>
        <h1 className="qs-display" style={{ fontSize: 28, lineHeight: 1.2 }}>
          Extracting your P&amp;ID
        </h1>
        <p style={{ color: "var(--fg-2)", marginTop: 12, fontSize: 14, lineHeight: 1.55 }}>
          <strong>{job.original_filename || `Job ${job.job_id}`}</strong> is being
          processed. The studio opens automatically the moment extraction
          finishes — usually under a minute.
        </p>
        <p style={{ color: "var(--fg-3)", marginTop: 6, fontSize: 12 }}>
          Status: <code>{job.status}</code> · polling every 3s
        </p>
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => navigate("/dashboard")}
          style={{ marginTop: 28, display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <ArrowLeft size={13} strokeWidth={1.6} /> Back to Dashboard
        </button>
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
