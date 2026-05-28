import { useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  ChevronDown,
  ChevronUp,
  Download,
  Filter,
  PanelRight,
  Search,
  X,
} from "lucide-react";
import DocTypeIcon from "../datasheet/DocTypeIcon";
import { COLUMNS, DELIVERABLES, DETAIL_GROUPS, type ColumnDef } from "./deliverables";
import { buildRows, type BulkRow } from "./buildRows";
import type { ProjectLike } from "../types";

interface Props {
  project: ProjectLike;
  onBack: () => void;
  onOpenInStudio: (id: string) => void;
}

function stColor(r: BulkRow): string {
  if (r.st === 100) return "var(--ok)";
  if (r.missing) return "var(--error)";
  if (r.st < 50) return "var(--warn)";
  return "var(--fg-2)";
}

function formatCell(r: BulkRow, col: ColumnDef): string {
  if (col.pct) {
    if (r.missing && r.st === 0) return "—";
    return `${r.st}%`;
  }
  const v = r[col.k];
  return v == null || v === "" ? "—" : String(v);
}

function detailValue(r: BulkRow, key: string): string {
  if (key === "st%") {
    if (r.missing && r.st === 0) return "—";
    return `${r.st}%`;
  }
  const v = r[key];
  return v == null ? "" : String(v);
}

export default function BulkReviewScreen({ project, onBack, onOpenInStudio }: Props) {
  const [activeDeliverable, setActiveDeliverable] = useState("datasheet");
  const rows = useMemo(() => buildRows(project), [project]);
  const [selectedId, setSelectedId] = useState<string>(() => rows.find((r) => r.sel)?.id || rows[0].id);
  const [checked, setChecked] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    rows.forEach((r) => {
      if (r.sel) init[r.id] = true;
    });
    return init;
  });
  const [query, setQuery] = useState("");
  const [showDetail, setShowDetail] = useState(true);

  const current = DELIVERABLES.find((d) => d.key === activeDeliverable) || DELIVERABLES[0];
  const cols = COLUMNS[activeDeliverable] || COLUMNS.datasheet;
  const groups = DETAIL_GROUPS[activeDeliverable] || DETAIL_GROUPS.datasheet;
  const selRow = rows.find((r) => r.id === selectedId) || rows[0];

  const filtered = useMemo(() => {
    if (!query) return rows;
    const q = query.toLowerCase();
    return rows.filter(
      (r) =>
        r.id.toLowerCase().includes(q) ||
        (r.type || "").toLowerCase().includes(q) ||
        (r.loop || "").toLowerCase().includes(q),
    );
  }, [rows, query]);

  const completeCount = rows.filter((r) => r.st === 100).length;
  const reviewCount = rows.filter((r) => r.st > 0 && r.st < 100 && !r.missing).length;
  const missingCount = rows.filter((r) => r.missing || r.st === 0).length;

  function toggleCheck(id: string) {
    setChecked((c) => ({ ...c, [id]: !c[id] }));
  }

  const gridTemplate = ["38px", ...cols.map((c) => c.w)].join(" ");

  return (
    <div className="bulk-review" data-screen-label="04 Bulk Review">
      <header className="br-top">
        <button className="br-back" onClick={onBack} title="Back to PID Studio">
          <ArrowLeft size={14} strokeWidth={1.6} />
          <span>Back to Studio</span>
        </button>
        <div className="br-divider"></div>
        <div className="br-crumbs">
          <span>{project.name}</span>
          <span className="sep">›</span>
          <span>Bulk Review</span>
          <span className="sep">›</span>
          <span className="strong">{current.name}</span>
        </div>
        <div style={{ flex: 1 }}></div>
        <div className="br-search">
          <Search size={12} strokeWidth={1.6} />
          <input
            placeholder="Find element, field, line…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <button className="br-btn">
          <Filter size={12} strokeWidth={1.6} />
          <span>Filter</span>
        </button>
        <button className="br-btn primary">
          <Download size={12} strokeWidth={1.6} />
          <span>Export</span>
        </button>
        <button
          className={`br-btn icon ${showDetail ? "active" : ""}`}
          onClick={() => setShowDetail((v) => !v)}
          title={showDetail ? "Hide detail panel" : "Show detail panel"}
        >
          <PanelRight size={13} strokeWidth={1.6} />
        </button>
      </header>

      <div className={`br-body ${showDetail ? "" : "no-detail"}`}>
        <aside className="br-nav">
          <div className="br-nav-head">
            <span>Deliverables</span>
            <span className="cnt">{DELIVERABLES.length}</span>
          </div>
          {DELIVERABLES.map((d) => {
            const pct = Math.round((d.done / d.total) * 100);
            return (
              <button
                key={d.key}
                className={`br-doc ${d.key === activeDeliverable ? "active" : ""}`}
                onClick={() => setActiveDeliverable(d.key)}
              >
                <DocTypeIcon name={d.icon} size={13} />
                <span className="nm">{d.name}</span>
                <span className="completion">
                  {d.done}/{d.total}
                </span>
                <div className="bar">
                  <div className="fill" style={{ width: `${pct}%` }} />
                </div>
              </button>
            );
          })}
        </aside>

        <section className="br-center">
          <div className="br-center-head">
            <div>
              <span className="overline">Bulk Review · Selected Deliverable</span>
              <h2>{current.name}</h2>
            </div>
            <div className="br-stats">
              <div className="stat">
                <strong>{rows.length}</strong>
                <span>Total</span>
              </div>
              <div className="stat">
                <strong style={{ color: "var(--ok)" }}>{completeCount}</strong>
                <span>Complete</span>
              </div>
              <div className="stat">
                <strong style={{ color: "var(--warn)" }}>{reviewCount}</strong>
                <span>Review</span>
              </div>
              <div className="stat">
                <strong style={{ color: "var(--error)" }}>{missingCount}</strong>
                <span>Missing</span>
              </div>
            </div>
          </div>

          <div className="br-table-wrap">
            <div className="br-table" style={{ gridTemplateColumns: gridTemplate }}>
              <div className="br-th"></div>
              {cols.map((c) => (
                <div key={c.k} className="br-th">
                  {c.lbl}
                </div>
              ))}
              {filtered.map((r) => {
                const sel = r.id === selectedId;
                return (
                  <div
                    key={r.id}
                    className={`br-row ${sel ? "selected" : ""}`}
                    style={{ display: "contents" }}
                    onClick={() => setSelectedId(r.id)}
                  >
                    <div
                      className="br-td check"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleCheck(r.id);
                      }}
                    >
                      <input type="checkbox" checked={!!checked[r.id]} onChange={() => undefined} />
                    </div>
                    {cols.map((c) => {
                      const cls = ["br-td"];
                      if (c.m) cls.push("mono");
                      if (c.small) cls.push("small");
                      if (c.pct) cls.push("pct");
                      if (c.sel) cls.push("tag");
                      const style: React.CSSProperties = {};
                      if (c.sel && sel) style.color = "var(--qong-magenta)";
                      if (c.pct) style.color = stColor(r);
                      return (
                        <div key={c.k} className={cls.join(" ")} style={style}>
                          {formatCell(r, c)}
                        </div>
                      );
                    })}
                  </div>
                );
              })}
              {filtered.length === 0 && (
                <div className="br-empty" style={{ gridColumn: "1 / -1" }}>
                  No instruments match "{query}"
                </div>
              )}
            </div>
          </div>
        </section>

        {showDetail && (
          <aside className="br-detail">
            <div className="row-hd">
              <span className="overline">
                Row · {filtered.findIndex((r) => r.id === selRow.id) + 1} of {filtered.length}
              </span>
              <div className="nav">
                <button title="Previous">
                  <ChevronUp size={13} strokeWidth={1.6} />
                </button>
                <button title="Next">
                  <ChevronDown size={13} strokeWidth={1.6} />
                </button>
                <button title="Close panel" onClick={() => setShowDetail(false)}>
                  <X size={13} strokeWidth={1.6} />
                </button>
              </div>
            </div>
            <h3 style={{ color: "var(--qong-magenta)" }}>{selRow.id}</h3>
            <div className="row-meta">{selRow.type}</div>

            {groups.map((g) => (
              <div key={g.title} className="group">
                <h4>{g.title}</h4>
                {g.rows.map(([lbl, key]) => {
                  const v = detailValue(selRow, key);
                  const empty = !v || v === "—";
                  return (
                    <div key={key} className="kv">
                      <span className="k">{lbl}</span>
                      <span
                        className={`v ${empty ? "miss" : ""}`}
                        style={key === "st%" ? { color: stColor(selRow) } : {}}
                      >
                        {empty ? "enter manually" : v}
                      </span>
                    </div>
                  );
                })}
              </div>
            ))}

            <div className="actions">
              <button className="br-btn small">Skip</button>
              <button className="br-btn small primary" onClick={() => onOpenInStudio(selRow.id)}>
                <ArrowUpRight size={11} strokeWidth={1.6} /> Open in Studio
              </button>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
