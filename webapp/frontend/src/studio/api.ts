/**
 * Thin fetch helpers for the studio surfaces.
 * Cookie auth; same Vite proxy as the rest of the SPA.
 */
import type { JobGraph } from "./types";

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

// HttpError is declared before `call<T>` so reads can also throw it; the
// DatasheetDrawer branches on `e instanceof HttpError && e.status === 404`
// to render the "not in canonical" UX instead of the raw error message.
export class HttpError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function call<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: "include", redirect: "manual" });
  if (res.status === 0 || res.type === "opaqueredirect") {
    throw new HttpError("Not authenticated", 401);
  }
  if (!res.ok) {
    throw new HttpError(`HTTP ${res.status}`, res.status);
  }
  return (await res.json()) as T;
}

/** Status-aware JSON fetcher for write-ish verbs. Returns the parsed body on
 *  2xx; throws an `HttpError` carrying the status code on non-2xx so callers
 *  can distinguish 404 (entity not in canonical) from 400 (read-only field)
 *  from 401 (login expired). Mirrors the shape of `call<T>` so the same
 *  cookie-credential rules apply. */

async function callJson<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "include",
    redirect: "manual",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 0 || res.type === "opaqueredirect") {
    throw new HttpError("Not authenticated", 401);
  }
  if (!res.ok) {
    throw new HttpError(`HTTP ${res.status}`, res.status);
  }
  return (await res.json()) as T;
}

export const getJobSheets = (jobId: number) => call<JobSheetsResp>(`/api/v1/jobs/${jobId}/sheets`);
export const getJobDetections = (jobId: number) =>
  call<JobDetectionsResp>(`/api/v1/jobs/${jobId}/detections`);

// ──────────────────────────────────────────────────────────────────────────────
// Persisted sheet "Apply" state (design 2026-06-13 §1b)
// ──────────────────────────────────────────────────────────────────────────────

/** {sheet_number: applied_at_iso}. JSON object keys arrive as strings; the
 *  frontend re-keys them to numbers when seeding `appliedBySheet`. */
export interface AppliedMapResponse {
  applied: Record<string, string>;
}

/** Fetch the map of applied sheets for a job so Studio can seed `appliedBySheet`
 *  on load. */
export const getAppliedSheets = (jobId: number) =>
  call<AppliedMapResponse>(`/api/v1/jobs/${jobId}/sheets/applied`);

/** Mark a sheet applied (upsert). Fire-and-forget alongside the optimistic UI. */
export const applySheet = (jobId: number, sheetNumber: number) =>
  callJson<unknown>("POST", `/api/v1/jobs/${jobId}/sheets/${sheetNumber}/apply`);

// ──────────────────────────────────────────────────────────────────────────────
// Editable deliverables (Spec A / FEATURES #26 — entity_overrides API)
// ──────────────────────────────────────────────────────────────────────────────

/** Column schema row from the customer template (one cell per row in the UI).
 *  Mirrors `webapp/routers/entities.py:ColumnSchema`. */
export interface EntityColumn {
  field: string;        // dot-notation path: "tag", "fields.size", "vendor_match.vendor_name"
  header: string;       // human-readable label, e.g. "Size"
  order: number;
  editable: boolean;    // false for read-only (entity_id, pid_number, sheet_number, bbox, entity_class)
}

/** One cell value from the GET response, post-override merge. */
export interface EntityFieldValue {
  value: unknown;       // typed loosely — canonical fields are str|number|null|nested object
  source: "pid" | "manual";  // "pid" = pipeline-extracted, "manual" = user-supplied (null in canonical)
  is_override: boolean; // true iff there's an entity_overrides row for this (entity, field)
}

export interface EntityRow {
  entity_id: string;
  entity_class: string;
  sub_class: string;
  tag: string | null;
  pid_number: string;
  sheet_number: number;
  values: Record<string, EntityFieldValue>;  // keyed by EntityColumn.field
}

export interface EntitiesResponse {
  deliverable_type: string;
  customer_template_slug: string;
  schema: EntityColumn[];
  entities: EntityRow[];
}

export interface PatchEntityResponse {
  entity_id: string;
  applied: number;
}

/** Fetch every entity row + column schema for a given deliverable_type.
 *  The single-entity drawer currently filters this response client-side
 *  (no single-fetch endpoint exists yet — see follow-up note in D2 commit).
 *  Cheap for typical job sizes (≤ a few hundred entities); revisit if we
 *  hit jobs with thousands of valves where round-tripping all rows hurts. */
export const getEntities = (jobId: number, deliverableType: string) =>
  call<EntitiesResponse>(
    `/api/v1/jobs/${jobId}/entities?deliverable_type=${encodeURIComponent(deliverableType)}`,
  );

// ──────────────────────────────────────────────────────────────────────────────
// Process-graph visualization (Stream 3)
// ──────────────────────────────────────────────────────────────────────────────

/** Fetch the auto-extracted process graph (nodes + pipe edges) for a job's
 *  active page. Returns `null` when no graph is available — 404
 *  ({"error":"no_canonical"}, pipeline never ran) and 409
 *  ({"error":"canonical_required"}, graph not computed for a legacy job) are
 *  both treated as "no graph" and surface a quiet disabled state rather than
 *  an uncaught error. Any other status rethrows the HttpError. */
export const getJobGraph = (jobId: number): Promise<JobGraph | null> =>
  call<JobGraph>(`/api/v1/jobs/${jobId}/graph`).catch((e) => {
    if (e instanceof HttpError && (e.status === 404 || e.status === 409)) {
      return null;
    }
    throw e;
  });

/** PATCH a partial entity update. `fields` is a map of field-path → new value;
 *  the backend captures `prior_value` from the on-disk canonical (audit trail).
 *  Empty `fields` is a no-op (no-op returns 200 with applied=0). */
export const patchEntity = (
  jobId: number,
  entityId: string,
  fields: Record<string, unknown>,
) =>
  callJson<PatchEntityResponse>(
    "PATCH",
    `/api/v1/jobs/${jobId}/entities/${encodeURIComponent(entityId)}`,
    { fields },
  );

export interface CreateEntityResponse {
  entity_id: string;
  applied: number;
}

/** Create a brand-new entity in canonical.json (for YOLO detections that
 *  the pipeline didn't extract into the instrumentation_index / valve_list). */
export const createEntity = (
  jobId: number,
  data: {
    entity_class: string;
    sub_class?: string;
    fields: Record<string, unknown>;
  },
) =>
  callJson<CreateEntityResponse>(
    "POST",
    `/api/v1/jobs/${jobId}/entities`,
    data,
  );
