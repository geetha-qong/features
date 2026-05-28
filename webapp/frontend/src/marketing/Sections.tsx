import React from "react";
import {
  Brain,
  Zap,
  ClipboardList,
  FileText,
  Ban,
  Link2,
  TrendingDown,
  Flame,
  Pill,
  Droplets,
  FlaskConical,
} from "lucide-react";

/* Pinkify — split a string on standalone "QONG" word and wrap each match
   in a <span className="qong-mark">. Returns a React fragment. */
function pinkify(text: string): React.ReactNode {
  const parts = text.split(/(\bQONG\b)/);
  return parts.map((p, i) =>
    p === "QONG" ? (
      <span key={i} className="qong-mark">QONG</span>
    ) : (
      <React.Fragment key={i}>{p}</React.Fragment>
    )
  );
}

/* ---------- ABOUT ---------- */
export function About() {
  return (
    <section id="about" className="section">
      <div className="container">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1.2fr",
            gap: 80,
            alignItems: "center",
          }}
        >
          <div>
            <div className="overline-tag">
              About <span className="qong-mark">QONG</span> Systems
            </div>
            <h2
              style={{
                fontFamily: "var(--font-display)",
                fontSize: "clamp(34px, 4.8vw, 56px)",
                fontWeight: 800,
                letterSpacing: "-0.005em",
                lineHeight: 1.0,
                margin: 0,
                textTransform: "uppercase",
              }}
            >
              Redefining
              <br />
              <span className="text-gradient">Engineering Intelligence</span>
            </h2>
          </div>
          <div>
            <p style={{ fontSize: 18, color: "var(--fg-2)", lineHeight: 1.6, margin: 0 }}>
              {pinkify(
                "QONG Systems is a Next-Engineered solution for the Oil & Gas energy sector, designed to bridge the gap between traditional industrial design and modern digital engineering."
              )}
            </p>
            <p style={{ fontSize: 18, color: "var(--fg-2)", lineHeight: 1.6, marginTop: 18 }}>
              We don&apos;t just draw — we standardise, optimise, and innovate, helping industries build smarter, safer, and more efficiently.
            </p>
            <a href="#about" className="mkt-btn mkt-btn-ghost" style={{ marginTop: 20, padding: "8px 0" }}>
              About <span className="qong-mark">QONG</span> Systems →
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ---------- FEATURES ---------- */
export function Features() {
  const cards: [React.ReactNode, string, string][] = [
    [<Brain size={26} />, "AI-Powered P&ID Reading", "Computer vision reads P&ID drawings automatically, extracting all instruments, valves, and process connections."],
    [<Zap size={26} />, "Unified Cross-Discipline Platform", "One platform synchronises Instrumentation, Mechanical, Electrical, Civil — eliminating costly revision chains."],
    [<ClipboardList size={26} />, "Auto-Generated Deliverables", "From a P&ID upload, QONG Systems outputs Instrument Index, Datasheets, Control Narrative, Cause & Effect, and more."],
  ];
  return (
    <section className="section tight elev">
      <div className="container">
        <div className="feat-grid">
          {cards.map(([icon, title, desc]) => (
            <div key={title} className="feat-card">
              <div className="ic">{icon}</div>
              <h3>{title}</h3>
              <p>{pinkify(desc)}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------- PROBLEMS ---------- */
export function Problems() {
  const cards: [React.ReactNode, string, string][] = [
    [<FileText size={22} />, "Manual Documentation Overload", "Every dependent stream breaks — Instrument Lists, Control Logic, I/O Lists, Datasheets are manually maintained and out of sync."],
    [<Ban size={22} />, "No Intelligent Tools", "AutoCAD, SPI, AVEVA only store what engineers draw. They cannot interpret P&ID or validate cross-disciplinary consistency."],
    [<Link2 size={22} />, "Change/Error Cascade", "A single change causes all documents to be revised manually across every discipline. No unified extraction layer."],
    [<TrendingDown size={22} />, "High Revisions = High Costs", "Projects average R5 revisions. Small changes compound into Civil, Mechanical, Instrumentation, Electrical rework."],
  ];
  return (
    <section id="product" className="section">
      <div className="container">
        <div className="section-head">
          <div className="overline-tag">The Problem</div>
          <h2>
            Industry <span className="accent">Pain Points</span>
          </h2>
        </div>
        <div className="prob-grid">
          {cards.map(([icon, title, desc]) => (
            <div key={title} className="prob-card">
              <div className="ic">{icon}</div>
              <h4>{title}</h4>
              <p>{desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---- Process sub-components ---- */
interface StepProps {
  ov: string;
  t: React.ReactNode;
  m: string;
  gradient?: boolean;
}

function Step({ ov, t, m, gradient }: StepProps) {
  return (
    <div
      style={{
        padding: "22px 22px",
        borderRadius: 16,
        background: gradient ? "var(--qong-gradient)" : "rgba(255,255,255,0.04)",
        border: gradient ? "none" : "1px solid rgba(255,255,255,0.1)",
        boxShadow: gradient ? "var(--glow-brand)" : "none",
        color: "#fff",
      }}
    >
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          opacity: 0.85,
          marginBottom: 6,
        }}
      >
        {ov}
      </div>
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontWeight: 700,
          fontSize: 22,
          letterSpacing: 0,
          textTransform: "uppercase",
          marginBottom: 4,
        }}
      >
        {t}
      </div>
      <div style={{ fontSize: 13, opacity: 0.85 }}>{m}</div>
    </div>
  );
}

function Arrow({ label }: { label: string }) {
  return (
    <div
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color: "var(--qong-violet-300)",
        textAlign: "center",
        textTransform: "uppercase",
        letterSpacing: "0.12em",
      }}
    >
      {label}
      <br />
      <span style={{ fontSize: 18, color: "#fff" }}>→</span>
    </div>
  );
}

/* ---------- PROCESS ---------- */
export function Process() {
  return (
    <section
      className="section dark"
      style={{ background: "var(--ink-1000)", position: "relative", overflow: "hidden" }}
    >
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 800,
          height: 400,
          background: "radial-gradient(ellipse, rgba(139,63,206,0.18) 0%, transparent 60%)",
          pointerEvents: "none",
        }}
      />
      <div className="container" style={{ position: "relative" }}>
        <div className="section-head">
          <div className="overline-tag">The Process</div>
          <h2>
            How <span className="qong-mark">QONG</span> Drive Works
          </h2>
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr auto 1fr auto 1fr",
            gap: 20,
            alignItems: "center",
            maxWidth: 1100,
            margin: "0 auto",
          }}
        >
          <Step ov="Input" t="Engineering Drawings" m="P&ID, vendor & project data" />
          <Arrow label="AI reads" />
          <Step
            ov="Process"
            t={<><span className="qong-mark">QONG</span> AI Engine</>}
            m="Reads, interprets & cross-links"
            gradient
          />
          <Arrow label="generates" />
          <Step ov="Output" t="Engineering Deliverables" m="Ready in minutes" />
        </div>
      </div>
    </section>
  );
}

/* ---------- CORE ENGINE ---------- */
export function CoreEngine() {
  const bullets = [
    "A Single Intelligent Source of extraction for all stream documents.",
    "Enforced standards, accuracy, consistency and engineered documents.",
    "Solving Synchronisation + Revision headaches with AI validations.",
    "QONG BOX processes everything on-device — your P&IDs and deliverables never leave your plant boundary.",
  ];
  return (
    <section
      className="section dark"
      style={{ background: "var(--ink-1000)", position: "relative", overflow: "hidden" }}
    >
      <div
        style={{
          position: "absolute",
          top: "-100px",
          right: "-200px",
          width: 600,
          height: 600,
          borderRadius: "999px",
          background: "radial-gradient(circle, rgba(255,77,168,0.18) 0%, transparent 60%)",
          pointerEvents: "none",
          filter: "blur(40px)",
        }}
      />
      <div className="container" style={{ position: "relative" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 80,
            alignItems: "start",
          }}
        >
          <div>
            <div className="overline-tag">Core Engine</div>
            <h2
              style={{
                fontFamily: "var(--font-display)",
                fontSize: "clamp(40px, 5.2vw, 72px)",
                fontWeight: 900,
                letterSpacing: "-0.005em",
                lineHeight: 0.92,
                textTransform: "uppercase",
                margin: 0,
                color: "#fff",
              }}
            >
              AI-Powered
              <br />
              <span
                style={{
                  background: "var(--qong-gradient-pink)",
                  WebkitBackgroundClip: "text",
                  backgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  color: "transparent",
                  filter: "drop-shadow(0 2px 16px rgba(255,77,168,0.25))",
                }}
              >
                P&amp;ID Interpretation
              </span>
            </h2>
          </div>
          <div>
            <p style={{ fontSize: 18, color: "var(--ink-300)", lineHeight: 1.6, margin: "0 0 28px" }}>
              {pinkify(
                "The core engine that can read and understand P&ID drawings. QONG uses AI to read P&IDs, auto-generate engineering deliverables, synchronise disciplines, and eliminate manual rework — delivering faster, safer, and more consistent plant documentation."
              )}
            </p>
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 14 }}>
              {bullets.map((b, i) => (
                <li key={i} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                  <span
                    style={{
                      flexShrink: 0,
                      marginTop: 5,
                      width: 18,
                      height: 18,
                      borderRadius: 999,
                      background: "var(--qong-gradient-pink)",
                      display: "grid",
                      placeItems: "center",
                      boxShadow: "0 0 12px rgba(255,77,168,0.4)",
                    }}
                  >
                    <svg
                      width="10"
                      height="10"
                      viewBox="0 0 10 10"
                      fill="none"
                      stroke="#fff"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M2 5 L4 7 L8 3" />
                    </svg>
                  </span>
                  <span style={{ fontSize: 15, color: "var(--ink-200)", lineHeight: 1.55 }}>
                    {pinkify(b)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ---------- WHY CHOOSE / ADVANTAGES ---------- */
export function Advantages() {
  const list: [string, React.ReactNode, string][] = [
    ["01", "2D Twin Layer", "Auto-generates structured output for a living plant model that updates in real-time as drawings are uploaded."],
    ["02", "Cross-Disciplinary Intelligence", "Understands relationships between mechanical, electrical, instrumentation, and civil domains simultaneously."],
    ["03", "Human-in-loop Accuracy", "Engineers validate and teach the model — accuracy improves with every project."],
    ["04", "Brownfield + Greenfield", "Works with scanned legacy drawings and modern CAD files alike."],
    ["05", <><span className="qong-mark">QONG</span> BOX</>, "Your AI on your hardware. Not a cloud policy — a physical guarantee. Plant data never leaves your plant."],
    ["06", "ISA & IEC Compliant", "Engineering standards encoded into the engine. Every output is validated before delivery."],
  ];
  return (
    <section id="technology" className="section elev">
      <div className="container">
        <div className="section-head">
          <div className="overline-tag">
            Why Choose <span className="qong-mark">QONG</span> Systems
          </div>
          <h2>
            Unique <span className="accent">Advantages</span>
          </h2>
        </div>
        <div className="adv-grid">
          {list.map(([n, title, desc]) => (
            <div key={n} className="adv">
              <div className="num">{n}</div>
              <div>
                <h4>{title}</h4>
                <p>{pinkify(desc)}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------- SECTORS ---------- */
export function Sectors() {
  const list: [React.ReactNode, string, string][] = [
    [<Flame size={26} />, "Oil & Gas", "Upstream, midstream & downstream"],
    [<Pill size={26} />, "Pharma", "Process plants & sterile manufacturing"],
    [<Droplets size={26} />, "Water", "Treatment, distribution & desalination"],
    [<FlaskConical size={26} />, "Chemical", "Specialty chemicals & process"],
    [<Zap size={26} />, "Power & Energy", "Generation, transmission & renewables"],
  ];
  return (
    <section className="section tight">
      <div className="container">
        <div className="section-head" style={{ marginBottom: 36 }}>
          <div className="overline-tag">Our Market</div>
          <h2 style={{ fontSize: 36 }}>Sectors We Serve</h2>
        </div>
        <div className="sector-grid">
          {list.map(([icon, title, desc]) => (
            <div key={title} className="sector">
              <div className="ic">{icon}</div>
              <h4>{title}</h4>
              <p>{desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------- FAQ ---------- */
export function FAQ() {
  const qs: [string, string][] = [
    ["What is QONG Systems?", "QONG Systems is an AI-powered engineering platform for Oil & Gas FEED and EPC. It reads P&ID drawings and auto-generates a complete set of engineering deliverables — Instrument Index, Datasheets, Control Narrative, Cause & Effect, I/O Lists — in a fraction of the time of manual methods."],
    ["How does QONG Systems process P&ID drawings?", "The QONG AI Engine interprets symbols, annotations, tag numbers, and the relationships between components. It builds a structured engineering dataset automatically, which drives all downstream deliverable generation without any manual data entry."],
    ["Is my P&ID data kept secure and private?", "Yes. QONG BOX runs the entire AI stack locally on-premises — your P&IDs and deliverables never leave the plant boundary. For clients with strict air-gap requirements, QONG BOX operates fully offline with no cloud dependency."],
    ["Which deliverables does QONG Systems generate?", "Instrument Index, Datasheets, Control Narrative, Cause & Effect Matrix, I/O Lists, and Valve Lists. All deliverables are structured, exportable, and cross-linked — a change to a P&ID propagates automatically."],
    ["Is QONG Systems available now?", "QONG Systems is in active development with early access available to select engineering teams. Request early access to join the pilot programme."],
  ];
  return (
    <section
      className="section dark"
      id="contact"
      style={{ background: "var(--ink-1000)", position: "relative", overflow: "hidden" }}
    >
      <div
        style={{
          position: "absolute",
          top: "20%",
          left: "-200px",
          width: 600,
          height: 600,
          borderRadius: "999px",
          background: "radial-gradient(circle, rgba(139,63,206,0.2) 0%, transparent 60%)",
          pointerEvents: "none",
          filter: "blur(50px)",
        }}
      />
      <div className="container" style={{ position: "relative" }}>
        <div className="section-head">
          <div className="overline-tag">Common Questions</div>
          <h2>
            Frequently Asked <span className="accent">Questions</span>
          </h2>
        </div>
        <div className="faq-list">
          {qs.map(([q, a], i) => (
            <details key={i} className="faq" open={i === 0}>
              <summary>{pinkify(q)}</summary>
              <div className="faq-body">{pinkify(a)}</div>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------- CTA STRIP ---------- */
interface CTAStripProps {
  onCTA?: (msg: string) => void;
}

export function CTAStrip({ onCTA }: CTAStripProps) {
  return (
    <section
      className="section dark"
      style={{
        background: "var(--ink-1000)",
        position: "relative",
        overflow: "hidden",
        textAlign: "center",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: "radial-gradient(ellipse at center, rgba(199,63,190,0.25) 0%, transparent 60%)",
          pointerEvents: "none",
        }}
      />
      <div className="container" style={{ position: "relative" }}>
        <div
          className="dev-chip"
          style={{
            background: "rgba(34,211,238,0.08)",
            border: "1px solid rgba(34,211,238,0.35)",
            color: "var(--scan-cyan)",
          }}
        >
          <span
            className="dot"
            style={{
              background: "var(--scan-cyan)",
              boxShadow: "0 0 10px var(--scan-cyan)",
            }}
          />{" "}
          Now in Active Development
        </div>
        <h2
          style={{
            fontFamily: "var(--font-display)",
            fontSize: "clamp(40px, 5.5vw, 68px)",
            fontWeight: 800,
            letterSpacing: "-0.005em",
            lineHeight: 1.0,
            textTransform: "uppercase",
            margin: "0 0 18px",
            color: "#fff",
          }}
        >
          Ready to Go <span className="accent">Beyond Plant</span>?
        </h2>
        <p
          style={{
            fontSize: 18,
            color: "var(--ink-300)",
            maxWidth: 580,
            margin: "0 auto 32px",
            lineHeight: 1.55,
          }}
        >
          Join the next generation of engineering teams using AI to eliminate documentation errors, reduce revisions, and accelerate project delivery.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
          <a
            href="mailto:hello@qongsystems.com"
            className="mkt-btn mkt-btn-primary"
            onClick={() => onCTA?.("Early-access request received")}
          >
            Request Early Access
          </a>
          <a
            href="#product"
            className="mkt-btn mkt-btn-secondary"
            onClick={() => onCTA?.("Loading product page")}
          >
            View Product
          </a>
        </div>
      </div>
    </section>
  );
}
