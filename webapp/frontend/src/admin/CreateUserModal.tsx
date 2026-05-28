import { useEffect, useState } from "react";
import { ArrowRight, X } from "lucide-react";
import * as api from "./api";
import type { Role } from "./types";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export default function CreateUserModal({ open, onClose, onCreated }: Props) {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("user");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setUsername("");
      setEmail("");
      setPassword("");
      setRole("user");
      setError(null);
    }
  }, [open]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && open) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.createUser({ username: username.trim(), email: email.trim(), password, role });
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form className="modal" onSubmit={submit} data-testid="create-user-form">
        <div className="modal-head">
          <span className="overline">Admin · New Account</span>
          <h2>Create User</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            <X size={16} strokeWidth={1.6} />
          </button>
        </div>
        <div className="modal-body">
          <div className="field">
            <label className="field-label">Username</label>
            <input
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="alice"
              required
              autoFocus
              data-testid="create-user-username"
            />
          </div>
          <div className="field">
            <label className="field-label">Email (optional)</label>
            <input
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="alice@operator.com"
            />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
            <div className="field">
              <label className="field-label">Password</label>
              <input
                className="input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                data-testid="create-user-password"
              />
            </div>
            <div className="field">
              <label className="field-label">Role</label>
              <select
                className="input"
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
                data-testid="create-user-role"
              >
                <option value="user">User</option>
                <option value="annotator">Annotator</option>
                <option value="super_admin">Super-admin</option>
              </select>
            </div>
          </div>
          {error && (
            <div
              className="err"
              style={{ color: "var(--error)", marginTop: 4, fontSize: 13 }}
              role="alert"
            >
              {error}
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!username.trim() || !password || submitting}
          >
            {submitting ? "Creating…" : "Create User"}
            <ArrowRight size={14} strokeWidth={1.6} />
          </button>
        </div>
      </form>
    </div>
  );
}
