import { NavLink, Outlet } from "react-router-dom";
import {
  Activity,
  CreditCard,
  GitBranch,
  Inbox,
  LayoutDashboard,
  Tags,
  Users,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";

const NAV: Array<{ to: string; label: string; icon: typeof Users }> = [
  { to: "/admin/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/admin/users", label: "Users", icon: Users },
  { to: "/admin/feedback", label: "Feedback", icon: Inbox },
  { to: "/admin/credits", label: "Credits", icon: CreditCard },
  { to: "/admin/plans", label: "Plans", icon: Tags },
  { to: "/admin/label-studio", label: "Label Studio", icon: GitBranch },
];

export default function AdminLayout() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <main className="empty-state" style={{ padding: "48px 32px" }}>
        <Activity size={28} strokeWidth={1.6} />
        <h3>Loading…</h3>
      </main>
    );
  }

  if (!user || user.role !== "super_admin") {
    return (
      <main className="empty-state" style={{ padding: "48px 32px" }}>
        <h3>403 — Super-admin access required</h3>
        <p>
          This area is restricted to administrators. Return to the{" "}
          <NavLink to="/dashboard" style={{ color: "var(--qong-magenta)" }}>
            Dashboard
          </NavLink>
          .
        </p>
      </main>
    );
  }

  return (
    <div className="projects-shell">
      <aside className="projects-sidebar">
        <div className="sidebar-section">
          <div className="head">Admin</div>
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => `sidebar-item ${isActive ? "active" : ""}`}
            >
              <Icon size={16} strokeWidth={1.6} />
              <span>{label}</span>
            </NavLink>
          ))}
        </div>
      </aside>
      <main className="projects-main">
        <Outlet />
      </main>
    </div>
  );
}
