import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  ChevronDown,
  Download,
  Info,
  LayoutGrid,
  Lock,
  Pencil,
  RotateCcw,
  ScanSearch,
  X,
} from "lucide-react";
import DocTypeIcon from "./DocTypeIcon";
import { DOC_TYPES, type DocTypeKey } from "./schemas";
import {
  HttpError,
  createEntity,
  getEntities,
  patchEntity,
  type EntitiesResponse,
  type EntityColumn,
  type EntityFieldValue,
  type EntityRow,
} from "../api";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Job ID from the parent route — drives all `/api/v1/jobs/{jobId}/entities` calls. */
  jobId: number;
  /** Entity UUID surfaced via PidCanvas's `onSelect(entity_id)` (post-D1.5).
   *  Null when the canvas hasn't selected anything canonical yet (e.g. user
   *  clicked a prototype demo element on a job without canonical.json). */
  entityId: string | null;
  /** Canonical entity_class for the selected entity ("valve" | "instrument" |
   *  "equipment"). Drives the drawer's initial deliverable-type so a clicked
   *  valve opens as Valve List rather than the previous always-Instrument-Index
   *  default — which surfaced as a phantom "Entity not found" because a valve
   *  UUID isn't in the instrument_index filter. Undefined → fall back to the
   *  prior default. */
  entityClass?: string;
  /** Optional fallback labels for the drawer head when the API hasn't loaded
   *  yet — keeps the header from flashing empty during the GET. */
  fallbackTag?: string;
  fallbackType?: string;
  onBulkReview?: () => void;
  totalCount?: number;
}

/** deliverable_type → DocTypeKey inversion for auto-discovery docType switch. */

/** 4 of 10 doc-types map to a real backend deliverable_type. The other 6 are
 *  "Coming soon" — visible in the dropdown so the design intent is preserved,
 *  but disabled (no generator wired). Keep this mapping in sync with
 *  `webapp/routers/entities.py:DELIVERABLE_ENTITY_CLASS`. */
const DOC_TYPE_TO_DELIVERABLE: Partial<Record<DocTypeKey, string>> = {
  index: "instrument_index",
  datasheet: "datasheet",
  valves: "valve_list",
  equip: "equipment_list",
};

/** Heuristic: a field path is "P&ID-extracted" if the canonical had a value
 *  for it before any user edits. The badge cue mirrors what the legacy
 *  mocked drawer showed via `field.extracted`. */
function isPidSourced(fv: EntityFieldValue | undefined): boolean {
  return !!fv && fv.source === "pid";
}

/** Render any JSON-shaped value to a string the user can edit in a text
 *  input. Numbers + strings pass through; null/undefined become empty. We
 *  don't try to round-trip booleans / nested objects through the input —
 *  the schema's editable fields are all scalar today, and the backend
 *  PATCH validates field paths so a stray object can't sneak in. */
function valueToString(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  // Objects / arrays — show JSON so editing is at least visible (rare path).
  try {
    return JSON.stringify(v);
  } catch {
    return "";
  }
}

/** Parse a user-entered string back to a canonical-compatible value. We try
 *  number coercion only when the original value was a number (avoids
 *  silently turning a serial like "0001" into the number 1). */
function stringToValue(s: string, originalType: string): unknown {
  if (s === "") return null;
  if (originalType === "number") {
    const n = Number(s);
    if (!Number.isNaN(n)) return n;
  }
  return s;
}

export default function DatasheetDrawer({
  open,
  onClose,
  jobId,
  entityId,
  entityClass: _entityClass,
  fallbackTag,
  fallbackType,
  onBulkReview,
  totalCount = 0,
}: Props) {
  // Default to Instrument Index. The drawer no longer auto-switches docType
  // based on entity_class — auto-discovery in fetchEntity finds the entity
  // wherever it lives and only auto-switches when the entity genuinely isn't
  // in the currently selected deliverable.
  const [docType, setDocType] = useState<DocTypeKey>("index");
  const [showDocPicker, setShowDocPicker] = useState(false);

  // When the user explicitly picks a deliverable type from the dropdown, flag
  // it so fetchEntity won't immediately override their choice via auto-discovery.
  // Reset on entityId change (new element selected → allow auto-discovery again).
  const skipAutoDiscoveryRef = useRef(false);
  useEffect(() => {
    skipAutoDiscoveryRef.current = false;
  }, [entityId]);

  // Backend response + drift between original (pre-edit snapshot) and the
  // editable working copy. `originalEntity` powers the diff that drives Save
  // Draft + the per-field Reset button.
  const [resp, setResp] = useState<EntitiesResponse | null>(null);
  const [originalEntity, setOriginalEntity] = useState<EntityRow | null>(null);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [unlocked, setUnlocked] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  // Two distinct empty states, formerly conflated under `notFound`:
  //   * notFound       → API returned 200 + a real entity list, but the current
  //                       `entityId` isn't in it (wrong deliverable type, click
  //                       on a non-canonical detection, or the prototype-tag
  //                       default before any real selection).
  //   * legacyJobNoCanonical → API returned 404 (`canonical.json` missing).
  //                       The whole job has no editable entities.
  // Different copy for each so users aren't told a job is legacy when it isn't.
  const [notFound, setNotFound] = useState(false);
  const [legacyJobNoCanonical, setLegacyJobNoCanonical] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ kind: "ok" | "error"; msg: string } | null>(null);

  // Avoid stale state-setters when the user spam-switches docType or entity.
  const reqIdRef = useRef(0);

  const deliverableType = docType ? DOC_TYPE_TO_DELIVERABLE[docType] : undefined;
  const isDeliverableSupported = !!deliverableType;

  // Discovery order: try the current deliverable first, then the others.
  // This handles the common mismatch where the user had switched to "Instrument
  // Datasheet" but then clicks a valve — auto-discovery finds it in valve_list
  // and flips docType automatically so the user never sees "entity not found".
  const DISCOVERY_ORDER = ["valve_list", "instrument_index", "datasheet", "equipment_list"];

  const fetchEntity = useCallback(async () => {
    if (!entityId || !deliverableType || !open) return;
    const myReq = ++reqIdRef.current;
    setLoading(true);
    setNotFound(false);
    setLegacyJobNoCanonical(false);
    setFetchError(null);
    try {
      // Phase 1: fetch from the current deliverable type.
      const r = await getEntities(jobId, deliverableType);
      if (myReq !== reqIdRef.current) return;

      // Try UUID match first, then tag fallback (handles UUID drift between
      // YOLO detection IDs and canonical pipeline_emitter UUIDs).
      let match: EntityRow | null =
        r.entities.find((e) => e.entity_id === entityId) ||
        (fallbackTag ? r.entities.find((e) => e.tag === fallbackTag) || null : null) ||
        null;
      let activeResp = r;

      // Phase 2: auto-discover across other deliverable types so clicking any
      // element (valve / instrument / equipment) always surfaces its data even
      // when the user has a mismatched deliverable type open.
      // Skipped when the user explicitly chose a type from the dropdown.
      if (!match && !skipAutoDiscoveryRef.current) {
        const others = DISCOVERY_ORDER.filter((t) => t !== deliverableType);
        for (const t of others) {
          try {
            const other = await getEntities(jobId, t);
            if (myReq !== reqIdRef.current) return;
            const found =
              other.entities.find((e) => e.entity_id === entityId) ||
              (fallbackTag ? other.entities.find((e) => e.tag === fallbackTag) || null : null) ||
              null;
            if (found) {
              match = found;
              activeResp = other;
              // Flip docType so the header + dropdown reflect the real deliverable.
              const newDocType = (
                Object.entries(DOC_TYPE_TO_DELIVERABLE) as [string, string][]
              ).find(([, v]) => v === t)?.[0] as DocTypeKey | undefined;
              if (newDocType) setDocType(newDocType as DocTypeKey);
              break;
            }
          } catch {
            /* deliverable type unavailable — skip */
          }
        }
      }

      setResp(activeResp);
      setOriginalEntity(match);
      if (match) {
        const init: Record<string, string> = {};
        for (const col of activeResp.schema) {
          init[col.field] = valueToString(match.values[col.field]?.value);
        }
        setEditValues(init);
        setUnlocked({});
        setNotFound(false);
      } else {
        // Blank form: initialise every editable field to "" so the user can
        // fill in data manually and create the entity via the POST endpoint.
        const init: Record<string, string> = {};
        for (const col of activeResp.schema) {
          init[col.field] = "";
        }
        setEditValues(init);
        setNotFound(true);
      }
    } catch (e) {
      if (myReq !== reqIdRef.current) return;
      const msg = e instanceof Error ? e.message : "Failed to load entity";
      // 404 from the list endpoint = job has no canonical.json (legacy job
      // pre-2026-05-28). Distinct from "entity not in canonical" so the UX
      // can tell the user to re-run the job, not to pick a different bbox.
      // Other errors keep the drawer mounted so the user can retry.
      if (e instanceof HttpError && e.status === 404) {
        setLegacyJobNoCanonical(true);
      } else {
        setFetchError(msg);
      }
    } finally {
      if (myReq === reqIdRef.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, entityId, deliverableType, open, fallbackTag]);

  useEffect(() => {
    if (open) void fetchEntity();
  }, [fetchEntity, open]);

  // Esc to close, same UX as before.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Auto-clear toast after 2.5s so it doesn't linger across saves.
  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 2500);
    return () => window.clearTimeout(id);
  }, [toast]);

  // Build the diff (dirty fields) — only editable fields whose serialized
  // value differs from the original. Read-only fields are filtered out
  // upstream by the schema's `editable` flag.
  const dirtyFields = useMemo(() => {
    if (!resp) return {};
    const out: Record<string, unknown> = {};
    for (const col of resp.schema) {
      if (!col.editable) continue;
      const cur = editValues[col.field] ?? "";
      if (!originalEntity) {
        // New entity mode: every non-empty field is "dirty" (to be created).
        if (cur.trim()) out[col.field] = cur;
      } else {
        const orig = originalEntity.values[col.field]?.value;
        const origStr = valueToString(orig);
        if (cur !== origStr) {
          const origType = typeof orig === "number" ? "number" : "string";
          out[col.field] = stringToValue(cur, origType);
        }
      }
    }
    return out;
  }, [resp, originalEntity, editValues]);

  const dirtyCount = Object.keys(dirtyFields).length;

  if (!open) return null;

  const currentDoc = DOC_TYPES.find((d) => d.key === docType) || DOC_TYPES[0];
  const headerTag = originalEntity?.tag ?? fallbackTag ?? entityId ?? "—";
  const headerType = originalEntity?.sub_class ?? fallbackType ?? "Entity";

  // For the progress bar: filled = non-empty values across editable columns.
  // We count from `editValues` (the working copy) so the count reflects what
  // the user is actually staging, not the persisted state.
  const editableCols = resp?.schema.filter((c) => c.editable) ?? [];
  const filled = editableCols.filter(
    (c) => (editValues[c.field] ?? "").trim() !== "",
  ).length;
  const totalFields = editableCols.length;
  const completion = totalFields === 0 ? 0 : Math.round((filled / totalFields) * 100);

  function update(key: string, val: string) {
    setEditValues((v) => ({ ...v, [key]: val }));
  }

  /** Reset a single field to its value at drawer-open. For overrides that
   *  predate this session there's no DELETE endpoint, so true revert-to-pid
   *  isn't possible — the button is only shown for fields the user edited
   *  during this session OR that were `is_override` at open and have a
   *  prior pid value we can re-PATCH. */
  async function resetField(fieldPath: string) {
    if (!originalEntity) return;
    const origVal = originalEntity.values[fieldPath]?.value;
    update(fieldPath, valueToString(origVal));
    // No PATCH here — Save Draft will re-PATCH iff something else is dirty.
    // For pre-existing overrides this resets the *form*, not the backend;
    // see open question in commit body.
  }

  async function onSaveDraft() {
    if (!entityId || saving) return;
    if (dirtyCount === 0) {
      // No-op save: still close-friendly behavior, but be explicit.
      setToast({ kind: "ok", msg: "Nothing to save" });
      return;
    }
    setSaving(true);
    try {
      await patchEntity(jobId, entityId, dirtyFields);
      setToast({ kind: "ok", msg: `Saved (${dirtyCount} field${dirtyCount === 1 ? "" : "s"})` });
      // Refresh from server so `is_override` flips on the just-saved fields
      // and we have a fresh snapshot for the next diff.
      await fetchEntity();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Save failed";
      setToast({ kind: "error", msg });
    } finally {
      setSaving(false);
    }
  }

  async function onCreateDraft() {
    if (saving || dirtyCount === 0) {
      setToast({ kind: "error", msg: "Fill in at least one field before creating" });
      return;
    }
    setSaving(true);
    try {
      const entityClassForCreate =
        deliverableType === "valve_list" ? "valve"
        : deliverableType === "equipment_list" ? "equipment"
        : "instrument";
      const result = await createEntity(jobId, {
        entity_class: entityClassForCreate,
        fields: dirtyFields,
      });
      setToast({ kind: "ok", msg: `Created — ${dirtyCount} field${dirtyCount === 1 ? "" : "s"} saved` });
      // Refetch using the new UUID so the drawer flips from blank form to full edit mode.
      setNotFound(false);
      // Trigger re-fetch by temporarily bumping the request counter — the
      // parent will pass the new entity_id on next render if it picks up the
      // return value, but for now close the drawer so the user can reselect.
      void result; // entity_id available here for future auto-select
      await fetchEntity();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Create failed";
      setToast({ kind: "error", msg });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="ds-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside className="ds-drawer" data-comment-anchor="datasheet-drawer">
        <header className="ds-head">
          <div className="ds-head-top">
            <button className="ds-doc-picker" onClick={() => setShowDocPicker((v) => !v)}>
              <DocTypeIcon name={currentDoc.icon} size={14} />
              <span>{currentDoc.name}</span>
              <ChevronDown size={12} strokeWidth={1.6} />
            </button>
            {showDocPicker && (
              <div className="ds-doc-menu" onMouseLeave={() => setShowDocPicker(false)}>
                {DOC_TYPES.map((d) => {
                  const supported = !!DOC_TYPE_TO_DELIVERABLE[d.key];
                  const active = d.key === docType;
                  return (
                    <button
                      key={d.key}
                      className={`${active ? "active" : ""} ${supported ? "" : "disabled"}`}
                      disabled={!supported}
                      title={supported ? d.name : "Coming soon — no backend generator yet"}
                      onClick={() => {
                        if (!supported) return;
                        skipAutoDiscoveryRef.current = true; // user chose explicitly — don't auto-switch away
                        setDocType(d.key);
                        setShowDocPicker(false);
                      }}
                      style={
                        supported
                          ? undefined
                          : { opacity: 0.45, cursor: "not-allowed" }
                      }
                    >
                      <DocTypeIcon name={d.icon} size={13} />
                      <span>{d.name}</span>
                      {!supported && (
                        <span
                          className="overline"
                          style={{ fontSize: 9, color: "var(--fg-3)", marginLeft: 8 }}
                        >
                          Coming soon
                        </span>
                      )}
                      {active && <Check size={13} strokeWidth={1.6} />}
                    </button>
                  );
                })}
              </div>
            )}
            <div style={{ flex: 1 }}></div>
            {onBulkReview && (
              <button
                className="ds-bulk-btn"
                onClick={onBulkReview}
                title="Review all instruments in workbench"
              >
                <LayoutGrid size={12} strokeWidth={1.6} />
                <span>Bulk Review</span>
                <span className="num">{totalCount}</span>
              </button>
            )}
            <button className="ds-close" onClick={onClose} title="Close datasheet">
              <X size={16} strokeWidth={1.6} />
            </button>
          </div>
          <div className="ds-head-bot">
            <div className="ds-title-wrap">
              <span className="overline">{headerType}</span>
              <h2>{headerTag}</h2>
            </div>
            <div className="ds-progress">
              <div className="ds-progress-meta">
                <span>
                  {filled} of {totalFields} fields
                </span>
                <span className="pct">{completion}%</span>
              </div>
              <div className="ds-progress-bar">
                <div className="ds-progress-fill" style={{ width: `${completion}%` }}></div>
              </div>
            </div>
          </div>
        </header>

        <div className="ds-body">
          {!isDeliverableSupported && (
            <div className="ds-empty-state" style={{ padding: 32, textAlign: "center" }}>
              <p style={{ fontSize: 14, color: "var(--fg-2)" }}>
                <strong>{currentDoc.name}</strong> isn't wired to a backend generator yet.
              </p>
              <p style={{ fontSize: 12, color: "var(--fg-3)", marginTop: 8 }}>
                Pick Instrument Index, Instrument Datasheet, Valve List, or Equipment List
                to edit a real entity.
              </p>
            </div>
          )}

          {isDeliverableSupported && loading && (
            <div className="ds-empty-state" style={{ padding: 32, textAlign: "center" }}>
              <p style={{ fontSize: 13, color: "var(--fg-3)" }}>Loading entity…</p>
            </div>
          )}

          {isDeliverableSupported && !loading && fetchError && (
            <div className="ds-empty-state" style={{ padding: 32, textAlign: "center" }}>
              <p style={{ fontSize: 13, color: "var(--error, #dc2626)" }}>
                Failed to load: {fetchError}
              </p>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => void fetchEntity()}
                style={{ marginTop: 12 }}
              >
                Retry
              </button>
            </div>
          )}

          {isDeliverableSupported && !loading && !fetchError && legacyJobNoCanonical && (
            <div className="ds-empty-state" style={{ padding: 32, textAlign: "center" }}>
              <p style={{ fontSize: 14, color: "var(--fg-2)" }}>
                <strong>No editable entities for this job.</strong>
              </p>
              <p style={{ fontSize: 12, color: "var(--fg-3)", marginTop: 8 }}>
                Most likely this is a legacy job processed before the
                editable-entities feature shipped (2026-05-28). Re-run the job
                from the dashboard to regenerate <code>canonical.json</code>,
                or open a newer job.
              </p>
              <button className="btn btn-secondary btn-sm" onClick={onClose} style={{ marginTop: 16 }}>
                Close
              </button>
            </div>
          )}

          {isDeliverableSupported && !loading && !fetchError && notFound && !legacyJobNoCanonical && resp && (
            <EntityFieldList
              schema={resp.schema}
              entity={null}
              editValues={editValues}
              unlocked={unlocked}
              onChange={update}
              onUnlock={(k) => setUnlocked((u) => ({ ...u, [k]: true }))}
              onReset={resetField}
            />
          )}

          {isDeliverableSupported && !loading && !fetchError && !notFound && resp && originalEntity && (
            <EntityFieldList
              schema={resp.schema}
              entity={originalEntity}
              editValues={editValues}
              unlocked={unlocked}
              onChange={update}
              onUnlock={(k) => setUnlocked((u) => ({ ...u, [k]: true }))}
              onReset={resetField}
            />
          )}
        </div>

        <footer className="ds-foot">
          <div className="ds-foot-info">
            <Info size={13} strokeWidth={1.6} />
            <span>
              {notFound
                ? `${filled} / ${totalFields} fields filled`
                : dirtyCount === 0
                  ? `${totalFields - filled} fields remaining`
                  : `${dirtyCount} unsaved change${dirtyCount === 1 ? "" : "s"}`}
            </span>
          </div>
          {toast && (
            <div
              className="ds-toast"
              style={{
                fontSize: 12,
                padding: "4px 10px",
                borderRadius: 6,
                color: toast.kind === "ok" ? "var(--ok, #10b981)" : "var(--error, #dc2626)",
                background:
                  toast.kind === "ok"
                    ? "rgba(16,185,129,0.08)"
                    : "rgba(220,38,38,0.08)",
              }}
            >
              {toast.msg}
            </div>
          )}
          <div style={{ flex: 1 }}></div>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => notFound ? void onCreateDraft() : void onSaveDraft()}
            disabled={saving || dirtyCount === 0}
            title={
              notFound
                ? dirtyCount === 0 ? "Fill in fields to create" : `Create entry with ${dirtyCount} field(s)`
                : dirtyCount === 0 ? "No changes to save" : `Save ${dirtyCount} change(s)`
            }
          >
            {saving ? (notFound ? "Creating…" : "Saving…") : (notFound ? "Create Entry" : "Save Draft")}
          </button>
          <button className="btn btn-primary btn-sm" disabled>
            <Download size={12} strokeWidth={1.6} /> Export
          </button>
        </footer>
      </aside>
    </div>
  );
}

/** Render the editable form for one entity. Read-only columns appear visibly
 *  disabled at the top; editable columns follow. Per-field "Reset to P&ID"
 *  shows only for fields marked `is_override` at fetch time. */
function EntityFieldList({
  schema,
  entity,
  editValues,
  unlocked,
  onChange,
  onUnlock,
  onReset,
}: {
  schema: EntityColumn[];
  entity: EntityRow | null;
  editValues: Record<string, string>;
  unlocked: Record<string, boolean>;
  onChange: (k: string, v: string) => void;
  onUnlock: (k: string) => void;
  onReset: (k: string) => void;
}) {
  // Show read-only fields first so the user sees the entity's "identity" before
  // they start editing. Editable fields follow in template order.
  const readOnly = schema.filter((c) => !c.editable);
  const editable = schema.filter((c) => c.editable);

  return (
    <div className="ds-fields-flat" style={{ padding: "12px 16px" }}>
      {entity && readOnly.length > 0 && (
        <section className="ds-section open" style={{ marginBottom: 16 }}>
          <div
            className="ds-section-head"
            style={{ pointerEvents: "none", padding: "8px 0", display: "flex", alignItems: "center", gap: 8 }}
          >
            <span className="num">01</span>
            <h3 style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>Identity (read-only)</h3>
            <span className="ds-section-meta">{readOnly.length}</span>
          </div>
          <div
            className="ds-fields"
            style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}
          >
            {readOnly.map((col) => (
              <ReadOnlyCell key={col.field} col={col} fv={entity?.values[col.field]} />
            ))}
          </div>
        </section>
      )}

      <section className="ds-section open">
        <div
          className="ds-section-head"
          style={{ pointerEvents: "none", padding: "8px 0", display: "flex", alignItems: "center", gap: 8 }}
        >
          <span className="num">{readOnly.length > 0 ? "02" : "01"}</span>
          <h3 style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>Editable fields</h3>
          <span className="ds-section-meta">{editable.length}</span>
        </div>
        <div
          className="ds-fields"
          style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}
        >
          {editable.map((col) => {
            const fv = entity?.values[col.field];
            const isOverridden = !!fv?.is_override;
            const pidBadge = isPidSourced(fv) && !isOverridden;
            const locked = pidBadge && !unlocked[col.field];
            return (
              <EditableCell
                key={col.field}
                col={col}
                fv={fv}
                value={editValues[col.field] ?? ""}
                locked={locked}
                isOverridden={isOverridden}
                showPidBadge={pidBadge}
                onChange={(v) => onChange(col.field, v)}
                onUnlock={() => onUnlock(col.field)}
                onReset={() => onReset(col.field)}
              />
            );
          })}
        </div>
      </section>
    </div>
  );
}

function ReadOnlyCell({ col, fv }: { col: EntityColumn; fv: EntityFieldValue | undefined }) {
  const valueStr = valueToString(fv?.value);
  return (
    <div className="ds-field span-sm locked">
      <label className="ds-label">
        <span>{col.header}</span>
        <span
          className="ds-source"
          style={{
            color: "var(--fg-3)",
            background: "transparent",
            border: "1px solid var(--border)",
          }}
          title="Read-only — set by the pipeline, cannot be edited via the API"
        >
          <Lock size={10} strokeWidth={1.6} /> READ-ONLY
        </span>
      </label>
      <div className="ds-control">
        <div className="ds-locked" style={{ opacity: 0.7 }}>
          <span className="ds-value">{valueStr || <em>— missing —</em>}</span>
        </div>
      </div>
    </div>
  );
}

function EditableCell({
  col,
  fv,
  value,
  locked,
  isOverridden,
  showPidBadge,
  onChange,
  onUnlock,
  onReset,
}: {
  col: EntityColumn;
  fv: EntityFieldValue | undefined;
  value: string;
  locked: boolean;
  isOverridden: boolean;
  showPidBadge: boolean;
  onChange: (v: string) => void;
  onUnlock: () => void;
  onReset: () => void;
}) {
  const empty = !value || value === "";
  // Width heuristic: header length → field span. Backend templates don't
  // carry widths today; rather than guess per-field we let the 4-col grid
  // give every field equal width (span-sm). Long headers ("Service
  // Description", "Pneumatic Actuator ") still fit because the input wraps.
  return (
    <div className={`ds-field span-sm ${showPidBadge ? "extracted" : ""} ${locked ? "locked" : ""}`}>
      <label className="ds-label">
        <span>{col.header}</span>
        {showPidBadge && (
          <span className="ds-source" title="Value came from the P&ID pipeline (not user-edited)">
            <ScanSearch size={10} strokeWidth={1.6} /> P&amp;ID
          </span>
        )}
        {isOverridden && (
          <span
            className="ds-source"
            style={{
              color: "var(--qong-magenta, #FF4DA8)",
              background: "rgba(255,77,168,0.08)",
              border: "1px solid rgba(255,77,168,0.28)",
            }}
            title="This value was edited from its original P&ID-extracted value"
          >
            EDITED
          </span>
        )}
        {fv?.source === "manual" && !isOverridden && (
          <span className="ds-source" style={{
            color: "var(--fg-3)",
            background: "transparent",
            border: "1px solid var(--border)",
          }}>
            MANUAL
          </span>
        )}
      </label>
      <div className="ds-control">
        {locked ? (
          <div className="ds-locked">
            <span className="ds-value">{value || <em>— missing —</em>}</span>
            <button
              type="button"
              className="ds-unlock"
              onClick={onUnlock}
              title="Edit this P&ID-extracted value manually"
            >
              <Pencil size={11} strokeWidth={1.6} />
            </button>
          </div>
        ) : (
          <input
            className="ds-input"
            type="text"
            placeholder={showPidBadge ? "Not detected — enter manually" : "Add value…"}
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
        )}
        {empty && !locked && !showPidBadge && <span className="ds-hint">Manual</span>}
        {isOverridden && !locked && (
          <button
            type="button"
            onClick={onReset}
            title="Reset this field to the P&ID-extracted value"
            style={{
              position: "absolute",
              right: 8,
              top: -28,
              background: "transparent",
              border: "1px solid var(--border)",
              borderRadius: 6,
              padding: "2px 6px",
              fontSize: 10,
              color: "var(--fg-3)",
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: 3,
            }}
          >
            <RotateCcw size={10} strokeWidth={1.6} /> Reset
          </button>
        )}
      </div>
    </div>
  );
}
