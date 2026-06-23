/**
 * Annotation API — thin client over the FastAPI /jobs/{id}/annotations routes
 * landed in FEATURES #38 (Phase 1). Mirrors the Pydantic shapes from
 * webapp/routers/annotations.py 1:1.
 *
 * The on-canvas overlay uses a leaner `UserAnnotationLite` (see PidCanvas.tsx
 * `UserAnnotationLite`); this module exports a fuller `AnnotationRow` that
 * carries the audit fields (created_at, linked_correction_id, …) needed by
 * the PropertiesPanel / drawer. Both are kept in sync — when the canvas needs
 * to render the result of a create()/patch() round-trip, the caller projects
 * the AnnotationRow into the lite shape.
 */
import { HttpError } from "../api";
import type { UserAnnotationLite } from "../PidCanvas";

// Re-export so downstream importers don't need to know that the lite shape
// lives in PidCanvas.
export type { UserAnnotationLite };

// ─── Wire types ────────────────────────────────────────────────────────────

export type AnnotationStatus =
  | "model_found"
  | "user_added"
  | "user_confirmed"
  | "user_rejected";

export type AnnotationSource = "model" | "user";

export type EntityClass = "valve" | "instrument" | "equipment";

export interface AnnotationRow {
  id: number;
  job_id: number;
  entity_id: string;
  user_id: number;
  source: AnnotationSource;
  status: AnnotationStatus;
  entity_class: string;
  sub_class: string | null;
  bbox: [number, number, number, number];
  sheet_number: number;
  placeholder_tag: string | null;
  tag: string | null;
  fields_json: Record<string, unknown> | null;
  linked_detection_index: number | null;
  linked_correction_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface AnnotationsResponse {
  annotations: AnnotationRow[];
}

export interface AnnotationCreateBody {
  entity_class: EntityClass;
  sub_class?: string | null;
  bbox: [number, number, number, number];
  sheet_number?: number;
  linked_detection_index?: number | null;
}

export interface AnnotationPatchBody {
  status?: AnnotationStatus;
  tag?: string | null;
  fields_json?: Record<string, unknown> | null;
  sub_class?: string | null;
}

// ─── Shared fetch helper ───────────────────────────────────────────────────
// Local to this module to avoid leaking a generic write helper from studio/api.ts
// (that file exports a write helper only for entity patches today). Mirrors the
// same cookie + opaqueredirect handling so login expiry surfaces as 401.

async function callJson<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = {
    method,
    credentials: "include",
    redirect: "manual",
  };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (res.status === 0 || res.type === "opaqueredirect") {
    throw new HttpError("Not authenticated", 401);
  }
  if (!res.ok) {
    throw new HttpError(`HTTP ${res.status}`, res.status);
  }
  // DELETE may return 204 — guard the JSON parse.
  if (res.status === 204) return undefined as unknown as T;
  const ct = res.headers.get("content-type") ?? "";
  if (!ct.includes("application/json")) return undefined as unknown as T;
  return (await res.json()) as T;
}

// ─── Endpoints ─────────────────────────────────────────────────────────────

export const listAnnotations = (jobId: number) =>
  callJson<AnnotationsResponse>("GET", `/api/v1/jobs/${jobId}/annotations`);

export const createAnnotation = (jobId: number, body: AnnotationCreateBody) =>
  callJson<AnnotationRow>(
    "POST",
    `/api/v1/jobs/${jobId}/annotations`,
    body,
  );

export const patchAnnotation = (
  jobId: number,
  entityId: string,
  body: AnnotationPatchBody,
) =>
  callJson<AnnotationRow>(
    "PATCH",
    `/api/v1/jobs/${jobId}/annotations/${encodeURIComponent(entityId)}`,
    body,
  );

export const deleteAnnotation = (jobId: number, entityId: string) =>
  callJson<void>(
    "DELETE",
    `/api/v1/jobs/${jobId}/annotations/${encodeURIComponent(entityId)}`,
  );

// ─── Projection helpers ────────────────────────────────────────────────────

/** Project an AnnotationRow → UserAnnotationLite for canvas overlay. */
export function rowToLite(r: AnnotationRow): UserAnnotationLite {
  return {
    entity_id: r.entity_id,
    status: r.status,
    source: r.source,
    entity_class: r.entity_class,
    sub_class: r.sub_class,
    bbox: r.bbox,
    sheet_number: r.sheet_number,
    placeholder_tag: r.placeholder_tag,
    tag: r.tag,
  };
}
