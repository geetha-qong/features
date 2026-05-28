import { Clock } from "lucide-react";
import PidThumb from "../components/PidThumb";
import type { ProjectTile } from "./types";

export default function ProjectCard({ project, onOpen }: { project: ProjectTile; onOpen: () => void }) {
  const statusLabel = project.status === "ok" ? "Synced" : project.status === "run" ? "Extracting" : project.status === "fail" ? "Failed" : "Draft";
  return (
    <div className="project-card" onClick={onOpen} data-comment-anchor={`project-${project.id}`}>
      <div className="project-thumb">
        <span className={`status-pill ${project.status}`}>
          <span className="dot"></span>
          {statusLabel}
        </span>
        <PidThumb seed={project.id} />
      </div>
      <div className="project-card-body">
        <h3>{project.name}</h3>
        <p className="client">{project.client}</p>
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
