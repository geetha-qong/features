import qongMark from "./design/assets/qong-mark.png";

export default function App() {
  return (
    <main
      style={{
        maxWidth: 960,
        margin: "0 auto",
        padding: "64px 24px",
        display: "flex",
        flexDirection: "column",
        gap: 32,
      }}
    >
      <header style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <img src={qongMark} alt="QONG" style={{ width: 48, height: 48 }} />
        <div className="qs-display" style={{ fontSize: 32 }}>
          QONG <span className="qs-gradient-text">STUDIO</span>
        </div>
      </header>

      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="qs-overline" style={{ color: "#8B3FCE" }}>
          Next-Engineered for Oil &amp; Gas
        </div>
        <h1
          className="qs-display"
          style={{ fontSize: 72, margin: 0, lineHeight: 0.95 }}
        >
          Read your <span className="qs-gradient-text">P&amp;ID</span>.
          <br />
          Generate the rest.
        </h1>
        <p style={{ fontSize: 18, color: "#4B5563", maxWidth: 640, marginTop: 16 }}>
          QONG Studio extracts instruments, valves, lines and tags directly
          from your drawings — then keeps every deliverable in sync as
          revisions land.
        </p>
      </section>

      <section
        style={{
          background: "#0A0B14",
          color: "#ECEEF5",
          padding: 24,
          borderRadius: 12,
          maxWidth: 480,
        }}
      >
        <div
          className="qs-overline"
          style={{ color: "#C73FBE", marginBottom: 16, fontSize: 12 }}
        >
          Live Extraction · Demo
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 12,
          }}
        >
          {[
            ["PT-101", "Press Xmtr"],
            ["FT-201", "Flow Xmtr"],
            ["LT-301", "Level Xmtr"],
            ["TT-401", "Temp Xmtr"],
            ["V-102", "Gate · 4″"],
            ["V-101", "Ball · 2″"],
          ].map(([tag, label]) => (
            <div
              key={tag}
              style={{
                background: "#13141F",
                padding: "10px 14px",
                borderRadius: 6,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <span className="qs-tag" style={{ color: "#8B3FCE", fontSize: 13 }}>
                {tag}
              </span>
              <span style={{ color: "#9CA3AF", fontSize: 12 }}>{label}</span>
            </div>
          ))}
        </div>
      </section>

      <footer
        style={{
          fontSize: 12,
          color: "#9CA3AF",
          paddingTop: 32,
          borderTop: "1px solid #E5E7EB",
        }}
      >
        Plan B Phase 1 Task 2 — design system integration. Tokens from{" "}
        <code>design/QONG Design System/</code>. Routing + login screen land
        in Task 3 + Task 4.
      </footer>
    </main>
  );
}
