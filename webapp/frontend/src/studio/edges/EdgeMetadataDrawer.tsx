/**
 * EdgeMetadataDrawer — slide-up drawer that appears immediately after a
 * draw-edge gesture commits. Gives the user a single shot at attaching
 * semantic info to the edge before it disappears into the canvas:
 *
 *   - relation_type:  semantic relation (carries, measures, controls, ...)
 *   - group_id:       free-text grouping key for loops / interlocks
 *   - metadata_json:  up to 3 free-form key/value rows (v1)
 *
 * UX:
 *   - Save  → onSave(patchBody) with whatever the user filled in
 *   - Skip  → onClose without onSave (the edge stays as-is)
 *
 * Sits in the bottom of the canvas viewport; it's NOT a modal overlay —
 * keyboard shortcuts + canvas pan still work behind it.
 */

import { useState, type CSSProperties } from "react";
import type { EdgeLite } from "../PidCanvas";
import type { PatchEdgeBody } from "./api";

export type RelationType =
  | "none"
  | "pipe"
  | "carries"
  | "measures"
  | "controls"
  | "interlocks_with"
  | "loops_to";

const RELATION_OPTIONS: { value: RelationType; label: string }[] = [
  { value: "pipe",           label: "Pipe (undirected)" },
  { value: "none",           label: "— none —" },
  { value: "carries",        label: "carries" },
  { value: "measures",       label: "measures" },
  { value: "controls",       label: "controls" },
  { value: "interlocks_with", label: "interlocks_with" },
  { value: "loops_to",       label: "loops_to" },
];

const MAX_METADATA_ROWS = 3;

interface MetaRow {
  key: string;
  value: string;
}

export interface EdgeMetadataDrawerProps {
  edge: EdgeLite;
  onSave: (patch: PatchEdgeBody) => void;
  onClose: () => void;
  /** Render against the dark theme palette. */
  dark?: boolean;
}

function initialRows(edge: EdgeLite): MetaRow[] {
  // EdgeLite doesn't expose metadata_json today (canvas renderer doesn't need
  // it). Start with empty rows; the drawer is the place users fill them in.
  void edge;
  return [
    { key: "", value: "" },
    { key: "", value: "" },
    { key: "", value: "" },
  ];
}

export function EdgeMetadataDrawer({
  edge,
  onSave,
  onClose,
  dark = false,
}: EdgeMetadataDrawerProps) {
  const [relation, setRelation] = useState<RelationType>(
    (edge.relation_type as RelationType | null | undefined) ?? "pipe",
  );
  const [groupId, setGroupId] = useState<string>(edge.group_id ?? "");
  const [rows, setRows] = useState<MetaRow[]>(initialRows(edge));

  const handleSave = () => {
    const metadata_json: Record<string, unknown> = {};
    for (const r of rows) {
      const k = r.key.trim();
      if (k) {
        metadata_json[k] = r.value;
      }
    }
    const patch: PatchEdgeBody = {
      relation_type: relation === "none" ? null : relation,
      group_id: groupId.trim() === "" ? null : groupId.trim(),
      metadata_json: Object.keys(metadata_json).length > 0 ? metadata_json : null,
    };
    onSave(patch);
  };

  const bg = dark ? "var(--bg-elev, #1F2937)" : "var(--bg-elev, #FFFFFF)";
  const fg = dark ? "var(--ink-100, #E5E7EB)" : "var(--ink-800, #1F2937)";
  const border = dark
    ? "1px solid rgba(255,255,255,0.08)"
    : "1px solid rgba(0,0,0,0.08)";
  const inputBg = dark ? "rgba(255,255,255,0.06)" : "#FFFFFF";

  const wrapStyle: CSSProperties = {
    position: "absolute",
    bottom: "var(--s-3, 12px)",
    left: "50%",
    transform: "translateX(-50%)",
    width: 320,
    background: bg,
    color: fg,
    borderRadius: "var(--r-3, 8px)",
    boxShadow: "var(--shadow-md, 0 4px 12px rgba(0,0,0,0.18))",
    border,
    padding: "var(--s-3, 12px)",
    animation: "edge-drawer-slide-up 160ms ease-out",
    zIndex: 50,
  };

  const labelStyle: CSSProperties = {
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: 0.4,
    color: dark ? "var(--ink-300, #9CA3AF)" : "var(--ink-600, #4B5563)",
    marginBottom: 4,
    display: "block",
  };

  const inputStyle: CSSProperties = {
    width: "100%",
    height: 30,
    boxSizing: "border-box",
    padding: "0 8px",
    border,
    borderRadius: "var(--r-2, 6px)",
    background: inputBg,
    color: fg,
    fontSize: 13,
    outline: "none",
  };

  const headerStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 10,
  };

  const titleStyle: CSSProperties = {
    fontSize: 13,
    fontWeight: 600,
  };

  const sectionStyle: CSSProperties = { marginBottom: 10 };

  const kvRowStyle: CSSProperties = {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 6,
    marginBottom: 4,
  };

  const footerStyle: CSSProperties = {
    display: "flex",
    justifyContent: "flex-end",
    gap: 8,
    marginTop: 6,
  };

  const skipBtn: CSSProperties = {
    height: 30,
    padding: "0 12px",
    border,
    background: "transparent",
    color: fg,
    borderRadius: "var(--r-2, 6px)",
    fontSize: 13,
    cursor: "pointer",
  };

  const saveBtn: CSSProperties = {
    ...skipBtn,
    border: "1px solid var(--qong-pink, #FF4DA8)",
    background: "var(--qong-pink, #FF4DA8)",
    color: "#FFFFFF",
    fontWeight: 600,
  };

  return (
    <div
      role="dialog"
      aria-label="Edge metadata"
      data-testid="edge-metadata-drawer"
      style={wrapStyle}
    >
      <div style={headerStyle}>
        <span style={titleStyle}>Edge details</span>
        <span style={{ fontSize: 11, opacity: 0.6 }}>
          {edge.line_type}
        </span>
      </div>

      <div style={sectionStyle}>
        <label style={labelStyle} htmlFor="edge-relation">
          Relation
        </label>
        <select
          id="edge-relation"
          data-testid="edge-relation-select"
          value={relation}
          onChange={(e) => setRelation(e.target.value as RelationType)}
          style={inputStyle}
        >
          {RELATION_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div style={sectionStyle}>
        <label style={labelStyle} htmlFor="edge-group">
          Group ID
        </label>
        <input
          id="edge-group"
          data-testid="edge-group-input"
          type="text"
          placeholder="e.g. LOOP-101"
          value={groupId}
          onChange={(e) => setGroupId(e.target.value)}
          style={inputStyle}
        />
      </div>

      <div style={sectionStyle}>
        <span style={labelStyle}>Metadata</span>
        {rows.map((r, i) => (
          <div key={i} style={kvRowStyle}>
            <input
              type="text"
              placeholder="key"
              aria-label={`metadata key ${i + 1}`}
              data-testid={`edge-meta-key-${i}`}
              value={r.key}
              onChange={(e) =>
                setRows((prev) =>
                  prev.map((row, idx) =>
                    idx === i ? { ...row, key: e.target.value } : row,
                  ),
                )
              }
              style={inputStyle}
              maxLength={64}
            />
            <input
              type="text"
              placeholder="value"
              aria-label={`metadata value ${i + 1}`}
              data-testid={`edge-meta-value-${i}`}
              value={r.value}
              onChange={(e) =>
                setRows((prev) =>
                  prev.map((row, idx) =>
                    idx === i ? { ...row, value: e.target.value } : row,
                  ),
                )
              }
              style={inputStyle}
              maxLength={120}
            />
          </div>
        ))}
        {rows.length > MAX_METADATA_ROWS && (
          /* Defensive — initialRows fixes length at 3 today. */
          <span style={{ fontSize: 11, opacity: 0.6 }}>
            (only first {MAX_METADATA_ROWS} rows saved)
          </span>
        )}
      </div>

      <div style={footerStyle}>
        <button
          type="button"
          data-testid="edge-drawer-skip"
          onClick={onClose}
          style={skipBtn}
        >
          Skip
        </button>
        <button
          type="button"
          data-testid="edge-drawer-save"
          onClick={handleSave}
          style={saveBtn}
        >
          Save
        </button>
      </div>

      <style>
        {`@keyframes edge-drawer-slide-up {
          from { transform: translate(-50%, 24px); opacity: 0; }
          to   { transform: translate(-50%, 0);    opacity: 1; }
        }`}
      </style>
    </div>
  );
}

export default EdgeMetadataDrawer;
