export type SheetStatus = "ok" | "issues" | "review" | "pending";

export interface Sheet {
  id: number;
  name: string;
  label: string;
  status: SheetStatus;
  issues: number;
}

export interface CanvasElement {
  tag: string;
  type: string;
  confidence: number;
  lines: string[];
}

export interface SessionEvent {
  who: string;
  when: string;
  what: string;
}

export interface ProjectLike {
  id: number;
  name: string;
  pidCount: number;
}
