import type { Sheet, SheetStatus, ProjectLike } from "./types";

const TAG_PREFIXES = ["CDU", "VDU", "FCC", "HCU", "GTU", "AMU"];

export function buildSheets(project: ProjectLike): Sheet[] {
  const total = Math.max(8, Math.min(28, project.pidCount || 16));
  const sheets: Sheet[] = [];
  for (let i = 1; i <= total; i++) {
    const r = (i * 17 + project.id * 31) % 100;
    let status: SheetStatus = "ok";
    let issues = 0;
    if (r < 20) {
      status = "issues";
      issues = 1 + (r % 8);
    } else if (r < 40) {
      status = "review";
      issues = 1 + (r % 4);
    } else if (r < 50) {
      status = "pending";
    }
    const tagPrefix = TAG_PREFIXES[i % TAG_PREFIXES.length];
    const tagNum = String(100 + i).padStart(3, "0");
    sheets.push({
      id: i,
      name: `${tagPrefix}_FT-${tagNum}.pdf`,
      label: `Sheet ${i}`,
      status,
      issues,
    });
  }
  return sheets;
}
