import { Link, useParams } from "react-router-dom";

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  return (
    <div>
      <div className="qs-overline" style={{ color: "#8B3FCE", marginBottom: 12 }}>
        Project · placeholder
      </div>
      <h1 className="qs-display" style={{ fontSize: 48, margin: 0 }}>
        Project <span className="qs-tag" style={{ fontSize: 32, color: "#8B3FCE" }}>{projectId}</span>
      </h1>
      <p style={{ color: "#4B5563", marginTop: 16, maxWidth: 640 }}>
        Per-project view: list of jobs, deliverable status, vendor matches
        scoped to this engagement.
      </p>
      <div style={{ marginTop: 32 }}>
        <Link
          to="/jobs/1"
          style={{ color: "#8B3FCE", fontWeight: 600, textDecoration: "none" }}
        >
          → Open job 1 (real backend data)
        </Link>
      </div>
    </div>
  );
}
