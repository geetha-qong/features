import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  ChevronDown,
  ChevronUp,
  Download,
  Filter,
  PanelRight,
  RotateCcw,
  Search,
  X,
} from "lucide-react";
import DocTypeIcon from "../datasheet/DocTypeIcon";
import {
  HttpError,
  getEntities,
  patchEntity,
  type EntitiesResponse,
  type EntityColumn,
  type EntityFieldValue,
  type EntityRow,
} from "../api";
import { DELIVERABLES } from "./deliverables";

/** Maps the 10 design-time deliverable keys onto the 4 backend deliverable_type
 *  slugs. Kept verbatim with `DatasheetDrawer.tsx:DOC_TYPE_TO_DELIVERABLE` —
 *  if/when we wire more deliverables, update both. The remaining 6 keys render
 *  as disabled "Coming soon" tabs so the UX intent stays visible. */
const DELIVERABLE_KEY_TO_TYPE: Record<string, string | undefined> = {
  index: "instrument_index",
  datasheet: "datasheet",
  valves: "valve_list",
  equip: "equipment_list",
  // 6 unsupported (no backend generator yet)
  io: undefined,
  narrative: undefined,
  cande: undefined,
  lines: undefined,
  loop: undefined,
  tags: undefined,
};

interface Props {
  /** Job ID — drives every `/api/v1/jobs/{jobId}/entities` call. */
  jobId: number;
  /** Project name for the breadcrumb only. */
  projectName: string;
  /** Optional deliverable_type ("valve_list", "datasheet", …) the parent wants
   *  the workbench to open on. Falls back to the first supported tab. */
  initialDeliverableType?: string;
  onBack: () => void;
  /** Click "Open in Studio" on a row → close workbench, surface the drawer
   *  upstream by selecting the entity. The parent (Studio.tsx) decides
   *  what to do — currently flips `mode` back to "studio" and opens the
   *  DatasheetDrawer with the entity_id. */
  onOpenEntity: (entityId: string) => void;
}

/** Stringify any canonical-ish JSON value for the cell input. Mirrors
 *  DatasheetDrawer's `valueToString` so the two surfaces format identically. */
function valueToString(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return "";
  }
}

/** Coerce a user-edited string back to the original primitive type. Numeric
 *  coercion is opt-in (only when original was a number) so serials like
 *  "0001" don't get silently turned into 1. */
function stringToValue(s: string, original: unknown): unknown {
  if (s === "") return null;
  if (typeof original === "number") {
    const n = Number(s);
    if (!Number.isNaN(n)) return n;
  }
  return s;
}

/** Identity columns rendered sticky-left, regardless of template schema. */
const IDENTITY_COLS: { field: keyof EntityRow; header: string }[] = [
  { field: "tag", header: "Tag" },
  { field: "sub_class", header: "Sub-class" },
  { field: "pid_number", header: "P&ID" },
  { field: "sheet_number", header: "Sheet" },
];

export default function BulkReviewScreen({
  jobId,
  projectName,
  initialDeliverableType,
  onBack,
  onOpenEntity,
}: Props) {
  // Map the incoming deliverable_type back to a UI key so the tab highlights.
  const initialKey = useMemo<string>(() => {
    if (initialDeliverableType) {
      for (const [k, v] of Object.entries(DELIVERABLE_KEY_TO_TYPE)) {
        if (v === initialDeliverableType) return k;
      }
    }
    // Fall back to the first phase-1 supported tab (datasheet).
    return "datasheet";
  }, [initialDeliverableType]);

  const [activeKey, setActiveKey] = useState<string>(initialKey);
  const activeType = DELIVERABLE_KEY_TO_TYPE[activeKey];

  const [resp, setResp] = useState<EntitiesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  // Per-cell edit state — keyed `${entityId}:${field}` so a partially-edited
  // cell survives row-selection changes (until the user navigates away or
  // commits). null entry means "not editing"; string means "editing with this
  // working value".
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [cellError, setCellError] = useState<Record<string, string>>({});
  // Cells currently in-flight to PATCH — disables the input + shows a save hint.
  const [saving, setSaving] = useState<Record<string, boolean>>({});

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showDetail, setShowDetail] = useState(true);

  // Filter: typed value (immediate) + debounced value (the one we actually
  // filter on). Debounce reduces re-render churn on big tables.
  const [filterText, setFilterText] = useState("");
  const [debouncedFilter, setDebouncedFilter] = useState("");
  const [showOnlyEdited, setShowOnlyEdited] = useState(false);

  // Guard against stale GET responses if the user spam-clicks tabs.
  const reqIdRef = useRef(0);

  const fetchRows = useCallback(async () => {
    if (!activeType) {
      // Unsupported deliverable — clear state, render empty panel.
      setResp(null);
      setSelectedId(null);
      setFetchError(null);
      return;
    }
    const myReq = ++reqIdRef.current;
    setLoading(true);
    setFetchError(null);
    try {
      const r = await getEntities(jobId, activeType);
      if (myReq !== reqIdRef.current) return;
      setResp(r);
      setSelectedId(r.entities[0]?.entity_id ?? null);
      // Drop stale edit state from the previous tab — different rows / schema.
      setEditing({});
      setCellError({});
      setSaving({});
    } catch (e) {
      if (myReq !== reqIdRef.current) return;
      if (e instanceof HttpError && e.status === 404) {
        setFetchError("No canonical output yet — this job hasn't finished extraction.");
      } else {
        setFetchError(e instanceof Error ? e.message : "Failed to load entities");
      }
      setResp(null);
    } finally {
      if (myReq === reqIdRef.current) setLoading(false);
    }
  }, [jobId, activeType]);

  useEffect(() => {
    void fetchRows();
  }, [fetchRows]);

  // 150ms filter debounce — fast enough to feel live, slow enough that typing
  // doesn't re-filter every keystroke on a 500-row table.
  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedFilter(filterText), 150);
    return () => window.clearTimeout(id);
  }, [filterText]);

  // Esc closes detail panel; nice keyboard parity with the drawer.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && showDetail) setShowDetail(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showDetail]);

  const rows = resp?.entities ?? [];
  const schema = resp?.schema ?? [];

  // Editable columns from the template, in `order` ascending. Read-only columns
  // are dropped from the grid body — the identity columns above already cover
  // the same conceptual ground (tag, sub_class, pid_number, sheet_number).
  const editableColumns = useMemo<EntityColumn[]>(
    () => [...schema].filter((c) => c.editable).sort((a, b) => a.order - b.order),
    [schema],
  );

  // Filtered + optional "show only edited" rows. Cheap O(n*k) — fine at the
  // current scales we ship (typical jobs ≤ a few hundred entities).
  const filteredRows = useMemo(() => {
    const q = debouncedFilter.trim().toLowerCase();
    return rows.filter((r) => {
      if (q) {
        const hay = [
          r.tag ?? "",
          r.sub_class ?? "",
          r.pid_number ?? "",
          String(r.sheet_number ?? ""),
          r.entity_id,
        ]
          .join("|")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (showOnlyEdited) {
        const hasOverride = Object.values(r.values).some((v) => v.is_override);
        if (!hasOverride) return false;
      }
      return true;
    });
  }, [rows, debouncedFilter, showOnlyEdited]);

  // Keep selectedId valid when rows change (filter narrows, refresh swaps).
  useEffect(() => {
    if (selectedId && filteredRows.find((r) => r.entity_id === selectedId)) return;
    setSelectedId(filteredRows[0]?.entity_id ?? null);
  }, [filteredRows, selectedId]);

  const selectedRow = useMemo<EntityRow | null>(
    () => filteredRows.find((r) => r.entity_id === selectedId) ?? null,
    [filteredRows, selectedId],
  );

  function cellKey(entityId: string, field: string) {
    return `${entityId}:${field}`;
  }

  function beginEdit(entity: EntityRow, field: string) {
    const k = cellKey(entity.entity_id, field);
    if (editing[k] !== undefined) return; // already editing
    const cur = valueToString(entity.values[field]?.value);
    setEditing((s) => ({ ...s, [k]: cur }));
    setCellError((s) => {
      if (!(k in s)) return s;
      const next = { ...s };
      delete next[k];
      return next;
    });
  }

  function setEditingValue(entity: EntityRow, field: string, val: string) {
    const k = cellKey(entity.entity_id, field);
    setEditing((s) => ({ ...s, [k]: val }));
  }

  function cancelEdit(entity: EntityRow, field: string) {
    const k = cellKey(entity.entity_id, field);
    setEditing((s) => {
      if (!(k in s)) return s;
      const next = { ...s };
      delete next[k];
      return next;
    });
    setCellError((s) => {
      if (!(k in s)) return s;
      const next = { ...s };
      delete next[k];
      return next;
    });
  }

  async function commitEdit(entity: EntityRow, field: string) {
    const k = cellKey(entity.entity_id, field);
    const newStr = editing[k];
    if (newStr === undefined) return;
    const origVal = entity.values[field]?.value;
    const origStr = valueToString(origVal);
    if (newStr === origStr) {
      cancelEdit(entity, field);
      return;
    }
    const coerced = stringToValue(newStr, origVal);
    setSaving((s) => ({ ...s, [k]: true }));
    try {
      await patchEntity(jobId, entity.entity_id, { [field]: coerced });
      // Refresh just the active tab — keeps badges (is_override) accurate and
      // pulls in any concurrent edits from another tab. Cheap at current
      // entity counts; see open-question note on virtualization for the
      // threshold where this stops being free.
      await fetchRows();
      cancelEdit(entity, field);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Save failed";
      setCellError((s) => ({ ...s, [k]: msg }));
      // Leave the input mounted with the user's draft so they can retry / fix.
    } finally {
      setSaving((s) => {
        const next = { ...s };
        delete next[k];
        return next;
      });
    }
  }

  // Grid template: identity cols (sticky-left) · editable cols · open-action.
  const gridTemplate = useMemo(() => {
    const idCols = IDENTITY_COLS.map(() => "minmax(90px, 1fr)").join(" ");
    const editCols = editableColumns.map(() => "minmax(110px, 1.2fr)").join(" ");
    return `${idCols} ${editCols} 36px`;
  }, [editableColumns]);

  const totalCount = rows.length;
  const shownCount = filteredRows.length;

  return (
    <div className="bulk-review" data-screen-label="04 Bulk Review">
      <header className="br-top">
        <button className="br-back" onClick={onBack} title="Back to PID Studio">
          <ArrowLeft size={14} strokeWidth={1.6} />
          <span>Back to Studio</span>
        </button>
        <div className="br-divider"></div>
        <div className="br-crumbs">
          <span>{projectName}</span>
          <span className="sep">›</span>
          <span>Bulk Review</span>
          <span className="sep">›</span>
          <span className="strong">
            {DELIVERABLES.find((d) => d.key === activeKey)?.name ?? "—"}
          </span>
        </div>
        <div style={{ flex: 1 }}></div>

        <div className="br-search">
          <Search size={12} strokeWidth={1.6} />
          <input
            placeholder="Filter tag, sub-class, P&ID…"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
          />
          {filterText && (
            <button
              onClick={() => setFilterText("")}
              style={{
                background: "transparent",
                border: 0,
                color: "var(--fg-3)",
                cursor: "pointer",
                padding: 0,
                display: "inline-flex",
              }}
              title="Clear filter"
            >
              <X size={11} strokeWidth={1.6} />
            </button>
          )}
        </div>
        <button
          className={`br-btn ${showOnlyEdited ? "primary" : ""}`}
          onClick={() => setShowOnlyEdited((v) => !v)}
          title="Show only rows with overrides"
        >
          <Filter size={12} strokeWidth={1.6} />
          <span>{showOnlyEdited ? "Edited only" : "All rows"}</span>
        </button>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--fg-3)",
            padding: "0 6px",
          }}
        >
          {shownCount === totalCount
            ? `${totalCount} total`
            : `${shownCount} of ${totalCount}`}
        </span>
        <button className="br-btn primary" disabled title="Export coming soon">
          <Download size={12} strokeWidth={1.6} />
          <span>Export</span>
        </button>
        <button
          className={`br-btn icon ${showDetail ? "active" : ""}`}
          onClick={() => setShowDetail((v) => !v)}
          title={showDetail ? "Hide detail panel" : "Show detail panel"}
        >
          <PanelRight size={13} strokeWidth={1.6} />
        </button>
      </header>

      <div className={`br-body ${showDetail ? "" : "no-detail"}`}>
        <aside className="br-nav">
          <div className="br-nav-head">
            <span>Deliverables</span>
            <span className="cnt">{DELIVERABLES.length}</span>
          </div>
          {DELIVERABLES.map((d) => {
            const supported = !!DELIVERABLE_KEY_TO_TYPE[d.key];
            const isActive = d.key === activeKey;
            return (
              <button
                key={d.key}
                className={`br-doc ${isActive ? "active" : ""}`}
                disabled={!supported}
                title={
                  supported
                    ? d.name
                    : `${d.name} — Coming soon (no backend generator yet)`
                }
                onClick={() => supported && setActiveKey(d.key)}
                style={
                  supported
                    ? undefined
                    : { opacity: 0.4, cursor: "not-allowed" }
                }
              >
                <DocTypeIcon name={d.icon} size={13} />
                <span className="nm">{d.name}</span>
                {!supported ? (
                  <span
                    className="completion"
                    style={{ fontSize: 8.5, letterSpacing: "0.12em" }}
                  >
                    SOON
                  </span>
                ) : (
                  <span className="completion">
                    {/* No completion math from API yet; show entity count for
                     *  the active tab, dash for the others. */}
                    {isActive && resp ? resp.entities.length : "—"}
                  </span>
                )}
              </button>
            );
          })}
        </aside>

        <section className="br-center">
          <div className="br-center-head">
            <div>
              <span className="overline">Bulk Review · Editable Deliverable</span>
              <h2>
                {DELIVERABLES.find((d) => d.key === activeKey)?.name ?? "—"}
              </h2>
            </div>
            <div className="br-stats">
              <div className="stat">
                <strong>{totalCount}</strong>
                <span>Entities</span>
              </div>
              <div className="stat">
                <strong style={{ color: "var(--qong-magenta, #FF4DA8)" }}>
                  {rows.filter((r) =>
                    Object.values(r.values).some((v) => v.is_override),
                  ).length}
                </strong>
                <span>Edited</span>
              </div>
              <div className="stat">
                <strong>{editableColumns.length}</strong>
                <span>Editable Cols</span>
              </div>
            </div>
          </div>

          <div className="br-table-wrap">
            {loading && (
              <div className="br-empty">Loading entities…</div>
            )}
            {!loading && fetchError && (
              <div className="br-empty" style={{ color: "var(--error, #dc2626)" }}>
                {fetchError}
                <div style={{ marginTop: 12 }}>
                  <button className="br-btn small" onClick={() => void fetchRows()}>
                    Retry
                  </button>
                </div>
              </div>
            )}
            {!loading && !fetchError && !activeType && (
              <div className="br-empty">
                <strong>Coming soon.</strong> No backend generator for this
                deliverable yet.
              </div>
            )}
            {!loading && !fetchError && activeType && rows.length === 0 && (
              <div className="br-empty">
                No entities for this deliverable in job #{jobId}.
              </div>
            )}
            {!loading && !fetchError && activeType && rows.length > 0 && (
              <div className="br-table" style={{ gridTemplateColumns: gridTemplate }}>
                {/* Identity headers (sticky-left visually via column order) */}
                {IDENTITY_COLS.map((c) => (
                  <div key={`id-${c.field}`} className="br-th">
                    {c.header}
                  </div>
                ))}
                {editableColumns.map((c) => (
                  <div key={`ed-${c.field}`} className="br-th">
                    {c.header}
                  </div>
                ))}
                <div className="br-th"></div>

                {filteredRows.map((r) => {
                  const isSel = r.entity_id === selectedId;
                  return (
                    <div
                      key={r.entity_id}
                      className={`br-row ${isSel ? "selected" : ""}`}
                      style={{ display: "contents" }}
                      onClick={() => setSelectedId(r.entity_id)}
                    >
                      {/* Identity cells — read-only, sticky-left visually muted. */}
                      {IDENTITY_COLS.map((c) => {
                        const raw = r[c.field];
                        const display =
                          raw === null || raw === undefined || raw === ""
                            ? "—"
                            : String(raw);
                        const isEmpty = display === "—";
                        const cls = ["br-td"];
                        if (c.field === "tag" || c.field === "pid_number") cls.push("mono");
                        return (
                          <div
                            key={`id-${r.entity_id}-${c.field}`}
                            className={cls.join(" ")}
                            style={{
                              color: isEmpty ? "var(--fg-3)" : "var(--fg-2)",
                              fontStyle: isEmpty ? "italic" : "normal",
                            }}
                            title="Read-only — pipeline-extracted"
                          >
                            {display}
                          </div>
                        );
                      })}

                      {/* Editable cells — click to edit, blur/Enter to commit. */}
                      {editableColumns.map((col) => {
                        const fv: EntityFieldValue | undefined = r.values[col.field];
                        return (
                          <BulkCell
                            key={`ed-${r.entity_id}-${col.field}`}
                            entity={r}
                            col={col}
                            fv={fv}
                            ck={cellKey(r.entity_id, col.field)}
                            editing={editing[cellKey(r.entity_id, col.field)]}
                            saving={!!saving[cellKey(r.entity_id, col.field)]}
                            error={cellError[cellKey(r.entity_id, col.field)]}
                            onBeginEdit={() => beginEdit(r, col.field)}
                            onChange={(v) => setEditingValue(r, col.field, v)}
                            onCancel={() => cancelEdit(r, col.field)}
                            onCommit={() => void commitEdit(r, col.field)}
                          />
                        );
                      })}

                      {/* Per-row action: jump back into Studio with this entity. */}
                      <div
                        className="br-td"
                        style={{
                          textAlign: "center",
                          padding: "8px 6px",
                          cursor: "pointer",
                          color: "var(--fg-3)",
                        }}
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenEntity(r.entity_id);
                        }}
                        title="Open this entity in Studio (datasheet drawer)"
                      >
                        <ArrowUpRight size={13} strokeWidth={1.6} />
                      </div>
                    </div>
                  );
                })}

                {filteredRows.length === 0 && (
                  <div className="br-empty" style={{ gridColumn: "1 / -1" }}>
                    {debouncedFilter || showOnlyEdited
                      ? "No entities match the current filter."
                      : "No entities to show."}
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        {showDetail && (
          <aside className="br-detail">
            <div className="row-hd">
              <span className="overline">
                {selectedRow
                  ? `Row · ${filteredRows.findIndex((r) => r.entity_id === selectedRow.entity_id) + 1} of ${filteredRows.length}`
                  : "No row selected"}
              </span>
              <div className="nav">
                <button
                  title="Previous row"
                  onClick={() => {
                    if (!selectedRow) return;
                    const idx = filteredRows.findIndex(
                      (r) => r.entity_id === selectedRow.entity_id,
                    );
                    if (idx > 0) setSelectedId(filteredRows[idx - 1].entity_id);
                  }}
                  disabled={!selectedRow}
                >
                  <ChevronUp size={13} strokeWidth={1.6} />
                </button>
                <button
                  title="Next row"
                  onClick={() => {
                    if (!selectedRow) return;
                    const idx = filteredRows.findIndex(
                      (r) => r.entity_id === selectedRow.entity_id,
                    );
                    if (idx >= 0 && idx < filteredRows.length - 1) {
                      setSelectedId(filteredRows[idx + 1].entity_id);
                    }
                  }}
                  disabled={!selectedRow}
                >
                  <ChevronDown size={13} strokeWidth={1.6} />
                </button>
                <button title="Close panel" onClick={() => setShowDetail(false)}>
                  <X size={13} strokeWidth={1.6} />
                </button>
              </div>
            </div>

            {selectedRow ? (
              <>
                <h3 style={{ color: "var(--qong-magenta, #FF4DA8)" }}>
                  {selectedRow.tag || "Untagged"}
                </h3>
                <div
                  className="row-meta"
                  style={{ display: "flex", alignItems: "center", gap: 6 }}
                >
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 9.5,
                      letterSpacing: "0.14em",
                      textTransform: "uppercase",
                      padding: "2px 6px",
                      borderRadius: 4,
                      background: "var(--bg-elev)",
                      border: "1px solid var(--border)",
                      color: "var(--fg-2)",
                    }}
                  >
                    {selectedRow.entity_class}
                  </span>
                  <span>{selectedRow.sub_class}</span>
                </div>
                <div
                  className="row-meta"
                  style={{ fontSize: 10.5, marginTop: 4, opacity: 0.7 }}
                >
                  {selectedRow.pid_number} · sheet {selectedRow.sheet_number}
                </div>

                <div className="group">
                  <h4>Fields</h4>
                  <dl style={{ margin: 0 }}>
                    {schema.map((col) => {
                      const fv = selectedRow.values[col.field];
                      const v = valueToString(fv?.value);
                      const empty = v === "";
                      const overridden = !!fv?.is_override;
                      return (
                        <div key={col.field} className="kv">
                          <span className="k">{col.header}</span>
                          <span
                            className={`v ${empty ? "miss" : ""}`}
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 6,
                            }}
                          >
                            {empty ? "—" : v}
                            {overridden && (
                              <span
                                title="This value was edited from its original P&ID-extracted value"
                                style={{
                                  width: 6,
                                  height: 6,
                                  borderRadius: "50%",
                                  background: "var(--qong-magenta, #FF4DA8)",
                                  display: "inline-block",
                                }}
                              />
                            )}
                            {!overridden && fv?.source === "pid" && !empty && (
                              <span
                                title="Pipeline-extracted from the P&ID"
                                style={{
                                  width: 6,
                                  height: 6,
                                  borderRadius: "50%",
                                  background: "var(--qong-cyan, #06b6d4)",
                                  display: "inline-block",
                                  opacity: 0.7,
                                }}
                              />
                            )}
                            {overridden && col.editable && (
                              <button
                                type="button"
                                onClick={() => {
                                  // UI-only reset (DELETE-override doesn't
                                  // exist yet — same caveat as D2).
                                  setEditingValue(selectedRow, col.field, "");
                                  beginEdit(selectedRow, col.field);
                                }}
                                title="Clear cell (UI only — no backend DELETE-override yet)"
                                style={{
                                  background: "transparent",
                                  border: "1px solid var(--border)",
                                  borderRadius: 4,
                                  padding: "1px 4px",
                                  fontSize: 9,
                                  color: "var(--fg-3)",
                                  cursor: "pointer",
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: 2,
                                }}
                              >
                                <RotateCcw size={9} strokeWidth={1.6} />
                              </button>
                            )}
                          </span>
                        </div>
                      );
                    })}
                  </dl>
                </div>

                <div className="actions" style={{ marginTop: 16, display: "flex", gap: 8 }}>
                  <button
                    className="br-btn small primary"
                    onClick={() => onOpenEntity(selectedRow.entity_id)}
                  >
                    <ArrowUpRight size={11} strokeWidth={1.6} /> Open in Studio
                  </button>
                </div>
              </>
            ) : (
              <div className="row-meta" style={{ marginTop: 12 }}>
                Select a row to inspect its fields.
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}

/** One editable cell. Click → input; Enter / blur → PATCH; Esc → revert.
 *  Renders a P&ID dot for pipeline-extracted, un-overridden cells, and an
 *  EDITED dot for cells with an override. Read-only `null` / `""` show "—". */
function BulkCell({
  entity,
  col,
  fv,
  editing,
  saving,
  error,
  onBeginEdit,
  onChange,
  onCancel,
  onCommit,
}: {
  entity: EntityRow;
  col: EntityColumn;
  fv: EntityFieldValue | undefined;
  ck: string;
  editing: string | undefined;
  saving: boolean;
  error: string | undefined;
  onBeginEdit: () => void;
  onChange: (v: string) => void;
  onCancel: () => void;
  onCommit: () => void;
}) {
  const display = valueToString(fv?.value);
  const isEmpty = display === "";
  const isOverride = !!fv?.is_override;
  const isPidSourced = fv?.source === "pid" && !isOverride && !isEmpty;
  const isEditing = editing !== undefined;

  // Click-to-edit affordance: a single click flips the cell into an input,
  // pre-populated with the current value. We deliberately don't use a separate
  // "edit" icon — the whole cell is the affordance.
  return (
    <div
      className="br-td"
      style={{
        position: "relative",
        padding: isEditing ? "4px 6px" : "10px 12px",
        cursor: isEditing ? "text" : "pointer",
        background: isEditing ? "var(--bg-elev)" : undefined,
        boxShadow: error ? "inset 0 0 0 1px var(--error, #dc2626)" : undefined,
      }}
      onClick={(e) => {
        if (isEditing) return;
        e.stopPropagation();
        onBeginEdit();
      }}
      title={error || (isOverride ? "Edited" : isPidSourced ? "P&ID-extracted" : undefined)}
    >
      {isEditing ? (
        <input
          autoFocus
          type="text"
          value={editing ?? ""}
          disabled={saving}
          onChange={(e) => onChange(e.target.value)}
          onClick={(e) => e.stopPropagation()}
          onBlur={() => onCommit()}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onCommit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              onCancel();
            }
          }}
          style={{
            width: "100%",
            border: 0,
            outline: 0,
            background: "transparent",
            font: "inherit",
            color: "var(--fg-1)",
            padding: "6px 6px",
          }}
        />
      ) : (
        <>
          <span
            style={{
              color: isEmpty ? "var(--fg-3)" : "var(--fg-1)",
              fontStyle: isEmpty ? "italic" : "normal",
            }}
          >
            {isEmpty ? "—" : display}
          </span>
          {/* P&ID dot — top-right corner, small + subtle */}
          {isPidSourced && (
            <span
              style={{
                position: "absolute",
                top: 6,
                right: 6,
                width: 5,
                height: 5,
                borderRadius: "50%",
                background: "var(--qong-cyan, #06b6d4)",
                opacity: 0.7,
              }}
            />
          )}
          {/* EDITED dot — magenta, takes precedence over the P&ID dot */}
          {isOverride && (
            <span
              style={{
                position: "absolute",
                top: 6,
                right: 6,
                width: 5,
                height: 5,
                borderRadius: "50%",
                background: "var(--qong-magenta, #FF4DA8)",
              }}
            />
          )}
        </>
      )}
      {/* Make the entity prop "used" for ESLint — col + entity power the title
       *  attribute upstream, and entity is part of the prop API even though
       *  the cell itself doesn't render it. */}
      <span style={{ display: "none" }} aria-hidden>{entity.entity_id}{col.field}</span>
    </div>
  );
}
