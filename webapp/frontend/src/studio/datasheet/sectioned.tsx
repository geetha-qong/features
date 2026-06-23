/** Shared sectioned-datasheet rendering — used by BOTH the Studio
 *  DatasheetDrawer and the Bulk Review side panel so the two surfaces render
 *  the full per-instrument-type field set identically.
 *
 *  The field set is chosen automatically by the backend from the entity's
 *  sub_class (see webapp/deliverables/ids_schema.py): a Common section plus any
 *  type-specific sections (CV / PT / TT / …). Vendor fields render read-only;
 *  process/user fields are editable and persist via the EntityOverride PATCH.
 */
import { Lock, Pencil, RotateCcw, ScanSearch } from "lucide-react";
import type {
  DatasheetFieldOut,
  EntityColumn,
  EntityDatasheetResponse,
  EntityFieldValue,
} from "../api";

/** A field path is "P&ID-extracted" if the canonical had a value for it
 *  before any user edits — drives the cyan P&ID badge / lock affordance. */
export function isPidSourced(fv: EntityFieldValue | undefined): boolean {
  return !!fv && fv.source === "pid";
}

/** Render any JSON-shaped value to an editable string. Numbers/strings pass
 *  through; null/undefined become "". Objects fall back to JSON so editing is
 *  at least visible. */
export function valueToString(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return "";
  }
}

/** Parse a user-entered string back to a canonical-compatible value. Number
 *  coercion only when the original was a number (so serials like "0001" don't
 *  silently become 1). */
export function stringToValue(s: string, originalType: string): unknown {
  if (s === "") return null;
  if (originalType === "number") {
    const n = Number(s);
    if (!Number.isNaN(n)) return n;
  }
  return s;
}

/** Seed the editable working copy from a datasheet response — one entry per
 *  editable field, keyed by its dot-notation path. Vendor (read-only) fields
 *  are skipped (they're never edited here). */
export function seedDatasheetEditValues(
  resp: EntityDatasheetResponse,
): Record<string, string> {
  const init: Record<string, string> = {};
  for (const sec of resp.sections) {
    for (const f of sec.fields) {
      if (f.editable) init[f.field] = valueToString(f.value);
    }
  }
  return init;
}

/** Diff the working copy against the response — the map of field-path → coerced
 *  new value for every editable field whose serialized value changed. This is
 *  the exact payload the PATCH endpoint expects. */
export function computeDatasheetDirty(
  resp: EntityDatasheetResponse | null,
  editValues: Record<string, string>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (!resp) return out;
  for (const sec of resp.sections) {
    for (const f of sec.fields) {
      if (!f.editable) continue;
      const cur = editValues[f.field] ?? "";
      const origStr = valueToString(f.value);
      if (cur !== origStr) {
        const origType = typeof f.value === "number" ? "number" : "string";
        out[f.field] = stringToValue(cur, origType);
      }
    }
  }
  return out;
}

/** Render the full per-instrument-type datasheet grouped into sections.
 *  Each backend field is adapted into the synthetic `EntityColumn` +
 *  `EntityFieldValue` shapes the cells expect, so `EditableCell` /
 *  `ReadOnlyCell` are reused verbatim. Vendor (`editable === false`) fields
 *  render read-only; everything else is editable. */
export function SectionedDatasheet({
  response,
  editValues,
  unlocked,
  onChange,
  onUnlock,
}: {
  response: EntityDatasheetResponse;
  editValues: Record<string, string>;
  unlocked: Record<string, boolean>;
  onChange: (k: string, v: string) => void;
  onUnlock: (k: string) => void;
}) {
  // Map a backend field to the synthetic shapes the existing cells consume.
  // `source` collapses to the cell's "pid" | "manual" axis: vendor + overridden
  // values both read as "pid" (pipeline/vendor-sourced); user-blank reads as
  // "manual".
  function toCellShapes(
    f: DatasheetFieldOut,
    i: number,
  ): { col: EntityColumn; fv: EntityFieldValue } {
    const col: EntityColumn = {
      field: f.field,
      header: f.header,
      order: i,
      editable: f.editable,
    };
    const fv: EntityFieldValue = {
      value: f.value,
      source: f.source === "vendor" ? "pid" : f.is_override ? "pid" : "manual",
      is_override: f.is_override,
    };
    return { col, fv };
  }

  return (
    <div className="ds-fields-flat" style={{ padding: "12px 16px" }}>
      {!response.type_supported && (
        <p style={{ fontSize: 12, color: "var(--fg-3)", marginBottom: 12 }}>
          Generic datasheet — no type-specific fields for this sub-class yet.
        </p>
      )}
      {response.sections.map((section, si) => (
        <section key={`${section.name}-${si}`} className="ds-section open" style={{ marginBottom: 16 }}>
          <div
            className="ds-section-head"
            style={{ pointerEvents: "none", padding: "8px 0", display: "flex", alignItems: "center", gap: 8 }}
          >
            <span className="num">{String(si + 1).padStart(2, "0")}</span>
            <h3 style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>{section.name}</h3>
            <span className="ds-section-meta">{section.fields.length}</span>
          </div>
          <div
            className="ds-fields"
            style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}
          >
            {section.fields.map((f, fi) => {
              const { col, fv } = toCellShapes(f, fi);
              if (!f.editable) {
                return <ReadOnlyCell key={f.field} col={col} fv={fv} />;
              }
              const isOverridden = !!fv.is_override;
              const pidBadge = isPidSourced(fv) && !isOverridden;
              const locked = pidBadge && !unlocked[f.field];
              return (
                <EditableCell
                  key={f.field}
                  col={col}
                  fv={fv}
                  value={editValues[f.field] ?? ""}
                  locked={locked}
                  isOverridden={isOverridden}
                  showPidBadge={pidBadge}
                  onChange={(v) => onChange(f.field, v)}
                  onUnlock={() => onUnlock(f.field)}
                  onReset={() => onChange(f.field, valueToString(f.value))}
                />
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

export function ReadOnlyCell({ col, fv }: { col: EntityColumn; fv: EntityFieldValue | undefined }) {
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
          title="Read-only — set by the pipeline / vendor portal, cannot be edited here"
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

export function EditableCell({
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
