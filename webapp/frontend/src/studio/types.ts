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
  // Canonical entity_class ("valve" | "instrument" | "equipment"), present
  // when this element was built from real backend data. Drives the
  // DatasheetDrawer's initial deliverable type when a row is clicked.
  // Optional so the prototype DEMO_ELEMENT_DATA continues to compile.
  entityClass?: string;
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
