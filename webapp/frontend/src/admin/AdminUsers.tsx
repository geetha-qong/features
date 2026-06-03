import { useCallback, useEffect, useState } from "react";
import { Plus, Search } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import * as api from "./api";
import type { AdminUser, Role, Tier } from "./types";
import CreateUserModal from "./CreateUserModal";
import EditUserModal from "./EditUserModal";
import { formatDate, useUserTimezone } from "../util/datetime";

const ROLE_LABEL: Record<Role, string> = {
  user: "User",
  annotator: "Annotator",
  super_admin: "Super-admin",
};

const TIER_LABEL: Record<Tier, string> = {
  trial: "Trial",
  starter: "Starter",
  pro: "Pro",
  enterprise: "Enterprise",
};

export default function AdminUsers() {
  const { user: me } = useAuth();
  const tz = useUserTimezone();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listUsers();
      setUsers(data.users);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const filtered = users.filter((u) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      u.username.toLowerCase().includes(q) ||
      (u.email || "").toLowerCase().includes(q) ||
      u.role.toLowerCase().includes(q)
    );
  });

  const meId = me?.id ?? 0;

  return (
    <>
      <div className="projects-header">
        <div className="titlewrap">
          <span className="overline">Admin · Users</span>
          <h1>Users</h1>
          <p className="sub">Manage accounts, roles, credits, and tiers.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          <Plus size={14} strokeWidth={1.6} /> New User
        </button>
      </div>

      <div className="toolbar">
        <div className="input-with-icon search">
          <span className="ic" style={{ color: "var(--fg-3)" }}>
            <Search size={16} strokeWidth={1.6} />
          </span>
          <input
            className="input"
            placeholder="Search by username, email, role…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ height: 40 }}
            data-testid="admin-users-search"
          />
        </div>
        <div style={{ flex: 1 }} />
        <span className="props-sub">
          {filtered.length} of {users.length}
        </span>
      </div>

      {error && (
        <div
          style={{
            background: "var(--error-soft)",
            color: "var(--error)",
            padding: "12px 16px",
            borderRadius: 8,
            marginBottom: 16,
          }}
          role="alert"
        >
          {error}
        </div>
      )}

      {loading ? (
        <div className="empty-state">
          <h3>Loading users…</h3>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <h3>{users.length === 0 ? "No users yet" : "No matching users"}</h3>
        </div>
      ) : (
        <div className="projects-list" data-testid="admin-users-table">
          <div className="list-head" style={{ gridTemplateColumns: "2fr 1.2fr 1fr 1fr 0.8fr 0.8fr" }}>
            <div>User</div>
            <div>Email</div>
            <div>Role</div>
            <div>Tier</div>
            <div>Credits</div>
            <div>Status</div>
          </div>
          {filtered.map((u) => {
            const isSelf = u.id === meId;
            return (
              <div
                key={u.id}
                className="list-row"
                style={{ gridTemplateColumns: "2fr 1.2fr 1fr 1fr 0.8fr 0.8fr", cursor: "pointer" }}
                onClick={() => setEditing(u)}
                data-testid={`admin-user-row-${u.username}`}
              >
                <div>
                  <div className="name">
                    {u.username}
                    {isSelf && (
                      <span
                        className="qs-tag"
                        style={{
                          marginLeft: 8,
                          fontSize: 10,
                          color: "var(--qong-magenta)",
                          padding: "2px 6px",
                          border: "1px solid var(--qong-magenta)",
                          borderRadius: 4,
                        }}
                      >
                        YOU
                      </span>
                    )}
                  </div>
                  <div className="sub">
                    {u.created_at ? `Joined ${formatDate(u.created_at, tz)}` : ""}
                  </div>
                </div>
                <div className="cell-client">{u.email || "—"}</div>
                <div>{ROLE_LABEL[u.role]}</div>
                <div>{TIER_LABEL[u.tier]}</div>
                <div className="mono">{u.credits_remaining}</div>
                <div>
                  <span
                    className={`status-pill ${u.is_active ? "ok" : "draft"}`}
                    style={{ position: "static" }}
                  >
                    <span className="dot"></span>
                    {u.is_active ? "Active" : "Inactive"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <CreateUserModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => {
          setShowCreate(false);
          void refresh();
        }}
      />
      <EditUserModal
        user={editing}
        currentUserId={meId}
        onClose={() => setEditing(null)}
        onChanged={refresh}
      />
    </>
  );
}
