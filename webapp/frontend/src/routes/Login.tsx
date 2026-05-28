import { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  AlertCircle,
  ArrowRight,
  Loader2,
  Lock,
  ShieldCheck,
  User,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import BrandRow from "../components/BrandRow";

const DEMO_TAGS: ReadonlyArray<readonly [string, string, string]> = [
  ["PT-101", "Press Xmtr", "#8B3FCE"],
  ["FT-201", "Flow Xmtr", "#C73FBE"],
  ["LT-301", "Level Xmtr", "#E73FB0"],
  ["TT-401", "Temp Xmtr", "#FF4DA8"],
  ["V-102", "Gate · 4″", "#22D3EE"],
  ["V-101", "Ball · 2″", "#22D3EE"],
];

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const { login } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!username || !password) {
      setError("Please enter your username and password.");
      return;
    }
    setSubmitting(true);
    try {
      await login(username, password, remember);
      // If RequireAuth bounced the user here with `?next=`, route them back
      // to that protected page after login (defends against open-redirect by
      // requiring the path to start with "/" and not "//").
      const rawNext = searchParams.get("next") || "";
      const safeNext = rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/dashboard";
      navigate(safeNext, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  const formCard = (
    <div className="login-card">
      <h2>Sign In</h2>
      <p className="sub">Access your engineering workspace.</p>
      <form className="form" onSubmit={onSubmit}>
        <div className="field">
          <label className="field-label">Username</label>
          <div className="input-with-icon">
            <span className="ic">
              <User size={18} strokeWidth={1.6} />
            </span>
            <input
              className="input"
              type="text"
              autoComplete="username"
              placeholder="your-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
        </div>
        <div className="field">
          <label className="field-label">Password</label>
          <div className="input-with-icon">
            <span className="ic">
              <Lock size={18} strokeWidth={1.6} />
            </span>
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
        </div>
        {error && (
          <div className="err">
            <AlertCircle size={14} strokeWidth={1.6} /> {error}
          </div>
        )}
        <div className="row">
          <label className="check">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />
            Keep me signed in
          </label>
          <a
            href="#"
            className="forgot"
            onClick={(e) => e.preventDefault()}
          >
            Forgot password?
          </a>
        </div>
        <button
          className="btn btn-primary btn-block"
          type="submit"
          disabled={submitting}
        >
          {submitting ? (
            <>
              <Loader2 size={14} strokeWidth={1.6} /> Signing in…
            </>
          ) : (
            <>
              Sign In <ArrowRight size={14} strokeWidth={1.6} />
            </>
          )}
        </button>
      </form>
      <div className="invite">
        <span className="ic">
          <ShieldCheck size={16} strokeWidth={1.6} />
        </span>
        <div>
          <strong>Invite-only access</strong>
          QONG Studio is in private beta. Need an account?{" "}
          <Link
            to="/"
            style={{ color: "var(--qong-magenta)", fontWeight: 600 }}
          >
            Request access
          </Link>
          .
        </div>
      </div>
    </div>
  );

  return (
    <div className="login-screen" data-screen-label="01 Login">
      <aside className="login-brand">
        <BrandRow size={36} />
        <div className="brand-hero">
          <span className="overline">Next-Engineered for Oil &amp; Gas</span>
          <h1>
            Read your <span className="accent">P&amp;ID</span>.
            <br />
            Generate the rest.
          </h1>
          <p>
            QONG Studio extracts instruments, valves, lines and tags directly
            from your drawings — then keeps every deliverable in sync as
            revisions land.
          </p>
        </div>
        <div className="extract-viz">
          <div className="extract-viz-head">
            <span className="lbl">Live Extraction · Demo</span>
            <span className="state">
              <span className="dot"></span>Scanning
            </span>
          </div>
          <div className="extract-tags">
            {DEMO_TAGS.map(([tag, name, c]) => (
              <div className="extract-tag" key={tag}>
                <span className="tag" style={{ color: c }}>
                  {tag}
                </span>
                <span className="nm">{name}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="brand-footer">
          <span className="meta">v1.0 · Build 0427</span>
          <span className="airgap-chip">
            <span className="dot"></span>Encrypted · Air-gapped
          </span>
        </div>
      </aside>
      <div className="login-form-panel">{formCard}</div>
    </div>
  );
}
