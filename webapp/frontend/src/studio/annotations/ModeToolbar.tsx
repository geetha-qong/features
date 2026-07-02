/**
 * ModeToolbar — compact 3-button mode switcher for the canvas.
 *
 * Modes mirror PidCanvas.CanvasMode: "select" (default), "mark-symbol" (P3),
 * "draw-edge" (P4). Pink active state matches the rest of Studio's user-signal
 * accent.
 */
import { MousePointer2, Plus, ArrowUpRight } from "lucide-react";
import type { CanvasMode } from "../PidCanvas";

export interface ModeToolbarProps {
  mode: CanvasMode;
  setMode: (m: CanvasMode) => void;
  dark?: boolean;
}

interface ModeDef {
  key: CanvasMode;
  label: string;
  Icon: typeof MousePointer2;
}

const MODES: ModeDef[] = [
  { key: "select",      label: "Select",      Icon: MousePointer2 },
  { key: "mark-symbol", label: "Mark Symbol", Icon: Plus },
  { key: "draw-edge",   label: "Draw Edge",   Icon: ArrowUpRight },
];

export default function ModeToolbar({ mode, setMode, dark = false }: ModeToolbarProps) {
  const bg = dark ? "var(--bg-elev, #14162A)" : "var(--bg-elev, #ffffff)";
  const fg = dark ? "var(--fg, #E8EAF4)" : "var(--fg, #14162A)";
  const sub = dark ? "var(--ink-400, #9498AE)" : "var(--ink-600, #6B6F8A)";
  const border = dark ? "rgba(255,255,255,0.08)" : "rgba(20,22,42,0.08)";

  return (
    <div
      data-testid="mode-toolbar"
      role="toolbar"
      aria-label="Canvas interaction mode"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: 4,
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: "var(--r-3, 8px)",
        boxShadow: "var(--shadow-sm, 0 1px 2px rgba(0,0,0,0.06))",
        fontFamily: "Outfit, sans-serif",
      }}
    >
      {MODES.map((m) => {
        const isActive = m.key === mode;
        return (
          <button
            key={m.key}
            type="button"
            onClick={() => setMode(m.key)}
            data-testid={`mode-btn-${m.key}`}
            data-active={isActive ? "true" : "false"}
            aria-pressed={isActive}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 10px",
              borderRadius: "var(--r-2, 6px)",
              border: "none",
              background: isActive ? "var(--qong-pink, #FF4DA8)" : "transparent",
              color: isActive ? "#fff" : fg,
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
              outline: "none",
              transition: "background 0.12s ease, color 0.12s ease",
            }}
          >
            <m.Icon size={14} />
            <span>{m.label}</span>
          </button>
        );
      })}

      {(mode === "mark-symbol" || mode === "draw-edge") && (
        <span
          data-testid="mode-toolbar-esc-hint"
          style={{
            marginLeft: 6,
            paddingLeft: 8,
            borderLeft: `1px solid ${border}`,
            color: sub,
            fontSize: 11,
            fontFamily: "JetBrains Mono, monospace",
          }}
        >
          Esc to cancel
        </span>
      )}
    </div>
  );
}
