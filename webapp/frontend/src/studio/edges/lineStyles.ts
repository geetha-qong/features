/**
 * Per-line-type stroke pattern + color.
 *
 * Mirrors the LINE_STYLE map declared inside PidCanvas.tsx — keep these two
 * in sync. The colors come from `webapp/frontend/src/design/tokens.css`:
 *
 *   process_pipe → --scan-cyan #22D3EE solid
 *   instrument   → --qong-pink #FF4DA8 dashed
 *   signal       → --qong-purple #C73FBE long-dash
 *   interlock    → --warn #F59E0B dash-dot
 *
 * Exported separately so toolbar previews, metadata drawer chips, and any
 * other UI bits can reuse the same definitions without importing PidCanvas
 * (which would create a circular UI dependency).
 */

import type { LineType } from "../PidCanvas";

export interface LineStyleEntry {
  /** CSS color hex (matches a token in tokens.css) */
  color: string;
  /** SVG stroke-dasharray. "0" → solid. */
  dash: string;
  /** Default stroke width in page-pixel units. */
  width: number;
  /** Human-readable label used in the toolbar buttons. */
  label: string;
}

export const LINE_STYLE: Record<LineType, LineStyleEntry> = {
  plain_pipe:   { color: "#F97316", dash: "0",        width: 1.6, label: "Pipe" },
  process_pipe: { color: "#22D3EE", dash: "0",        width: 2.4, label: "Process Pipe" },
  instrument:   { color: "#FF4DA8", dash: "8 4",      width: 2.0, label: "Instrument" },
  signal:       { color: "#C73FBE", dash: "14 6",     width: 2.0, label: "Signal" },
  interlock:    { color: "#F59E0B", dash: "4 4 1 4",  width: 2.0, label: "Interlock" },
};

/** Convenience: ordered list of line types for toolbar rendering. */
export const LINE_TYPE_ORDER: LineType[] = [
  "plain_pipe",
  "process_pipe",
  "instrument",
  "signal",
  "interlock",
];
