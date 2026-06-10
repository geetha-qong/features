import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Boxes, GitPullRequest, Radio, Search } from "lucide-react";
import * as api from "./api";
import type {
  CanonicalEntityRowResp,
  EntityAggregates,
  EntitySearchResp,
} from "./types";

/**
 * Admin · Entity Index — cross-job query surface for the canonical_entities
 * table (FEATURES #34 / #35). One row per entity emitted by the pipeline,
 * across every job in the system.
 *
 * Three workflows on one page:
 *   - Aggregates strip across the top (total / per-class / top-N).
 *   - Filter bar (entity_class · sub_class · tag substring · job_id).
 *   - Paginated rows below with deep-links into the studio.
 *
 * Notes: reads pipeline-emitted state — entity_overrides are NOT applied.
 * For "what the user sees right now" use the deliverables API.
 */

const PAGE_SIZE = 50;
const CLASS_FILTERS = ["", "valve", "instrument", "equipment"];

function classIcon(c: string) {
  if (c === "valve") return <GitPullRequest size={13} strokeWidth={1.6} />;
  if (c === "instrument") return <Radio size={13} strokeWidth={1.6} />;
  return <Boxes size={13} strokeWidth={1.6} />;
}

export default function AdminEntities() {
  const [aggs, setAggs] = useState<EntityAggregates | null>(null);
  const [search, setSearch] = useState<EntitySearchResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [entityClass, setEntityClass] = useState<string>("");
  const [subClass, setSubClass] = useState<string>("");
  const [tagContains, setTagContains] = useState<string>("");
  const [jobId, setJobId] = useState<string>("");
  const [offset, setOffset] = useState<number>(0);

  // Aggregates only fetched once — cheap, doesn't change while page is open.
  useEffect(() => {
    let cancelled = false;
    api.getEntityAggregates()
      .then((r) => { if (!cancelled) setAggs(r); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); });
    return () => { cancelled = true; };
  }, []);

  // Fetch rows whenever filters or page change. Debounced via state batching;
  // tag_contains uses ILIKE so it's safe to refetch on every keystroke for
  // typical 1.3k-row tables.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.searchEntities({
      entity_class: entityClass || undefined,
      sub_class: subClass || undefined,
      tag_contains: tagContains || undefined,
      job_id: jobId ? Number(jobId) : undefined,
      limit: PAGE_SIZE,
      offset,
    })
      .then((r) => { if (!cancelled) setSearch(r); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [entityClass, subClass, tagContains, jobId, offset]);

  // Reset offset whenever a filter changes (otherwise paging into stale page-N).
  useEffect(() => { setOffset(0); }, [entityClass, subClass, tagContains, jobId]);

  // Sub-class dropdown options derived from the aggregates payload so it
  // stays in sync with the data on disk without a separate API call.
  const subClassOptions = useMemo(() => {
    if (!aggs?.top_valve_sub_classes) return [];
    return aggs.top_valve_sub_classes.map((s) => s.sub_class);
  }, [aggs]);

  const totalPages = search ? Math.max(1, Math.ceil(search.total / PAGE_SIZE)) : 1;
  const currentPage = search ? Math.floor(search.offset / PAGE_SIZE) + 1 : 1;

  return (
    <>
      <div className="projects-header">
        <div className="titlewrap">
          <span className="overline">Admin · Operations</span>
          <h1>Entity Index</h1>
          <p className="sub">Cross-job search over the canonical_entities table. Pipeline-emitted state.</p>
        </div>
      </div>

      {/* Aggregates — single-trip dashboard payload */}
      {aggs && (
        <>
          <div className="stat-strip" data-testid="entities-stats">
            <div className="stat">
              <div className="num accent">{aggs.total_rows.toLocaleString()}</div>
              <span className="lbl">Total entities</span>
            </div>
            {Object.entries(aggs.by_class).map(([cls, count]) => (
              <div className="stat" key={cls}>
                <div className="num">{count.toLocaleString()}</div>
                <span className="lbl">{cls}s</span>
              </div>
            ))}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginTop: 24 }}>
            <div>
              <h3 style={{ marginBottom: 12 }}>Top valve sub-classes</h3>
              <div className="projects-list">
                <div className="list-head" style={{ gridTemplateColumns: "1fr 1fr" }}>
                  <div>Sub-class</div>
                  <div>Count</div>
                </div>
                {aggs.top_valve_sub_classes.map((s) => (
                  <div
                    key={s.sub_class}
                    className="list-row"
                    style={{ gridTemplateColumns: "1fr 1fr", cursor: "pointer" }}
                    onClick={() => { setEntityClass("valve"); setSubClass(s.sub_class); }}
                  >
                    <div className="name">{s.sub_class}</div>
                    <div className="mono">{s.count}</div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <h3 style={{ marginBottom: 12 }}>Top jobs by valve count</h3>
              <div className="projects-list">
                <div className="list-head" style={{ gridTemplateColumns: "1fr 1fr" }}>
                  <div>Job</div>
                  <div>Valves</div>
                </div>
                {aggs.top_jobs_by_valve_count.map((j) => (
                  <div
                    key={j.job_id}
                    className="list-row"
                    style={{ gridTemplateColumns: "1fr 1fr", cursor: "pointer" }}
                    onClick={() => { setJobId(String(j.job_id)); }}
                  >
                    <Link to={`/jobs/${j.job_id}`} className="name" onClick={(e) => e.stopPropagation()}>
                      Job {j.job_id}
                    </Link>
                    <div className="mono">{j.count}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}

      <h3 style={{ marginTop: 32, marginBottom: 12 }}>Search</h3>

      {/* Filter bar */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ position: "relative" }}>
          <Search size={14} strokeWidth={1.6} style={{ position: "absolute", left: 10, top: 10, opacity: 0.5 }} />
          <input
            type="text"
            placeholder="Tag contains…"
            value={tagContains}
            onChange={(e) => setTagContains(e.target.value)}
            style={{ paddingLeft: 30, minWidth: 220 }}
          />
        </div>
        <select value={entityClass} onChange={(e) => { setEntityClass(e.target.value); setSubClass(""); }}>
          {CLASS_FILTERS.map((c) => <option key={c} value={c}>{c || "All classes"}</option>)}
        </select>
        {entityClass === "valve" && (
          <select value={subClass} onChange={(e) => setSubClass(e.target.value)}>
            <option value="">All sub-classes</option>
            {subClassOptions.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
        <input
          type="number"
          placeholder="Job ID"
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
          style={{ width: 100 }}
        />
        {(entityClass || subClass || tagContains || jobId) && (
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => { setEntityClass(""); setSubClass(""); setTagContains(""); setJobId(""); }}
          >
            Reset
          </button>
        )}
      </div>

      {error && (
        <div className="empty-state" role="alert">
          <h3>Error</h3>
          <p>{error}</p>
        </div>
      )}

      {/* Results */}
      {search && (
        <>
          <div style={{ marginBottom: 12, fontSize: 12, color: "var(--fg-3)" }}>
            {loading ? "Loading…" : <>
              <strong>{search.total.toLocaleString()}</strong> matches · page {currentPage} of {totalPages}
            </>}
          </div>

          <div className="projects-list" data-testid="entities-rows">
            <div className="list-head" style={{ gridTemplateColumns: "0.6fr 1.4fr 0.8fr 0.6fr 1.4fr 0.6fr" }}>
              <div>Job</div>
              <div>Tag</div>
              <div>Class / Sub</div>
              <div>Sheet</div>
              <div>P&amp;ID</div>
              <div>Open</div>
            </div>
            {search.rows.map((r: CanonicalEntityRowResp) => (
              <div
                key={`${r.job_id}:${r.entity_id}`}
                className="list-row"
                style={{ gridTemplateColumns: "0.6fr 1.4fr 0.8fr 0.6fr 1.4fr 0.6fr", cursor: "default" }}
              >
                <div className="mono">{r.job_id}</div>
                <div className="name">{r.tag || <em style={{ opacity: 0.6 }}>(no tag)</em>}</div>
                <div className="cell-client" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  {classIcon(r.entity_class)}
                  <span>{r.entity_class}{r.sub_class ? ` / ${r.sub_class}` : ""}</span>
                </div>
                <div className="mono">{r.sheet_number}</div>
                <div className="mono" style={{ fontSize: 11 }}>{r.pid_number}</div>
                <div>
                  <Link to={`/jobs/${r.job_id}`} className="btn btn-secondary btn-sm">Studio →</Link>
                </div>
              </div>
            ))}
            {search.rows.length === 0 && !loading && (
              <div className="empty-state" style={{ padding: 24 }}>
                <p>No entities match those filters.</p>
              </div>
            )}
          </div>

          {/* Pagination */}
          {search.total > PAGE_SIZE && (
            <div style={{ marginTop: 16, display: "flex", gap: 12, alignItems: "center", justifyContent: "center" }}>
              <button
                className="btn btn-secondary btn-sm"
                disabled={offset === 0 || loading}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                ← Prev
              </button>
              <span style={{ fontSize: 12, color: "var(--fg-3)" }}>
                {offset + 1}–{Math.min(offset + PAGE_SIZE, search.total)} of {search.total}
              </span>
              <button
                className="btn btn-secondary btn-sm"
                disabled={offset + PAGE_SIZE >= search.total || loading}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
}
