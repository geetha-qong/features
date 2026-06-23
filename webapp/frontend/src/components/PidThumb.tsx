interface PidThumbProps {
  seed?: number;
}

const PALETTE = ["#8B3FCE", "#C73FBE", "#E73FB0", "#FF4DA8", "#22D3EE"];

export default function PidThumb({ seed = 0 }: PidThumbProps) {
  const c1 = PALETTE[seed % PALETTE.length];
  const c2 = PALETTE[(seed + 2) % PALETTE.length];
  const offset = (seed * 11) % 30;

  return (
    <svg viewBox="0 0 300 152" className="thumb-svg" preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id={`tg-${seed}`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor={c1} stopOpacity="0.18" />
          <stop offset="100%" stopColor={c2} stopOpacity="0.05" />
        </linearGradient>
        <pattern id={`grid-${seed}`} width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M 20 0 L 0 0 0 20" fill="none" stroke="currentColor" strokeOpacity="0.08" strokeWidth="0.5" />
        </pattern>
      </defs>
      <rect width="300" height="152" fill={`url(#tg-${seed})`} />
      <rect width="300" height="152" fill={`url(#grid-${seed})`} style={{ color: "var(--fg-3)" }} />
      <line x1="20" y1={50 + offset / 3} x2="280" y2={50 + offset / 3} stroke={c1} strokeWidth="2" />
      <line x1="20" y1={108 - offset / 4} x2="280" y2={108 - offset / 4} stroke={c2} strokeWidth="2" />
      <line x1={90 + offset} y1={50 + offset / 3} x2={90 + offset} y2={108 - offset / 4} stroke={c1} strokeWidth="2" />
      <line x1={200 - offset / 2} y1={50 + offset / 3} x2={200 - offset / 2} y2={108 - offset / 4} stroke={c2} strokeWidth="2" />
      <circle cx={70} cy={50 + offset / 3} r="11" fill="var(--surface)" stroke={c1} strokeWidth="1.5" />
      <text x={70} y={50 + offset / 3 + 3} textAnchor="middle" fontSize="8" fontFamily="JetBrains Mono, monospace" fontWeight="700" fill={c1}>PT</text>
      <circle cx={220} cy={50 + offset / 3} r="11" fill="var(--surface)" stroke={c2} strokeWidth="1.5" />
      <text x={220} y={50 + offset / 3 + 3} textAnchor="middle" fontSize="8" fontFamily="JetBrains Mono, monospace" fontWeight="700" fill={c2}>FT</text>
      <circle cx={150 + offset / 3} cy={108 - offset / 4} r="11" fill="var(--surface)" stroke={c1} strokeWidth="1.5" />
      <text x={150 + offset / 3} y={108 - offset / 4 + 3} textAnchor="middle" fontSize="8" fontFamily="JetBrains Mono, monospace" fontWeight="700" fill={c1}>LT</text>
      <rect x={130} y={32} width={40} height={30} rx="3" fill="var(--surface)" stroke={c2} strokeWidth="1.5" />
      <polygon
        points={`${90 + offset - 6},${78} ${90 + offset + 6},${78} ${90 + offset - 6},${88} ${90 + offset + 6},${88}`}
        fill="var(--surface)"
        stroke={c1}
        strokeWidth="1.5"
      />
    </svg>
  );
}
