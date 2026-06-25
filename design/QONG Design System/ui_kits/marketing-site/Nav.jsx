/* global React */
const { useState, useEffect } = React;

function Nav({ active = 'home', onNavigate, theme = 'light', onThemeToggle }) {
  return (
    <div className="nav-wrap">
      <nav className="nav">
        <a className="brand" href="#home" onClick={(e) => { e.preventDefault(); onNavigate?.('home'); }}>
          <img src="../../assets/qong-mark.png" alt="QONG" />
          <span className="text-gradient">QONG</span>
        </a>
        <div className="spacer" />
        <div className="links">
          {[
            ['home', 'Home'],
            ['about', 'About'],
            ['product', 'Product'],
            ['technology', 'Technology'],
            ['careers', 'Careers'],
            ['contact', 'Contact'],
          ].map(([k, l]) => (
            <a key={k} href={`#${k}`} className={active === k ? 'active' : ''}
               onClick={(e) => { e.preventDefault(); onNavigate?.(k); }}>{l}</a>
          ))}
        </div>
        <button
          className="theme-toggle"
          onClick={onThemeToggle}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          aria-label="Toggle theme"
        >
          {theme === 'dark' ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="4"/>
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
            </svg>
          )}
        </button>
        <a className="btn btn-primary btn-sm" href="#contact" onClick={(e) => { e.preventDefault(); onNavigate?.('contact'); }}>Request Demo</a>
      </nav>
    </div>
  );
}

window.QongNav = Nav;
