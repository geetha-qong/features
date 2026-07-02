import { memo, useState, useEffect, useRef } from "react";
import {
  ArrowUpRight,
  Check,
  FileText,
  LogIn,
  LogOut,
  PanelRightClose,
  Pencil,
  RotateCcw,
  Trash2,
} from "lucide-react";
import PidSymbol, { subClassToSymKind } from "./PidSymbol";
import type { CanvasElement, GraphNode } from "./types";

/** Returns the upper-cased sub-class label from a YOLO class string.
 *  "valve_bv" → "BV", "instrument_ft" → "FT", unknown → "SYMBOL" */
function subClassFromLabel(label: string | null | undefined): string {
  if (!label) return "SYMBOL";
  const idx = label.indexOf("_");
  if (idx < 0) return label.toUpperCase();
  return label.slice(idx + 1).toUpperCase();
}

interface Props {
  elements: Record<string, CanvasElement>;
  selectedId: string;
  onSelect: (id: string, entityClass?: string) => void;
  hasDatasheet: boolean;
  onOpenDatasheet: () => void;
  onCollapse: () => void;
  /** Show the Remove action for the selected element. Widened from the old
   *  "user-added only" gate (node-corrections, 2026-06-28): now true for ANY
   *  selected node — detected nodes soft-reject, user-added ones hard-delete.
   *  onRemove decides which path by source. */
  canRemove?: boolean;
  /** Remove handler — routes reject (detected) vs delete (user-added) in Studio. */
  onRemove?: () => void;
  /** True when the selected node has been soft-rejected (ghosted on canvas).
   *  Swaps the Remove button for a Restore button. */
  isRejected?: boolean;
  /** Restore (un-reject) handler — shown instead of Remove when isRejected. */
  onRestore?: () => void;
  /** Soft-rejected (removed) detected nodes — listed in a persistent "Removed"
   *  section so they're restorable even after the Undo toast expires and without
   *  the graph overlay (node-corrections gap fix, 2026-06-28). */
  removedNodes?: { entity_id: string; tag: string }[];
  /** Restore a specific removed node by entity_id (from the Removed section). */
  onRestoreNode?: (entityId: string) => void;
  /** A type-B graph node (entity_id == null) the user clicked to adopt.
   *  When set, a "Confirm as <CLASS>" affordance is shown. */
  adoptTarget?: GraphNode | null;
  /** Called when the user confirms adoption of a type-B node. */
  onAdopt?: (node: GraphNode) => void;
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
  // Only count as equipment if matched to a canonical entity (subClass set).
  // Unmatched raw YOLO Motor/Pump detections are filtered out in buildElements,
  // but guard here too in case any slip through.
  if (el.entityClass === "equipment") return el.subClass ? "equipment" : "other";

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
  // Fallback equipment text-match: only promote to equipment if canonical entity
  // present (subClass set). Without it these are raw YOLO detections → "other".
  if (/\b(motor|pump|vessel|tank|compressor|exchanger)\b/.test(text) ||
      /\b[petv]-\d/.test(tag)) {
    return el.subClass ? "equipment" : "other";
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

const PropertiesPanel = memo(function PropertiesPanel({
  elements,
  selectedId,
  onSelect,
  hasDatasheet,
  onOpenDatasheet,
  onCollapse,
  canRemove,
  onRemove,
  isRejected,
  onRestore,
  removedNodes = [],
  onRestoreNode,
  adoptTarget,
  onAdopt,
}: Props) {
  const sel = elements[selectedId] || Object.values(elements)[0];
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  const [category, setCategory] = useState<Category>("all");
  const listRef = useRef<HTMLDivElement>(null);
  const selectedRowRef = useRef<HTMLDivElement>(null);

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
            {/* Remove / Restore — node-corrections (2026-06-28). Remove shows
                for ANY selected node (detected → soft-reject, user-added →
                hard-delete; Studio routes by source). A rejected node swaps to
                a Restore button so the soft-reject is reversible. */}
            {isRejected ? (
              <button
                type="button"
                className="mini-btn"
                onClick={onRestore}
                title="Restore this removed element"
              >
                <RotateCcw size={12} strokeWidth={1.6} /> Restore
              </button>
            ) : (
              canRemove && (
                <button
                  type="button"
                  className="mini-btn mini-btn--danger"
                  onClick={onRemove}
                  title="Remove this element (Del / Backspace)"
                >
                  <Trash2 size={12} strokeWidth={1.6} /> Remove
                </button>
              )
            )}
          </div>
          {hasDatasheet && (
            <button className="open-ds-btn" onClick={onOpenDatasheet}>
              <FileText size={13} strokeWidth={1.6} />
              Open Document
              <ArrowUpRight size={13} strokeWidth={1.6} />
            </button>
          )}
        </div>
      </div>

      {/* ── Adopt type-B node ───────────────────────────────────────── */}
      {adoptTarget && (
        <div className="props-section adopt-panel" data-testid="adopt-panel">
          <div className="props-head">
            <span>Unmatched Detection</span>
          </div>
          <div className="prop-card" style={{ fontSize: 12, lineHeight: 1.55 }}>
            <p style={{ margin: "0 0 10px" }}>
              YOLO detected this symbol but it has no entity record. Adopt it as a
              first-class entity so it appears in deliverables.
            </p>
            <div className="prop-actions">
              <button
                type="button"
                className="mini-btn"
                onClick={() => onAdopt?.(adoptTarget)}
                title={`Adopt as ${subClassFromLabel(adoptTarget.class)}`}
              >
                <Check size={12} strokeWidth={1.6} />
                {" "}Confirm as {subClassFromLabel(adoptTarget.class)}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Elements on P&ID ─────────────────────────────────────────── */}
      <div className="props-section">
        <div className="props-head">
          <span>Elements on P&amp;ID</span>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: "auto" }}>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as Category)}
              className="props-category-select"
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
            return (
              <div
                key={key}
                ref={isSel ? selectedRowRef : null}
                className={`element-row ${isSel ? "selected" : ""}`}
                onClick={() => isSel ? onSelect("", undefined) : onSelect(key, el.entityClass)}
                data-comment-anchor={`element-row-${key}`}
              >
                <div className="el-ic el-ic--sym">
                  <PidSymbol kind={subClassToSymKind(el.entityClass, el.subClass)} />
                </div>
                <div className="el-text">
                  <div className="el-tag">{el.tag}</div>
                  <div className="el-type">{el.type}</div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Removed (soft-rejected) nodes — a persistent, overlay-independent way
            to Restore after the Undo toast is gone (node-corrections, 2026-06-28). */}
        {removedNodes.length > 0 && (
          <div className="removed-list" data-testid="removed-list">
            <div className="removed-head">Removed · {removedNodes.length}</div>
            {removedNodes.map((rn) => (
              <div
                className="element-row removed-row"
                key={rn.entity_id}
                data-comment-anchor={`removed-row-${rn.entity_id}`}
              >
                <div className="el-text">
                  <div className="el-tag">{rn.tag}</div>
                  <div className="el-type">Removed</div>
                </div>
                <button
                  type="button"
                  className="mini-btn"
                  onClick={() => onRestoreNode?.(rn.entity_id)}
                  title="Restore this removed element"
                >
                  <RotateCcw size={12} strokeWidth={1.6} /> Restore
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
});

export default PropertiesPanel;
