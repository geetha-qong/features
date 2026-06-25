/**
 * Datetime display utilities — single source of truth on the frontend.
 *
 * Convention: the backend sends UTC ISO strings with explicit `Z` suffix
 * (see `webapp/datetime_utils.py:utc_iso`). `new Date(iso)` parses that
 * correctly as UTC. Display is then formatted in the user's preferred
 * timezone, which comes from `User.timezone` if set, or `Intl.DateTimeFormat`
 * browser auto-detect otherwise.
 *
 * Public API:
 *   - useUserTimezone()           → IANA name (e.g. "Asia/Kolkata"), never null
 *   - formatDateTime(iso, tz?)    → "3 Jun 2026, 12:23"
 *   - formatDate(iso, tz?)        → "3 Jun 2026"
 *   - formatRelative(iso)         → "about 3 hours ago"  (TZ-agnostic)
 */
import { formatDistanceToNow } from "date-fns";
import { detectBrowserTimezone, useAuthOptional } from "../auth/AuthContext";

/**
 * Returns the IANA TZ the SPA should render in for the current session.
 * Uses the AuthContext's user.timezone when available, else browser detection.
 * Resilient to being called outside <AuthProvider> (e.g. in isolated tests) —
 * falls back to browser detection instead of throwing.
 */
export function useUserTimezone(): string {
  const auth = useAuthOptional();
  return auth?.user?.timezone ?? detectBrowserTimezone();
}

function parseIso(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d;
}

/** Absolute date+time in the given (or browser-detected) IANA zone. */
export function formatDateTime(
  iso: string | null | undefined,
  tz?: string,
): string {
  const d = parseIso(iso);
  if (!d) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: tz || detectBrowserTimezone(),
      dateStyle: "medium",
      timeStyle: "short",
    }).format(d);
  } catch {
    // Unknown TZ → fall back to local browser format
    return d.toLocaleString();
  }
}

/** Absolute date only — no time component. */
export function formatDate(
  iso: string | null | undefined,
  tz?: string,
): string {
  const d = parseIso(iso);
  if (!d) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: tz || detectBrowserTimezone(),
      dateStyle: "medium",
    }).format(d);
  } catch {
    return d.toLocaleDateString();
  }
}

/** "about 3 hours ago" / "in 5 minutes" — TZ doesn't apply (delta is delta). */
export function formatRelative(iso: string | null | undefined): string {
  const d = parseIso(iso);
  if (!d) return "—";
  return formatDistanceToNow(d, { addSuffix: true });
}
