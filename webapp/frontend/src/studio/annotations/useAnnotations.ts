/**
 * useAnnotations — list + CRUD hook around /jobs/{id}/annotations.
 *
 * Returns the canvas-shaped `UserAnnotationLite[]` (PidCanvas consumes that
 * directly) and exposes create/patch/remove handlers. Optimistic where it's
 * safe; rollback on error. Errors are console.warn'd for v1 — toast plumbing
 * lives in Studio.tsx's integration pass.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AnnotationCreateBody,
  AnnotationPatchBody,
  AnnotationRow,
  createAnnotation,
  deleteAnnotation,
  listAnnotations,
  patchAnnotation,
  rowToLite,
} from "./api";
import type { UserAnnotationLite } from "../PidCanvas";

interface UseAnnotationsResult {
  annotations: UserAnnotationLite[];
  loading: boolean;
  error: string | null;
  create: (body: AnnotationCreateBody) => Promise<AnnotationRow | null>;
  patch: (entityId: string, body: AnnotationPatchBody) => Promise<AnnotationRow | null>;
  remove: (entityId: string) => Promise<boolean>;
  refresh: () => Promise<void>;
}

export function useAnnotations(jobId: number | null | undefined): UseAnnotationsResult {
  const [rows, setRows] = useState<AnnotationRow[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  // Track in-flight refreshes so an unmount mid-fetch doesn't setState on a
  // dead component. (React 18 dev StrictMode double-invokes effects; without
  // this guard we get the noisy "set state on unmounted" warning on test runs.)
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    if (jobId === null || jobId === undefined) return;
    setLoading(true);
    setError(null);
    try {
      const res = await listAnnotations(jobId);
      if (!aliveRef.current) return;
      setRows(res.annotations);
    } catch (e) {
      if (!aliveRef.current) return;
      const msg = e instanceof Error ? e.message : String(e);
      console.warn("[useAnnotations] list failed:", msg);
      setError(msg);
    } finally {
      if (aliveRef.current) setLoading(false);
    }
  }, [jobId]);

  // Initial load + refetch on jobId change.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = useCallback(
    async (body: AnnotationCreateBody): Promise<AnnotationRow | null> => {
      if (jobId === null || jobId === undefined) return null;
      try {
        const row = await createAnnotation(jobId, body);
        if (!aliveRef.current) return row;
        // Insert optimistically (server returns the canonical row, so just
        // append — refresh() afterwards reconciles ordering if needed).
        setRows((prev) => [...prev, row]);
        // Background reconcile in case the server inferred extra fields
        // (placeholder_tag, status flip on auto-confirm against a detection).
        void refresh();
        return row;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        console.warn("[useAnnotations] create failed:", msg);
        if (aliveRef.current) setError(msg);
        return null;
      }
    },
    [jobId, refresh],
  );

  const patch = useCallback(
    async (entityId: string, body: AnnotationPatchBody): Promise<AnnotationRow | null> => {
      if (jobId === null || jobId === undefined) return null;
      try {
        const row = await patchAnnotation(jobId, entityId, body);
        if (!aliveRef.current) return row;
        setRows((prev) => prev.map((r) => (r.entity_id === entityId ? row : r)));
        return row;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        console.warn("[useAnnotations] patch failed:", msg);
        if (aliveRef.current) setError(msg);
        return null;
      }
    },
    [jobId],
  );

  const remove = useCallback(
    async (entityId: string): Promise<boolean> => {
      if (jobId === null || jobId === undefined) return false;
      try {
        await deleteAnnotation(jobId, entityId);
        if (!aliveRef.current) return true;
        setRows((prev) => prev.filter((r) => r.entity_id !== entityId));
        return true;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        console.warn("[useAnnotations] delete failed:", msg);
        if (aliveRef.current) setError(msg);
        return false;
      }
    },
    [jobId],
  );

  return {
    annotations: rows.map(rowToLite),
    loading,
    error,
    create,
    patch,
    remove,
    refresh,
  };
}
