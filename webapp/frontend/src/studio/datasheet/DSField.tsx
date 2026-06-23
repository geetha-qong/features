import { Pencil, ScanSearch } from "lucide-react";
import type { FieldDef } from "./schemas";

function confColor(conf: number) {
  if (conf > 0.85) return "var(--ok)";
  if (conf > 0.7) return "var(--warn)";
  return "var(--error)";
}

function ConfidencePill({ conf }: { conf: number }) {
  const color = confColor(conf);
  return (
    <span className="conf-pill" style={{ color }}>
      <span className="dot" style={{ background: color }}></span>
      {conf.toFixed(2)}
    </span>
  );
}

interface Props {
  field: FieldDef;
  value: string;
  onChange: (v: string) => void;
  locked: boolean;
  onUnlock: () => void;
}

export default function DSField({ field, value, onChange, locked, onUnlock }: Props) {
  const empty = !value || value === "";
  const w = field.w || "sm";
  return (
    <div className={`ds-field span-${w} ${field.extracted ? "extracted" : ""} ${locked ? "locked" : ""}`}>
      <label className="ds-label">
        <span>{field.label}</span>
        {field.extracted && (
          <span className="ds-source">
            <ScanSearch size={10} strokeWidth={1.6} /> P&amp;ID
          </span>
        )}
      </label>
      <div className="ds-control">
        {locked ? (
          <div className="ds-locked">
            <span className="ds-value">{value || <em>— missing —</em>}</span>
            {field.extracted && field.conf !== undefined && <ConfidencePill conf={field.conf} />}
            <button type="button" className="ds-unlock" onClick={onUnlock} title="Edit manually">
              <Pencil size={11} strokeWidth={1.6} />
            </button>
          </div>
        ) : (
          <input
            className="ds-input"
            type="text"
            placeholder={field.extracted ? "Not detected — enter manually" : "Add value…"}
            value={value || ""}
            onChange={(e) => onChange(e.target.value)}
          />
        )}
        {empty && !locked && !field.extracted && <span className="ds-hint">Manual</span>}
      </div>
    </div>
  );
}
