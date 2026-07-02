/** Shared sectioned-datasheet rendering — used by BOTH the Studio
 *  DatasheetDrawer and the Bulk Review side panel so the two surfaces render
 *  the full per-instrument-type field set identically.
 *
 *  The field set is chosen automatically by the backend from the entity's
 *  sub_class (see webapp/deliverables/ids_schema.py): a Common section plus any
 *  type-specific sections (CV / PT / TT / …). Vendor fields render read-only;
 *  process/user fields are editable and persist via the EntityOverride PATCH.
 */
import React, { useEffect, useRef, useState } from "react";
import { Pencil, RotateCcw, ScanSearch } from "lucide-react";
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

/** Grid width hints for the 4-column `.ds-fields` layout (studio.css):
 *  xs = 1 col (4/row), sm = 2 cols (2/row), md = 3 cols, full = whole row. */
export type FieldSpan = "xs" | "sm" | "md" | "full";

/** Derive a width hint from a field's header so the form packs multiple inputs
 *  per row instead of one-per-line — restores the v3 design's compact layout
 *  (design/qong-studio-v3/project/datasheet.jsx). The backend datasheet/entity
 *  schemas don't carry width hints, so we infer one from the label:
 *    - long free-text (Description, Remarks, Narrative…) → full width
 *    - medium descriptors (Service, Range, Location…)    → 3 cols
 *    - short identifiers / codes / numbers              → 1 col
 *    - everything else                                  → 2 cols (default) */
export function spanForField(header: string): FieldSpan {
  const h = header.toLowerCase().trim();
  if (/(descrip|remark|narrative|note|comment|reason)/.test(h)) return "full";
  if (/(service|range|location|address)/.test(h)) return "md";
  const first = h.split(/[\s/]+/)[0];
  const SHORT = new Set([
    "tag", "rev", "size", "qty", "unit", "sheet", "loop", "disc", "discipline",
    "rating", "slot", "card", "chan", "channel", "cv", "action", "fail", "stem",
    "seat", "trim", "body", "sched", "spec", "no", "no.", "#", "id", "type",
    "i/o", "io", "signal", "set", "setpoint", "delay", "logic", "weight",
  ]);
  if (SHORT.has(first) || h.length <= 4) return "xs";
  return "sm";
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
  ): { col: EntityColumn; fv: EntityFieldValue; options?: string[]; group?: string } {
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
    return { col, fv, options: f.options, group: f.group };
  }

  const PINNED_FIRST = ["General", "Area Classification", "Process", "Element"];
  const PINNED_LAST = ["Commercial / Sign-off"];
  const pinnedSet = new Set([...PINNED_FIRST, ...PINNED_LAST]);
  const orderedSections = [
    ...PINNED_FIRST.flatMap((n) => response.sections.filter((s) => s.name === n)),
    ...response.sections.filter((s) => !pinnedSet.has(s.name)),
    ...PINNED_LAST.flatMap((n) => response.sections.filter((s) => s.name === n)),
  ];

  return (
    <div className="ds-fields-flat" style={{ padding: "12px 16px" }}>
      {!response.type_supported && (
        <p style={{ fontSize: 12, color: "var(--fg-3)", marginBottom: 12 }}>
          Generic datasheet — no type-specific fields for this sub-class yet.
        </p>
      )}
      {orderedSections.map((section, si) => {
        // Walk fields, collecting consecutive same-group fields into GroupedInputCell
        const rendered: React.ReactNode[] = [];
        let fi = 0;
        while (fi < section.fields.length) {
          const f = section.fields[fi];
          const { col, fv, options, group } = toCellShapes(f, fi);

          if (group) {
            // Collect all consecutive fields sharing this group key
            const groupItems: Array<{ col: EntityColumn; fv: EntityFieldValue; options?: string[] }> = [{ col, fv, options }];
            let fj = fi + 1;
            while (fj < section.fields.length && section.fields[fj].group === group) {
              const shaped = toCellShapes(section.fields[fj], fj);
              groupItems.push({ col: shaped.col, fv: shaped.fv, options: shaped.options });
              fj++;
            }
            rendered.push(
              <div key={`grp-${group}-${fi}`} style={{ gridColumn: "1 / -1" }}>
                <GroupedInputCell
                  fields={groupItems.map(({ col, fv, options }) => ({
                    col,
                    fv,
                    value: editValues[col.field] ?? "",
                    options,
                  }))}
                  unlocked={unlocked}
                  onChange={onChange}
                  onUnlock={onUnlock}
                />
              </div>
            );
            fi = fj;
          } else {
            const span = spanForField(f.header);
            if (!f.editable) {
              rendered.push(<ReadOnlyCell key={f.field} col={col} fv={fv} span={span} />);
            } else {
              const isOverridden = !!fv.is_override;
              const pidBadge = isPidSourced(fv) && !isOverridden;
              const locked = pidBadge && !unlocked[f.field];
              rendered.push(
                <EditableCell
                  key={f.field}
                  col={col}
                  fv={fv}
                  span={span}
                  value={editValues[f.field] ?? ""}
                  locked={locked}
                  isOverridden={isOverridden}
                  showPidBadge={pidBadge}
                  options={options}
                  onChange={(v) => onChange(f.field, v)}
                  onUnlock={() => onUnlock(f.field)}
                  onReset={() => onChange(f.field, valueToString(f.value))}
                />
              );
            }
            fi++;
          }
        }

        return (
          <section key={`${section.name}-${si}`} className="ds-section open" style={{ marginBottom: 16 }}>
            <div
              className="ds-section-head"
              style={{ pointerEvents: "none", padding: "8px 0", display: "flex", alignItems: "center", gap: 8 }}
            >
              <span className="num">{String(si + 1).padStart(2, "0")}</span>
              <h3 style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>{section.name}</h3>
            </div>
            <div className="ds-fields">{rendered}</div>
          </section>
        );
      })}
    </div>
  );
}

/** Flowbite single-button dropdown — mirrors the exact Flowbite HTML structure.
 *  Button + SVG chevron toggles a z-10 menu; closes on outside click. */
function FlowbiteDropdown({
  value,
  options,
  onChange,
  className = "",
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} className={`ds-dd-wrap ${className}`}>
      {/* Matches: <button class="inline-flex items-center ... dropdown-toggle"> */}
      <button
        id="dropdownDefaultButton"
        type="button"
        className="ds-dd-btn"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className={value ? "" : "ds-dd-placeholder"}>{value || "Select option"}</span>
        {/* Exact SVG from Flowbite dropdown docs */}
        <svg
          className={`ds-dd-chevron${open ? " open" : ""}`}
          aria-hidden="true"
          xmlns="http://www.w3.org/2000/svg"
          width="16" height="16"
          fill="none" viewBox="0 0 24 24"
        >
          <path stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="m19 9-7 7-7-7"/>
        </svg>
      </button>
      {/* Matches: <div class="z-10 hidden bg-neutral ... rounded-base shadow-lg w-44"> */}
      {open && (
        <div className="ds-dd-menu" id="dropdown">
          <ul className="ds-dd-list" aria-labelledby="dropdownDefaultButton">
            {options.map((opt) => (
              <li key={opt}>
                {/* Matches: <a class="inline-flex items-center w-full p-2 hover:bg-neutral ... rounded"> */}
                <button
                  type="button"
                  className={`ds-dd-item${opt === value ? " active" : ""}`}
                  onClick={() => { onChange(opt); setOpen(false); }}
                >
                  {opt}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Unified multi-field container: one outer border, vertical dividers between sections.
 *  Top row = labels (static text). Bottom row = editable inputs / selects.
 *  Used for Pipe Information, Equipment Info, Line Info, Requirements, Pressure, Temp groups. */
function GroupedInputCell({
  fields,
  unlocked,
  onChange,
  onUnlock,
}: {
  fields: Array<{
    col: EntityColumn;
    fv: EntityFieldValue | undefined;
    value: string;
    options?: string[];
  }>;
  unlocked: Record<string, boolean>;
  onChange: (field: string, v: string) => void;
  onUnlock: (field: string) => void;
}) {
  return (
    <div className="ds-grouped">
      {/* Label row */}
      <div className="ds-grouped-row ds-grouped-label-row">
        {fields.map(({ col }) => (
          <div key={`lbl-${col.field}`} className="ds-grouped-label" title={col.header}>
            {col.header}
          </div>
        ))}
      </div>
      {/* Input row */}
      <div className="ds-grouped-row ds-grouped-input-row">
        {fields.map(({ col, fv, value, options }) => {
          const isOverridden = !!fv?.is_override;
          const pidBadge = isPidSourced(fv) && !isOverridden;
          const locked = pidBadge && !unlocked[col.field];
          return (
            <div key={`inp-${col.field}`} className="ds-grouped-input-wrap">
              {locked ? (
                <div className="ds-grouped-locked">
                  <span className="ds-value">{value || <em>—</em>}</span>
                  <button
                    type="button"
                    className="ds-unlock"
                    onClick={() => onUnlock(col.field)}
                    title="Edit this P&ID-extracted value manually"
                  >
                    <Pencil size={10} strokeWidth={1.6} />
                  </button>
                </div>
              ) : options && options.length > 0 ? (
                <FlowbiteDropdown
                  value={value}
                  options={options}
                  onChange={(v) => onChange(col.field, v)}
                  className="ds-grouped-dd"
                />
              ) : (
                <input
                  className="ds-grouped-input"
                  type="text"
                  placeholder="—"
                  value={value}
                  onChange={(e) => onChange(col.field, e.target.value)}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ReadOnlyCell({
  col,
  fv,
  span = "sm",
}: {
  col: EntityColumn;
  fv: EntityFieldValue | undefined;
  span?: FieldSpan;
}) {
  const valueStr = valueToString(fv?.value);
  return (
    <div className={`ds-field span-${span}`} style={{ opacity: 0.7 }}>
      <label className="ds-label">
        <span>{col.header}</span>
      </label>
      <div className="ds-control">
        <div style={{ height: 36, padding: "0 10px", display: "flex", alignItems: "center" }}>
          <span style={{ fontSize: 13, color: "var(--fg-1)", fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {valueStr || <em style={{ color: "var(--fg-3)", fontStyle: "normal" }}>—</em>}
          </span>
        </div>
      </div>
    </div>
  );
}

export function EditableCell({
  col,
  fv: _fv,
  value,
  locked,
  isOverridden,
  showPidBadge,
  span = "sm",
  options,
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
  span?: FieldSpan;
  options?: string[];
  onChange: (v: string) => void;
  onUnlock: () => void;
  onReset: () => void;
}) {
  return (
    <div className={`ds-field span-${span} ${showPidBadge ? "extracted" : ""} ${locked ? "locked" : ""}`}>
      <label className="ds-label">
        <span>{col.header}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
          {showPidBadge && (
            <span className="ds-source" title="Value came from the P&ID pipeline (not user-edited)">
              <ScanSearch size={9} strokeWidth={1.6} /> P&amp;ID
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
          {isOverridden && !locked && (
            <button
              type="button"
              onClick={onReset}
              title="Reset to P&ID value"
              style={{
                background: "transparent",
                border: "none",
                padding: "1px 3px",
                color: "var(--fg-3)",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 2,
                fontSize: 9,
                borderRadius: 4,
              }}
            >
              <RotateCcw size={9} strokeWidth={1.6} />
            </button>
          )}
        </div>
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
        ) : options && options.length > 0 ? (
          <FlowbiteDropdown value={value} options={options} onChange={onChange} />
        ) : (
          <input
            className="ds-input"
            type="text"
            placeholder="—"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
        )}
      </div>
    </div>
  );
}
