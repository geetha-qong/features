import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Search, X } from "lucide-react";
import {
  HttpError,
  getEntities,
  getJobDetections,
  type DetectionItem,
  type EntityRow,
} from "../api";

/**
 * "All Data" view — one searchable surface that lists every extracted artefact
 * for a single job: canonical entities (valves / instruments / equipment) plus
 * raw YOLO detections (the model boxes). Built as a sibling of
 * BulkReviewScreen — mirrors its `.br-*` chrome, debounced filter, sticky
 * table and stale-request guard — so the two screens feel consistent.
 *
 * Frontend-only. Aggregates four deliverable_type fetches (deduped by
 * entity_id) + the detections endpoint. Degrades gracefully when a job has no
 * canonical yet (404/409) or no detections.
 */

interface Props {
  jobId: number;
  projectName: string;
  onBack: () => void;
}

/** Deliverable types we pull entities from. `valve_list` and `datasheet` can
 *  surface the same canonical entity (a valve also has a datasheet) — we dedupe
 *  by entity_id so each physical component appears once. */
const ENTITY_TYPES = ["valve_list", "instrument_index", "equipment_list", "datasheet"];

/** Unified row shape — either a canonical entity or a YOLO detection, flattened
 *  to a common set of columns so a single table can render both. */
interface UnifiedRow {
  /** Stable key for React. entity_id for entities; synthetic for detections. */
  key: string;
  /** "entity" vs "detection" — drives the Source column + filter category. */
  source: "entity" | "detection";
  /** One of: valve | instrument | equipment | detection (for filter chips). */
  category: "valve" | "instrument" | "equipment" | "detection";
  tag: string;
  /** entity_class/sub_class for entities, YOLO label for detections. */
  type: string;
  pid: string;
  sheet: string;
  /** YOLO confidence (detections only). */
  confidence: number | null;
  /** A short human summary of the key field values / bbox. */
  detail: string;
}

/** Map a canonical entity_class onto a filter category. Anything that isn't a
 *  recognised class still shows up — bucketed by its raw class string so it's
 *  never silently dropped. */
function entityCategory(entityClass: string): UnifiedRow["category"] {
  const c = (entityClass || "").toLowerCase();
  if (c.includes("valve")) return "valve";
  if (c.includes("instrument")) return "instrument";
  if (c.includes("equip")) return "equipment";
  // Unknown canonical classes fall into the instrument bucket — they still
  // always show under the "All" chip, so nothing is hidden.
  return "instrument";
}

/** Stringify a small set of the most useful canonical field values into a
 *  one-line summary for the unified table. We don't know the template schema
 *  ahead of time, so we surface up to 4 non-empty values by header. */
function summariseEntity(row: EntityRow): string {
  const parts: string[] = [];
  for (const [field, fv] of Object.entries(row.values)) {
    if (parts.length >= 4) break;
    if (field === "tag" || field === "pid_number" || field === "sheet_number") continue;
    const v = fv?.value;
    if (v === null || v === undefined || v === "") continue;
    const str = typeof v === "object" ? JSON.stringify(v) : String(v);
    if (!str) continue;
    parts.push(str);
  }
  return parts.join(" · ");
}

function summariseDetection(d: DetectionItem): string {
  if (Array.isArray(d.bbox) && d.bbox.length === 4) {
    const [x1, y1, x2, y2] = d.bbox;
    return `bbox ${Math.round(x1)},${Math.round(y1)} → ${Math.round(x2)},${Math.round(y2)}`;
  }
  return d.tile ? `tile ${d.tile}` : "—";
}

export default function AllDataView({ jobId, projectName, onBack }: Props) {
  const [entities, setEntities] = useState<EntityRow[]>([]);
  const [detections, setDetections] = useState<DetectionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [filterText, setFilterText] = useState("");
  const [debouncedFilter, setDebouncedFilter] = useState("");
  const [activeChip, setActiveChip] = useState<"all" | UnifiedRow["category"]>("all");

  // Guard against stale responses if the component re-fetches (jobId change).
  const reqIdRef = useRef(0);

  const fetchAll = useCallback(async () => {
    const myReq = ++reqIdRef.current;
    setLoading(true);
    setError(null);
    try {
      // Entities: hit each deliverable type. 404/409 = "no canonical for this
      // type" → treat as empty, not fatal. Other HTTP errors propagate.
      const entityResults = await Promise.all(
        ENTITY_TYPES.map((t) =>
          getEntities(jobId, t)
            .then((r) => r.entities)
            .catch((e) => {
              if (e instanceof HttpError && (e.status === 404 || e.status === 409)) {
                return [] as EntityRow[];
              }
              throw e;
            }),
        ),
      );
      // Detections: absence is non-fatal (job may predate GPU surfacing).
      const detResult = await getJobDetections(jobId)
        .then((r) => r.detections ?? [])
        .catch((e) => {
          if (e instanceof HttpError && (e.status === 404 || e.status === 409)) {
            return [] as DetectionItem[];
          }
          throw e;
        });

      if (myReq !== reqIdRef.current) return;

      // Dedupe entities by entity_id across the 4 deliverable fetches.
      const byId = new Map<string, EntityRow>();
      for (const list of entityResults) {
        for (const e of list) {
          if (!byId.has(e.entity_id)) byId.set(e.entity_id, e);
        }
      }
      const deduped = [...byId.values()];
      setEntities(deduped);
      setDetections(detResult);
    } catch (e) {
      if (myReq !== reqIdRef.current) return;
      setError(e instanceof Error ? e.message : "Failed to load extracted data");
      setEntities([]);
      setDetections([]);
    } finally {
      if (myReq === reqIdRef.current) setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  // 150ms filter debounce — matches BulkReviewScreen.
  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedFilter(filterText), 150);
    return () => window.clearTimeout(id);
  }, [filterText]);

  // Build the unified row list once per data change.
  const unified = useMemo<UnifiedRow[]>(() => {
    const rows: UnifiedRow[] = [];
    for (const e of entities) {
      rows.push({
        key: `entity:${e.entity_id}`,
        source: "entity",
        category: entityCategory(e.entity_class),
        tag: e.tag || "Untagged",
        type: e.sub_class || e.entity_class || "—",
        pid: e.pid_number || "—",
        sheet: e.sheet_number != null ? String(e.sheet_number) : "—",
        confidence: null,
        detail: summariseEntity(e),
      });
    }
    detections.forEach((d, i) => {
      // Detections have no tag — surface the YOLO class label as the row's
      // identifier. The Type column carries the category (or "Detection") so
      // the label isn't echoed in two columns.
      rows.push({
        key: `det:${i}:${d.tile ?? ""}:${d.label ?? ""}`,
        source: "detection",
        category: "detection",
        tag: d.label || "(unlabelled)",
        type: d.category || "Detection",
        pid: "—",
        sheet: d.page != null ? String(d.page) : "—",
        confidence: typeof d.confidence === "number" ? d.confidence : null,
        detail: summariseDetection(d),
      });
    });
    return rows;
  }, [entities, detections]);

  // Live counts per category (computed on the unfiltered set).
  const counts = useMemo(() => {
    const c = { all: unified.length, valve: 0, instrument: 0, equipment: 0, detection: 0 };
    for (const r of unified) c[r.category] += 1;
    return c;
  }, [unified]);

  const filtered = useMemo(() => {
    const q = debouncedFilter.trim().toLowerCase();
    return unified.filter((r) => {
      if (activeChip !== "all" && r.category !== activeChip) return false;
      if (q) {
        const hay = [r.tag, r.type, r.pid, r.detail].join("|").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [unified, debouncedFilter, activeChip]);

  const chips: { key: "all" | UnifiedRow["category"]; label: string; n: number }[] = [
    { key: "all", label: "All", n: counts.all },
    { key: "valve", label: "Valves", n: counts.valve },
    { key: "instrument", label: "Instruments", n: counts.instrument },
    { key: "equipment", label: "Equipment", n: counts.equipment },
    { key: "detection", label: "Detections", n: counts.detection },
  ];

  return (
    <div className="bulk-review alldata" data-screen-label="All Data">
      <header className="br-top">
        <button className="br-back" onClick={onBack} title="Back to Studio">
          <ArrowLeft size={14} strokeWidth={1.6} />
          <span>Back to Studio</span>
        </button>
        <div className="br-divider"></div>
        <div className="br-crumbs">
          <span>{projectName}</span>
          <span className="sep">›</span>
          <span className="strong">All Data</span>
        </div>
        <div style={{ flex: 1 }}></div>

        <div className="br-search">
          <Search size={12} strokeWidth={1.6} />
          <input
            placeholder="Search tag, label, type…"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            aria-label="Search all data"
          />
          {filterText && (
            <button
              onClick={() => setFilterText("")}
              title="Clear search"
              style={{
                background: "transparent",
                border: 0,
                color: "var(--fg-3)",
                cursor: "pointer",
                padding: 0,
                display: "inline-flex",
              }}
            >
              <X size={11} strokeWidth={1.6} />
            </button>
          )}
        </div>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--fg-3)",
            padding: "0 6px",
          }}
        >
          {filtered.length === unified.length
            ? `${unified.length} total`
            : `${filtered.length} of ${unified.length}`}
        </span>
      </header>

      <div className="alldata-summary" data-testid="alldata-summary">
        <div className="alldata-summary-card">
          <strong>{counts.all}</strong>
          <span>Total rows</span>
        </div>
        <div className="alldata-summary-card">
          <strong>{counts.valve}</strong>
          <span>Valves</span>
        </div>
        <div className="alldata-summary-card">
          <strong>{counts.instrument}</strong>
          <span>Instruments</span>
        </div>
        <div className="alldata-summary-card">
          <strong>{counts.equipment}</strong>
          <span>Equipment</span>
        </div>
        <div className="alldata-summary-card">
          <strong>{counts.detection}</strong>
          <span>Detections</span>
        </div>
      </div>

      <div className="alldata-chips" role="tablist" aria-label="Filter by type">
        {chips.map((c) => (
          <button
            key={c.key}
            role="tab"
            aria-selected={activeChip === c.key}
            className={`alldata-chip ${activeChip === c.key ? "active" : ""}`}
            onClick={() => setActiveChip(c.key)}
          >
            {c.label}
            <span className="cnt">{c.n}</span>
          </button>
        ))}
      </div>

      <div className="alldata-table-wrap">
        {loading && <div className="br-empty">Loading extracted data…</div>}

        {!loading && error && (
          <div className="br-empty" style={{ color: "var(--error, #dc2626)" }}>
            {error}
            <div style={{ marginTop: 12 }}>
              <button className="br-btn small" onClick={() => void fetchAll()}>
                Retry
              </button>
            </div>
          </div>
        )}

        {!loading && !error && unified.length === 0 && (
          <div className="br-empty">No extracted data for job #{jobId} yet.</div>
        )}

        {!loading && !error && unified.length > 0 && (
          <table className="alldata-table">
            <thead>
              <tr>
                <th>Tag</th>
                <th>Type</th>
                <th>Source</th>
                <th>P&amp;ID</th>
                <th>Sheet</th>
                <th>Confidence</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.key} data-source={r.source}>
                  <td className="mono tag">{r.tag}</td>
                  <td>{r.type}</td>
                  <td>
                    <span className={`alldata-src-badge ${r.source}`}>
                      {r.source === "entity" ? "Entity" : "YOLO"}
                    </span>
                  </td>
                  <td className="mono">{r.pid}</td>
                  <td className="mono">{r.sheet}</td>
                  <td className="mono">
                    {r.confidence != null ? `${(r.confidence * 100).toFixed(0)}%` : "—"}
                  </td>
                  <td className="detail">{r.detail || "—"}</td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={7} className="alldata-empty-row">
                    No data matches the current filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
