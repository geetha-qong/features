import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Lock, User, ShieldCheck } from "lucide-react";
import qongMark from "../design/assets/qong-mark.png";
import { useAuth } from "../auth/AuthContext";

const BRAND_GRADIENT =
  "linear-gradient(90deg, #2E3FBE 0%, #5347CC 25%, #8B3FCE 50%, #C73FBE 100%)";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [keepSignedIn, setKeepSignedIn] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const { login } = useAuth();
  const navigate = useNavigate();

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password, keepSignedIn);
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", minHeight: "100vh" }}>
      <LeftPanel />
      <RightPanel
        username={username}
        setUsername={setUsername}
        password={password}
        setPassword={setPassword}
        keepSignedIn={keepSignedIn}
        setKeepSignedIn={setKeepSignedIn}
        onSubmit={onSubmit}
        error={error}
        submitting={submitting}
      />
    </div>
  );
}

function LeftPanel() {
  const demoTags: Array<[string, string]> = [
    ["PT-101", "Press Xmtr"],
    ["FT-201", "Flow Xmtr"],
    ["LT-301", "Level Xmtr"],
    ["TT-401", "Temp Xmtr"],
    ["V-102", "Gate · 4″"],
    ["V-101", "Ball · 2″"],
  ];
  return (
    <aside
      style={{
        background: "#0A0B14",
        color: "#ECEEF5",
        padding: "48px 64px",
        display: "flex",
        flexDirection: "column",
        position: "relative",
      }}
    >
      <header style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 80 }}>
        <img src={qongMark} alt="QONG" style={{ width: 36, height: 36 }} />
        <span className="qs-display" style={{ fontSize: 22, color: "#ECEEF5" }}>
          QONG <span className="qs-gradient-text">STUDIO</span>
        </span>
      </header>

      <section style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", maxWidth: 540 }}>
        <div className="qs-overline" style={{ color: "#C73FBE", marginBottom: 24 }}>
          Next-Engineered for Oil &amp; Gas
        </div>
        <h1 className="qs-display" style={{ fontSize: 64, margin: 0, lineHeight: 0.95, color: "#ECEEF5" }}>
          READ YOUR{" "}
          <span className="qs-gradient-text">P&amp;ID</span>.<br />
          GENERATE THE REST.
        </h1>
        <p style={{ marginTop: 24, fontSize: 16, color: "#9CA3AF", maxWidth: 460, lineHeight: 1.55 }}>
          QONG Studio extracts instruments, valves, lines and tags directly
          from your drawings — then keeps every deliverable in sync as
          revisions land.
        </p>

        <div
          style={{
            marginTop: 56,
            background: "#13141F",
            borderRadius: 12,
            padding: "20px 22px",
            border: "1px solid #1F2030",
            maxWidth: 460,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
            <span className="qs-overline" style={{ color: "#6B7280", fontSize: 11 }}>
              Live Extraction · Demo
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#34D399" }}>
              <span
                aria-hidden="true"
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: "#34D399",
                  boxShadow: "0 0 8px #34D399",
                  animation: "qs-pulse 1.6s ease-in-out infinite",
                  display: "inline-block",
                }}
              />
              Scanning
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            {demoTags.map(([tag, label]) => (
              <div
                key={tag}
                style={{
                  background: "#0A0B14",
                  padding: "10px 12px",
                  borderRadius: 8,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  border: "1px solid #1F2030",
                }}
              >
                <span className="qs-tag" style={{ color: "#C73FBE", fontSize: 13 }}>{tag}</span>
                <span style={{ color: "#6B7280", fontSize: 11 }}>{label}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 48, fontSize: 12, color: "#4B5563" }}>
        <span className="qs-tag" style={{ fontSize: 11 }}>v1.0 · build 0427</span>
        <span
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "6px 12px",
            border: "1px solid #1F2030",
            borderRadius: 999,
            color: "#22D3EE",
            background: "rgba(34, 211, 238, 0.06)",
            fontSize: 11,
          }}
          className="qs-overline"
        >
          <span
            aria-hidden="true"
            style={{ width: 6, height: 6, borderRadius: "50%", background: "#22D3EE", display: "inline-block" }}
          />
          Encrypted · Air-Gapped
        </span>
      </footer>

      <style>{`
        @keyframes qs-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.55; transform: scale(1.15); }
        }
      `}</style>
    </aside>
  );
}

interface RightPanelProps {
  username: string;
  setUsername: (v: string) => void;
  password: string;
  setPassword: (v: string) => void;
  keepSignedIn: boolean;
  setKeepSignedIn: (v: boolean) => void;
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  error: string | null;
  submitting: boolean;
}

function RightPanel(p: RightPanelProps) {
  return (
    <section
      style={{
        background: "#FFFFFF",
        padding: "48px 64px",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
      }}
    >
      <form onSubmit={p.onSubmit} style={{ maxWidth: 420, width: "100%", margin: "0 auto" }}>
        <h1 className="qs-display" style={{ fontSize: 48, margin: 0, color: "#0A0B14" }}>
          SIGN IN
        </h1>
        <p style={{ marginTop: 8, color: "#6B7280", fontSize: 15 }}>
          Access your engineering workspace.
        </p>

        <FieldGroup
          label="Username"
          icon={<User size={18} strokeWidth={1.8} color="#9CA3AF" />}
          input={
            <input
              type="text"
              value={p.username}
              onChange={(e) => p.setUsername(e.target.value)}
              placeholder="your-username"
              autoComplete="username"
              required
              style={inputStyle}
            />
          }
          marginTop={32}
        />

        <FieldGroup
          label="Password"
          icon={<Lock size={18} strokeWidth={1.8} color="#9CA3AF" />}
          input={
            <input
              type="password"
              value={p.password}
              onChange={(e) => p.setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              required
              style={inputStyle}
            />
          }
          marginTop={20}
        />

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: 16,
            fontSize: 13,
          }}
        >
          <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", color: "#4B5563" }}>
            <input
              type="checkbox"
              checked={p.keepSignedIn}
              onChange={(e) => p.setKeepSignedIn(e.target.checked)}
              style={{ accentColor: "#8B3FCE", width: 16, height: 16, cursor: "pointer" }}
            />
            Keep me signed in
          </label>
          <a href="#" style={{ color: "#8B3FCE", textDecoration: "none", fontWeight: 500 }}>
            Forgot password?
          </a>
        </div>

        <button
          type="submit"
          disabled={p.submitting}
          style={{
            marginTop: 28,
            width: "100%",
            background: p.submitting
              ? "linear-gradient(90deg, #6B7280 0%, #9CA3AF 100%)"
              : BRAND_GRADIENT,
            color: "#FFFFFF",
            border: "none",
            padding: "16px 24px",
            borderRadius: 10,
            fontSize: 15,
            fontWeight: 600,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            cursor: p.submitting ? "not-allowed" : "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            boxShadow: p.submitting ? "none" : "0 4px 12px rgba(139, 63, 206, 0.25)",
            transition: "transform 0.08s, box-shadow 0.12s",
            opacity: p.submitting ? 0.75 : 1,
          }}
          onMouseDown={(e) => {
            if (!p.submitting) e.currentTarget.style.transform = "scale(0.985)";
          }}
          onMouseUp={(e) => {
            e.currentTarget.style.transform = "scale(1)";
          }}
        >
          {p.submitting ? "Signing in…" : <>Sign In <ArrowRight size={18} strokeWidth={2.2} /></>}
        </button>

        {p.error && (
          <div
            role="alert"
            style={{
              marginTop: 16,
              padding: "12px 14px",
              background: "#FEF2F2",
              border: "1px solid #FECACA",
              borderRadius: 8,
              color: "#B91C1C",
              fontSize: 13,
            }}
          >
            {p.error}
          </div>
        )}

        <div
          style={{
            marginTop: 24,
            padding: 18,
            border: "1px solid #E5E7EB",
            borderRadius: 12,
            display: "flex",
            gap: 14,
            background: "#F9FAFB",
          }}
        >
          <ShieldCheck size={22} strokeWidth={1.6} color="#8B3FCE" style={{ flexShrink: 0, marginTop: 2 }} />
          <div style={{ fontSize: 13, color: "#4B5563", lineHeight: 1.55 }}>
            <div style={{ fontWeight: 600, color: "#0A0B14", marginBottom: 2 }}>
              Invite-only access
            </div>
            QONG Studio is in private beta. Need an account?{" "}
            <Link to="/" style={{ color: "#8B3FCE", fontWeight: 600, textDecoration: "none" }}>
              Request access
            </Link>
            .
          </div>
        </div>
      </form>
    </section>
  );
}

interface FieldGroupProps {
  label: string;
  icon: React.ReactNode;
  input: React.ReactNode;
  marginTop?: number;
}

function FieldGroup(p: FieldGroupProps) {
  return (
    <div style={{ marginTop: p.marginTop ?? 0 }}>
      <div
        className="qs-overline"
        style={{ fontSize: 11, color: "#6B7280", marginBottom: 8, letterSpacing: "0.12em" }}
      >
        {p.label}
      </div>
      <div
        style={{
          position: "relative",
          display: "flex",
          alignItems: "center",
        }}
      >
        <span style={{ position: "absolute", left: 14, display: "flex", pointerEvents: "none" }}>
          {p.icon}
        </span>
        {p.input}
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "12px 14px 12px 42px",
  border: "1px solid #E5E7EB",
  borderRadius: 10,
  fontSize: 15,
  fontFamily: "Outfit, system-ui, sans-serif",
  color: "#0A0B14",
  background: "#FFFFFF",
  outline: "none",
  transition: "border-color 0.12s, box-shadow 0.12s",
  boxSizing: "border-box",
};
