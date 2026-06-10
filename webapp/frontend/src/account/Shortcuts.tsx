/**
 * Studio Shortcuts — per-user keymap editor (FEATURES #38 P5).
 *
 * Lives under /account/shortcuts. Mirrors the layout of routes/Account.tsx:
 *   - centered ~1100px column
 *   - section headers at fontSize 18
 *   - simple table with subtle row dividers
 *
 * Edit model (whole-object replace under the hood — see backend contract in
 * webapp/routers/shortcuts.py):
 *   - Local `draft` map is what the UI shows + edits.
 *   - "Save changes" calls PATCH with the whole draft.
 *   - "Reset to Defaults" calls POST /reset and reloads.
 *
 * Conflict UX: when the user picks a key that already exists in the draft
 * we surface an inline warning + require an explicit "Overwrite" confirm
 * click before the binding lands.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { RotateCcw, Trash2, Plus, AlertTriangle } from "lucide-react";
import { useTheme } from "../theme/ThemeContext";
import {
  getShortcuts,
  patchShortcuts,
  resetShortcuts,
  type ShortcutBinding,
  type ShortcutMap,
} from "../studio/shortcuts/api";

// ──────────────────────────────────────────────────────────────────────────
// Action catalog — mirrors backend ALLOWED_ACTIONS + the per-action shape.
// ──────────────────────────────────────────────────────────────────────────

const ACTIONS: { value: string; label: string }[] = [
  { value: "select-class", label: "Select entity class" },
  { value: "mode", label: "Switch mode" },
  { value: "cancel", label: "Cancel current action" },
  { value: "delete-selected", label: "Delete selected" },
];

/** Sub-class catalog for select-class. Pairs with entity_class. Kept in this
 *  file (vs fetched) because the surface is tiny and the backend doesn't yet
 *  expose a "list known sub_classes" endpoint. */
const SUB_CLASSES: Record<string, { value: string; label: string }[]> = {
  valve: [
    { value: "BV", label: "BV — Ball valve" },
    { value: "GT", label: "GT — Gate valve" },
    { value: "BF", label: "BF — Butterfly valve" },
    { value: "CV", label: "CV — Control valve" },
    { value: "CK", label: "CK — Check valve" },
    { value: "GL", label: "GL — Globe valve" },
  ],
  instrument: [
    { value: "FT", label: "FT — Flow transmitter" },
    { value: "PT", label: "PT — Pressure transmitter" },
    { value: "TT", label: "TT — Temperature transmitter" },
    { value: "LT", label: "LT — Level transmitter" },
    { value: "FI", label: "FI — Flow indicator" },
    { value: "PI", label: "PI — Pressure indicator" },
  ],
};

const MODES: { value: string; label: string }[] = [
  { value: "select", label: "Select" },
  { value: "mark-symbol", label: "Mark symbol" },
  { value: "draw-edge", label: "Draw edge" },
];

// ──────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────

function describeBinding(b: ShortcutBinding): string {
  switch (b.action) {
    case "select-class":
      return `Select class: ${b.entity_class ?? "?"} / ${b.sub_class ?? "?"}`;
    case "mode":
      return `Mode → ${b.mode ?? "?"}`;
    case "cancel":
      return "Cancel current action";
    case "delete-selected":
      return "Delete selected";
    default:
      return b.action;
  }
}

function describeKey(k: string): string {
  if (k === " ") return "Space";
  if (k.length === 1) return k.toUpperCase();
  return k;
}

// ──────────────────────────────────────────────────────────────────────────
// Component
// ──────────────────────────────────────────────────────────────────────────

export default function Shortcuts() {
  const { theme } = useTheme();
  const [draft, setDraft] = useState<ShortcutMap>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  // "Add new binding" row state.
  const [newKey, setNewKey] = useState("");
  const [newAction, setNewAction] = useState<string>("select-class");
  const [newEntityClass, setNewEntityClass] = useState<string>("valve");
  const [newSubClass, setNewSubClass] = useState<string>("BV");
  const [newMode, setNewMode] = useState<string>("select");
  const [pendingOverwrite, setPendingOverwrite] = useState(false);

  const loadShortcuts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const m = await getShortcuts();
      setDraft(m);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadShortcuts();
  }, [loadShortcuts]);

  const sortedKeys = useMemo(() => {
    return Object.keys(draft).sort((a, b) => {
      // Single-char keys first, alphabetically; multi-char keys after.
      if (a.length === 1 && b.length !== 1) return -1;
      if (a.length !== 1 && b.length === 1) return 1;
      return a.localeCompare(b);
    });
  }, [draft]);

  // Conflict detection for the add-row.
  const conflict = newKey !== "" && Object.prototype.hasOwnProperty.call(draft, newKey);

  function buildNewBinding(): ShortcutBinding | null {
    if (!newKey) return null;
    if (newAction === "select-class") {
      return {
        action: "select-class",
        entity_class: newEntityClass,
        sub_class: newSubClass,
      };
    }
    if (newAction === "mode") {
      return { action: "mode", mode: newMode };
    }
    return { action: newAction };
  }

  function handleAdd() {
    const binding = buildNewBinding();
    if (!binding) return;
    if (conflict && !pendingOverwrite) {
      setPendingOverwrite(true);
      return;
    }
    setDraft((cur) => ({ ...cur, [newKey]: binding }));
    setNewKey("");
    setPendingOverwrite(false);
  }

  function handleDelete(key: string) {
    setDraft((cur) => {
      const next = { ...cur };
      delete next[key];
      return next;
    });
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await patchShortcuts(draft);
      // Pull the merged-with-defaults view so the UI reflects backend truth
      // (a deleted user-override surfaces the default again).
      const merged = await getShortcuts();
      setDraft(merged);
      setSavedAt(Date.now());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    setResetting(true);
    setError(null);
    try {
      const defaults = await resetShortcuts();
      setDraft(defaults);
      setSavedAt(Date.now());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setResetting(false);
    }
  }

  // ──────────────────────────────────────────────────────────────────────
  // Render
  // ──────────────────────────────────────────────────────────────────────

  const borderColor = theme === "dark" ? "var(--ink-700)" : "var(--ink-200)";
  const dividerColor = theme === "dark" ? "var(--ink-800)" : "var(--ink-100)";
  const mutedFg = theme === "dark" ? "var(--ink-400)" : "var(--ink-500)";

  if (loading) {
    return <div style={{ padding: 32 }}>Loading shortcuts…</div>;
  }

  return (
    <div style={{ padding: 32, maxWidth: 1100, margin: "0 auto" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 24,
        }}
      >
        <h1 style={{ margin: 0 }}>Studio Shortcuts</h1>
        <button
          onClick={() => void handleReset()}
          disabled={resetting || saving}
          data-testid="shortcuts-reset"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "8px 14px",
            background: "transparent",
            border: `1px solid ${borderColor}`,
            borderRadius: "var(--r-2)",
            cursor: resetting ? "wait" : "pointer",
            color: "var(--fg)",
          }}
        >
          <RotateCcw size={14} /> Reset to Defaults
        </button>
      </div>

      <p style={{ color: mutedFg, marginBottom: 24 }}>
        These keyboard bindings apply only to Studio (the in-house annotation
        UI). Bindings are per-user — your teammates keep their own. Modifier
        chords (Ctrl/Alt/Cmd) are reserved for the browser and aren't
        configurable here.
      </p>

      {error && (
        <div
          style={{
            padding: 12,
            marginBottom: 16,
            background: "var(--error-soft)",
            color: "var(--error)",
            borderRadius: "var(--r-2)",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
          data-testid="shortcuts-error"
        >
          <AlertTriangle size={14} /> {error}
        </div>
      )}

      <section style={{ marginBottom: 32 }}>
        <h2 style={{ fontSize: 18, marginBottom: 12 }}>Current bindings</h2>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: `1px solid ${borderColor}` }}>
              <th style={{ padding: 8, width: 140 }}>Key</th>
              <th style={{ padding: 8 }}>Action</th>
              <th style={{ padding: 8, width: 100, textAlign: "right" }}>Edit</th>
            </tr>
          </thead>
          <tbody>
            {sortedKeys.length === 0 ? (
              <tr>
                <td colSpan={3} style={{ padding: 16, color: mutedFg }}>
                  No bindings.
                </td>
              </tr>
            ) : (
              sortedKeys.map((k) => (
                <tr
                  key={k}
                  style={{ borderBottom: `1px solid ${dividerColor}` }}
                  data-testid={`shortcuts-row-${k}`}
                >
                  <td style={{ padding: 8 }}>
                    <kbd
                      style={{
                        padding: "2px 8px",
                        background: "var(--bg-muted)",
                        border: `1px solid ${borderColor}`,
                        borderRadius: "var(--r-2)",
                        fontFamily: "monospace",
                      }}
                    >
                      {describeKey(k)}
                    </kbd>
                  </td>
                  <td style={{ padding: 8 }}>{describeBinding(draft[k])}</td>
                  <td style={{ padding: 8, textAlign: "right" }}>
                    <button
                      onClick={() => handleDelete(k)}
                      data-testid={`shortcuts-delete-${k}`}
                      title="Delete this binding"
                      style={{
                        background: "transparent",
                        border: "none",
                        color: "var(--error)",
                        cursor: "pointer",
                        padding: 4,
                      }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>

      <section
        style={{
          marginBottom: 24,
          padding: 16,
          border: `1px solid ${borderColor}`,
          borderRadius: "var(--r-3)",
        }}
      >
        <h2 style={{ fontSize: 18, marginTop: 0, marginBottom: 12 }}>Add new binding</h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1.4fr auto",
            gap: 12,
            alignItems: "center",
          }}
        >
          <div>
            <label style={{ display: "block", fontSize: 12, color: mutedFg, marginBottom: 4 }}>
              Press a key…
            </label>
            <input
              type="text"
              value={newKey === " " ? "Space" : newKey}
              readOnly
              data-testid="shortcuts-new-key"
              onKeyDown={(e) => {
                // Capture the actual key, NOT type text. This makes
                // "press a key to bind" the literal interaction.
                if (e.ctrlKey || e.altKey || e.metaKey) return;
                e.preventDefault();
                const k = e.key;
                if (k.length === 1) {
                  setNewKey(k.toLowerCase());
                  setPendingOverwrite(false);
                } else if (["Escape", "Delete", "Tab", "Enter", " "].includes(k)) {
                  setNewKey(k);
                  setPendingOverwrite(false);
                }
              }}
              placeholder="Click here, then press a key"
              style={{
                width: "100%",
                padding: "6px 10px",
                border: `1px solid ${borderColor}`,
                borderRadius: "var(--r-2)",
                background: "var(--surface)",
                color: "var(--fg)",
                fontFamily: "monospace",
              }}
            />
          </div>

          <div>
            <label style={{ display: "block", fontSize: 12, color: mutedFg, marginBottom: 4 }}>
              Action
            </label>
            <select
              value={newAction}
              onChange={(e) => setNewAction(e.target.value)}
              data-testid="shortcuts-new-action"
              style={{
                width: "100%",
                padding: "6px 10px",
                border: `1px solid ${borderColor}`,
                borderRadius: "var(--r-2)",
                background: "var(--surface)",
                color: "var(--fg)",
              }}
            >
              {ACTIONS.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>

            {newAction === "select-class" && (
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <select
                  value={newEntityClass}
                  onChange={(e) => {
                    setNewEntityClass(e.target.value);
                    const subs = SUB_CLASSES[e.target.value];
                    if (subs && subs.length > 0) setNewSubClass(subs[0].value);
                  }}
                  data-testid="shortcuts-new-entity-class"
                  style={{
                    flex: 1,
                    padding: "6px 10px",
                    border: `1px solid ${borderColor}`,
                    borderRadius: "var(--r-2)",
                    background: "var(--surface)",
                    color: "var(--fg)",
                  }}
                >
                  <option value="valve">Valve</option>
                  <option value="instrument">Instrument</option>
                </select>
                <select
                  value={newSubClass}
                  onChange={(e) => setNewSubClass(e.target.value)}
                  data-testid="shortcuts-new-sub-class"
                  style={{
                    flex: 2,
                    padding: "6px 10px",
                    border: `1px solid ${borderColor}`,
                    borderRadius: "var(--r-2)",
                    background: "var(--surface)",
                    color: "var(--fg)",
                  }}
                >
                  {(SUB_CLASSES[newEntityClass] ?? []).map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {newAction === "mode" && (
              <select
                value={newMode}
                onChange={(e) => setNewMode(e.target.value)}
                data-testid="shortcuts-new-mode"
                style={{
                  width: "100%",
                  marginTop: 8,
                  padding: "6px 10px",
                  border: `1px solid ${borderColor}`,
                  borderRadius: "var(--r-2)",
                  background: "var(--surface)",
                  color: "var(--fg)",
                }}
              >
                {MODES.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            )}
          </div>

          <button
            onClick={handleAdd}
            disabled={!newKey}
            data-testid="shortcuts-add"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 14px",
              background: conflict && pendingOverwrite ? "var(--warn)" : "var(--qong-purple)",
              color: "white",
              border: "none",
              borderRadius: "var(--r-2)",
              cursor: newKey ? "pointer" : "not-allowed",
              opacity: newKey ? 1 : 0.5,
              alignSelf: "end",
            }}
          >
            <Plus size={14} />
            {conflict && pendingOverwrite ? "Overwrite" : "Add"}
          </button>
        </div>

        {conflict && (
          <div
            style={{
              marginTop: 10,
              padding: 8,
              background: "var(--warn-soft)",
              color: "var(--warn)",
              borderRadius: "var(--r-2)",
              fontSize: 13,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
            data-testid="shortcuts-conflict"
          >
            <AlertTriangle size={14} />
            Key <strong style={{ margin: "0 4px" }}>{describeKey(newKey)}</strong> is already
            bound to <em>{describeBinding(draft[newKey])}</em>.
            {pendingOverwrite ? " Click Overwrite to replace." : " Click Add again to confirm overwrite."}
          </div>
        )}
      </section>

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, alignItems: "center" }}>
        {savedAt && (
          <span style={{ color: "var(--ok)", fontSize: 13 }} data-testid="shortcuts-saved">
            Saved.
          </span>
        )}
        <button
          onClick={() => void handleSave()}
          disabled={saving || resetting}
          data-testid="shortcuts-save"
          style={{
            padding: "10px 20px",
            background: "var(--qong-pink)",
            color: "white",
            border: "none",
            borderRadius: "var(--r-2)",
            cursor: saving ? "wait" : "pointer",
            fontWeight: 600,
          }}
        >
          {saving ? "Saving…" : "Save changes"}
        </button>
      </div>
    </div>
  );
}
