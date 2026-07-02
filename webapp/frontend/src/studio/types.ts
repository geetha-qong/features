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
  // Canonical sub_class code (BV / FT / PUMP / …) when known. Used purely to
  // pick the P&ID glyph for the on-stage element row; optional so the
  // prototype data keeps compiling.
  subClass?: string;
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

// ── Process-graph visualization (Stream 3) ─────────────────────────────────
// Shapes mirror GET /api/v1/jobs/{jobId}/graph exactly. ALL coordinates are
// page-pixel (the same space the full-page canvas already uses) — graph
// nodes/edges do NOT need tile→page translation, unlike raw detections.

export type GraphEdgeMethod = "opencv" | "llm_fallback" | "user_added";

export interface GraphNode {
  id: string;
  entity_id: string | null;
  tag: string | null;
  class: string | null;
  /** [x1, y1, x2, y2] in page-pixel coords; null when the node has no bbox. */
  bbox: number[] | null;
  tile: string;
  confidence: number;
  /** Pipe line designation extracted from the valve entity (e.g. 4"-P-1234-BGA). */
  line?: string | null;
  /** Provenance of the node (node-corrections, 2026-06-28). "auto" = YOLO
   *  detection; "user" = a symbol the user added via Mark Symbol that the
   *  backend now surfaces as a real, connectable graph node. Absent on legacy
   *  graphs → treat as "auto". */
  source?: "auto" | "user";
  /** True when the user soft-rejected this node (node-corrections). Rejected
   *  nodes are still returned by GET /graph (not hidden) so they can be rendered
   *  ghosted with a Restore action. Edges touching a rejected node are omitted
   *  by the backend. Absent → not rejected. */
  rejected?: boolean;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  /** Array of [x, y] page-pixel points. */
  polyline: number[][];
  tile: string;
  method: GraphEdgeMethod;
  confidence: number;
  /**
   * Direction flag. `true` ⇒ edge is oriented source→target (rendered with an
   * arrowhead). Missing/`false` ⇒ undirected (rendered as today, no arrowhead).
   * User-drawn edges are always directed; auto edges are directed iff an arrow
   * oriented them. See spec 2026-06-17-graph-directions-design.md.
   */
  directed?: boolean;
}

export interface GraphStats {
  nodes: number;
  edges: number;
  fallback_used: boolean;
  auto_edges: number;
  user_edges: number;
}

export interface GraphOrphanLine {
  polyline: number[][];
  tile?: string;
  reason?: string;
  source?: string;
  is_dashed?: boolean;
}

export interface JobGraph {
  version: string;
  job_id: number;
  page: number;
  /** Page-image dimensions the node/edge/orphan coords live in (the full-page
   *  PNG the pipeline traced). GraphLayer scales graph coords by
   *  natural/page_{width,height} onto the canvas. Absent on legacy graphs →
   *  no scaling (render unscaled). */
  page_width?: number | null;
  page_height?: number | null;
  generated_at: string;
  stats: GraphStats;
  nodes: GraphNode[];
  edges: GraphEdge[];
  floating_nodes: string[];
  orphan_lines: GraphOrphanLine[];
}
