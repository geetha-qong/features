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
import { FileDown, Save } from "lucide-react";
import {
  HttpError,
  getEntityDatasheet,
  patchEntity,
  type DatasheetSectionOut,
  type EntityDatasheetResponse,
} from "../api";
import {
  SectionedDatasheet,
  computeDatasheetDirty,
  seedDatasheetEditValues,
} from "./sectioned";

// ── Instrument spec auto-fill ─────────────────────────────────────────────────
const SPEC_API_URL = "/api/v1/jobs/instrument-spec";

/** API response is a free-form dict — use Record for dynamic key lookup. */
type InstrumentSpecResponse = Record<string, string | null | undefined>;

/** "Case Type" → "case_type", "Model No." → "model_no", "Graduation & Color" → "graduation_color" */
const _toSnakeCase = (str: string) =>
  str
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");

/** Headers where snake_case(header) doesn't match the API key directly. */
const _SPEC_OVERRIDES: Record<string, string> = {
  model_no:               "model_number",
  dial_size:              "dial_size_value",
  process_conn_size:      "connection_size",
  process_conn_type:      "connection_type",
  process_conn_location:  "connection_position",
  graduation_color:       "graduation_color",
  nom_accuracy_grade:     "nom_accuracy_grade",
  ambient_temp_min:       "ambient_temp_min",
  ambient_temp_max:       "ambient_temp_max",
  instrument_range_min:   "instrument_range_min",
  instrument_range_max:   "instrument_range_max",
};

/** Unit fields to append to value (keyed by snake_case header). */
const _SPEC_UNIT_MAP: Record<string, string> = {
  ambient_temp_min:    "ambient_temp_unit",
  ambient_temp_max:    "ambient_temp_unit",
  instrument_range_min: "instrument_range_unit",
  instrument_range_max: "instrument_range_unit",
  dial_size:           "dial_size_unit",
};

/** Resolve a single field header → value string from the spec API response. */
function _getSpecValue(header: string, apiData: InstrumentSpecResponse): string {
  const snakeHeader = _toSnakeCase(header);
  const mappedKey = _SPEC_OVERRIDES[snakeHeader] ?? snakeHeader;
  const rawVal = (apiData[mappedKey] ?? "").trim();
  if (!rawVal) return "";
  const unitKey = _SPEC_UNIT_MAP[snakeHeader];
  if (unitKey) {
    const unit = (apiData[unitKey] ?? "").trim();
    return unit ? `${rawVal} ${unit}` : rawVal;
  }
  return rawVal;
}

/** Apply spec values to editable fields → updated editValues. */
function _applySpecToEditValues(
  spec: InstrumentSpecResponse,
  sections: DatasheetSectionOut[],
  base: Record<string, string>,
): Record<string, string> {
  const updates: Record<string, string> = {};
  for (const sec of sections) {
    for (const f of sec.fields) {
      if (!f.editable) continue;
      const val = _getSpecValue(f.header, spec);
      if (val !== "") updates[f.field] = val;
    }
  }
  return { ...base, ...updates };
}

/** Inject spec values into vendor (read-only) field values in the response so
 *  ReadOnlyCell renders them. Editable fields are handled via editValues only. */
function _injectSpecIntoResp(
  spec: InstrumentSpecResponse,
  ds: EntityDatasheetResponse,
): EntityDatasheetResponse {
  return {
    ...ds,
    sections: ds.sections.map((sec) => ({
      ...sec,
      fields: sec.fields.map((f) => {
        if (f.editable) return f;
        const val = _getSpecValue(f.header, spec);
        return val !== "" ? { ...f, value: val } : f;
      }),
    })),
  };
}
// ─────────────────────────────────────────────────────────────────────────────

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
      const seeded = seedDatasheetEditValues(ds);
      setEditValues(seeded);
      setUnlocked({});

      // Auto-fill fields from the instrument spec API using the instrument type
      // (sub_class, e.g. "PG"). Errors are silently swallowed — the user can
      // always fill fields manually if the spec API is unavailable.
      const instType = ds.tag?.split('-')[1];
      console.log("[spec] tag:", ds.tag, "→ instType:", instType);
      if (instType) {
        try {
          const specRes = await fetch(SPEC_API_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ instType }),
          });
          console.log("[spec] API status:", specRes.status, specRes.ok);
          if (specRes.ok && myReq === reqIdRef.current) {
            const rawResp = await specRes.json() as { success: boolean; instType: string; data: InstrumentSpecResponse };
            const spec = rawResp.data ?? rawResp;
            console.log("[spec] data keys:", Object.keys(spec));
            console.log("[spec] data values:", JSON.stringify(spec));
            // Log each field and what value would be assigned
            for (const sec of ds.sections) {
              for (const f of sec.fields) {
                const val = _getSpecValue(f.header, spec);
                if (val) console.log(`[spec] match: "${f.header}" → snake:"${_toSnakeCase(f.header)}" → val:"${val}" editable:${f.editable}`);
              }
            }
            setResp(_injectSpecIntoResp(spec, ds));
            const appliedValues = _applySpecToEditValues(spec, ds.sections, seeded);
            const specKeys = Object.keys(appliedValues).filter(k => !seeded[k] || seeded[k] !== appliedValues[k]);
            console.log("[spec] fields updated:", specKeys.length, specKeys);
            setEditValues(prev => ({ ...prev, ...appliedValues }));
          }
        } catch (err) {
          console.error("[spec] API error:", err);
        }
      }
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

  async function exportToExcel() {
    if (!resp) return;
    const url = `/api/v1/jobs/${jobId}/entities/${encodeURIComponent(entityId)}/datasheet/export`;
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) {
      setToast({ kind: "error", msg: "Export failed" });
      return;
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${resp.tag ?? "datasheet"}_datasheet.xlsx`;
    a.click();
    URL.revokeObjectURL(a.href);
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
          className="br-btn small"
          onClick={() => void exportToExcel()}
          title="Export datasheet to Excel"
        >
          <FileDown size={12} strokeWidth={1.6} />
          <span>Export</span>
        </button>
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
