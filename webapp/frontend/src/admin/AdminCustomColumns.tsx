/**
 * Admin · Custom Columns — D5 from Spec A (FEATURES #26 A.4).
 *
 * Edit per-customer-template column labels, ordering, and visibility.
 * The canonical JSON templates on disk stay as the fallback; overrides
 * live in `customer_templates_overrides` and merge at template-load time.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, RotateCcw, Save } from "lucide-react";
import * as api from "./api";
import type {
  CustomerTemplateColumn,
  CustomerTemplateOverridePayload,
  CustomerTemplateResponse,
  DeliverableType,
} from "./types";
import { formatDateTime, useUserTimezone } from "../util/datetime";

const DELIVERABLE_TYPES: DeliverableType[] = [
  "valve_list",
  "instrument_index",
  "equipment_list",
  "datasheet",
];

const DELIVERABLE_LABEL: Record<DeliverableType, string> = {
  valve_list: "Valve List",
  instrument_index: "Instrument Index",
  equipment_list: "Equipment List",
  datasheet: "Datasheet",
};

interface EditableColumn extends CustomerTemplateColumn {
  // Snapshot of the JSON-side label, so we can detect whether the current
  // `label` is a true override vs a no-op edit back to the default.
  original_label: string;
}

export default function AdminCustomColumns() {
  const tz = useUserTimezone();
  const [slug, setSlug] = useState<string>("default");
  const [data, setData] = useState<CustomerTemplateResponse | null>(null);
  const [columns, setColumns] = useState<Record<DeliverableType, EditableColumn[]>>({
    valve_list: [],
    instrument_index: [],
    equipment_list: [],
    datasheet: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const ingest = useCallback((resp: CustomerTemplateResponse) => {
    setData(resp);
    const next: Record<DeliverableType, EditableColumn[]> = {
      valve_list: [],
      instrument_index: [],
      equipment_list: [],
      datasheet: [],
    };
    for (const dtype of DELIVERABLE_TYPES) {
      const cols = resp.deliverables?.[dtype] ?? [];
      // The API returns hidden columns at their stored position; clone so
      // local reordering doesn't mutate the response.
      next[dtype] = cols.map((c) => ({ ...c, original_label: c.label }));
    }
    setColumns(next);
  }, []);

  const refresh = useCallback(
    async (targetSlug: string) => {
      setLoading(true);
      setError(null);
      try {
        const resp = await api.getCustomerTemplate(targetSlug);
        ingest(resp);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [ingest],
  );

  useEffect(() => {
    void refresh(slug);
  }, [slug, refresh]);

  function move(dtype: DeliverableType, idx: number, dir: -1 | 1) {
    setColumns((prev) => {
      const list = [...prev[dtype]];
      const target = idx + dir;
      if (target < 0 || target >= list.length) return prev;
      [list[idx], list[target]] = [list[target], list[idx]];
      return { ...prev, [dtype]: list };
    });
  }

  function updateLabel(dtype: DeliverableType, idx: number, label: string) {
    setColumns((prev) => {
      const list = [...prev[dtype]];
      list[idx] = { ...list[idx], label };
      return { ...prev, [dtype]: list };
    });
  }

  function toggleHidden(dtype: DeliverableType, idx: number) {
    setColumns((prev) => {
      const list = [...prev[dtype]];
      list[idx] = { ...list[idx], hidden: !list[idx].hidden };
      return { ...prev, [dtype]: list };
    });
  }

  function resetColumn(dtype: DeliverableType, idx: number) {
    setColumns((prev) => {
      const list = [...prev[dtype]];
      const c = list[idx];
      list[idx] = { ...c, label: c.original_label, hidden: false, is_overridden: false };
      return { ...prev, [dtype]: list };
    });
  }

  function buildPayload(): CustomerTemplateOverridePayload[] {
    const out: CustomerTemplateOverridePayload[] = [];
    for (const dtype of DELIVERABLE_TYPES) {
      const list = columns[dtype];
      list.forEach((c, i) => {
        const labelChanged = c.label.trim() !== c.original_label.trim() && c.label.trim() !== "";
        const newOrder = i + 1;
        const orderChanged = c.order_in_template !== newOrder;
        const hidden = c.hidden;
        // Only emit a row if at least one field deviates from the template.
        if (!labelChanged && !orderChanged && !hidden) return;
        out.push({
          deliverable_type: dtype,
          column_key: c.key,
          label_override: labelChanged ? c.label.trim() : null,
          column_order: orderChanged ? newOrder : null,
          hidden,
        });
      });
    }
    return out;
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const payload = buildPayload();
      const resp = await api.putCustomerTemplate(slug, payload);
      ingest(resp);
      setSavedAt(new Date().toISOString());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    if (!confirm(`Reset all overrides for "${slug}"? This restores the canonical template.`)) return;
    setResetting(true);
    setError(null);
    try {
      const resp = await api.resetCustomerTemplate(slug);
      ingest(resp);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setResetting(false);
    }
  }

  const availableSlugs = useMemo(() => data?.available_slugs ?? [slug], [data, slug]);
  const hasOverrides = useMemo(
    () =>
      DELIVERABLE_TYPES.some((d) =>
        columns[d].some((c) => c.is_overridden || c.hidden),
      ),
    [columns],
  );

  return (
    <>
      <div className="projects-header">
        <div className="titlewrap">
          <span className="overline">Admin · Templates</span>
          <h1>Custom Columns</h1>
          <p className="sub">
            Rename, reorder, or hide deliverable columns per customer template.
            Canonical JSON templates stay as the fallback; overrides apply at
            CSV / Excel generation time.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="btn btn-secondary"
            onClick={() => void reset()}
            disabled={resetting || !hasOverrides}
            data-testid="custom-cols-reset"
          >
            <RotateCcw size={14} strokeWidth={1.6} />
            {resetting ? "Resetting…" : "Reset all"}
          </button>
          <button
            className="btn btn-primary"
            onClick={() => void save()}
            disabled={saving || loading}
            data-testid="custom-cols-save"
          >
            <Save size={14} strokeWidth={1.6} />
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      <div className="toolbar">
        <div className="field" style={{ maxWidth: 320 }}>
          <label className="field-label" htmlFor="cct-slug">Customer template</label>
          <select
            id="cct-slug"
            className="input"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            data-testid="custom-cols-slug-picker"
          >
            {availableSlugs.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <div style={{ flex: 1 }} />
        {data?.last_updated_at && (
          <span className="props-sub">
            Last updated {formatDateTime(data.last_updated_at, tz)}
          </span>
        )}
        {savedAt && !data?.last_updated_at && (
          <span className="props-sub">Saved {formatDateTime(savedAt, tz)}</span>
        )}
      </div>

      {error && (
        <div
          style={{
            background: "var(--error-soft)",
            color: "var(--error)",
            padding: "12px 16px",
            borderRadius: 8,
            marginBottom: 16,
          }}
          role="alert"
        >
          {error}
        </div>
      )}

      {loading ? (
        <div className="empty-state">
          <h3>Loading template…</h3>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          {DELIVERABLE_TYPES.map((dtype) => (
            <DeliverableSection
              key={dtype}
              dtype={dtype}
              columns={columns[dtype]}
              onMove={(idx, dir) => move(dtype, idx, dir)}
              onLabelChange={(idx, label) => updateLabel(dtype, idx, label)}
              onToggleHidden={(idx) => toggleHidden(dtype, idx)}
              onResetColumn={(idx) => resetColumn(dtype, idx)}
            />
          ))}
        </div>
      )}
    </>
  );
}

interface SectionProps {
  dtype: DeliverableType;
  columns: EditableColumn[];
  onMove: (idx: number, dir: -1 | 1) => void;
  onLabelChange: (idx: number, label: string) => void;
  onToggleHidden: (idx: number) => void;
  onResetColumn: (idx: number) => void;
}

function DeliverableSection({
  dtype,
  columns,
  onMove,
  onLabelChange,
  onToggleHidden,
  onResetColumn,
}: SectionProps) {
  return (
    <section data-testid={`custom-cols-section-${dtype}`}>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>{DELIVERABLE_LABEL[dtype]}</h2>
      {columns.length === 0 ? (
        <div className="empty-state" style={{ padding: 20 }}>
          <p className="props-sub">No columns defined for this deliverable.</p>
        </div>
      ) : (
        <div className="projects-list">
          <div
            className="list-head"
            style={{ gridTemplateColumns: "60px 1.4fr 2fr 100px 80px" }}
          >
            <div>Order</div>
            <div>Key</div>
            <div>Label</div>
            <div>Visible</div>
            <div></div>
          </div>
          {columns.map((col, idx) => (
            <div
              key={col.key}
              className="list-row"
              style={{
                gridTemplateColumns: "60px 1.4fr 2fr 100px 80px",
                cursor: "default",
                opacity: col.hidden ? 0.55 : 1,
              }}
              data-testid={`custom-cols-row-${dtype}-${col.key}`}
            >
              <div style={{ display: "flex", gap: 4 }}>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => onMove(idx, -1)}
                  disabled={idx === 0}
                  aria-label="Move up"
                  data-testid={`custom-cols-up-${dtype}-${col.key}`}
                  style={{ padding: "2px 6px" }}
                >
                  <ArrowUp size={14} strokeWidth={1.6} />
                </button>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => onMove(idx, 1)}
                  disabled={idx === columns.length - 1}
                  aria-label="Move down"
                  data-testid={`custom-cols-down-${dtype}-${col.key}`}
                  style={{ padding: "2px 6px" }}
                >
                  <ArrowDown size={14} strokeWidth={1.6} />
                </button>
              </div>
              <div className="mono caption" title={col.key}>{col.key}</div>
              <div>
                <input
                  className="input"
                  value={col.label}
                  onChange={(e) => onLabelChange(idx, e.target.value)}
                  data-testid={`custom-cols-label-${dtype}-${col.key}`}
                  style={{ height: 32 }}
                />
              </div>
              <div>
                <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input
                    type="checkbox"
                    checked={!col.hidden}
                    onChange={() => onToggleHidden(idx)}
                    data-testid={`custom-cols-visible-${dtype}-${col.key}`}
                  />
                  {col.hidden ? "Hidden" : "Shown"}
                </label>
              </div>
              <div>
                {col.is_overridden && (
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => onResetColumn(idx)}
                    title="Reset to template default"
                    data-testid={`custom-cols-reset-col-${dtype}-${col.key}`}
                  >
                    Reset
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
