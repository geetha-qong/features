import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusBadge, { STATUS_BADGE_COLORS } from "./StatusBadge";
import type { AnnotationStatus } from "./api";

const CASES: Array<{ status: AnnotationStatus; label: string }> = [
  { status: "model_found",    label: "MODEL" },
  { status: "user_added",     label: "USER" },
  { status: "user_confirmed", label: "CONFIRMED" },
  { status: "user_rejected",  label: "REJECTED" },
];

describe("StatusBadge", () => {
  for (const { status, label } of CASES) {
    test(`renders "${label}" for status="${status}"`, () => {
      render(<StatusBadge status={status} />);
      const badge = screen.getByTestId(`status-badge-${status}`);
      expect(badge.textContent).toBe(label);
      expect(badge.getAttribute("data-status")).toBe(status);
    });

    test(`sets the right background color for status="${status}"`, () => {
      render(<StatusBadge status={status} />);
      const badge = screen.getByTestId(`status-badge-${status}`);
      const bg = (badge as HTMLSpanElement).style.background.toLowerCase();
      const expected = STATUS_BADGE_COLORS[status].toLowerCase();
      // Inline style serializes the CSS var with fallback; check both pieces.
      expect(bg).toContain(expected);
    });
  }
});
