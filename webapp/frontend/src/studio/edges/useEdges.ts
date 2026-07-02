/**
 * useEdges — React hook that owns the edges list for a single job.
 *
 * Mirrors the useAnnotations pattern (Phase 3): optimistic insert on
 * `create`, in-place merge on `patch`, removal on `remove`, and a `refresh`
 * escape hatch when the caller suspects local state has drifted from the
 * server (e.g. a websocket nudge once that lands).
 *
 * Optimistic mutations rollback on error — we re-throw so caller toast
 * surfaces the failure. Network shape and HttpError are inherited from
 * `./api.ts`.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  listEdges,
  createEdge,
  patchEdge,
  deleteEdge,
  type CreateEdgeBody,
  type PatchEdgeBody,
} from "./api";
import type { EdgeLite } from "../PidCanvas";

export interface UseEdgesResult {
  edges: EdgeLite[];
  loading: boolean;
  error: Error | null;
  create: (body: CreateEdgeBody) => Promise<EdgeLite>;
  patch: (edgeId: string, body: PatchEdgeBody) => Promise<EdgeLite>;
  remove: (edgeId: string) => Promise<void>;
  refresh: () => Promise<void>;
}

/** Generate a client-side temporary edge_id used for optimistic inserts.
 *  The server returns the real UUID on POST success — we swap it in. */
function tempEdgeId(): string {
  // RFC4122-ish but only good enough to be unique locally; never sent.
  return `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function useEdges(jobId: number | null | undefined): UseEdgesResult {
  const [edges, setEdges] = useState<EdgeLite[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);

  // Guard against unmounted setState — the studio surface mounts/unmounts
  // freely as users navigate between jobs.
  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    if (jobId == null) return;
    setLoading(true);
    setError(null);
    try {
      const res = await listEdges(jobId);
      if (aliveRef.current) {
        setEdges(res.edges ?? []);
      }
    } catch (e) {
      if (aliveRef.current) {
        setError(e instanceof Error ? e : new Error(String(e)));
      }
    } finally {
      if (aliveRef.current) {
        setLoading(false);
      }
    }
  }, [jobId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = useCallback(
    async (body: CreateEdgeBody): Promise<EdgeLite> => {
      if (jobId == null) throw new Error("useEdges.create called before jobId is set");
      // Optimistic insert with a placeholder edge_id; swap on server reply.
      const tmpId = tempEdgeId();
      const optimistic: EdgeLite = {
        edge_id: tmpId,
        source: "user",
        status: "user_added",
        line_type: body.line_type,
        relation_type: body.relation_type ?? null,
        source_entity_id: body.source_entity_id,
        target_entity_id: body.target_entity_id,
        polyline: body.polyline,
        sheet_number: body.sheet_number,
        group_id: body.group_id ?? null,
        directed: body.directed,
      };
      setEdges((prev) => [...prev, optimistic]);
      try {
        const created = await createEdge(jobId, body);
        setEdges((prev) => prev.map((e) => (e.edge_id === tmpId ? created : e)));
        return created;
      } catch (e) {
        // Roll back optimistic insert.
        setEdges((prev) => prev.filter((e) => e.edge_id !== tmpId));
        throw e;
      }
    },
    [jobId],
  );

  const patch = useCallback(
    async (edgeId: string, body: PatchEdgeBody): Promise<EdgeLite> => {
      if (jobId == null) throw new Error("useEdges.patch called before jobId is set");
      const prior = edges.find((e) => e.edge_id === edgeId);
      // Optimistic merge.
      setEdges((prev) =>
        prev.map((e) =>
          e.edge_id === edgeId
            ? {
                ...e,
                ...(body.status !== undefined ? { status: body.status } : {}),
                ...(body.line_type !== undefined ? { line_type: body.line_type } : {}),
                ...(body.relation_type !== undefined
                  ? { relation_type: body.relation_type }
                  : {}),
                ...(body.polyline !== undefined ? { polyline: body.polyline } : {}),
                ...(body.group_id !== undefined ? { group_id: body.group_id } : {}),
              }
            : e,
        ),
      );
      try {
        const updated = await patchEdge(jobId, edgeId, body);
        setEdges((prev) => prev.map((e) => (e.edge_id === edgeId ? updated : e)));
        return updated;
      } catch (e) {
        // Rollback by restoring the prior copy.
        if (prior) {
          setEdges((prev) => prev.map((x) => (x.edge_id === edgeId ? prior : x)));
        }
        throw e;
      }
    },
    [jobId, edges],
  );

  const remove = useCallback(
    async (edgeId: string): Promise<void> => {
      if (jobId == null) throw new Error("useEdges.remove called before jobId is set");
      const prior = edges.find((e) => e.edge_id === edgeId);
      setEdges((prev) => prev.filter((e) => e.edge_id !== edgeId));
      try {
        await deleteEdge(jobId, edgeId);
      } catch (e) {
        if (prior) {
          setEdges((prev) => [...prev, prior]);
        }
        throw e;
      }
    },
    [jobId, edges],
  );

  return { edges, loading, error, create, patch, remove, refresh };
}
