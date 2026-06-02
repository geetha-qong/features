import { Link, Outlet, useLocation } from "react-router-dom";
import { Search, Bell, ChevronRight, Shield } from "lucide-react";
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
          <button className="icon-btn" title="Notifications">
            <Bell size={18} strokeWidth={1.6} />
          </button>
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
