/**
 * Global keyboard listener that maps shortcuts → actions in Studio.
 *
 * Studio.tsx (integration pass) supplies the `dispatch` callback which
 * routes a binding to the actual side-effect (mode switch, class select,
 * cancel, delete). Keeping the dispatcher independent of Studio's internals
 * means it can be unit-tested with a fake dispatch and reused if we ever
 * surface shortcuts in other contexts (bulk-review, datasheet drawer).
 */
import { useEffect } from "react";
import type { ShortcutBinding, ShortcutMap } from "./api";
import { bindingToAction, normalizeKey } from "./keyboard";

export type ShortcutDispatch = (binding: ShortcutBinding) => void;

export interface UseShortcutDispatcherOptions {
  /** Disable the listener (e.g. while a modal is open and owns the keyboard). */
  enabled?: boolean;
}

export function useShortcutDispatcher(
  shortcuts: ShortcutMap,
  dispatch: ShortcutDispatch,
  options: UseShortcutDispatcherOptions = {},
): void {
  const enabled = options.enabled !== false;

  useEffect(() => {
    if (!enabled) return;

    function onKeyDown(e: KeyboardEvent) {
      const key = normalizeKey(e);
      if (key === null) return;

      const binding = shortcuts[key];
      if (!binding) return;

      // We have a real match. Stop the browser from also acting on it
      // (e.g. Escape closing dialogs we don't own, Delete navigating back).
      e.preventDefault();
      dispatch(bindingToAction(binding));
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [shortcuts, dispatch, enabled]);
}
