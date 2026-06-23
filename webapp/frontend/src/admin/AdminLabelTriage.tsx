import { useEffect, useMemo, useState } from "react";
import { Tags } from "lucide-react";
import * as api from "./api";
import { HttpError } from "./api";
import type { LabelTriageItem, TaxonomyResp, ClassifyTriagePayload } from "./api";
import { formatDateTime } from "../util/datetime";
import { useUserTimezone } from "../util/datetime";

/**
 * Admin · Label Triage — staging surface for OCR-discovered labels that aren't
 * yet in the unified taxonomy (Phase 4c).
 *
 * Workflow per pending row: pick entity_class (valve/instrument/equipment) +
 * sub_class + display_name/color/glyph_kind, then Approve (appends a class to
 * taxonomy.json on disk + upserts the DB read-index), or Ignore / Reject (just
 * records the decision). After any classify the list refreshes.
 *
 * The right-hand panel shows the current taxonomy (GET /taxonomy) read-only for
 * reference while classifying.
 */

const ENTITY_CLASSES = ["valve", "instrument", "equipment"] as const;
const STATUS_FILTERS = ["pending", "approved", "ignored", "rejected", "all"] as const;
const DEFAULT_COLOR = "#9498AE";
const DEFAULT_GLYPH = "valve_gen";

interface RowDraft {
  entity_class: string;
  sub_class: string;
  display_name: string;
  color: string;
  glyph_kind: string;
}

function emptyDraft(): RowDraft {
  return {
    entity_class: "valve",
    sub_class: "",
    display_name: "",
    color: DEFAULT_COLOR,
    glyph_kind: DEFAULT_GLYPH,
  };
}

export default function AdminLabelTriage() {
  const [items, setItems] = useState<LabelTriageItem[]>([]);
  const [taxonomy, setTaxonomy] = useState<TaxonomyResp | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("pending");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<Record<number, RowDraft>>({});
  const tz = useUserTimezone();

  // Taxonomy is reference-only — fetched once.
  useEffect(() => {
    let cancelled = false;
    api.getTaxonomy()
      .then((r) => { if (!cancelled) setTaxonomy(r); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); });
    return () => { cancelled = true; };
  }, []);

  function refresh(status = statusFilter) {
    setLoading(true);
    setError(null);
    return api.listLabelTriage(status)
      .then((r) => { setItems(r.items); })
      .catch((e) => { setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { setLoading(false); });
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.listLabelTriage(statusFilter)
      .then((r) => { if (!cancelled) setItems(r.items); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [statusFilter]);

  function draftFor(item: LabelTriageItem): RowDraft {
    const existing = drafts[item.id];
    if (existing) return existing;
    return {
      ...emptyDraft(),
      display_name: item.label_value,
    };
  }

  function updateDraft(id: number, patch: Partial<RowDraft>) {
    setDrafts((prev) => ({
      ...prev,
      [id]: { ...(prev[id] ?? emptyDraft()), ...patch },
    }));
  }

  async function classify(item: LabelTriageItem, action: ClassifyTriagePayload["action"]) {
    const payload: ClassifyTriagePayload = { action };
    if (action === "approve") {
      const d = draftFor(item);
      payload.entity_class = d.entity_class;
      payload.sub_class = d.sub_class || undefined;
      payload.display_name = d.display_name || item.label_value;
      payload.color = d.color || DEFAULT_COLOR;
      payload.glyph_kind = d.glyph_kind || DEFAULT_GLYPH;
    }
    setBusyId(item.id);
    setError(null);
    try {
      await api.classifyLabelTriage(item.id, payload);
      // Re-fetch taxonomy too — an approve mutates taxonomy.json.
      if (action === "approve") {
        api.getTaxonomy().then(setTaxonomy).catch(() => { /* non-fatal */ });
      }
      await refresh();
    } catch (e) {
      const msg = e instanceof HttpError ? e.detail ?? e.message : e instanceof Error ? e.message : String(e);
      setError(msg ?? "Classify failed");
    } finally {
      setBusyId(null);
    }
  }

  const sortedTaxonomy = useMemo(() => {
    if (!taxonomy) return [];
    return [...taxonomy.classes].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  }, [taxonomy]);

  return (
    <div data-testid="label-triage-root">
      <div className="projects-header">
        <div className="titlewrap">
          <span className="overline">Admin · Operations</span>
          <h1>Label Triage</h1>
          <p className="sub">
            Classify OCR-discovered labels into the unified taxonomy. Approving a
            label appends a class to <code>taxonomy.json</code> (source of truth).
          </p>
        </div>
      </div>

      {/* Status filter */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            data-testid={`triage-filter-${s}`}
            className={`btn btn-sm ${statusFilter === s ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setStatusFilter(s)}
          >
            {s}
          </button>
        ))}
      </div>

      {error && (
        <div className="empty-state" role="alert" data-testid="triage-error">
          <h3>Error</h3>
          <p>{error}</p>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1.7fr 1fr", gap: 24, alignItems: "start" }}>
        {/* Triage rows */}
        <div>
          <div style={{ marginBottom: 12, fontSize: 12, color: "var(--fg-3)" }}>
            {loading ? "Loading…" : <><strong>{items.length}</strong> {statusFilter} label{items.length === 1 ? "" : "s"}</>}
          </div>

          <div className="projects-list" data-testid="triage-rows">
            {items.map((item) => {
              const d = draftFor(item);
              const isPending = item.status === "pending";
              return (
                <div
                  key={item.id}
                  data-testid={`triage-item-${item.id}`}
                  className="list-row"
                  style={{ gridTemplateColumns: "1fr", display: "block", padding: 16 }}
                >
                  <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: isPending ? 12 : 0, flexWrap: "wrap" }}>
                    <span className="name mono" style={{ fontWeight: 600 }}>{item.label_value}</span>
                    <span className="sub" style={{ fontSize: 11 }}>
                      {item.source ? `source: ${item.source}` : "no source"}
                      {item.discovered_at ? ` · ${formatDateTime(item.discovered_at, tz)}` : ""}
                    </span>
                    {!isPending && (
                      <span
                        data-testid={`triage-status-${item.id}`}
                        className="mono"
                        style={{ fontSize: 11, opacity: 0.8, marginLeft: "auto" }}
                      >
                        {item.status}
                        {item.assigned_entity_class ? ` → ${item.assigned_entity_class}${item.assigned_sub_class ? "/" + item.assigned_sub_class : ""}` : ""}
                      </span>
                    )}
                  </div>

                  {isPending && (
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                      <select
                        aria-label="entity class"
                        data-testid={`triage-class-${item.id}`}
                        value={d.entity_class}
                        onChange={(e) => updateDraft(item.id, { entity_class: e.target.value })}
                      >
                        {ENTITY_CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                      <input
                        aria-label="sub class"
                        data-testid={`triage-subclass-${item.id}`}
                        type="text"
                        placeholder="sub_class"
                        value={d.sub_class}
                        onChange={(e) => updateDraft(item.id, { sub_class: e.target.value })}
                        style={{ width: 110 }}
                      />
                      <input
                        aria-label="display name"
                        data-testid={`triage-display-${item.id}`}
                        type="text"
                        placeholder="display_name"
                        value={d.display_name}
                        onChange={(e) => updateDraft(item.id, { display_name: e.target.value })}
                        style={{ width: 160 }}
                      />
                      <input
                        aria-label="color"
                        data-testid={`triage-color-${item.id}`}
                        type="text"
                        placeholder="#RRGGBB"
                        value={d.color}
                        onChange={(e) => updateDraft(item.id, { color: e.target.value })}
                        style={{ width: 90 }}
                      />
                      <input
                        aria-label="glyph kind"
                        data-testid={`triage-glyph-${item.id}`}
                        type="text"
                        placeholder="glyph_kind"
                        value={d.glyph_kind}
                        onChange={(e) => updateDraft(item.id, { glyph_kind: e.target.value })}
                        style={{ width: 120 }}
                      />
                      <button
                        data-testid={`triage-approve-${item.id}`}
                        className="btn btn-primary btn-sm"
                        disabled={busyId === item.id}
                        onClick={() => classify(item, "approve")}
                      >
                        Approve
                      </button>
                      <button
                        data-testid={`triage-ignore-${item.id}`}
                        className="btn btn-secondary btn-sm"
                        disabled={busyId === item.id}
                        onClick={() => classify(item, "ignore")}
                      >
                        Ignore
                      </button>
                      <button
                        data-testid={`triage-reject-${item.id}`}
                        className="btn btn-secondary btn-sm"
                        disabled={busyId === item.id}
                        onClick={() => classify(item, "reject")}
                      >
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
            {items.length === 0 && !loading && (
              <div className="empty-state" style={{ padding: 24 }}>
                <p>No {statusFilter === "all" ? "" : statusFilter + " "}labels to triage.</p>
              </div>
            )}
          </div>
        </div>

        {/* Taxonomy reference (read-only) */}
        <div>
          <h3 style={{ marginBottom: 4, display: "flex", alignItems: "center", gap: 8 }}>
            <Tags size={15} strokeWidth={1.6} />
            Current taxonomy
          </h3>
          <p className="sub" style={{ marginTop: 0, marginBottom: 12, fontSize: 12 }}>
            Read-only reference. {taxonomy ? `${taxonomy.classes.length} classes (v${taxonomy.schema_version}).` : ""}
          </p>
          <div className="projects-list" data-testid="taxonomy-list">
            <div className="list-head" style={{ gridTemplateColumns: "1.2fr 0.7fr 1.2fr" }}>
              <div>Display</div>
              <div>Class</div>
              <div>Sub / glyph</div>
            </div>
            {sortedTaxonomy.map((c, i) => (
              <div
                key={`${c.yolo_label ?? "ocr"}-${c.sub_class ?? "x"}-${i}`}
                className="list-row"
                style={{ gridTemplateColumns: "1.2fr 0.7fr 1.2fr", cursor: "default" }}
              >
                <div className="name" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span
                    aria-hidden
                    style={{ width: 10, height: 10, borderRadius: 2, background: c.color, display: "inline-block", flex: "0 0 auto" }}
                  />
                  {c.display_name}
                </div>
                <div className="mono" style={{ fontSize: 11 }}>{c.entity_class ?? "—"}</div>
                <div className="mono" style={{ fontSize: 11 }}>
                  {(c.sub_class ?? "—")} · {c.glyph_kind}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
