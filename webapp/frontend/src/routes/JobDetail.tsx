import { Link, useParams } from "react-router-dom";

export default function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>();
  const deliverables: Array<[string, string, string]> = [
    ["Valve List", "valve_list", "xlsx"],
    ["Valve List (CSV)", "valve_list", "csv"],
    ["Instrument Index", "instrument_index", "xlsx"],
    ["Equipment List", "equipment_list", "xlsx"],
    ["Datasheet", "datasheet", "xlsx"],
  ];
  return (
    <div>
      <div className="qs-overline" style={{ color: "#8B3FCE", marginBottom: 12 }}>
        Job · placeholder
      </div>
      <h1 className="qs-display" style={{ fontSize: 48, margin: 0 }}>
        Job <span className="qs-tag" style={{ fontSize: 32, color: "#8B3FCE" }}>{jobId}</span>
      </h1>
      <p style={{ color: "#4B5563", marginTop: 16, maxWidth: 640 }}>
        Job detail view. The links below hit the real{" "}
        <code>POST /api/v1/jobs/{`{id}`}/export/...</code> endpoint built in
        Plan A — they will return 200 + file once auth + ownership are wired
        in Task 5.
      </p>
      <div
        style={{
          marginTop: 32,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
          gap: 12,
        }}
      >
        {deliverables.map(([label, type, fmt]) => (
          <a
            key={`${type}.${fmt}`}
            href={`/api/v1/jobs/${jobId}/export/${type}/${fmt}`}
            style={{
              border: "1px solid #E5E7EB",
              borderRadius: 10,
              padding: 16,
              textDecoration: "none",
              color: "#0A0B14",
              transition: "border-color 0.12s",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = "#8B3FCE")}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = "#E5E7EB")}
          >
            <div style={{ fontWeight: 600 }}>{label}</div>
            <div className="qs-tag" style={{ fontSize: 11, color: "#9CA3AF", marginTop: 4 }}>
              {type.toUpperCase()} · {fmt.toUpperCase()}
            </div>
          </a>
        ))}
      </div>
      <div style={{ marginTop: 32 }}>
        <Link
          to={`/jobs/${jobId}/review`}
          style={{ color: "#8B3FCE", fontWeight: 600, textDecoration: "none" }}
        >
          → Open Qong Studio review canvas (Plan B.2)
        </Link>
      </div>
    </div>
  );
}
