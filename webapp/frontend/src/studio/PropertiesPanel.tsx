import { useState, useEffect, useRef } from "react";
import {
  ArrowUpRight,
  Check,
  FileText,
  LogIn,
  LogOut,
  PanelRightClose,
  Pencil,
  Trash2,
} from "lucide-react";
import PidSymbol, { subClassToSymKind } from "./PidSymbol";
import type { CanvasElement } from "./types";

interface Props {
  elements: Record<string, CanvasElement>;
  selectedId: string;
  onSelect: (id: string, entityClass?: string) => void;
  hasDatasheet: boolean;
  onOpenDatasheet: () => void;
  onCollapse: () => void;
  canDelete?: boolean;
  onDelete?: () => void;
}

const VENDOR_SUPPORTED = new Set([
  "PT","PIT","PDT","PG","TT","TE","TI","TG","FT","FI","LT","LI","VT",
  "PBS","PS","LS","RTD","TC","TW","FM","FE","RO","CVP","PSV","V",
  "ACT","MOT","CMP","BLW","FAN","GBX","HEX","TN","VS","FIL","STR","PLC",
]);

function extractInstType(tag: string): string | null {
  const match = tag.match(/^([A-Za-z]+)/);
  if (!match) return null;
  const rawCode = match[1].toUpperCase();
  if (VENDOR_SUPPORTED.has(rawCode)) return rawCode;
  const stripped = rawCode.replace(/IT$/, "T");
  if (VENDOR_SUPPORTED.has(stripped)) return stripped;
  if (rawCode.startsWith("PD")) return "PDT";
  if (rawCode.startsWith("PZ")) return "PIT";
  const firstTwo = rawCode.slice(0, 2);
  if (VENDOR_SUPPORTED.has(firstTwo)) return firstTwo;
  return null;
}

function confColor(conf: number): string {
  if (conf > 0.85) return "var(--ok)";
  if (conf > 0.7) return "var(--warn)";
  return "var(--error)";
}

// Map a CanvasElement to one of the 5 broad filter categories.
// entityClass is the primary signal (set by the backend for all valve/instrument/equipment
// detections); pattern matching on tag + type is a fallback for unclassified elements.
type Category = "all" | "valve" | "instrument" | "equipment" | "other";

function getElementCategory(el: CanvasElement): Exclude<Category, "all"> {
  // Primary signal: entityClass set by the backend YOLO label mapper.
  if (el.entityClass === "valve") return "valve";
  // Interlock and SIS-R are P&ID logic/connector symbols, not field instruments.
  // Their YOLO class maps to entity_class="instrument" on the backend (so they
  // appear on canvas), but the sidebar should group them under "Other".
  if (el.tag === "interlock" || el.tag === "SIS-R" ||
      el.type === "Interlock" || el.type === "SIS Device") return "other";
  if (el.entityClass === "instrument") return "instrument";
  if (el.entityClass === "equipment") return "equipment";

  // Fallback for elements where entityClass is null/missing (can happen if
  // the backend omits the field for a detection class it doesn't recognise).
  // For unmatched detections el.tag holds the raw YOLO label (e.g. "valve_bf",
  // "inst_bpcs") so we check tag prefix first, then a broader text search.
  const tag = el.tag.toLowerCase();
  const text = `${tag} ${el.type.toLowerCase()}`;

  // valve_*, valve_bf, valve_gt, valve_bv, valve_cv, valve_db, valve_nv …
  if (tag.startsWith("valve_") || text.includes("valve") ||
      /\b(bv|bf|gv|cv|nv|gate|ball|butterfly|check|needle|globe)\b/.test(text)) {
    return "valve";
  }
  // inst_bpcs, inst_sis, inst_local_panel, SIS-R, interlock …
  if (tag.startsWith("inst_") || text.includes("bpcs") || text.includes("(sis") ||
      /\b(instrument|transmitter|ft|pt|tt|lt|fic|pic|tic|lic)\b/.test(text)) {
    return "instrument";
  }
  if (/\b(motor|pump|vessel|tank|compressor|exchanger)\b/.test(text) ||
      /\b[petv]-\d/.test(tag)) {
    return "equipment";
  }
  return "other";
}

const CATEGORY_LABELS: Record<Category, string> = {
  all:        "All",
  valve:      "Valve",
  instrument: "Instrument",
  equipment:  "Equipment",
  other:      "Other",
};

export default function PropertiesPanel({
  elements,
  selectedId,
  onSelect,
  hasDatasheet,
  onOpenDatasheet,
  onCollapse,
  canDelete,
  onDelete,
}: Props) {
  const sel = elements[selectedId] || Object.values(elements)[0];
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  const [category, setCategory] = useState<Category>("all");
  const listRef = useRef<HTMLDivElement>(null);
  const selectedRowRef = useRef<HTMLDivElement>(null);

  const [vendorList, setVendorList] = useState<Record<string, unknown>[]>([]);
  const [vendorLoading, setVendorLoading] = useState(false);

  useEffect(() => {
    if (!sel || getElementCategory(sel) !== "instrument") {
      setVendorList([]);
      return;
    }
    const instType = extractInstType(sel.tag);
    if (!instType) { setVendorList([]); return; }

    let cancelled = false;
    setVendorList([]);
    setVendorLoading(true);
    fetch("https://dill-payday-chirping.ngrok-free.dev/api/qong-instrument", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": "qong-local-dev-key-0000000000000000",
        "ngrok-skip-browser-warning": "true",
      },
      body: JSON.stringify({ instType }),
    })
      .then((r) => r.json())
      .then((json: { success?: boolean; data?: unknown }) => {
        if (!cancelled && json.success && json.data) {
          const raw = json.data;
          setVendorList(Array.isArray(raw) ? (raw as Record<string, unknown>[]) : [raw as Record<string, unknown>]);
        }
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setVendorLoading(false); });
    return () => { cancelled = true; };
  }, [sel?.tag]); // re-fetch when selected instrument changes

  // Auto-scroll the list to keep the selected element visible when selectedId changes
  useEffect(() => {
    selectedRowRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedId]);

  const detected = Object.entries(elements);
  const total = detected.length;

  // Count per broad category for the dropdown labels
  const categoryCounts: Record<string, number> = { valve: 0, instrument: 0, equipment: 0, other: 0 };
  for (const [, el] of detected) {
    categoryCounts[getElementCategory(el)]++;
  }

  const filteredElements = category === "all"
    ? detected
    : detected.filter(([, el]) => getElementCategory(el) === category);

  return (
    <aside className="props-col">
      {/* ── Selected Element ─────────────────────────────────────────── */}
      <div className="props-section">
        <div className="props-head">
          <span>Selected Element</span>
          <button
            type="button"
            className="props-collapse"
            onClick={onCollapse}
            title="Hide details panel"
            aria-label="Hide details panel"
          >
            <PanelRightClose size={15} strokeWidth={1.6} />
          </button>
        </div>
        <div className="prop-card">
          <div className="prop-head">
            <span className="prop-tag">{sel.tag}</span>
            <span className="prop-type">{sel.type}</span>
          </div>
          <div className="prop-conf">
            <span className="k">Confidence</span>
            <span className="v">{sel.confidence.toFixed(2)}</span>
            <div className="bar">
              <div
                className="fill"
                style={{ width: `${sel.confidence * 100}%`, background: confColor(sel.confidence) }}
              />
            </div>
          </div>
          {sel.lines.map((l, i) => (
            <div className="prop-line" key={i}>
              {i === 0 ? <LogIn size={12} strokeWidth={1.6} /> : <LogOut size={12} strokeWidth={1.6} />}
              <span>{l}</span>
            </div>
          ))}
          <div className="prop-actions">
            <button
              className={`mini-btn ${confirmed[sel.tag] ? "active" : ""}`}
              onClick={() => setConfirmed({ ...confirmed, [sel.tag]: !confirmed[sel.tag] })}
            >
              <Check size={12} strokeWidth={1.6} /> {confirmed[sel.tag] ? "Confirmed" : "Confirm"}
            </button>
            {/* Edit — opens the entity's full editable datasheet drawer */}
            <button
              type="button"
              className="mini-btn"
              onClick={onOpenDatasheet}
              title="Edit all fields for this entity"
            >
              <Pencil size={12} strokeWidth={1.6} /> Edit
            </button>
            {canDelete && (
              <button
                type="button"
                className="mini-btn mini-btn--danger"
                onClick={onDelete}
                title="Delete this annotation (Del / Backspace)"
              >
                <Trash2 size={12} strokeWidth={1.6} /> Delete
              </button>
            )}
          </div>
          {hasDatasheet && (
            <button className="open-ds-btn" onClick={onOpenDatasheet}>
              <FileText size={13} strokeWidth={1.6} />
              Open Document
              <ArrowUpRight size={13} strokeWidth={1.6} />
            </button>
          )}
          {getElementCategory(sel) === "instrument" && (
            <div style={{ marginTop: 8, borderTop: "1px solid var(--border, rgba(255,255,255,0.08))", paddingTop: 8 }}>
              <div style={{ fontSize: 10, color: "var(--fg-3, rgba(255,255,255,0.4))", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Vendor
              </div>
              {vendorLoading ? (
                <span style={{ fontSize: 11, color: "var(--fg-3, rgba(255,255,255,0.4))" }}>Loading vendors…</span>
              ) : (
                <select
                  style={{
                    width: "100%",
                    background: "var(--bg-2, #1a1d27)",
                    border: "1px solid var(--border, rgba(255,255,255,0.1))",
                    color: vendorList.length > 0 ? "var(--fg-1, rgba(255,255,255,0.85))" : "var(--fg-3, rgba(255,255,255,0.4))",
                    borderRadius: 4,
                    fontSize: 11,
                    padding: "4px 6px",
                    cursor: vendorList.length > 0 ? "pointer" : "default",
                    appearance: "auto",
                  }}
                  defaultValue=""
                  disabled={vendorList.length === 0}
                  onChange={(e) => { if (e.target.value) onOpenDatasheet(); }}
                >
                  <option value="" disabled>
                    {vendorList.length > 0 ? "-- Select Vendor --" : "-- No vendors found --"}
                  </option>
                  {vendorList.map((v, i) => {
                    const name = String(v.vendor_name ?? v.manufacturer ?? v.brand ?? `Vendor ${i + 1}`);
                    const key = String(v.product_id ?? i);
                    return <option key={key} value={key}>{name}</option>;
                  })}
                </select>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Elements on P&ID ─────────────────────────────────────────── */}
      <div className="props-section">
        <div className="props-head">
          <span>Elements on P&amp;ID</span>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: "auto" }}>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as Category)}
              style={{
                background: "var(--bg-2, #1a1d27)",
                border: "1px solid var(--border, rgba(255,255,255,0.1))",
                color: "var(--fg-2, rgba(255,255,255,0.6))",
                borderRadius: 4,
                fontSize: 10,
                padding: "2px 4px",
                cursor: "pointer",
              }}
            >
              <option value="all">{CATEGORY_LABELS.all} ({total})</option>
              <option value="valve">{CATEGORY_LABELS.valve} ({categoryCounts.valve})</option>
              <option value="instrument">{CATEGORY_LABELS.instrument} ({categoryCounts.instrument})</option>
              <option value="equipment">{CATEGORY_LABELS.equipment} ({categoryCounts.equipment})</option>
              <option value="other">{CATEGORY_LABELS.other} ({categoryCounts.other})</option>
            </select>
            <span
              className="props-sub"
              title={
                `Stage shows every model detection on this sheet — ${total} total ` +
                `(${categoryCounts.valve} valve, ${categoryCounts.instrument} instrument, ` +
                `${categoryCounts.equipment} equipment, ${categoryCounts.other} other). ` +
                `Bulk Review / exports list only deliverable entities (valves, instruments, ` +
                `equipment) across all sheets, so its per-tab counts are expected to differ ` +
                `from this stage total — "other" items (arrows, connectors) are never exported.`
              }
            >
              {filteredElements.length}{category !== "all" ? ` / ${total}` : ""} detected
            </span>
          </div>
        </div>
        <div className="elements-list" ref={listRef}>
          {filteredElements.map(([key, el]) => {
            const isSel = key === selectedId;
            const color = confColor(el.confidence);
            return (
              <div
                key={key}
                ref={isSel ? selectedRowRef : null}
                className={`element-row ${isSel ? "selected" : ""}`}
                onClick={() => onSelect(key, el.entityClass)}
                data-comment-anchor={`element-row-${key}`}
              >
                <div className="el-ic el-ic--sym">
                  <PidSymbol kind={subClassToSymKind(el.entityClass, el.subClass)} />
                </div>
                <div className="el-text">
                  <div className="el-tag">{el.tag}</div>
                  <div className="el-type">{el.type}</div>
                </div>
                <span className="el-conf" style={{ color }}>
                  <span className="dot" style={{ background: color }}></span>
                  {el.confidence.toFixed(2)}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
