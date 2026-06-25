import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Copy, Trash2, ArrowLeft } from "lucide-react";
import { createApiKey, listApiKeys, revokeApiKey } from "../account/api";
import type { ApiKey, CreatedApiKey } from "../account/types";
import { formatDateTime, useUserTimezone } from "../util/datetime";

export default function AccountApiKeys() {
  const tz = useUserTimezone();
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [revealed, setRevealed] = useState<CreatedApiKey | null>(null);
  const [copied, setCopied] = useState(false);

  function refresh() {
    setLoading(true);
    setError(null);
    listApiKeys()
      .then((res) => setKeys(res.keys))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const k = await createApiKey(name.trim());
      setRevealed(k);
      setName("");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  }

  async function onRevoke(id: number) {
    if (!confirm("Revoke this API key? Any service using it will stop working immediately.")) return;
    setError(null);
    try {
      await revokeApiKey(id);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function copyKey() {
    if (!revealed) return;
    try {
      await navigator.clipboard.writeText(revealed.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked */
    }
  }

  return (
    <div style={{ padding: 32, maxWidth: 900, margin: "0 auto" }}>
      <Link to="/account" style={{ display: "inline-flex", alignItems: "center", gap: 4, marginBottom: 12 }}>
        <ArrowLeft size={14} /> Back to Account
      </Link>
      <h1 style={{ marginTop: 0, marginBottom: 24 }}>API Keys</h1>

      {error && (
        <div style={{ background: "#fee", border: "1px solid #fbb", color: "#900", padding: 12, borderRadius: 6, marginBottom: 16 }}>
          {error}
        </div>
      )}

      {revealed && (
        <div style={{ background: "#fffbe6", border: "1px solid #f0c674", padding: 16, borderRadius: 6, marginBottom: 24 }}>
          <h3 style={{ marginTop: 0 }}>New key created — copy it now</h3>
          <p style={{ marginTop: 0, color: "#664" }}>
            This is the only time the full key will be displayed. Save it somewhere safe.
          </p>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <code style={{ flex: 1, background: "#fff", padding: 10, border: "1px solid #ddd", borderRadius: 4, fontFamily: "monospace", overflow: "auto" }}>
              {revealed.key}
            </code>
            <button onClick={copyKey} style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "8px 12px" }}>
              <Copy size={14} /> {copied ? "Copied!" : "Copy"}
            </button>
          </div>
          <button
            onClick={() => setRevealed(null)}
            style={{ marginTop: 12, padding: "6px 10px", background: "#eee", border: "1px solid #ccc", borderRadius: 4 }}
          >
            I've saved it — dismiss
          </button>
        </div>
      )}

      <section style={{ marginBottom: 32 }}>
        <h2 style={{ fontSize: 16 }}>Create a new key</h2>
        <form onSubmit={onCreate} style={{ display: "flex", gap: 8 }}>
          <input
            type="text"
            placeholder="Key name (e.g. CI pipeline, local laptop)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={64}
            style={{ flex: 1, padding: 8, border: "1px solid #ccc", borderRadius: 4 }}
          />
          <button
            type="submit"
            disabled={creating || !name.trim()}
            style={{ padding: "8px 16px", background: "#0070f3", color: "#fff", border: "none", borderRadius: 4 }}
          >
            {creating ? "Creating…" : "Create key"}
          </button>
        </form>
      </section>

      <section>
        <h2 style={{ fontSize: 16 }}>Active keys</h2>
        {loading ? (
          <p>Loading…</p>
        ) : keys.length === 0 ? (
          <p style={{ color: "#666" }}>You don't have any API keys yet.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>
                <th style={{ padding: 8 }}>Name</th>
                <th style={{ padding: 8 }}>Prefix</th>
                <th style={{ padding: 8 }}>Created</th>
                <th style={{ padding: 8 }}>Last used</th>
                <th style={{ padding: 8 }}></th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id} style={{ borderBottom: "1px solid #f0f0f0" }}>
                  <td style={{ padding: 8 }}>{k.name}</td>
                  <td style={{ padding: 8, fontFamily: "monospace" }}>{k.key_prefix}…</td>
                  <td style={{ padding: 8 }}>{formatDateTime(k.created_at, tz)}</td>
                  <td style={{ padding: 8 }}>{formatDateTime(k.last_used_at, tz)}</td>
                  <td style={{ padding: 8, textAlign: "right" }}>
                    <button
                      onClick={() => onRevoke(k.id)}
                      style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "4px 8px", background: "#fee", color: "#900", border: "1px solid #fbb", borderRadius: 4 }}
                    >
                      <Trash2 size={12} /> Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
