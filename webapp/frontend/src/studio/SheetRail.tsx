import { Check, Search } from "lucide-react";
import SheetGlyph from "./SheetGlyph";
import type { Sheet } from "./types";

interface Props {
  sheets: Sheet[];
  activeSheet: number;
  onActivate: (idx: number) => void;
  projectId: number;
  dark: boolean;
}

export default function SheetRail({ sheets, activeSheet, onActivate, projectId, dark }: Props) {
  return (
    <aside className="sheet-rail">
      <div className="rail-head">
        <span className="lbl">Sheets</span>
        <span className="cnt">{sheets.length}</span>
      </div>
      <div className="rail-search">
        <Search size={13} strokeWidth={1.6} />
        <input placeholder="Find sheet…" />
      </div>
      <div className="rail-tabs">
        <button className="active">All</button>
        <button>Issues</button>
        <button>Pending</button>
      </div>
      <div className="rail-scroll">
        {sheets.map((s, i) => (
          <div
            key={s.id}
            className={`sheet-tile ${i === activeSheet ? "active" : ""}`}
            onClick={() => onActivate(i)}
            data-comment-anchor={`sheet-${s.id}`}
          >
            <div className="tile-thumb">
              <SheetGlyph seed={s.id + projectId * 7} dim={i !== activeSheet} dark={dark} />
              {s.status === "issues" && <span className="tile-badge issues">{s.issues}</span>}
              {s.status === "review" && <span className="tile-badge review">{s.issues}</span>}
              {s.status === "pending" && <span className="tile-badge pending">·</span>}
              {s.status === "ok" && (
                <span className="tile-badge ok">
                  <Check size={9} strokeWidth={1.6} />
                </span>
              )}
            </div>
            <div className="tile-meta">
              <div className="tile-num">{String(s.id).padStart(2, "0")}</div>
              <div className="tile-name">{s.name.replace(".pdf", "")}</div>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
