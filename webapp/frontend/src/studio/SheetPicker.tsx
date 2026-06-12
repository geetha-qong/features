import { useEffect, useMemo, useRef, useState } from "react";
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
 * SheetPicker — top-bar pill that opens a dropdown listing every **page** of
 * the project's PDF (one entry per page, not per tile crop). For single-page
 * jobs the dropdown is suppressed and we render a static "Page 1" pill so the
 * UI doesn't pretend there's something to switch.
 *
 * The redesign originally fed the picker directly with `realSheets`, but the
 * backend's RealSheet list is **per-tile** (the 3x3 grid produced by
 * `pdf_to_tiles.py`). So a 1-page job would show 9 entries pointing at the
 * same page — see job 46 (user-reported, FEATURES #41). The dropdown now
 * dedupes by page index parsed from `tile_p{N}_r{R}_c{C}.png`, picks the
 * center tile (r1_c1, the most representative thumb) as the visual for each
 * page, and emits the **tile-indexed** `activeSheet` Studio.tsx still expects
 * — keeps the parent's API stable while presenting a page-shaped UX.
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

  /** Page-grouped view of the input sheets. For tile-based backends we dedupe
   *  by `tile_p{N}_` extraction; otherwise each sheet is its own "page". */
  const pages = useMemo(() => {
    interface PageEntry {
      pageIndex: number;
      sheetIdx: number;      // tile-index into the flat sheets array; what onActivate consumes
      sheetId: number;
      label: string;
      thumbUrl?: string;
      appliedCount: number;
      status: "ok" | "issues" | "review" | "pending";
      issues: number;
    }
    const out: PageEntry[] = [];
    const seenPage = new Set<number>();
    const tilePageRe = /tile_p(\d+)_/;

    function pickCenterTileIdx(pageIdx: number): number {
      // Prefer the r1_c1 (center) tile for the page; fall back to first match.
      if (!realSheets) return -1;
      const center = realSheets.findIndex(
        (r) => r.filename.includes(`tile_p${pageIdx}_r1_c1`),
      );
      if (center >= 0) return center;
      return realSheets.findIndex((r) => r.filename.startsWith(`tile_p${pageIdx}_`));
    }

    if (hasReal) {
      for (const r of realSheets!) {
        const m = r.filename.match(tilePageRe);
        // Non-tile filename (e.g. legacy single-PNG job) → treat as page 0.
        const pageIdx = m ? parseInt(m[1], 10) : 0;
        if (seenPage.has(pageIdx)) continue;
        seenPage.add(pageIdx);
        const sheetIdx = pickCenterTileIdx(pageIdx);
        if (sheetIdx < 0) continue;
        const center = realSheets![sheetIdx];
        out.push({
          pageIndex: pageIdx,
          sheetIdx,
          sheetId: pageIdx + 1,   // 1-based for display
          label: center.label,
          thumbUrl: center.url,
          appliedCount: appliedBySheet[center.id] ?? 0,
          status: "ok",
          issues: 0,
        });
      }
      out.sort((a, b) => a.pageIndex - b.pageIndex);
    } else {
      // Prototype fallback — every prototype sheet is its own page.
      for (let i = 0; i < sheets.length; i++) {
        const s = sheets[i];
        out.push({
          pageIndex: i,
          sheetIdx: i,
          sheetId: s.id,
          label: s.name,
          appliedCount: appliedBySheet[s.id] ?? 0,
          status: s.status,
          issues: s.issues,
        });
      }
    }
    return out;
  }, [hasReal, realSheets, sheets, appliedBySheet]);

  // Map the parent's `activeSheet` (tile index) → which **page** is active.
  const activePageEntryIdx = useMemo(() => {
    const i = pages.findIndex((p) => p.sheetIdx === activeSheet);
    return i >= 0 ? i : 0;
  }, [pages, activeSheet]);
  const current = pages[activePageEntryIdx];

  if (pages.length <= 1) {
    // Nothing to switch between — render a quiet static label so reviewers
    // know they're seeing one page rather than wondering where the picker went.
    return (
      <span className="sheet-picker sheet-picker--static" title="This project has a single page">
        <Layers size={14} strokeWidth={1.6} />
        <span className="sp-label">Page 1</span>
      </span>
    );
  }

  return (
    <div className="sheet-picker" ref={rootRef}>
      <button
        type="button"
        className={`sheet-picker-btn ${open ? "is-open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        title="Switch page"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <Layers size={15} strokeWidth={1.6} />
        <span className="sp-label">
          Page {current?.pageIndex + 1}{" "}
          <span className="sp-pages">/ {pages.length}</span>
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
            Pages <span>{pages.length}</span>
          </div>
          <div className="sheet-menu-scroll">
            {pages.map((p, i) => (
              <button
                key={p.pageIndex}
                className={`sheet-menu-item ${i === activePageEntryIdx ? "active" : ""}`}
                onClick={() => {
                  onActivate(p.sheetIdx);
                  setOpen(false);
                }}
                role="option"
                aria-selected={i === activePageEntryIdx}
              >
                <span className="smi-thumb">
                  {p.thumbUrl ? (
                    <img
                      src={p.thumbUrl}
                      alt={p.label}
                      loading="lazy"
                      style={{
                        width: "100%",
                        height: "100%",
                        objectFit: "cover",
                        opacity: i === activePageEntryIdx ? 1 : 0.7,
                      }}
                    />
                  ) : (
                    <SheetGlyph
                      seed={p.sheetId + projectId * 7}
                      dim={i !== activePageEntryIdx}
                      dark={dark}
                    />
                  )}
                </span>
                <span className="smi-meta">
                  <span className="smi-num">PAGE {String(p.pageIndex + 1).padStart(2, "0")}</span>
                  <span className="smi-name">{p.label.replace(".pdf", "")}</span>
                </span>
                {p.appliedCount ? (
                  <span className="smi-applied" title={`${p.appliedCount} marks applied`}>
                    <CheckCheck size={11} strokeWidth={2} /> {p.appliedCount}
                  </span>
                ) : p.status === "issues" ? (
                  <span className="smi-badge issues">{p.issues}</span>
                ) : p.status === "ok" ? (
                  <span className="smi-badge ok">
                    <Check size={10} strokeWidth={2.4} />
                  </span>
                ) : null}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
