import { Clock } from "lucide-react";
import type { ProjectTile } from "./types";

export default function ProjectCard({ project, onOpen }: { project: ProjectTile; onOpen: () => void }) {
  // "not-ready" blocks opening — only block while actively processing/pending,
  // not for failed (deliverables still accessible) or done.
  const isBlocked = project.status === "run" || project.status === "draft";

  const statusLabel =
    project.status === "ok" ? "Done" :
    project.status === "run" ? "Preparing" :
    project.status === "fail" ? "Failed" : "Draft";


  return (
    <div
      className={`project-card no-thumb ${isBlocked ? "not-ready" : ""}`}
      onClick={onOpen}
      data-comment-anchor={`project-${project.id}`}
      title={isBlocked ? "Still extracting — opens when ready" : undefined}
    >
      <div className="project-card-body">
        <h3>{project.name}</h3>
        <p className="client">{project.client}</p>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <span className={`status-pill inline ${project.status}`}>
            <span className="dot"></span>
            {statusLabel}
          </span>
        </div>
        <div className="meta-row">
          <span className="date">
            <Clock size={13} strokeWidth={1.6} />
            {project.lastModified}
          </span>
          <div className="avatar-stack">
            {project.team.slice(0, 3).map((m, i) => (
              <div key={i} className="avatar xs" title={m.name} style={{ background: m.color }}>
                {m.initials}
              </div>
            ))}
            {project.team.length > 3 && (
              <div className="avatar xs" style={{ background: "var(--ink-300)", color: "var(--ink-800)" }}>
                +{project.team.length - 3}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
