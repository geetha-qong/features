/**
 * StatusBadge — tiny pill rendering the 4 annotation statuses.
 *
 * Color map is the canonical FEATURES #38 P3 mapping, matched 1:1 with
 * STATUS_STROKE in PidCanvas.tsx so badges and bbox strokes always agree.
 */
import type { AnnotationStatus } from "./api";

export interface StatusBadgeProps {
  status: AnnotationStatus;
}

interface BadgeSpec {
  label: string;
  bg: string;          // CSS var with hex fallback
  fg: string;          // text color
  testStyleColor: string; // pure hex for test inspection
}

const SPEC: Record<AnnotationStatus, BadgeSpec> = {
  model_found:    { label: "MODEL",     bg: "var(--info, #3B82F6)",       fg: "#fff", testStyleColor: "#3B82F6" },
  user_added:     { label: "USER",      bg: "var(--qong-pink, #FF4DA8)",  fg: "#fff", testStyleColor: "#FF4DA8" },
  user_confirmed: { label: "CONFIRMED", bg: "var(--ok, #10B981)",         fg: "#fff", testStyleColor: "#10B981" },
  user_rejected:  { label: "REJECTED",  bg: "var(--error, #EF4444)",      fg: "#fff", testStyleColor: "#EF4444" },
};

export default function StatusBadge({ status }: StatusBadgeProps) {
  const s = SPEC[status];
  return (
    <span
      data-testid={`status-badge-${status}`}
      data-status={status}
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: "var(--r-pill, 999px)",
        background: s.bg,
        color: s.fg,
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.06em",
        lineHeight: 1.4,
        whiteSpace: "nowrap",
      }}
    >
      {s.label}
    </span>
  );
}

// Exported for tests — same source of truth as the inline style above.
export const STATUS_BADGE_COLORS: Record<AnnotationStatus, string> = {
  model_found:    SPEC.model_found.testStyleColor,
  user_added:     SPEC.user_added.testStyleColor,
  user_confirmed: SPEC.user_confirmed.testStyleColor,
  user_rejected:  SPEC.user_rejected.testStyleColor,
};
