/**
 * React hook for the user's Studio keymap.
 *
 * Surface:
 *   const { shortcuts, update, reset, loading, error } = useShortcuts();
 *
 * On mount: GET /api/v1/users/me/shortcuts.
 * `update(key, binding)` patches one entry and PATCHes the whole map (the
 * backend contract is whole-object replace; we merge locally then send).
 * `reset()` calls the reset endpoint and replaces local state with the
 * returned defaults.
 */
import { useCallback, useEffect, useState } from "react";
import {
  getShortcuts,
  patchShortcuts,
  resetShortcuts,
  type ShortcutBinding,
  type ShortcutMap,
} from "./api";

export interface UseShortcutsResult {
  shortcuts: ShortcutMap;
  /** Update one key locally and send the merged map to the backend. */
  update: (key: string, binding: ShortcutBinding) => Promise<void>;
  /** Replace the entire map locally and send it to the backend. Useful for
   *  bulk edits / delete operations from the Account page. */
  replace: (map: ShortcutMap) => Promise<void>;
  /** Clear stored overrides — backend returns defaults. */
  reset: () => Promise<void>;
  loading: boolean;
  error: string | null;
}

export function useShortcuts(): UseShortcutsResult {
  const [shortcuts, setShortcuts] = useState<ShortcutMap>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getShortcuts()
      .then((m) => {
        if (!cancelled) setShortcuts(m);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const update = useCallback(
    async (key: string, binding: ShortcutBinding) => {
      const next: ShortcutMap = { ...shortcuts, [key]: binding };
      setShortcuts(next);
      try {
        // Backend returns the stored value (NOT merged); we re-load via GET
        // to pick the merged-with-defaults view for the UI.
        await patchShortcuts(next);
        const merged = await getShortcuts();
        setShortcuts(merged);
      } catch (e) {
        setError((e as Error).message);
        throw e;
      }
    },
    [shortcuts],
  );

  const replace = useCallback(async (map: ShortcutMap) => {
    setShortcuts(map);
    try {
      await patchShortcuts(map);
      const merged = await getShortcuts();
      setShortcuts(merged);
    } catch (e) {
      setError((e as Error).message);
      throw e;
    }
  }, []);

  const reset = useCallback(async () => {
    try {
      const defaults = await resetShortcuts();
      setShortcuts(defaults);
    } catch (e) {
      setError((e as Error).message);
      throw e;
    }
  }, []);

  return { shortcuts, update, replace, reset, loading, error };
}
