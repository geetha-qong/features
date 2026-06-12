import { useEffect, useRef, useState } from "react";
import { Check, CheckCheck, ChevronDown, Layers } from "lucide-react";
import SheetGlyph from "./SheetGlyph";
import type { Sheet } from "./types";
import type { RealSheet } from "./api";

interface Props {
  sheets: Sheet[];
  activeSheet: number;
  onActivate: (idx: number) => void;
  projectId: number;
  dark: boolean;
  realSheets?: RealSheet[];
  appliedBySheet: Record<number, number>;
}

/**
 * SheetPicker — top-bar pill that opens a dropdown listing every sheet with a
 * thumbnail and status badge. Replaces the previous left-rail SheetRail per
 * the QONG Studio redesign (Jun 2026): sheets-as-dropdown frees the entire
 * left column for the symbol palette and full-width canvas.
 *
 * Real thumbnails (cropped PID tiles) come from `realSheets`; the generated
 * SheetGlyph SVG fallback keeps brand-new / legacy jobs renderable.
 */
export default function SheetPicker({
  sheets,
  activeSheet,
  onActivate,
  projectId,
  dark,
  realSheets,
  appliedBySheet,
}: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Close on outside-click. Listener only attached while open so the picker
  // stays cheap when most of the session is spent inside the canvas.
  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const hasReal = realSheets && realSheets.length > 0;
  const renderSheets = hasReal
    ? realSheets!.map((r) => ({
        id: r.id,
        name: r.label,
        label: r.label,
        status: "ok" as const,
        issues: 0,
        thumbUrl: r.url,
      }))
    : sheets.map((s) => ({ ...s, thumbUrl: undefined as string | undefined }));
  const current = renderSheets[activeSheet] ?? renderSheets[0];

  return (
    <div className="sheet-picker" ref={rootRef}>
      <button
        type="button"
        className={`sheet-picker-btn ${open ? "is-open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        title="Switch sheet"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <Layers size={15} strokeWidth={1.6} />
        <span className="sp-label">
          Sheet {current?.id ?? activeSheet + 1}{" "}
          <span className="sp-pages">/ {renderSheets.length}</span>
        </span>
        <ChevronDown
          size={14}
          strokeWidth={1.6}
          className="sp-chev"
          style={{ transform: open ? "rotate(180deg)" : "none" }}
        />
      </button>

      {open && (
        <div className="sheet-menu" role="listbox">
          <div className="sheet-menu-head">
            Sheets <span>{renderSheets.length}</span>
          </div>
          <div className="sheet-menu-scroll">
            {renderSheets.map((s, i) => {
              const applied = appliedBySheet[s.id];
              return (
                <button
                  key={s.id}
                  className={`sheet-menu-item ${i === activeSheet ? "active" : ""}`}
                  onClick={() => {
                    onActivate(i);
                    setOpen(false);
                  }}
                  role="option"
                  aria-selected={i === activeSheet}
                >
                  <span className="smi-thumb">
                    {s.thumbUrl ? (
                      <img
                        src={s.thumbUrl}
                        alt={s.label}
                        loading="lazy"
                        style={{
                          width: "100%",
                          height: "100%",
                          objectFit: "cover",
                          opacity: i === activeSheet ? 1 : 0.7,
                        }}
                      />
                    ) : (
                      <SheetGlyph
                        seed={s.id + projectId * 7}
                        dim={i !== activeSheet}
                        dark={dark}
                      />
                    )}
                  </span>
                  <span className="smi-meta">
                    <span className="smi-num">{String(s.id).padStart(2, "0")}</span>
                    <span className="smi-name">{s.name.replace(".pdf", "")}</span>
                  </span>
                  {applied ? (
                    <span className="smi-applied" title={`${applied} marks applied`}>
                      <CheckCheck size={11} strokeWidth={2} /> {applied}
                    </span>
                  ) : s.status === "issues" ? (
                    <span className="smi-badge issues">{s.issues}</span>
                  ) : s.status === "ok" ? (
                    <span className="smi-badge ok">
                      <Check size={10} strokeWidth={2.4} />
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
