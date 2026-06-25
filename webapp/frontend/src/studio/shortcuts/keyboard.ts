/**
 * Pure key-handling helpers for the Studio shortcut dispatcher.
 *
 * Two concerns are intentionally split out here so they can be unit-tested
 * without React:
 *   - normalizeKey: turn a KeyboardEvent into the keymap key we look up.
 *     Returns null when we should ignore the event (input focus, modifier
 *     chord, etc.).
 *   - bindingToAction: identity passthrough for now; the layer exists so we
 *     have a single place to add transforms (e.g. rebadging an action name)
 *     without touching the dispatcher.
 */
import type { ShortcutBinding } from "./api";

/** DOM tag names we treat as "user is typing — don't intercept keystrokes". */
const TEXT_INPUT_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT"]);

/** Multi-char key names the backend accepts verbatim. Keep in sync with
 *  webapp/routers/shortcuts.py:NAMED_KEYS. */
const NAMED_KEYS = new Set(["Escape", "Delete", "Tab", "Enter", " "]);

/**
 * Map a KeyboardEvent to the keymap lookup string, or null when we should
 * not dispatch.
 *
 * Rules (mirrors the backend's validation and the FEATURES #38 spec):
 *  - Modifier chord held (ctrl/alt/meta)? → null. We don't bind chords in v1
 *    because they collide with browser/OS shortcuts.
 *  - Target is an input-like element OR contentEditable? → null.
 *  - Single printable character? → lowercased character ("V" → "v").
 *  - Named multi-char key (Escape, Delete, Tab, Enter)? → returned verbatim.
 *  - Space bar arrives as " " from the browser; we map it to " " (the same
 *    convention the backend uses; storage layer rejects other multi-char
 *    names so unknown long keys are dropped silently here).
 */
export function normalizeKey(e: KeyboardEvent): string | null {
  // Modifier chords — bail. shiftKey is intentionally NOT in this list:
  // capital "V" is just "V" pressed with shift; we lowercase it below.
  if (e.ctrlKey || e.altKey || e.metaKey) return null;

  // Input focus bypass. Check both target tag and contentEditable.
  const tgt = e.target as HTMLElement | null;
  if (tgt) {
    if (TEXT_INPUT_TAGS.has(tgt.tagName)) return null;
    if (tgt.isContentEditable) return null;
  }

  const key = e.key;
  if (!key) return null;

  // Single character (printable) — lowercase. Handles letters and digits.
  if (key.length === 1) {
    return key.toLowerCase();
  }

  // Multi-char — only accept the named keys we bind.
  if (NAMED_KEYS.has(key)) return key;

  return null;
}

/** Identity passthrough. Exists so the dispatcher has one place to evolve
 *  binding shape (e.g. wrapping with telemetry) without touching callers. */
export function bindingToAction(binding: ShortcutBinding): ShortcutBinding {
  return binding;
}
