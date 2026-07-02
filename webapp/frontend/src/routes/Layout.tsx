import { useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { Search, Bell, ChevronRight, Shield, BellOff } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import AccountMenu from "../components/AccountMenu";
import BrandRow from "../components/BrandRow";

// `/` no longer renders any UI (RootRedirect bounces to /dashboard or /signin).
// /signin is full-bleed (no app header) since the user hasn't picked a workspace yet.
const FULL_BLEED_EXACT = new Set(["/signin"]);
const FULL_BLEED_PATTERNS = [/^\/jobs\/[^/]+(\/review)?\/?$/];

function isFullBleed(pathname: string): boolean {
  if (FULL_BLEED_EXACT.has(pathname)) return true;
  return FULL_BLEED_PATTERNS.some((re) => re.test(pathname));
}

export default function Layout() {
  const loc = useLocation();
  const { user } = useAuth();
  const [notifOpen, setNotifOpen] = useState(false);
  const notifRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!notifOpen) return;
    function onDocDown(e: MouseEvent) {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) setNotifOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setNotifOpen(false);
    }
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [notifOpen]);

  if (isFullBleed(loc.pathname)) {
    return <Outlet />;
  }

  const seg = loc.pathname.split("/").filter(Boolean)[0] || "dashboard";
  const breadcrumbLabel = seg.charAt(0).toUpperCase() + seg.slice(1);

  return (
    <div className="app-root">
      <header className="app-nav">
        <Link to="/dashboard" style={{ textDecoration: "none" }}>
          <BrandRow size={26} />
        </Link>
        <div className="nav-divider"></div>
        <div className="breadcrumbs">
          <span>Workspace</span>
          <ChevronRight size={12} strokeWidth={1.6} />
          <span className="current">{breadcrumbLabel}</span>
        </div>
        <div className="spacer"></div>
        <div className="nav-actions">
          <button className="icon-btn" title="Search">
            <Search size={18} strokeWidth={1.6} />
          </button>
          <div className="settings-wrap" ref={notifRef} style={{ position: "relative" }}>
            <button
              className="icon-btn"
              title="Notifications"
              onClick={() => setNotifOpen((v) => !v)}
              aria-expanded={notifOpen}
            >
              <Bell size={18} strokeWidth={1.6} />
            </button>
            {notifOpen && (
              <div className="settings-pop" role="dialog" aria-label="Notifications" style={{ minWidth: 300, right: 0, left: "auto" }}>
                <div className="settings-head" style={{ padding: "12px 14px 10px" }}>
                  <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15, color: "var(--fg-1)" }}>
                    Notifications
                  </div>
                </div>
                <div className="settings-divider"></div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8, padding: "28px 16px 32px", color: "var(--fg-3)" }}>
                  <BellOff size={28} strokeWidth={1.4} style={{ opacity: 0.45 }} />
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg-2)" }}>No notifications</div>
                  <div style={{ fontSize: 12, textAlign: "center", lineHeight: 1.5 }}>
                    You're all caught up. We'll notify you when something needs your attention.
                  </div>
                </div>
              </div>
            )}
          </div>
          {user?.role === "super_admin" && (
            <Link
              to="/admin/users"
              className="icon-btn"
              title="Admin"
              style={{ display: "inline-flex", alignItems: "center", justifyContent: "center" }}
            >
              <Shield size={18} strokeWidth={1.6} />
            </Link>
          )}
          <div style={{ width: 8 }}></div>
          {user ? (
            <AccountMenu />
          ) : (
            <Link to="/signin" className="btn btn-secondary btn-sm">
              Sign in
            </Link>
          )}
        </div>
      </header>
      <Outlet />
    </div>
  );
}
