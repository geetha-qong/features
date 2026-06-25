/* global React, QongSocialRow */
function Footer() {
  return (
    <footer className="footer">
      <div className="container">
        <div className="grid">
          <div>
            <div className="brand">
              <img src="../../assets/qong-mark.png" alt="QONG" />
              <span className="text-gradient"><span className="qong-mark">QONG</span></span>&nbsp;Systems
            </div>
            <p style={{ fontSize: 14, color: 'var(--ink-300)', lineHeight: 1.55, margin: '0 0 8px', maxWidth: 320 }}>
              Next-Engineered solution for Oil &amp; Gas Energy sector. Bridging traditional industrial design with modern AI-powered digital engineering.
            </p>
            <div className="tag">BEYOND PLANT</div>
            <div style={{ marginTop: 28 }}>
              <div style={{
                fontFamily: 'var(--font-display)',
                fontSize: 13, fontWeight: 700,
                letterSpacing: '0.18em', textTransform: 'uppercase',
                color: 'var(--qong-magenta)', marginBottom: 12,
              }}>Follow Us</div>
              <QongSocialRow size={40} variant="dark" />
            </div>
          </div>
          <div>
            <h5>Platform</h5>
            <a href="#product">P&amp;ID Interpretation</a>
            <a href="#product">Deliverables</a>
            <a href="#technology">Key Technologies</a>
          </div>
          <div>
            <h5>Company</h5>
            <a href="#about">About <span className="qong-mark">QONG</span></a>
            <a href="#about">Vision &amp; Mission</a>
            <a href="#about">Team</a>
            <a href="#about">Careers</a>
          </div>
          <div>
            <h5>Contact</h5>
            <a href="#contact">Get in Touch</a>
            <a href="#contact">Request Demo</a>
            <a href="#contact">Early Access</a>
          </div>
        </div>
        <div className="copy">
          <div>© 2026 <span className="qong-mark">QONG</span> Systems · Operated by INNOARTHI PRIVATE LIMITED · CIN: U77309KA2025PTC202654</div>
          <div style={{ display: 'flex', gap: 18 }}>
            <a href="#" style={{ display: 'inline' }}>Privacy</a>
            <a href="#" style={{ display: 'inline' }}>Terms</a>
            <a href="#" style={{ display: 'inline' }}>Cookies</a>
          </div>
        </div>
      </div>
    </footer>
  );
}

window.QongFooter = Footer;
