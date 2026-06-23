/** Self-contained per-instrument datasheet panel.
 *
 *  Given a job + entity, fetches that entity's FULL datasheet (the field set is
 *  chosen automatically by the backend from the entity's sub_class — see
 *  webapp/deliverables/ids_schema.py), renders every section, and persists
 *  edits via the EntityOverride PATCH. Used in the Bulk Review side drawer so a
 *  selected row shows its complete datasheet — not just the few list columns.
 *
 *  Mirrors the Studio DatasheetDrawer's datasheet path but stripped of the
 *  drawer's doc-type switching / OCR / create-mode — those don't apply here.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Save } from "lucide-react";
import {
  HttpError,
  getEntityDatasheet,
  patchEntity,
  type EntityDatasheetResponse,
} from "../api";
import {
  SectionedDatasheet,
  computeDatasheetDirty,
  seedDatasheetEditValues,
} from "./sectioned";

export default function DatasheetPanel({
  jobId,
  entityId,
  onSaved,
}: {
  jobId: number;
  entityId: string;
  /** Called after a successful save so the parent can refresh its row list
   *  (keeps the grid's is_override badges + values in sync). */
  onSaved?: () => void;
}) {
  const [resp, setResp] = useState<EntityDatasheetResponse | null>(null);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [unlocked, setUnlocked] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [legacy, setLegacy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ kind: "ok" | "error"; msg: string } | null>(null);

  // Guard against stale fetches when the user clicks through rows quickly.
  const reqIdRef = useRef(0);

  const fetchDatasheet = useCallback(async () => {
    const myReq = ++reqIdRef.current;
    setLoading(true);
    setError(null);
    setLegacy(false);
    try {
      const ds = await getEntityDatasheet(jobId, entityId);
      if (myReq !== reqIdRef.current) return;
      setResp(ds);
      setEditValues(seedDatasheetEditValues(ds));
      setUnlocked({});
    } catch (e) {
      if (myReq !== reqIdRef.current) return;
      if (e instanceof HttpError && e.status === 404) {
        setLegacy(true);
      } else {
        setError(e instanceof Error ? e.message : "Failed to load datasheet");
      }
      setResp(null);
    } finally {
      if (myReq === reqIdRef.current) setLoading(false);
    }
  }, [jobId, entityId]);

  useEffect(() => {
    void fetchDatasheet();
  }, [fetchDatasheet]);

  // Auto-clear toast.
  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 2500);
    return () => window.clearTimeout(id);
  }, [toast]);

  const dirty = computeDatasheetDirty(resp, editValues);
  const dirtyCount = Object.keys(dirty).length;

  function update(key: string, val: string) {
    setEditValues((v) => ({ ...v, [key]: val }));
  }

  async function onSave() {
    if (saving || dirtyCount === 0) return;
    setSaving(true);
    try {
      await patchEntity(jobId, entityId, dirty);
      setToast({ kind: "ok", msg: `Saved (${dirtyCount} field${dirtyCount === 1 ? "" : "s"})` });
      await fetchDatasheet(); // refresh so EDITED badges + values reflect server
      onSaved?.();
    } catch (e) {
      setToast({ kind: "error", msg: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="br-empty" style={{ padding: 24 }}>Loading datasheet…</div>;
  }
  if (legacy) {
    return (
      <div className="br-empty" style={{ padding: 24 }}>
        No editable datasheet for this job — most likely a legacy job processed
        before the editable-entities feature shipped. Re-run the job to
        regenerate <code>canonical.json</code>.
      </div>
    );
  }
  if (error) {
    return (
      <div className="br-empty" style={{ padding: 24, color: "var(--error, #dc2626)" }}>
        {error}
        <div style={{ marginTop: 12 }}>
          <button className="br-btn small" onClick={() => void fetchDatasheet()}>Retry</button>
        </div>
      </div>
    );
  }
  if (!resp) return null;

  return (
    <div className="ds-panel" data-testid="datasheet-panel">
      {/* Sticky save bar — the panel can be long, so keep Save reachable. */}
      <div
        className="ds-panel-savebar"
        style={{
          position: "sticky",
          top: 0,
          zIndex: 2,
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 12px",
          background: "var(--bg-elev, #15151c)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <span style={{ fontSize: 11, color: "var(--fg-3)" }}>
          {resp.type_label} · {resp.sections.reduce((n, s) => n + s.fields.length, 0)} fields
        </span>
        <div style={{ flex: 1 }} />
        {toast && (
          <span
            style={{
              fontSize: 11,
              color: toast.kind === "ok" ? "var(--ok, #10b981)" : "var(--error, #dc2626)",
            }}
          >
            {toast.msg}
          </span>
        )}
        <button
          className={`br-btn small${dirtyCount > 0 ? " primary" : ""}`}
          onClick={() => void onSave()}
          disabled={saving || dirtyCount === 0}
          title={dirtyCount === 0 ? "No changes to save" : `Save ${dirtyCount} change(s)`}
        >
          <Save size={12} strokeWidth={1.6} />
          <span>{saving ? "Saving…" : dirtyCount > 0 ? `Save (${dirtyCount})` : "Saved"}</span>
        </button>
      </div>

      <SectionedDatasheet
        response={resp}
        editValues={editValues}
        unlocked={unlocked}
        onChange={update}
        onUnlock={(k) => setUnlocked((u) => ({ ...u, [k]: true }))}
      />
    </div>
  );
}
