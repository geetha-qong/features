import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div style={{ textAlign: "center", padding: "120px 24px" }}>
      <div
        className="qs-display qs-gradient-text"
        style={{ fontSize: 144, lineHeight: 1, margin: 0 }}
      >
        404
      </div>
      <p style={{ color: "#4B5563", marginTop: 16 }}>This page doesn't exist.</p>
      <Link
        to="/"
        style={{
          color: "#8B3FCE",
          fontWeight: 600,
          textDecoration: "none",
          marginTop: 24,
          display: "inline-block",
        }}
      >
        ← Back home
      </Link>
    </div>
  );
}
