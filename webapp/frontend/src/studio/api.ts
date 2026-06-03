/**
 * Thin fetch helpers for the studio surfaces.
 * Cookie auth; same Vite proxy as the rest of the SPA.
 */

export interface RealSheet {
  id: number;
  filename: string;
  url: string;
  label: string;
}

export interface DetectionItem {
  // Shape comes from the GPU worker callback — bbox is the source of truth.
  // Field names match what the Windows worker produces; conservative typing
  // here so the canvas can render whatever subset is present.
  page?: number;
  bbox?: [number, number, number, number]; // x1, y1, x2, y2 in pixel coords on the tile
  tile?: string;
  label?: string;
  confidence?: number;
  category?: string;
  /** Backend-attached canonical entity UUID (FEATURES #27 / D1.5). Null when
   *  no canonical match (e.g. label is a symbol-class string, not a tag, or
   *  canonical.json hasn't been written yet). The DatasheetDrawer keys edits
   *  by this — detections with null `entity_id` are read-only. */
  entity_id?: string | null;
  /** Canonical entity_class ("valve" | "instrument" | …) — also from the
   *  backend match. Used to choose which deliverable type to render. */
  entity_class?: string;
  [k: string]: unknown;
}

export interface ValveRow {
  id: number;
  pid_no: string;
  category: string;
  size: string;
  serial_no: string;
  fluid_code: string;
  piping_class: string;
  qty: number;
  line: string;
  motor_actuator: string;
  pneumatic_actuator: string;
  solenoid: string;
}

export interface JobSheetsResp {
  job_id: number;
  pid_no: string;
  sheet_count: number;
  sheets: RealSheet[];
}

export interface JobDetectionsResp {
  job_id: number;
  status: string;
  valve_count: number;
  detections: DetectionItem[];
  detection_count: number;
  valves: ValveRow[];
}

async function call<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: "include", redirect: "manual" });
  if (res.status === 0 || res.type === "opaqueredirect") {
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export const getJobSheets = (jobId: number) => call<JobSheetsResp>(`/api/v1/jobs/${jobId}/sheets`);
export const getJobDetections = (jobId: number) =>
  call<JobDetectionsResp>(`/api/v1/jobs/${jobId}/detections`);
