import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Settings,
  Sun,
  Moon,
  CheckCircle2,
  ChevronRight,
  User,
  Keyboard,
  Bell,
} from "lucide-react";
import { useTheme } from "../theme/ThemeContext";

export default function SettingsMenu({ variant = "light" }: { variant?: "light" | "dark-chrome" }) {
  const { theme, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();

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

  const isDark = theme === "dark";

  return (
    <div className={`settings-wrap ${variant === "dark-chrome" ? "is-dark-chrome" : ""}`} ref={rootRef}>
      <button
        className={variant === "dark-chrome" ? "icon-btn studio-ic" : "icon-btn"}
        title="Settings"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <Settings size={18} strokeWidth={1.6} />
      </button>
      {open && (
        <div className="settings-pop" role="menu">
          <div className="settings-head">
            <span className="overline">Preferences</span>
          </div>

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
              <User size={14} strokeWidth={1.6} />
              <span>Account</span>
              <ChevronRight size={12} strokeWidth={1.6} />
            </button>
            <button className="settings-item" onClick={() => { setOpen(false); navigate("/account/shortcuts"); }}>
              <Keyboard size={14} strokeWidth={1.6} />
              <span>Shortcuts</span>
              <ChevronRight size={12} strokeWidth={1.6} />
            </button>
            <button className="settings-item" onClick={() => { setOpen(false); navigate("/account"); }}>
              <Bell size={14} strokeWidth={1.6} />
              <span>Notifications</span>
              <ChevronRight size={12} strokeWidth={1.6} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
