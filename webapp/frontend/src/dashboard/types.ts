export type ApiJobStatus = "pending" | "processing" | "done" | "failed";
export type ProjectStatus = "draft" | "run" | "ok" | "fail";

export interface ApiJob {
  id: number;
  name: string;
  pid_no: string;
  status: ApiJobStatus;
  valve_count: number;
  created_at: string | null;
  owner_username: string | null;
}

export interface ProjectTile {
  id: number;
  name: string;
  client: string;
  lastModified: string;
  rev: string;
  pidCount: number;
  status: ProjectStatus;
  team: TeamMember[];
}

export interface TeamMember {
  name: string;
  initials: string;
  color: string;
}

const TEAM_COLORS = [
  "linear-gradient(135deg,#8B3FCE,#C73FBE)",
  "linear-gradient(135deg,#C73FBE,#FF4DA8)",
  "linear-gradient(135deg,#5347CC,#8B3FCE)",
  "linear-gradient(135deg,#FF4DA8,#E73FB0)",
  "linear-gradient(135deg,#22D3EE,#5347CC)",
];

export function statusOf(s: ApiJobStatus): ProjectStatus {
  if (s === "done") return "ok";
  if (s === "processing") return "run";
  if (s === "failed") return "fail";
  return "draft";
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const diffSec = Math.max(0, (Date.now() - then) / 1000);
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.round(diffSec / 60)} min ago`;
  if (diffSec < 86400) return `${Math.round(diffSec / 3600)} hr ago`;
  if (diffSec < 86400 * 2) return "Yesterday";
  if (diffSec < 86400 * 7) return `${Math.round(diffSec / 86400)} days ago`;
  if (diffSec < 86400 * 30) return `${Math.round(diffSec / 86400 / 7)} weeks ago`;
  return new Date(iso).toLocaleDateString();
}

export function avatarFor(username: string | null): TeamMember {
  const name = username || "User";
  const initials = name.slice(0, 2).toUpperCase();
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0;
  const color = TEAM_COLORS[Math.abs(hash) % TEAM_COLORS.length];
  return { name, initials, color };
}

export function toProjectTile(job: ApiJob): ProjectTile {
  return {
    id: job.id,
    name: job.name.replace(/\.pdf$/i, ""),
    client: job.owner_username || "Internal",
    lastModified: relativeTime(job.created_at),
    rev: "R1",
    pidCount: 1,
    status: statusOf(job.status),
    team: [avatarFor(job.owner_username)],
  };
}
