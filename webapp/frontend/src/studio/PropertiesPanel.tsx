import { useState } from "react";
import {
  ArrowUpRight,
  Boxes,
  Check,
  CircleDot,
  FileText,
  GitPullRequest,
  LogIn,
  LogOut,
  Pencil,
  Radio,
  Settings2,
} from "lucide-react";
import type { CanvasElement, SessionEvent } from "./types";

interface Props {
  elements: Record<string, CanvasElement>;
  selectedId: string;
  // `id` is the dictionary key in `elements` — either a prototype tag
  // ("PV-203") for the demo fallback or a real entity_id UUID for live
  // backend data. `entityClass` propagates from CanvasElement.entityClass
  // when present so the drawer picks the right deliverable type.
  onSelect: (id: string, entityClass?: string) => void;
  sessionEvents: SessionEvent[];
  hasDatasheet: boolean;
  onOpenDatasheet: () => void;
}

function iconFor(type: string) {
  if (type.includes("Valve")) return <GitPullRequest size={13} strokeWidth={1.6} />;
  if (type.includes("Transmitter")) return <Radio size={13} strokeWidth={1.6} />;
  if (type.includes("Pump")) return <Settings2 size={13} strokeWidth={1.6} />;
  if (type.includes("Exchanger")) return <Boxes size={13} strokeWidth={1.6} />;
  return <CircleDot size={13} strokeWidth={1.6} />;
}

function confColor(conf: number): string {
  if (conf > 0.85) return "var(--ok)";
  if (conf > 0.7) return "var(--warn)";
  return "var(--error)";
}

export default function PropertiesPanel({
  elements,
  selectedId,
  onSelect,
  sessionEvents,
  hasDatasheet,
  onOpenDatasheet,
}: Props) {
  const sel = elements[selectedId] || Object.values(elements)[0];
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  // [key, element] pairs — key is the dictionary key (entity_id UUID for
  // real data, prototype tag for demo fallback). Used for row click + isSel
  // so prototype + real selection behave the same way.
  const detected = Object.entries(elements);

  return (
    <aside className="props-col">
      <div className="props-section">
        <div className="props-head">Selected Element</div>
        <div className="prop-card">
          <div className="prop-head">
            <span className="prop-tag">{sel.tag}</span>
            <span className="prop-type">{sel.type}</span>
          </div>
          <div className="prop-conf">
            <span className="k">Confidence</span>
            <span className="v">{sel.confidence.toFixed(2)}</span>
            <div className="bar">
              <div
                className="fill"
                style={{ width: `${sel.confidence * 100}%`, background: confColor(sel.confidence) }}
              />
            </div>
          </div>
          {sel.lines.map((l, i) => (
            <div className="prop-line" key={i}>
              {i === 0 ? <LogIn size={12} strokeWidth={1.6} /> : <LogOut size={12} strokeWidth={1.6} />}
              <span>{l}</span>
            </div>
          ))}
          <div className="prop-actions">
            <button
              className={`mini-btn ${confirmed[sel.tag] ? "active" : ""}`}
              onClick={() => setConfirmed({ ...confirmed, [sel.tag]: !confirmed[sel.tag] })}
            >
              <Check size={12} strokeWidth={1.6} /> {confirmed[sel.tag] ? "Confirmed" : "Confirm"}
            </button>
            <button className="mini-btn">
              <Pencil size={12} strokeWidth={1.6} /> Edit
            </button>
          </div>
          {hasDatasheet && (
            <button className="open-ds-btn" onClick={onOpenDatasheet}>
              <FileText size={13} strokeWidth={1.6} />
              Open Datasheet
              <ArrowUpRight size={13} strokeWidth={1.6} />
            </button>
          )}
        </div>
      </div>

      <div className="props-section">
        <div className="props-head">
          <span>Elements on Sheet</span>
          <span className="props-sub">{detected.length} detected</span>
        </div>
        <div className="elements-list">
          {detected.map(([key, el]) => {
            const isSel = key === selectedId;
            const color = confColor(el.confidence);
            return (
              <div
                key={key}
                className={`element-row ${isSel ? "selected" : ""}`}
                onClick={() => onSelect(key, el.entityClass)}
                data-comment-anchor={`element-row-${key}`}
              >
                <div className="el-ic">{iconFor(el.type)}</div>
                <div className="el-text">
                  <div className="el-tag">{el.tag}</div>
                  <div className="el-type">{el.type}</div>
                </div>
                <span className="el-conf" style={{ color }}>
                  <span className="dot" style={{ background: color }}></span>
                  {el.confidence.toFixed(2)}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="props-section">
        <div className="props-head">This Session</div>
        <div className="session-list">
          {sessionEvents.map((s, i) => (
            <div className="session-row" key={i}>
              <span className="dot"></span>
              <div>
                <div className="line">
                  <strong>{s.who}</strong> {s.what}
                </div>
                <div className="when">{s.when}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}

