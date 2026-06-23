/* global React, QongDrive */
function Hero({ onCTA }) {
  return (
    <section
      id="home"
      style={{
        position: 'relative',
        background: 'radial-gradient(ellipse at top, #1a1d3a 0%, #0a0b14 60%)',
        color: '#fff',
        padding: '100px 0 80px',
        overflow: 'hidden',
      }}
    >
      {/* gradient orb — pulled right so it doesn't wash over the headline */}
      <div style={{
        position: 'absolute', top: '-150px', right: '-200px',
        width: '780px', height: '780px', borderRadius: '999px',
        background: 'radial-gradient(circle, rgba(199,63,190,0.28) 0%, transparent 55%)',
        pointerEvents: 'none', filter: 'blur(50px)',
      }} />
      <div style={{
        position: 'absolute', bottom: '-200px', left: '-200px',
        width: '600px', height: '600px', borderRadius: '999px',
        background: 'radial-gradient(circle, rgba(46,63,190,0.18) 0%, transparent 60%)',
        pointerEvents: 'none', filter: 'blur(40px)',
      }} />
      {/* subtle dot grid */}
      <div style={{
        position: 'absolute', inset: 0,
        backgroundImage: 'radial-gradient(rgba(255,255,255,0.06) 1px, transparent 1px)',
        backgroundSize: '32px 32px', pointerEvents: 'none', opacity: 0.4,
      }} />
      <div className="container" style={{ position: 'relative', display: 'grid', gridTemplateColumns: '1.1fr 1fr', gap: 60, alignItems: 'center' }}>
        <div>
          <div className="overline-tag" style={{ color: 'var(--qong-violet-300)' }}>Next-Engineered for Oil &amp; Gas</div>
          <h1 style={{
            fontFamily: 'var(--font-condensed)', fontWeight: 900,
            fontSize: 'clamp(56px, 8.5vw, 112px)', lineHeight: 0.92,
            letterSpacing: '-0.005em', margin: 0,
            textTransform: 'uppercase',
          }}>
            <span style={{
              background: 'var(--qong-gradient-pink)',
              WebkitBackgroundClip: 'text',
              backgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              color: 'transparent',
              filter: 'drop-shadow(0 4px 24px rgba(255,77,168,0.35))',
            }}>QONG</span>
            <br />
            <span style={{ color: '#FFFFFF' }}>BEYOND</span>
            <br />
            <span style={{ color: '#7E839A' }}>PLANT</span>
          </h1>
          <div style={{
            marginTop: 18,
            fontFamily: 'var(--font-display)',
            fontSize: 14,
            fontWeight: 500,
            letterSpacing: '0.22em',
            textTransform: 'uppercase',
            color: '#6B6F8A',
          }}>AI-Powered Engineering</div>
          <p style={{
            marginTop: 24, fontSize: 18, lineHeight: 1.55,
            color: 'var(--ink-300)', maxWidth: 460,
          }}>
            AI-Powered Engineering Intelligence — <span className="qong-mark">QONG</span> Systems bridges traditional industrial design and modern digital engineering across FEED, instrumentation, mechanical, and electrical on one platform.
          </p>
          <div style={{ display: 'flex', gap: 12, marginTop: 32 }}>
            <button className="btn btn-primary" onClick={() => onCTA?.('Demo requested — we\'ll be in touch')}>
              Request Demo →
            </button>
            <button className="btn btn-secondary" onClick={() => onCTA?.('Loaded the platform overview')}>
              Explore Platform
            </button>
          </div>
          {/* stats */}
          <div style={{ display: 'flex', gap: 40, marginTop: 56, paddingTop: 28, borderTop: '1px solid rgba(255,255,255,0.08)' }}>
            {[['800+', 'Instruments'], ['180+', 'Datasheets'], ['<5 min', 'Per P&ID']].map(([n, l]) => (
              <div key={l}>
                <div style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: 28, letterSpacing: '-0.005em' }} className="text-gradient">{n}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--ink-400)', marginTop: 2 }}>{l}</div>
              </div>
            ))}
          </div>
        </div>
        <QongDrive />
      </div>
    </section>
  );
}

window.QongHero = Hero;
