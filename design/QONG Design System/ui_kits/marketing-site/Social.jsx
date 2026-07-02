/* global React */

const SOCIAL_LINKS = [
  ['x',         'https://x.com/QongSystems',                   'Twitter / X'],
  ['linkedin',  'https://www.linkedin.com/company/qong-systems/', 'LinkedIn'],
  ['youtube',   'https://www.youtube.com/@QongSystems',         'YouTube'],
  ['instagram', 'https://www.instagram.com/qongsystems',        'Instagram'],
];

function SocialIcon({ kind }) {
  const common = { width: 16, height: 16, fill: 'currentColor' };
  switch (kind) {
    case 'x':
      return (
        <svg {...common} viewBox="0 0 24 24"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
      );
    case 'linkedin':
      return (
        <svg {...common} viewBox="0 0 24 24"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.026-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.063 2.063 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>
      );
    case 'youtube':
      return (
        <svg {...common} viewBox="0 0 24 24"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>
      );
    case 'instagram':
      return (
        <svg {...common} viewBox="0 0 24 24"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 1 0 0 12.324 6.162 6.162 0 0 0 0-12.324zM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm6.406-11.845a1.44 1.44 0 1 0 0 2.881 1.44 1.44 0 0 0 0-2.881z"/></svg>
      );
    default: return null;
  }
}

function SocialRow({ size = 36, variant = 'dark', align = 'left' }) {
  const wrap = {
    display: 'flex',
    gap: 10,
    justifyContent: align === 'center' ? 'center' : align === 'right' ? 'flex-end' : 'flex-start',
  };
  const isLight = variant === 'light';
  const itemStyle = {
    width: size, height: size,
    borderRadius: 3,
    border: `1px solid ${isLight ? 'var(--border)' : 'rgba(255,255,255,0.12)'}`,
    background: isLight ? 'var(--surface)' : 'rgba(255,255,255,0.04)',
    display: 'grid', placeItems: 'center',
    color: isLight ? 'var(--fg-2)' : 'var(--ink-300)',
    transition: 'all 200ms cubic-bezier(0.16,1,0.3,1)',
  };
  return (
    <div style={wrap}>
      {SOCIAL_LINKS.map(([kind, href, label]) => (
        <a
          key={kind}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={label}
          title={label}
          className="social-icon"
          style={itemStyle}
        >
          <SocialIcon kind={kind} />
        </a>
      ))}
    </div>
  );
}

Object.assign(window, { QongSocialRow: SocialRow, QongSocialIcon: SocialIcon });
