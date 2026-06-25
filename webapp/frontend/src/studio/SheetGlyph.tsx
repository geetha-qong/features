interface Props {
  seed: number;
  dim?: boolean;
  dark?: boolean;
}

const PALETTE = ["#8B3FCE", "#C73FBE", "#E73FB0", "#FF4DA8", "#22D3EE"];

export default function SheetGlyph({ seed, dim = false, dark = true }: Props) {
  const r = (n: number) => ((seed * 9301 + n * 49297) % 233280) / 233280;
  const c1 = PALETTE[seed % 5];
  const c2 = PALETTE[(seed + 2) % 5];
  const op = dim ? 0.45 : 0.9;
  const grid = dark ? "#ffffff" : "#000000";
  return (
    <svg viewBox="0 0 80 60" className="sheet-glyph" preserveAspectRatio="xMidYMid meet">
      <defs>
        <pattern id={`sg-grid-${seed}`} width="10" height="10" patternUnits="userSpaceOnUse">
          <path d="M 10 0 L 0 0 0 10" fill="none" stroke={grid} strokeOpacity="0.07" strokeWidth="0.4" />
        </pattern>
      </defs>
      <rect width="80" height="60" fill={`url(#sg-grid-${seed})`} />
      <line x1="10" y1={18 + r(1) * 8} x2="70" y2={18 + r(1) * 8} stroke={c1} strokeWidth="1.1" opacity={op} />
      <line x1="10" y1={42 - r(2) * 8} x2="70" y2={42 - r(2) * 8} stroke={c2} strokeWidth="1.1" opacity={op} />
      <line
        x1={28 + r(3) * 8}
        y1={18 + r(1) * 8}
        x2={28 + r(3) * 8}
        y2={42 - r(2) * 8}
        stroke={c1}
        strokeWidth="1.1"
        opacity={op}
      />
      <circle cx={20 + r(4) * 10} cy={18 + r(1) * 8} r="3.5" fill="none" stroke={c1} strokeWidth="1" opacity={op} />
      <circle cx={56 + r(5) * 8} cy={42 - r(2) * 8} r="3.5" fill="none" stroke={c2} strokeWidth="1" opacity={op} />
      <rect x="38" y="10" width="8" height="6" fill="none" stroke={c1} strokeWidth="0.9" opacity={op} />
    </svg>
  );
}
