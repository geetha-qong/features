/**
 * Edges API client (FEATURES #38 Phase 4).
 *
 * Mirrors the backend at `/api/v1/jobs/{job_id}/edges` — see the spec at
 * `docs/superpowers/specs/2026-06-10-qong-studio-marking-design.md` §4.
 *
 * Same cookie-credential + HttpError pattern as `studio/api.ts`. We re-use
 * `HttpError` so callers can branch on `e.status` (404 → edge gone, 400 →
 * read-only field, 401 → login expired).
 */

import { HttpError } from "../api";
import type { EdgeLite, LineType } from "../PidCanvas";

// ── Request bodies (match the FastAPI Pydantic models) ───────────────────────

/** Body for POST /api/v1/jobs/{job_id}/edges. */
export interface CreateEdgeBody {
  line_type: LineType;
  source_entity_id: string;
  target_entity_id: string;
  polyline: Array<[number, number]>;
  sheet_number: number;
  relation_type?: string | null;
  group_id?: string | null;
  target_sheet_number?: number | null;
  metadata_json?: Record<string, unknown> | null;
}

/** Body for PATCH /api/v1/jobs/{job_id}/edges/{edge_id}. Any subset. */
export interface PatchEdgeBody {
  status?: EdgeLite["status"];
  line_type?: LineType;
  relation_type?: string | null;
  polyline?: Array<[number, number]>;
  group_id?: string | null;
  metadata_json?: Record<string, unknown> | null;
}

// ── Response shapes ──────────────────────────────────────────────────────────

export interface ListEdgesResponse {
  edges: EdgeLite[];
}

// ── Internal fetch helper (mirrors studio/api.ts call/callJson) ──────────────

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
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
  // 204 No Content (DELETE) — return undefined cast as T.
  if (res.status === 204) {
    return undefined as unknown as T;
  }
  return (await res.json()) as T;
}

// ── Public API ───────────────────────────────────────────────────────────────

export const listEdges = (jobId: number): Promise<ListEdgesResponse> =>
  request<ListEdgesResponse>("GET", `/api/v1/jobs/${jobId}/edges`);

export const createEdge = (jobId: number, body: CreateEdgeBody): Promise<EdgeLite> =>
  request<EdgeLite>("POST", `/api/v1/jobs/${jobId}/edges`, body);

export const patchEdge = (
  jobId: number,
  edgeId: string,
  body: PatchEdgeBody,
): Promise<EdgeLite> =>
  request<EdgeLite>(
    "PATCH",
    `/api/v1/jobs/${jobId}/edges/${encodeURIComponent(edgeId)}`,
    body,
  );

export const deleteEdge = (jobId: number, edgeId: string): Promise<void> =>
  request<void>(
    "DELETE",
    `/api/v1/jobs/${jobId}/edges/${encodeURIComponent(edgeId)}`,
  );
