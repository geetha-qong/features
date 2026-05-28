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
