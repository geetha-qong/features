import { Clock } from "lucide-react";
import type { ProjectTile } from "./types";

/**
 * Clean "no-thumb" project card — matches the Claude Design v4 dashboard:
 * title · client (mono uppercase) · inline status pill · dashed divider ·
 * meta row (relative time + owner avatar). No thumbnail, no icon badge.
 * The `not-ready` class still gates opening jobs that are still extracting.
 */
export default function ProjectCard({ project, onOpen }: { project: ProjectTile; onOpen: () => void }) {
  const statusLabel =
    project.status === "ok" ? "Synced" :
    project.status === "run" ? "Extracting" :
    project.status === "fail" ? "Failed" : "Draft";
  return (
    <div
      className={`project-card no-thumb ${project.status === "ok" ? "" : "not-ready"}`}
      onClick={onOpen}
      data-comment-anchor={`project-${project.id}`}
      title={project.status === "ok" ? undefined : "Still extracting — opens when ready"}
    >
      <div className="project-card-body">
        <h3>{project.name}</h3>
        <p className="client">{project.client}</p>
        <span className={`status-pill inline ${project.status}`}>
          <span className="dot"></span>
          {statusLabel}
        </span>
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
