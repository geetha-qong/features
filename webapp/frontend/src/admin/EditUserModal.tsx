import { useEffect, useState } from "react";
import { Trash2, X } from "lucide-react";
import * as api from "./api";
import type { AdminUser, Role, Tier } from "./types";

interface Props {
  user: AdminUser | null;
  currentUserId: number;
  onClose: () => void;
  onChanged: () => void;
}

export default function EditUserModal({ user, currentUserId, onClose, onChanged }: Props) {
  const [role, setRole] = useState<Role>("user");
  const [tier, setTier] = useState<Tier>("trial");
  const [grantAmount, setGrantAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user) {
      setRole(user.role);
      setTier(user.tier);
      setGrantAmount("");
      setError(null);
    }
  }, [user]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && user) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [user, onClose]);

  if (!user) return null;

  const isSelf = user.id === currentUserId;

  async function runAction<T>(fn: () => Promise<T>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" data-testid="edit-user-modal" style={{ maxWidth: 600 }}>
        <div className="modal-head">
          <span className="overline">Admin · Edit Account</span>
          <h2>{user.username}</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            <X size={16} strokeWidth={1.6} />
          </button>
        </div>
        <div className="modal-body">
          {/* Status */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
            <div>
              <div className="overline" style={{ marginBottom: 4 }}>Status</div>
              <span className={`status-pill ${user.is_active ? "ok" : "draft"}`} style={{ position: "static" }}>
                <span className="dot"></span>
                {user.is_active ? "Active" : "Inactive"}
              </span>
            </div>
            {user.is_active ? (
              <button
                className="btn btn-secondary btn-sm"
                disabled={busy || isSelf}
                onClick={() => runAction(() => api.deactivateUser(user.id))}
                data-testid="edit-user-deactivate"
              >
                Deactivate
              </button>
            ) : (
              <button
                className="btn btn-primary btn-sm"
                disabled={busy}
                onClick={() => runAction(() => api.activateUser(user.id))}
                data-testid="edit-user-activate"
              >
                Activate
              </button>
            )}
          </div>

          {/* Role */}
          <div className="field" style={{ marginBottom: 18 }}>
            <label className="field-label">Role</label>
            <div style={{ display: "flex", gap: 8 }}>
              <select
                className="input"
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
                disabled={isSelf}
                data-testid="edit-user-role"
              >
                <option value="user">User</option>
                <option value="annotator">Annotator</option>
                <option value="super_admin">Super-admin</option>
              </select>
              <button
                className="btn btn-secondary btn-sm"
                disabled={busy || isSelf || role === user.role}
                onClick={() => runAction(() => api.changeRole(user.id, role))}
              >
                Apply
              </button>
            </div>
            {isSelf && (
              <div className="caption" style={{ color: "var(--fg-3)", marginTop: 4 }}>
                You cannot change your own role.
              </div>
            )}
          </div>

          {/* Tier */}
          <div className="field" style={{ marginBottom: 18 }}>
            <label className="field-label">Tier</label>
            <div style={{ display: "flex", gap: 8 }}>
              <select
                className="input"
                value={tier}
                onChange={(e) => setTier(e.target.value as Tier)}
                data-testid="edit-user-tier"
              >
                <option value="trial">Trial</option>
                <option value="starter">Starter</option>
                <option value="pro">Pro</option>
                <option value="enterprise">Enterprise</option>
              </select>
              <button
                className="btn btn-secondary btn-sm"
                disabled={busy || tier === user.tier}
                onClick={() => runAction(() => api.changeTier(user.id, tier))}
              >
                Apply
              </button>
            </div>
          </div>

          {/* Credits */}
          <div className="field" style={{ marginBottom: 18 }}>
            <label className="field-label">
              Grant credits <span className="caption">(current balance: {user.credits_remaining})</span>
            </label>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                className="input"
                type="number"
                min={1}
                max={10000}
                value={grantAmount}
                onChange={(e) => setGrantAmount(e.target.value)}
                placeholder="e.g. 100"
                data-testid="edit-user-grant-amount"
              />
              <button
                className="btn btn-primary btn-sm"
                disabled={busy || !grantAmount || Number(grantAmount) <= 0}
                onClick={() =>
                  runAction(async () => {
                    await api.grantCredits(user.id, Number(grantAmount));
                    setGrantAmount("");
                  })
                }
                data-testid="edit-user-grant-submit"
              >
                Grant
              </button>
            </div>
          </div>

          {/* Delete */}
          <div
            style={{
              marginTop: 24,
              padding: "16px",
              border: "1px solid var(--error)",
              borderRadius: 8,
              background: "var(--error-soft)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <strong style={{ color: "var(--error)" }}>Danger zone</strong>
                <div className="caption" style={{ color: "var(--fg-2)" }}>
                  Permanently delete this account. This action cannot be undone.
                </div>
              </div>
              <button
                className="btn btn-secondary btn-sm"
                style={{ color: "var(--error)", borderColor: "var(--error)" }}
                disabled={busy || isSelf}
                onClick={() => {
                  if (!confirm(`Delete user '${user.username}'? This cannot be undone.`)) return;
                  void runAction(async () => {
                    await api.deleteUser(user.id);
                    onClose();
                  });
                }}
                data-testid="edit-user-delete"
              >
                <Trash2 size={13} strokeWidth={1.6} /> Delete
              </button>
            </div>
          </div>

          {error && (
            <div
              className="err"
              style={{ color: "var(--error)", marginTop: 16, fontSize: 13 }}
              role="alert"
            >
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
