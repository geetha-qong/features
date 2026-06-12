import { FileText, MoreHorizontal } from "lucide-react";
import type { ProjectTile } from "./types";

export default function ProjectRow({ project, onOpen }: { project: ProjectTile; onOpen: () => void }) {
  return (
    <div
      className={`list-row ${project.status === "ok" ? "" : "not-ready"}`}
      onClick={onOpen}
      data-comment-anchor={`project-${project.id}`}
      title={project.status === "ok" ? undefined : "Still extracting — opens when ready"}
    >
      <div className="name-cell">
        <div className="thumb-mini">
          <FileText size={18} strokeWidth={1.6} />
        </div>
        <div style={{ minWidth: 0 }}>
          <div className="name">{project.name}</div>
          <div className="sub">
            {project.pidCount} P&amp;IDs · Rev {project.rev}
          </div>
        </div>
      </div>
      <div className="cell-client">{project.client}</div>
      <div className="cell-date">{project.lastModified}</div>
      <div>
        <div className="avatar-stack">
          {project.team.slice(0, 3).map((m, i) => (
            <div key={i} className="avatar xs" title={m.name} style={{ background: m.color }}>
              {m.initials}
            </div>
          ))}
        </div>
      </div>
      <div className="cell-action">
        <button className="icon-btn" onClick={(e) => e.stopPropagation()}>
          <MoreHorizontal size={18} strokeWidth={1.6} />
        </button>
      </div>
    </div>
  );
}
