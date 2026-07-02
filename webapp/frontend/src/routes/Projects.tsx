import { Link } from "react-router-dom";

export default function Projects() {
  return (
    <div>
      <div className="qs-overline" style={{ color: "#8B3FCE", marginBottom: 12 }}>
        Placeholder
      </div>
      <h1 className="qs-display" style={{ fontSize: 48, margin: 0 }}>Projects</h1>
      <p style={{ color: "#4B5563", marginTop: 16, maxWidth: 640 }}>
        Project workspace for agencies — one project per EPC client engagement.
        Placeholder until Plan B.2.
      </p>
      <div style={{ marginTop: 32 }}>
        <Link
          to="/projects/demo"
          style={{ color: "#8B3FCE", fontWeight: 600, textDecoration: "none" }}
        >
          → Open demo project
        </Link>
      </div>
    </div>
  );
}
