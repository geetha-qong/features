import { Link, Outlet, useLocation } from "react-router-dom";
import qongMark from "../design/assets/qong-mark.png";
import { useAuth } from "../auth/AuthContext";

const FULL_BLEED_ROUTES = new Set(["/signin"]);

export default function Layout() {
  const loc = useLocation();
  const { user, logout } = useAuth();

  if (FULL_BLEED_ROUTES.has(loc.pathname)) {
    return <Outlet />;
  }

  const linkStyle = (path: string): React.CSSProperties => ({
    color: loc.pathname === path ? "#8B3FCE" : "#4B5563",
    textDecoration: "none",
    fontWeight: loc.pathname === path ? 600 : 500,
    padding: "6px 10px",
    borderRadius: 6,
    transition: "background 0.12s",
  });
  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          padding: "16px 32px",
          borderBottom: "1px solid #E5E7EB",
          gap: 32,
        }}
      >
        <Link to="/" style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none" }}>
          <img src={qongMark} alt="QONG" style={{ width: 28, height: 28 }} />
          <span className="qs-display" style={{ fontSize: 18, color: "#0A0B14" }}>
            QONG <span className="qs-gradient-text">STUDIO</span>
          </span>
        </Link>
        <nav style={{ display: "flex", gap: 4, marginLeft: "auto", alignItems: "center" }}>
          <Link to="/dashboard" style={linkStyle("/dashboard")}>Dashboard</Link>
          <Link to="/projects" style={linkStyle("/projects")}>Projects</Link>
          {user ? (
            <>
              <span style={{ color: "#4B5563", fontSize: 14, padding: "6px 10px" }}>
                {user.email}
              </span>
              <button
                onClick={async () => { await logout(); }}
                style={{
                  background: "none",
                  border: "1px solid #E5E7EB",
                  padding: "6px 14px",
                  borderRadius: 6,
                  cursor: "pointer",
                  color: "#4B5563",
                  fontSize: 14,
                }}
              >
                Sign out
              </button>
            </>
          ) : (
            <Link to="/signin" style={linkStyle("/signin")}>Sign in</Link>
          )}
        </nav>
      </header>
      <main style={{ flex: 1, padding: "48px 32px", maxWidth: 1200, margin: "0 auto", width: "100%" }}>
        <Outlet />
      </main>
    </div>
  );
}
