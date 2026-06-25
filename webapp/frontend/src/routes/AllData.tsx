import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import AllDataView from "../studio/alldata/AllDataView";

/**
 * /jobs/:jobId/data — the "All Data" surface. A thin route wrapper that
 * resolves the job's display name (best-effort) and mounts AllDataView, which
 * does the heavy lifting (fetching entities + detections). Sibling of the
 * /jobs/:jobId/review route. Frontend-only.
 */
interface JobResponse {
  job_id: number;
  original_filename: string;
}

export default function AllData() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [name, setName] = useState<string>("");

  const numericId = jobId ? Number(jobId) : NaN;

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    // Best-effort name resolution — the view renders regardless, so a failed
    // job lookup just falls back to "Job N" in the breadcrumb.
    fetch(`/api/v1/jobs/${jobId}`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: JobResponse) => {
        if (cancelled) return;
        setName((data.original_filename || `Job ${data.job_id}`).replace(/\.pdf$/i, ""));
      })
      .catch(() => {
        if (cancelled) return;
        setName(`Job ${jobId}`);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  if (!jobId || Number.isNaN(numericId)) {
    return (
      <main style={{ padding: "48px 32px", textAlign: "center", color: "var(--fg-3)" }}>
        Invalid job.
      </main>
    );
  }

  return (
    <AllDataView
      jobId={numericId}
      projectName={name || `Job ${jobId}`}
      onBack={() => navigate(`/jobs/${jobId}`)}
    />
  );
}
