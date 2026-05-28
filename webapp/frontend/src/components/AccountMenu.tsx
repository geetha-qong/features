import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bell,
  CheckCircle2,
  ChevronRight,
  Keyboard,
  LogOut,
  Moon,
  Sun,
  User as UserIcon,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useTheme } from "../theme/ThemeContext";

/**
 * Avatar-driven account menu in the main nav.
 *
 * Clicking the avatar opens a popover with:
 *  - Current account info (username + email)
 *  - Theme toggle (light/dark) — moved from the separate gear icon
 *  - Account / Shortcuts / Notifications shortcuts (placeholders)
 *  - Sign Out
 *
 * The standalone gear `<SettingsMenu />` was removed from the nav per
 * user feedback — clicking the avatar to log out was a footgun.
 */
export default function AccountMenu() {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onDocDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;

  const isDark = theme === "dark";
  const initials = user.username.slice(0, 2).toUpperCase();

  async function onSignOut() {
    setOpen(false);
    await logout();
    navigate("/signin", { replace: true });
  }

  return (
    <div className="settings-wrap" ref={rootRef}>
      <button
        className="avatar"
        title={user.username}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          cursor: "pointer",
          border: "none",
          padding: 0,
          font: "inherit",
        }}
      >
        {initials}
      </button>
      {open && (
        <div className="settings-pop" role="menu" style={{ minWidth: 280 }}>
          <div className="settings-head" style={{ padding: "12px 14px 8px" }}>
            <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15, color: "var(--fg-1)" }}>
              {user.username}
            </div>
            {user.email && user.email !== user.username && (
              <div className="caption" style={{ color: "var(--fg-3)", marginTop: 2 }}>
                {user.email}
              </div>
            )}
            <div className="caption" style={{ color: "var(--qong-magenta)", marginTop: 4, textTransform: "uppercase", letterSpacing: "0.1em", fontSize: 10, fontWeight: 700 }}>
              {user.role.replace("_", " ")}
            </div>
          </div>

          <div className="settings-divider"></div>

          <div className="settings-section">
            <div className="settings-toggle-row">
              <div className="settings-label">
                {isDark ? <Moon size={14} strokeWidth={1.6} /> : <Sun size={14} strokeWidth={1.6} />}
                <div>
                  <div className="t1">Appearance</div>
                  <div className="t2">{isDark ? "Dark mode" : "Light mode"}</div>
                </div>
              </div>
              <button
                role="switch"
                aria-checked={isDark}
                aria-label="Toggle dark mode"
                className={`tswitch ${isDark ? "on" : ""}`}
                onClick={toggle}
              >
                <span className="tswitch-thumb">
                  {isDark ? <Moon size={10} strokeWidth={1.6} /> : <Sun size={10} strokeWidth={1.6} />}
                </span>
              </button>
            </div>
            <div className="settings-hint">
              <CheckCircle2 size={11} strokeWidth={1.6} />
              <span>Saved to this device</span>
            </div>
          </div>

          <div className="settings-divider"></div>

          <div className="settings-section">
            <button className="settings-item" onClick={() => { setOpen(false); navigate("/account"); }}>
              <UserIcon size={14} strokeWidth={1.6} />
              <span>Account</span>
              <ChevronRight size={12} strokeWidth={1.6} />
            </button>
            <button className="settings-item">
              <Keyboard size={14} strokeWidth={1.6} />
              <span>Shortcuts</span>
              <ChevronRight size={12} strokeWidth={1.6} />
            </button>
            <button className="settings-item">
              <Bell size={14} strokeWidth={1.6} />
              <span>Notifications</span>
              <ChevronRight size={12} strokeWidth={1.6} />
            </button>
          </div>

          <div className="settings-divider"></div>

          <div className="settings-section">
            <button
              className="settings-item"
              onClick={onSignOut}
              data-testid="account-menu-signout"
              style={{ color: "var(--error)" }}
            >
              <LogOut size={14} strokeWidth={1.6} />
              <span>Sign out</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
