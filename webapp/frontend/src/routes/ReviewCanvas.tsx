import { useParams } from "react-router-dom";

export default function ReviewCanvas() {
  const { jobId } = useParams<{ jobId: string }>();
  return (
    <div>
      <div className="qs-overline" style={{ color: "#8B3FCE", marginBottom: 12 }}>
        Plan B.2
      </div>
      <h1 className="qs-display" style={{ fontSize: 48, margin: 0 }}>
        Review canvas — Job{" "}
        <span className="qs-tag" style={{ fontSize: 32, color: "#8B3FCE" }}>{jobId}</span>
      </h1>
      <p style={{ color: "#4B5563", marginTop: 16, maxWidth: 640 }}>
        The Konva-based P&amp;ID review canvas — bbox editing, tag overlays,
        keyboard shortcuts targeting &lt;15 min/sheet reviewer flow — ships in
        Plan B.2 once your canvas design lands.
      </p>
    </div>
  );
}
