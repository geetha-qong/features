import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, FileText, Search, X } from "lucide-react";
import type { EntityRow, TextSearchResult } from "./api";
import { searchDrawingText } from "./api";

interface Props {
  jobId: number;
  entities: EntityRow[];
  /** Called when user selects / navigates to a result. */
  onJumpTo: (entityId: string, entityClass: string) => void;
  /** Called whenever the matched result-set changes (used to drive dim highlights). */
  onResultsChange: (entityIds: string[]) => void;
  /** Called whenever the actively-jumped-to entity changes (used for sonar ring). */
  onActiveChange: (entityId: string | null) => void;
  /** Called when user clicks a drawing-text result to navigate to that sheet. */
  onJumpToSheet: (pageIndex: number) => void;
}

function getServiceDesc(e: EntityRow): string {
  const fv = e.values["service_description"] ?? e.values["fields.service_description"];
  if (!fv) return "";
  return String(fv.value ?? "");
}

/** Returns the first field (key + value) that matches the query, excluding
 *  tag/sub_class/service_description which are already shown in the row. */
function getMatchedField(e: EntityRow, q: string): { label: string; value: string } | null {
  const skip = new Set(["service_description", "fields.service_description"]);
  for (const [key, fv] of Object.entries(e.values)) {
    if (skip.has(key)) continue;
    const v = fv.value;
    if (v == null || v === "") continue;
    const str = String(v);
    if (str.toLowerCase().includes(q)) {
      const label = key.replace(/^fields\./, "").replace(/_/g, " ");
      return { label, value: str };
    }
  }
  return null;
}

function HighlightMatch({ text, query }: { text: string; query: string }) {
  if (!query || !text) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark
        style={{
          background: "rgba(255,20,147,0.28)",
          color: "inherit",
          borderRadius: 2,
          padding: "0 1px",
        }}
      >
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </>
  );
}

export default function SearchBar({
  jobId,
  entities,
  onJumpTo,
  onResultsChange,
  onActiveChange,
  onJumpToSheet,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  /** Which row in the dropdown is keyboard-highlighted. */
  const [dropdownIdx, setDropdownIdx] = useState(0);
  /** Which result the user most recently jumped to (for the counter). */
  const [activeIdx, setActiveIdx] = useState(0);
  /** Drawing text search results (async, debounced). */
  const [textResults, setTextResults] = useState<TextSearchResult[]>([]);

  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // ── Search logic (client-side, per spec) ──────────────────────────────────
  const results = useMemo(() => {
    if (!query || query.length < 2) return [];
    const q = query.toLowerCase();
    return entities
      .filter((e) => {
        if ((e.tag ?? "").toLowerCase().includes(q)) return true;
        if ((e.sub_class ?? "").toLowerCase().includes(q)) return true;
        if ((e.pid_number ?? "").toLowerCase().includes(q)) return true;
        // Search ALL field values loaded in memory
        for (const fv of Object.values(e.values)) {
          const v = fv.value;
          if (v != null && v !== "" && String(v).toLowerCase().includes(q)) return true;
        }
        return false;
      })
      .slice(0, 12);
  }, [query, entities]);

  // ── Async drawing-text search (debounced 400ms) ───────────────────────────
  useEffect(() => {
    if (!query || query.length < 2) {
      setTextResults([]);
      return;
    }
    const timer = setTimeout(() => {
      searchDrawingText(jobId, query)
        .then((r) => setTextResults(r.results))
        .catch(() => setTextResults([]));
    }, 400);
    return () => clearTimeout(timer);
  }, [query, jobId]);

  // Notify parent when result set changes; reset active index.
  useEffect(() => {
    onResultsChange(results.map((r) => r.entity_id));
    setActiveIdx(0);
    setDropdownIdx(0);
  }, [results, onResultsChange]);

  // Notify parent of which entity is actively highlighted.
  useEffect(() => {
    onActiveChange(results[activeIdx]?.entity_id ?? null);
  }, [results, activeIdx, onActiveChange]);

  // ── Global Ctrl+F / Cmd+F shortcut ────────────────────────────────────────
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault();
        setOpen(true);
        setTimeout(() => inputRef.current?.focus(), 0);
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Focus input when opened; clear when closed.
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 0);
    } else {
      setQuery("");
      setDropdownOpen(false);
      setTextResults([]);
      onResultsChange([]);
      onActiveChange(null);
    }
  }, [open, onResultsChange, onActiveChange]);

  // Click outside → close dropdown (but keep search open).
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // ── Handlers ──────────────────────────────────────────────────────────────
  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const v = e.target.value;
    setQuery(v);
    setDropdownOpen(v.length >= 2);
  }

  function handleInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setQuery("");
      setDropdownOpen(false);
      setOpen(false);
      return;
    }
    if (!dropdownOpen || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setDropdownIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setDropdownIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const r = results[dropdownIdx];
      if (r) selectResult(r, dropdownIdx);
    }
  }

  function selectResult(r: EntityRow, idx: number) {
    setActiveIdx(idx);
    setDropdownOpen(false);
    onJumpTo(r.entity_id, r.entity_class);
  }

  function navigate(delta: number) {
    const next = Math.max(0, Math.min(results.length - 1, activeIdx + delta));
    setActiveIdx(next);
    const r = results[next];
    if (r) onJumpTo(r.entity_id, r.entity_class);
  }

  // ── Collapsed state (button) ───────────────────────────────────────────────
  if (!open) {
    return (
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        onClick={() => setOpen(true)}
        title="Search all fields (Ctrl+F)"
        style={{ gap: 4 }}
      >
        <Search size={13} strokeWidth={1.6} />
        Search
      </button>
    );
  }

  // ── Expanded state ─────────────────────────────────────────────────────────
  return (
    <div
      ref={containerRef}
      style={{ position: "relative", display: "flex", alignItems: "center", gap: 4 }}
    >
      {/* Input with icon + clear button */}
      <div style={{ position: "relative" }}>
        <Search
          size={12}
          strokeWidth={1.6}
          style={{
            position: "absolute",
            left: 8,
            top: "50%",
            transform: "translateY(-50%)",
            color: "var(--fg-3)",
            pointerEvents: "none",
          }}
        />
        <input
          ref={inputRef}
          type="text"
          value={query}
          placeholder="Search all fields..."
          onChange={handleInputChange}
          onFocus={() => {
            setFocused(true);
            if (query.length >= 2) setDropdownOpen(true);
          }}
          onBlur={() => setFocused(false)}
          onKeyDown={handleInputKeyDown}
          style={{
            width: focused ? 320 : 200,
            transition: "width 0.2s ease",
            height: 28,
            paddingLeft: 28,
            paddingRight: query ? 28 : 8,
            fontSize: 12,
            background: "var(--surface-alt)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            color: "var(--fg-1)",
            outline: "none",
            boxSizing: "border-box",
          }}
        />
        {query && (
          <button
            type="button"
            onClick={() => {
              setQuery("");
              setDropdownOpen(false);
            }}
            style={{
              position: "absolute",
              right: 6,
              top: "50%",
              transform: "translateY(-50%)",
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "var(--fg-3)",
              padding: 0,
              display: "flex",
              alignItems: "center",
            }}
            title="Clear"
          >
            <X size={11} strokeWidth={2} />
          </button>
        )}

        {/* Dropdown */}
        {dropdownOpen && (
          <div
            style={{
              position: "absolute",
              top: "calc(100% + 6px)",
              left: 0,
              minWidth: 340,
              background: "var(--surface-alt)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
              zIndex: 500,
              overflow: "hidden",
            }}
          >
            {results.length === 0 && textResults.length === 0 ? (
              <div
                style={{
                  padding: "10px 14px",
                  color: "var(--fg-3)",
                  fontSize: 12,
                }}
              >
                No results found
              </div>
            ) : (
              results.map((r, i) => {
                const tag = r.tag ?? "(no tag)";
                const sc = r.sub_class ?? "";
                const sd = getServiceDesc(r);
                const matched = getMatchedField(r, query.toLowerCase());
                const isHighlighted = i === dropdownIdx;
                return (
                  <div
                    key={r.entity_id}
                    onMouseEnter={() => setDropdownIdx(i)}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      selectResult(r, i);
                    }}
                    style={{
                      padding: "7px 14px",
                      cursor: "pointer",
                      background: isHighlighted
                        ? "rgba(255,20,147,0.07)"
                        : "transparent",
                      borderBottom:
                        i < results.length - 1
                          ? "1px solid var(--border)"
                          : "none",
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                    }}
                  >
                    {/* tag (bold, pink, monospace) */}
                    <span
                      style={{
                        fontWeight: 700,
                        fontSize: 12,
                        fontFamily: "monospace",
                        color: "var(--qong-magenta)",
                        minWidth: 90,
                        flexShrink: 0,
                      }}
                    >
                      <HighlightMatch text={tag} query={query} />
                    </span>
                    {/* sub_class */}
                    <span
                      style={{
                        fontSize: 11,
                        color: "var(--fg-2)",
                        flexShrink: 0,
                      }}
                    >
                      <HighlightMatch text={sc} query={query} />
                    </span>
                    {/* service description OR matched field hint */}
                    {sd ? (
                      <span
                        style={{
                          fontSize: 11,
                          color: "var(--fg-3)",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          flex: 1,
                        }}
                      >
                        — <HighlightMatch text={sd} query={query} />
                      </span>
                    ) : matched ? (
                      <span
                        style={{
                          fontSize: 11,
                          color: "var(--fg-3)",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          flex: 1,
                        }}
                      >
                        <span style={{ color: "var(--fg-2)" }}>{matched.label}:</span>{" "}
                        <HighlightMatch text={matched.value} query={query} />
                      </span>
                    ) : null}
                    {/* sheet number */}
                    <span
                      style={{
                        fontSize: 10,
                        color: "var(--fg-3)",
                        marginLeft: "auto",
                        flexShrink: 0,
                      }}
                    >
                      sh {r.sheet_number}
                    </span>
                  </div>
                );
              })
            )}

            {/* ── Drawing text results (notes, holds, annotations) ── */}
            {textResults.length > 0 && (
              <>
                <div
                  style={{
                    padding: "4px 14px",
                    fontSize: 10,
                    color: "var(--fg-3)",
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    borderTop: results.length > 0 ? "1px solid var(--border)" : "none",
                    marginTop: results.length > 0 ? 4 : 0,
                  }}
                >
                  Drawing text
                </div>
                {textResults.map((tr, i) => (
                  <div
                    key={`txt-${tr.page_index}-${i}`}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setDropdownOpen(false);
                      onJumpToSheet(tr.page_index);
                    }}
                    style={{
                      padding: "7px 14px",
                      cursor: "pointer",
                      borderBottom:
                        i < textResults.length - 1
                          ? "1px solid var(--border)"
                          : "none",
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 8,
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLElement).style.background = "var(--bg-muted)";
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLElement).style.background = "transparent";
                    }}
                  >
                    <FileText
                      size={11}
                      strokeWidth={1.6}
                      style={{ color: "var(--fg-brand)", flexShrink: 0, marginTop: 1 }}
                    />
                    <span
                      style={{
                        fontSize: 11,
                        color: "var(--fg-2)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        flex: 1,
                        lineHeight: 1.4,
                      }}
                    >
                      <HighlightMatch text={tr.snippet} query={query} />
                    </span>
                    <span
                      style={{
                        fontSize: 10,
                        color: "var(--fg-3)",
                        marginLeft: "auto",
                        flexShrink: 0,
                      }}
                    >
                      sh {tr.sheet}
                    </span>
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {/* "1 of N" counter + prev / next buttons (only when >1 result) */}
      {results.length > 1 && (
        <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
          <button
            type="button"
            className="icon-btn studio-ic"
            onClick={() => navigate(-1)}
            disabled={activeIdx === 0}
            title="Previous result"
          >
            <ChevronLeft size={13} strokeWidth={2} />
          </button>
          <span
            style={{
              fontSize: 11,
              color: "var(--fg-2)",
              whiteSpace: "nowrap",
              minWidth: 44,
              textAlign: "center",
            }}
          >
            {activeIdx + 1} of {results.length}
          </span>
          <button
            type="button"
            className="icon-btn studio-ic"
            onClick={() => navigate(1)}
            disabled={activeIdx === results.length - 1}
            title="Next result"
          >
            <ChevronRight size={13} strokeWidth={2} />
          </button>
        </div>
      )}
    </div>
  );
}
