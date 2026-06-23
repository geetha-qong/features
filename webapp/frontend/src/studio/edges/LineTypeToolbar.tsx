/**
 * LineTypeToolbar — horizontal 4-button picker shown while the canvas is in
 * draw-edge mode. Each button previews its stroke style inline so the user
 * doesn't need to recall which dash pattern means what.
 *
 * Spec ref: docs/superpowers/specs/2026-06-10-qong-studio-marking-design.md §5
 * (LineTypeToolbar).
 */

import type { CSSProperties } from "react";
import { LINE_STYLE, LINE_TYPE_ORDER } from "./lineStyles";
import type { LineType } from "../PidCanvas";

export interface LineTypeToolbarProps {
  activeLineType: LineType;
  setActiveLineType: (lt: LineType) => void;
  /** When true, render against the dark theme palette. */
  dark?: boolean;
}

const TOOLBAR_HEIGHT = 40;

const PREVIEW_WIDTH = 36;
const PREVIEW_HEIGHT = 12;

export function LineTypeToolbar({
  activeLineType,
  setActiveLineType,
  dark = false,
}: LineTypeToolbarProps) {
  const wrapStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: "var(--s-2, 8px)",
    height: TOOLBAR_HEIGHT,
    padding: "0 var(--s-2, 8px)",
  };

  return (
    <div
      role="toolbar"
      aria-label="Line type"
      data-testid="line-type-toolbar"
      style={wrapStyle}
    >
      {LINE_TYPE_ORDER.map((lt) => {
        const style = LINE_STYLE[lt];
        const active = lt === activeLineType;

        const inactiveBg = dark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.03)";
        const inactiveColor = dark ? "var(--ink-100, #E5E7EB)" : "var(--ink-800, #1F2937)";
        const inactiveBorder = dark
          ? "1px solid rgba(255,255,255,0.08)"
          : "1px solid rgba(0,0,0,0.08)";

        const btnStyle: CSSProperties = {
          display: "inline-flex",
          alignItems: "center",
          gap: "var(--s-2, 8px)",
          height: 32,
          padding: "0 12px",
          borderRadius: "var(--r-2, 6px)",
          border: active ? "1px solid var(--qong-pink, #FF4DA8)" : inactiveBorder,
          background: active ? "var(--qong-pink, #FF4DA8)" : inactiveBg,
          color: active ? "#FFFFFF" : inactiveColor,
          fontSize: 13,
          fontWeight: active ? 600 : 500,
          cursor: "pointer",
          transition: "background 120ms ease, color 120ms ease",
        };

        // When active, the preview stroke renders white so it stays legible
        // against the pink fill. Inactive shows the line type's true color.
        const strokeColor = active ? "#FFFFFF" : style.color;
        const dashArray = style.dash === "0" ? undefined : style.dash;

        return (
          <button
            key={lt}
            type="button"
            onClick={() => setActiveLineType(lt)}
            aria-pressed={active}
            data-testid={`line-type-btn-${lt}`}
            data-active={active ? "true" : "false"}
            style={btnStyle}
          >
            <svg
              width={PREVIEW_WIDTH}
              height={PREVIEW_HEIGHT}
              viewBox={`0 0 ${PREVIEW_WIDTH} ${PREVIEW_HEIGHT}`}
              aria-hidden="true"
            >
              <line
                x1={2}
                y1={PREVIEW_HEIGHT / 2}
                x2={PREVIEW_WIDTH - 2}
                y2={PREVIEW_HEIGHT / 2}
                stroke={strokeColor}
                strokeWidth={Math.max(1.5, style.width)}
                strokeDasharray={dashArray}
                strokeLinecap="round"
              />
            </svg>
            <span>{style.label}</span>
          </button>
        );
      })}
    </div>
  );
}

export default LineTypeToolbar;
