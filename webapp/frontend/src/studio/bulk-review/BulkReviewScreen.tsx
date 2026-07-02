import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  ChevronDown,
  ChevronUp,
  Download,
  Filter,
  PanelRight,
  Save,
  Search,
  X,
} from "lucide-react";
import DatasheetPanel from "../datasheet/DatasheetPanel";
import DocTypeIcon from "../datasheet/DocTypeIcon";
import { PdfModal } from "../PdfModal";
import {
  HttpError,
  getEntities,
  getJobDetections,
  patchEntity,
  type EntitiesResponse,
  type EntityColumn,
  type EntityFieldValue,
  type EntityRow,
} from "../api";
import { DELIVERABLES } from "./deliverables";

/** Maps the 10 design-time deliverable keys onto the 4 backend deliverable_type
 *  slugs. Kept verbatim with `DatasheetDrawer.tsx:DOC_TYPE_TO_DELIVERABLE` —
 *  if/when we wire more deliverables, update both. The remaining 6 keys render
 *  as disabled "Coming soon" tabs so the UX intent stays visible. */
const DELIVERABLE_KEY_TO_TYPE: Record<string, string | undefined> = {
  index: "instrument_index",
  datasheet: "datasheet",
  valves: "valve_list",
  equip: "equipment_list",
  lines: "line_list",
  io: "io_list",
  // 4 unsupported (no backend generator yet)
  narrative: undefined,
  cande: undefined,
  loop: undefined,
  tags: undefined,
};

/** Per-deliverable export format — mirrors Studio.tsx:EXPORT_FORMAT so the two
 *  download surfaces stay consistent. */
const EXPORT_FORMAT: Record<string, "csv" | "xlsx"> = {
  valve_list: "csv",
  instrument_index: "xlsx",
  equipment_list: "xlsx",
  io_list: "xlsx",
  line_list: "xlsx",
  datasheet: "xlsx",
};

const VENDOR_FIELDS = new Set([
  "vendor_match.vendor_name",
  "vendor_match.product_name",
  "fields.ids_pipe_class",
  "fields.ids_calibration_range_min",
  "fields.ids_calibration_range_max",
  "fields.ids_calibration_range_unit",
  "fields.ids_instrument_range_min",
  "fields.ids_instrument_range_max",
  "fields.ids_instrument_range_unit",
  "fields.ids_certification_special_requirement",
  "vendor_match.catalog_fields.output_signal_type",
  "vendor_match.catalog_fields.signal_power_supply",
  "vendor_match.catalog_fields.external_power_supply",
]);

interface Props {
  /** Job ID — drives every `/api/v1/jobs/{jobId}/entities` call. */
  jobId: number;
  /** Project name for the breadcrumb only. */
  projectName: string;
  /** Optional deliverable_type ("valve_list", "datasheet", …) the parent wants
   *  the workbench to open on. Falls back to the first supported tab. */
  initialDeliverableType?: string;
  onBack: () => void;
  /** Click "Open in Studio" on a row → close workbench, surface the drawer
   *  upstream by selecting the entity. The parent (Studio.tsx) decides
   *  what to do — currently flips `mode` back to "studio" and opens the
   *  DatasheetDrawer with the entity_id. Class is also forwarded so the
   *  drawer can default its deliverable_type to match (clicking a valve in
   *  Bulk Review shouldn't open the Instrument Index in Studio). */
  onOpenEntity: (entityId: string, entityClass?: string) => void;
}

/** Stringify any canonical-ish JSON value for the cell input. Mirrors
 *  DatasheetDrawer's `valueToString` so the two surfaces format identically. */
function valueToString(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return "";
  }
}

/** Coerce a user-edited string back to the original primitive type. Numeric
 *  coercion is opt-in (only when original was a number) so serials like
 *  "0001" don't get silently turned into 1. */
function stringToValue(s: string, original: unknown): unknown {
  if (s === "") return null;
  if (typeof original === "number") {
    const n = Number(s);
    if (!Number.isNaN(n)) return n;
  }
  return s;
}

// ── ISA-5.1 tag sort v2 (mirrors webapp/deliverables/tag_sort.py) ─────────────
const _SUFFIX_ORDER = ["W","E","G","T","I","DIT","IT","AH","AHH","AL","ALL"];
const _SUFFIX_RANK: Record<string, number> = Object.fromEntries(
  _SUFFIX_ORDER.map((s, i) => [s, i]),
);
const _UNKNOWN_RANK = _SUFFIX_ORDER.length;

function _naturalChunks(s: string): Array<[number, number | string]> {
  return s.split(/(\d+)/).filter(Boolean).map(tok =>
    /^\d+$/.test(tok)
      ? [0, parseInt(tok, 10)] as [number, number]
      : [1, tok.toLowerCase()] as [number, string],
  );
}

function _cmpChunks(
  a: Array<[number, number | string]>,
  b: Array<[number, number | string]>,
): number {
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    if (a[i][0] !== b[i][0]) return (a[i][0] as number) - (b[i][0] as number);
    if (a[i][1] < b[i][1]) return -1;
    if (a[i][1] > b[i][1]) return 1;
  }
  return a.length - b.length;
}

function _tagCmp(tagA: string | null | undefined, tagB: string | null | undefined): number {
  const key = (tag: string | null | undefined) => {
    if (!tag) return { area: [[2, ""]] as Array<[number, number | string]>, seq: [[2, ""]] as Array<[number, number | string]>, rank: _UNKNOWN_RANK };
    const parts = tag.trim().split("-");
    let area: Array<[number, number | string]>, seq: Array<[number, number | string]>, typeCode: string;
    if (parts.length === 1)      { area = []; typeCode = parts[0]; seq = []; }
    else if (parts.length === 2) { area = []; typeCode = parts[0]; seq = _naturalChunks(parts[1]); }
    else                         { area = _naturalChunks(parts[0]); typeCode = parts[1]; seq = _naturalChunks(parts.slice(2).join("-")); }
    const v   = (typeCode[0] ?? "").toUpperCase();
    const suf = typeCode.slice(1).toUpperCase();
    const rank = suf === "W"
      ? (v === "T" ? (_SUFFIX_RANK["W"] ?? _UNKNOWN_RANK) : _UNKNOWN_RANK)
      : (_SUFFIX_RANK[suf] ?? _UNKNOWN_RANK);
    return { area, seq, rank };
  };
  const a = key(tagA), b = key(tagB);
  return _cmpChunks(a.area, b.area) || _cmpChunks(a.seq, b.seq) || (a.rank - b.rank);
}
// ─────────────────────────────────────────────────────────────────────────────

/** Identity columns rendered sticky-left, regardless of template schema.
 *  editable: true → double-click opens inline edit (backend allows PATCH).
 *  pid_number + sheet_number are in READ_ONLY_FIELDS on the backend — keep them display-only. */
const IDENTITY_COLS: { field: keyof EntityRow; header: string; editable: boolean }[] = [
  { field: "tag",          header: "Tag",              editable: true },
  { field: "sub_class",    header: "Process Function", editable: true },
  { field: "pid_number",   header: "P&ID",             editable: true },
  { field: "sheet_number", header: "Sheet",            editable: true },
];

export default function BulkReviewScreen({
  jobId,
  projectName: _projectName,
  initialDeliverableType,
  onBack,
  onOpenEntity,
}: Props) {
  // Map the incoming deliverable_type back to a UI key so the tab highlights.
  const initialKey = useMemo<string>(() => {
    if (initialDeliverableType) {
      for (const [k, v] of Object.entries(DELIVERABLE_KEY_TO_TYPE)) {
        if (v === initialDeliverableType) return k;
      }
    }
    // Fall back to the first phase-1 supported tab (datasheet).
    return "datasheet";
  }, [initialDeliverableType]);

  const [activeKey, setActiveKey] = useState<string>(initialKey);
  const activeType = DELIVERABLE_KEY_TO_TYPE[activeKey];

  // Set of entity_ids that have a YOLO detection box — used to filter out
  // text-extracted canonical entities that were never visually detected.
  // Falls back to showing all entities if detections can't be loaded.
  const [detectedIds, setDetectedIds] = useState<Set<string> | null>(null);

  useEffect(() => {
    let cancelled = false;
    getJobDetections(jobId)
      .then((r) => {
        if (cancelled) return;
        const ids = new Set<string>();
        for (const d of r.detections || []) {
          if (d.entity_id) ids.add(d.entity_id);
        }
        setDetectedIds(ids.size > 0 ? ids : null);
      })
      .catch((err) => {
        if (!cancelled) {
          console.warn("Failed to load detections for job", jobId, err);
          setDetectedIds(null); // if detections unavailable, show all
        }
      });
    return () => { cancelled = true; };
  }, [jobId]);

  const [resp, setResp] = useState<EntitiesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  // Per-cell edit state — keyed `${entityId}:${field}` so a partially-edited
  // cell survives row-selection changes (until the user navigates away or
  // commits). null entry means "not editing"; string means "editing with this
  // working value".
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [cellError, setCellError] = useState<Record<string, string>>({});
  // Cells currently in-flight to PATCH — disables the input + shows a save hint.
  const [saving, setSaving] = useState<Record<string, boolean>>({});

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showDetail, setShowDetail] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [exportErr, setExportErr] = useState<string | null>(null);
  // Cache entity_ids per tab key so non-active tabs show their count too. We
  // store ids (not a raw number) so the count can be re-filtered against the
  // detected-set once detections load asynchronously after these are cached.
  const [tabEntityIds, setTabEntityIds] = useState<Record<string, string[]>>({});
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved">("idle");

  // Column header renames — persisted in localStorage; double-click any <th> to rename.
  const [headerOverrides, setHeaderOverrides] = useState<Record<string, string>>(() => {
    try { return JSON.parse(localStorage.getItem("br-header-overrides") ?? "{}"); } catch { return {}; }
  });
  const [editingHeader, setEditingHeader] = useState<string | null>(null);
  const [headerDraft, setHeaderDraft] = useState("");

  // Vendor lookup — populated by POST /api/qong-instrument when a row is selected.
  const [vendorApiData, setVendorApiData] = useState<Record<string, unknown>[] | null>(null);
  const [vendorLoading, setVendorLoading] = useState(false);
  const [vendorSaving, setVendorSaving] = useState(false);
  const [pdfModalUrl, setPdfModalUrl] = useState<string | null>(null);
  const [pendingVendorData, setPendingVendorData] = useState<Record<string, unknown> | null>(null);
  const [vendorAccepted, setVendorAccepted] = useState(false);

  // Batch-save all cells currently in edit mode. PATCHes each independently
  // then does a single refresh so the table reflects the saved state.
  async function saveAll() {
    const entries = Object.entries(editing);
    if (entries.length === 0) {
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 1500);
      return;
    }
    setSaveStatus("saving");
    await Promise.all(
      entries.map(([k, draft]) => {
        const colonIdx = k.indexOf(":");
        const entityId = k.slice(0, colonIdx);
        const field = k.slice(colonIdx + 1);
        const entity = rows.find(r => r.entity_id === entityId);
        if (!entity) return Promise.resolve();
        const origVal = entity.values[field]?.value;
        if (draft === valueToString(origVal)) return Promise.resolve();
        return patchEntity(jobId, entityId, { [field]: stringToValue(draft, origVal) }).catch(() => {});
      })
    );
    await fetchRows();
    setSaveStatus("saved");
    setTimeout(() => setSaveStatus("idle"), 1500);
  }

  // Filter: typed value (immediate) + debounced value (the one we actually
  // filter on). Debounce reduces re-render churn on big tables.
  const [filterText, setFilterText] = useState("");
  const [debouncedFilter, setDebouncedFilter] = useState("");
  const [showOnlyEdited, setShowOnlyEdited] = useState(false);

  // Guard against stale GET responses if the user spam-clicks tabs.
  const reqIdRef = useRef(0);

  const fetchRows = useCallback(async () => {
    if (!activeType) {
      // Unsupported deliverable — clear state, render empty panel.
      setResp(null);
      setSelectedId(null);
      setFetchError(null);
      return;
    }
    const myReq = ++reqIdRef.current;
    setLoading(true);
    setFetchError(null);
    try {
      const r = await getEntities(jobId, activeType);
      if (myReq !== reqIdRef.current) return;
      setResp(r);
      // Preserve the current selection across a refresh (e.g. after a side-panel
      // or cell save) — only fall back to the first row when the previously
      // selected entity is gone or nothing was selected. Functional update so we
      // don't need selectedId in this callback's deps.
      setSelectedId((prev) =>
        prev && r.entities.some((e) => e.entity_id === prev)
          ? prev
          : (r.entities[0]?.entity_id ?? null),
      );
      // Cache this tab's entity_ids so the sidebar shows its (detected) count
      // even when the tab is inactive.
      setTabEntityIds(prev => ({ ...prev, [activeKey]: r.entities.map(e => e.entity_id) }));
      // Drop stale edit state from the previous tab — different rows / schema.
      setEditing({});
      setCellError({});
      setSaving({});
      setEditingHeader(null);
    } catch (e) {
      if (myReq !== reqIdRef.current) return;
      if (e instanceof HttpError && e.status === 404) {
        setFetchError("No canonical output yet — this job hasn't finished extraction.");
      } else {
        setFetchError(e instanceof Error ? e.message : "Failed to load entities");
      }
      setResp(null);
    } finally {
      if (myReq === reqIdRef.current) setLoading(false);
    }
  }, [jobId, activeType]);

  useEffect(() => {
    void fetchRows();
  }, [fetchRows]);

  // Pre-fetch counts for every supported tab in parallel on mount so the
  // sidebar shows totals immediately without the user clicking each tab.
  useEffect(() => {
    const supported = (
      Object.entries(DELIVERABLE_KEY_TO_TYPE) as [string, string | undefined][]
    ).filter((e): e is [string, string] => e[1] !== undefined);
    Promise.all(
      supported.map(([key, type]) =>
        getEntities(jobId, type)
          .then(r => ({ key, ids: r.entities.map(e => e.entity_id) }))
          .catch(() => null)
      )
    ).then(results => {
      const byKey: Record<string, string[]> = {};
      for (const r of results) {
        if (r) byKey[r.key] = r.ids;
      }
      setTabEntityIds(byKey);
    });
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  // 150ms filter debounce — fast enough to feel live, slow enough that typing
  // doesn't re-filter every keystroke on a 500-row table.
  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedFilter(filterText), 150);
    return () => window.clearTimeout(id);
  }, [filterText]);

  // Esc closes detail panel; nice keyboard parity with the drawer.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && showDetail) setShowDetail(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showDetail]);

  // line_list is derived from pipe lines (deduped by line number), not from
  // detected symbols — exempt it so filtering by detection never empties it.
  const isDetectionFilterExempt = (type: string | undefined) => type === "line_list";

  // Filter an entities array to only those visually detected (have a YOLO box).
  // Falls back to the full set when detections are unavailable or the type is exempt.
  const filterDetectedEntities = useCallback(
    (entities: EntityRow[], type: string | undefined): EntityRow[] => {
      if (!detectedIds || isDetectionFilterExempt(type)) return entities;
      return entities.filter((e) => detectedIds.has(e.entity_id));
    },
    [detectedIds],
  );

  // Detected count for a tab from its cached entity_ids (re-filtered reactively
  // once detections load — they may arrive after the counts were cached).
  const tabCountFor = useCallback(
    (key: string): number | undefined => {
      const ids = tabEntityIds[key];
      if (ids === undefined) return undefined;
      const type = DELIVERABLE_KEY_TO_TYPE[key];
      if (!detectedIds || isDetectionFilterExempt(type)) return ids.length;
      return ids.filter((id) => detectedIds.has(id)).length;
    },
    [tabEntityIds, detectedIds],
  );

  // Filter entities to only those with a YOLO detection box. When detectedIds is
  // null (detections fetch failed or still loading), fall back to showing all.
  const rows = useMemo(
    () => filterDetectedEntities(resp?.entities ?? [], activeType),
    [resp, filterDetectedEntities, activeType],
  );
  const schema = resp?.schema ?? [];

  // Editable columns from the template, in `order` ascending. Read-only columns
  // (pid_number, sheet_number, entity_id, entity_class, bbox) are dropped from
  // the grid body — the identity columns above already cover pid_number + sheet_number.
  const editableColumns = useMemo<EntityColumn[]>(
    () => [...schema].filter((c) => c.editable).sort((a, b) => a.order - b.order),
    [schema],
  );

  // Filtered + optional "show only edited" rows. Cheap O(n*k) — fine at the
  // current scales we ship (typical jobs ≤ a few hundred entities).
  const filteredRows = useMemo(() => {
    const q = debouncedFilter.trim().toLowerCase();
    const filtered = rows.filter((r) => {
      if (q) {
        const hay = [
          r.tag ?? "",
          r.sub_class ?? "",
          r.pid_number ?? "",
          String(r.sheet_number ?? ""),
          r.entity_id,
        ]
          .join("|")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (showOnlyEdited) {
        const hasOverride = Object.values(r.values).some((v) => v.is_override);
        if (!hasOverride) return false;
      }
      return true;
    });
    return [...filtered].sort((a, b) => _tagCmp(a.tag, b.tag) || (a.entity_id < b.entity_id ? -1 : a.entity_id > b.entity_id ? 1 : 0));
  }, [rows, debouncedFilter, showOnlyEdited]);

  // Keep selectedId valid when rows change (filter narrows, refresh swaps).
  useEffect(() => {
    if (selectedId && filteredRows.find((r) => r.entity_id === selectedId)) return;
    setSelectedId(filteredRows[0]?.entity_id ?? null);
  }, [filteredRows, selectedId]);

  const selectedRow = useMemo<EntityRow | null>(
    () => filteredRows.find((r) => r.entity_id === selectedId) ?? null,
    [filteredRows, selectedId],
  );

  // Download the active deliverable. Declared here (after filteredRows + selectedRow)
  // so the dep array can capture the current selection without a stale closure.
  const onExport = useCallback(async () => {
    if (!activeType) return;
    const format = EXPORT_FORMAT[activeType] || "xlsx";
    setExporting(true);
    setExportErr(null);
    try {
      // Use selected row's tag; fall back to first visible row so Excel always
      // opens on an instrument sheet rather than the workbook's first sheet.
      const activeTag = selectedRow?.tag ?? filteredRows[0]?.tag;
      const activeSheetParam = activeTag
        ? `?active_sheet=${encodeURIComponent(activeTag)}`
        : "";
      const res = await fetch(`/api/v1/jobs/${jobId}/export/${activeType}/${format}${activeSheetParam}`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        setExportErr(`Export failed (HTTP ${res.status}) ${detail.slice(0, 80)}`);
        return;
      }
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      a.download = `job-${jobId}-${activeType}-${ts}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
    } catch (e) {
      setExportErr(e instanceof Error ? e.message : "Export error");
    } finally {
      setExporting(false);
    }
  }, [activeType, jobId, selectedRow, filteredRows]);

  // Fetch available vendors when an instrument row is selected on the index tab.
  useEffect(() => {
    if (activeKey !== "index" || !selectedRow) {
      setVendorApiData(null);
      return;
    }
    const rawCode = String(
      selectedRow.values["fields.tag_type_code"]?.value ?? ""
    ).trim().toUpperCase();
    if (!rawCode) return;

    const SUPPORTED = new Set([
      "PT","PIT","PDT","PG","TT","TE","TI","TG","FT","FI","LT","LI","VT",
      "PBS","PS","LS","RTD","TC","TW","FM","FE","RO","CVP","PSV","V",
      "ACT","MOT","CMP","BLW","FAN","GBX","HEX","TN","VS","FIL","STR","PLC",
    ]);
    let instType = rawCode;
    if (!SUPPORTED.has(instType)) {
      const stripped = rawCode.replace(/IT$/, "T");
      if (SUPPORTED.has(stripped)) { instType = stripped; }
      else if (rawCode.startsWith("PD")) { instType = "PDT"; }
      else if (rawCode.startsWith("PZ")) { instType = "PIT"; }
      else {
        const firstTwo = rawCode.slice(0, 2);
        if (SUPPORTED.has(firstTwo)) instType = firstTwo;
      }
    }

    let cancelled = false;
    setVendorApiData(null);
    setVendorLoading(true);
    // Same-origin proxy (FEATURES #124) — the vendor API key stays server-side
    // (in VENDOR_MATCH_API_URL/KEY env), never shipped to the browser. Cookie
    // auth rides along automatically on this same-origin request.
    fetch("/api/v1/vendor-match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instType }),
    })
      .then((r) => r.json())
      .then((json: { success?: boolean; data?: unknown }) => {
        if (!cancelled && json.success && json.data) {
          const raw = json.data;
          const list = Array.isArray(raw)
            ? (raw as Record<string, unknown>[])
            : [raw as Record<string, unknown>];
          setVendorApiData(list);
          // Re-hydrate the dropdown from the row's PERSISTED vendor so returning
          // to an already-configured row shows its selection (not a blank).
          // Match on manufacturer + model — the same fields handleVendorAccept
          // stored into vendor_match.* — so the dropdown reflects per-row state.
          const persistedVendor = valueToString(selectedRow?.values["vendor_match.vendor_name"]?.value);
          const persistedModel = valueToString(selectedRow?.values["vendor_match.product_name"]?.value);
          if (persistedVendor) {
            const match = list.find((v) =>
              String(v.manufacturer ?? "") === persistedVendor &&
              (!persistedModel || String(v.model_number ?? "") === persistedModel)
            );
            if (match) setPendingVendorData(match);
          }
        }
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setVendorLoading(false); });
    return () => { cancelled = true; };
  }, [activeKey, selectedRow?.entity_id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-derive vendor UI state when a different instrument row is selected.
  // The vendor selection itself is persisted per-entity (PATCHed to
  // vendor_match.*), so we DERIVE the display from the selected row's persisted
  // data instead of blindly clearing it — otherwise navigating away and back
  // would hide a row's already-chosen vendor. `vendorAccepted` gates the masked
  // vendor-field display: a row that already has a persisted vendor shows it
  // immediately; the dropdown value is re-hydrated by the fetch effect above.
  useEffect(() => {
    setPendingVendorData(null);
    setPdfModalUrl(null);
    const persistedVendor = selectedRow
      ? valueToString(selectedRow.values["vendor_match.vendor_name"]?.value)
      : "";
    setVendorAccepted(!!persistedVendor);
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Persist vendor datasheet fields to DB when the datasheet tab is opened.
  // Uses the tag prefix (e.g. "PT" from "PT-3069A") — never reads fields.tag_type_code
  // since many instrument types don't have that field.
  // Skips if vendor_name is already persisted (avoids redundant DB writes).
  useEffect(() => {
    if (activeKey !== "datasheet" || !selectedRow) return;

    // Skip if a vendor has already been persisted for this entity.
    const alreadyHasVendor = String(
      selectedRow.values["vendor_match.vendor_name"]?.value ?? ""
    ).trim();
    if (alreadyHasVendor) return;

    // Derive instrument type from tag prefix: "PT-3069A" → "PT", "PIT-3087" → "PIT" → "PT"
    const rawCode = (selectedRow.tag ?? "").split("-")[0].toUpperCase();
    if (!rawCode) return;

    let instType = rawCode;
    if (rawCode.length > 2 && rawCode.endsWith("T")) instType = rawCode[0] + "T";
    else if (rawCode.length > 2 && rawCode.endsWith("E")) instType = rawCode[0] + "E";

    let cancelled = false;
    fetch(`/api/v1/vendor-datasheet?instType=${encodeURIComponent(instType)}`, {
      credentials: "include",
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((json: { success?: boolean; data?: Record<string, string> } | null) => {
        if (cancelled || !json?.success || !json.data) return;
        const patch: Record<string, string> = {};
        for (const [path, value] of Object.entries(json.data)) {
          if (value?.trim()) patch[path] = value;
        }
        if (Object.keys(patch).length === 0) return;
        patchEntity(jobId, selectedRow.entity_id, patch)
          .then(() => fetchRows())
          .catch(() => {});
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [activeKey, selectedRow?.entity_id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleVendorSelect(productIdStr: string) {
    if (!vendorApiData || !selectedRow) return;
    if (!productIdStr) {
      setPendingVendorData(null);
      setPdfModalUrl(null);
      setVendorAccepted(false);
      const clearPatch: Record<string, string> = {
        "vendor_match.vendor_name":                        "",
        "vendor_match.product_name":                       "",
        "fields.ids_pipe_class":                           "",
        "fields.ids_calibration_range_min":                "",
        "fields.ids_calibration_range_max":                "",
        "fields.ids_calibration_range_unit":               "",
        "fields.ids_instrument_range_min":                 "",
        "fields.ids_instrument_range_max":                 "",
        "fields.ids_instrument_range_unit":                "",
        "fields.ids_certification_special_requirement":    "",
        "vendor_match.catalog_fields.output_signal_type":  "",
        "vendor_match.catalog_fields.signal_power_supply": "",
        "vendor_match.catalog_fields.external_power_supply": "",
      };
      try {
        await patchEntity(jobId, selectedRow.entity_id, clearPatch);
        await fetchRows();
      } catch (e) {
        console.error("Vendor clear failed", e);
      }
      return;
    }
    const d = vendorApiData.find((v) => String(v.product_id) === productIdStr);
    if (!d) return;
    setPendingVendorData(d);
    if (d.datasheet_url && String(d.datasheet_url).startsWith("http")) {
      setPdfModalUrl(String(d.datasheet_url));
    }
    // Persist the vendor selection immediately when dropdown is changed.
    // Map vendor API fields to entity override fields and PATCH to database.
    const patch: Record<string, string> = {
      "vendor_match.vendor_name":    String(d.manufacturer ?? ""),
      "vendor_match.product_name":   String(d.model_number ?? ""),
      "fields.piping_class":         String(d.piping_class ?? ""),
      "fields.calb_range_min":       String(d.calibration_range_min ?? ""),
      "fields.calb_range_max":       String(d.calibration_range_max ?? ""),
      "fields.calb_range_unit":      String(d.calibration_range_unit ?? ""),
      "fields.measuring_range_min":  String(d.measuring_range_min ?? ""),
      "fields.measuring_range_max":  String(d.measuring_range_max ?? ""),
      "fields.measuring_range_unit": String(d.measuring_range_unit ?? ""),
      "fields.certification":        String(d.certificate ?? ""),
      "fields.power_in":             String(d.power_supply_input ?? ""),
      "fields.power_out":            String(d.power_supply_output ?? ""),
      "fields.io_output":            String(d.io_output ?? ""),
      "fields.datasheet_ref":        "TBD",
    };
    const cleanPatch: Record<string, string> = {};
    for (const [k, v] of Object.entries(patch)) {
      if (v && v !== "undefined") {
        cleanPatch[k] = v;
      }
    }
    // PATCH to database (fire-and-forget; errors logged to console)
    patchEntity(jobId, selectedRow.entity_id, cleanPatch)
      .then(() => fetchRows())
      .catch((e) => console.error("Vendor persist on select failed", e));
  }

  async function handleVendorAccept() {
    if (!pendingVendorData || !selectedRow) return;
    const d = pendingVendorData;
    const fieldMap: Record<string, unknown> = {
      // Vendor identity
      "vendor_match.vendor_name":                          d.manufacturer,
      "vendor_match.product_name":                         d.model_number,
      // USER/PROCESS fields — IDS paths (fields.ids_<col>)
      "fields.ids_pipe_class":                             d.piping_class,
      "fields.ids_calibration_range_min":                  d.calibration_range_min,
      "fields.ids_calibration_range_max":                  d.calibration_range_max,
      "fields.ids_calibration_range_unit":                 d.calibration_range_unit,
      "fields.ids_instrument_range_min":                   d.measuring_range_min,
      "fields.ids_instrument_range_max":                   d.measuring_range_max,
      "fields.ids_instrument_range_unit":                  d.measuring_range_unit,
      "fields.ids_certification_special_requirement":      d.certificate,
      // Vendor catalog fields (vendor_match.catalog_fields.<key>)
      "vendor_match.catalog_fields.output_signal_type":    d.io_output,
      "vendor_match.catalog_fields.signal_power_supply":   d.power_supply_input,
      "vendor_match.catalog_fields.external_power_supply": d.external_power_supply,
    };
    const patch: Record<string, string> = {};
    for (const [k, v] of Object.entries(fieldMap)) {
      if (v !== null && v !== undefined && String(v).trim() !== "") {
        patch[k] = String(v);
      }
    }
    if (Object.keys(patch).length === 0) return;
    setVendorSaving(true);
    try {
      await patchEntity(jobId, selectedRow.entity_id, patch);
      await fetchRows();
      setVendorAccepted(true);
    } catch (e) {
      console.error("Vendor apply failed", e);
    } finally {
      setVendorSaving(false);
    }
  }

  function handleVendorDecline() {
    setPendingVendorData(null);
  }

  function cellKey(entityId: string, field: string) {
    return `${entityId}:${field}`;
  }

  function beginEdit(entity: EntityRow, field: string) {
    const k = cellKey(entity.entity_id, field);
    if (editing[k] !== undefined) return; // already editing
    // Prefer the values dict (tracks overrides). Fall back to the top-level
    // entity property for identity fields like sub_class that aren't in the schema.
    const cur = field in entity.values
      ? valueToString(entity.values[field]?.value)
      : valueToString((entity as unknown as Record<string, unknown>)[field]);
    setEditing((s) => ({ ...s, [k]: cur }));
    setCellError((s) => {
      if (!(k in s)) return s;
      const next = { ...s };
      delete next[k];
      return next;
    });
  }

  function setEditingValue(entity: EntityRow, field: string, val: string) {
    const k = cellKey(entity.entity_id, field);
    setEditing((s) => ({ ...s, [k]: val }));
  }

  function cancelEdit(entity: EntityRow, field: string) {
    const k = cellKey(entity.entity_id, field);
    setEditing((s) => {
      if (!(k in s)) return s;
      const next = { ...s };
      delete next[k];
      return next;
    });
    setCellError((s) => {
      if (!(k in s)) return s;
      const next = { ...s };
      delete next[k];
      return next;
    });
  }

  async function commitEdit(entity: EntityRow, field: string) {
    const k = cellKey(entity.entity_id, field);
    const newStr = editing[k];
    if (newStr === undefined) return;
    const origVal = entity.values[field]?.value;
    const origStr = valueToString(origVal);
    if (newStr === origStr) {
      cancelEdit(entity, field);
      return;
    }
    const coerced = stringToValue(newStr, origVal);
    setSaving((s) => ({ ...s, [k]: true }));
    try {
      await patchEntity(jobId, entity.entity_id, { [field]: coerced });
      // If Rev. No is edited, apply the same value to all other rows so the
      // entire deliverable shares one revision number.
      if (field === "fields.rev_no") {
        const others = rows.filter((r) => r.entity_id !== entity.entity_id);
        await Promise.all(others.map((r) => patchEntity(jobId, r.entity_id, { [field]: coerced })));
      }
      // Refresh just the active tab — keeps badges (is_override) accurate and
      // pulls in any concurrent edits from another tab. Cheap at current
      // entity counts; see open-question note on virtualization for the
      // threshold where this stops being free.
      await fetchRows();
      cancelEdit(entity, field);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Save failed";
      setCellError((s) => ({ ...s, [k]: msg }));
      // Leave the input mounted with the user's draft so they can retry / fix.
    } finally {
      setSaving((s) => {
        const next = { ...s };
        delete next[k];
        return next;
      });
    }
  }

  // --- Column header rename helpers ---
  function headerKey(field: string) { return `${activeType ?? ""}:${field}`; }
  function getHeader(field: string, def: string) { return headerOverrides[headerKey(field)] ?? def; }
  function startHeaderEdit(field: string, def: string) {
    setEditingHeader(field);
    setHeaderDraft(getHeader(field, def));
  }
  function commitHeaderEdit() {
    if (!editingHeader) return;
    const k = headerKey(editingHeader);
    const val = headerDraft.trim();
    const next = val
      ? { ...headerOverrides, [k]: val }
      : ((): Record<string, string> => { const o = { ...headerOverrides }; delete o[k]; return o; })();
    setHeaderOverrides(next);
    localStorage.setItem("br-header-overrides", JSON.stringify(next));
    setEditingHeader(null);
  }
  function cancelHeaderEdit() { setEditingHeader(null); }

  // Line list doesn't need tag or process-function columns — hide them.
  const visibleIdentityCols = activeKey === "lines"
    ? IDENTITY_COLS.filter((c) => c.field !== "tag" && c.field !== "sub_class")
    : IDENTITY_COLS;

  // Grid template: identity cols (sticky-left) · editable cols · open-action.
  const gridTemplate = useMemo(() => {
    const idCols = visibleIdentityCols.map(() => "minmax(90px, 1fr)").join(" ");
    const editCols = editableColumns.map(() => "minmax(110px, 1.2fr)").join(" ");
    return `${idCols} ${editCols} 36px`;
  }, [visibleIdentityCols, editableColumns]);

  const totalCount = rows.length;
  const shownCount = filteredRows.length;

  return (
    <div className="bulk-review" data-screen-label="04 Bulk Review">
      <header className="br-top">
        <button className="br-back" onClick={onBack} title="Back to PID Studio">
          <ArrowLeft size={14} strokeWidth={1.6} />
          <span>Back to Studio</span>
        </button>
        <div className="br-divider"></div>
        <div className="br-crumbs">
          <span className="strong">
            {DELIVERABLES.find((d) => d.key === activeKey)?.name ?? "—"}
          </span>
        </div>
        <div style={{ flex: 1 }}></div>

        <div className="br-search">
          <Search size={12} strokeWidth={1.6} />
          <input
            placeholder="Filter tag, sub-class, P&ID…"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
          />
          {filterText && (
            <button
              onClick={() => setFilterText("")}
              style={{
                background: "transparent",
                border: 0,
                color: "var(--fg-3)",
                cursor: "pointer",
                padding: 0,
                display: "inline-flex",
              }}
              title="Clear filter"
            >
              <X size={11} strokeWidth={1.6} />
            </button>
          )}
        </div>
        <button
          className={`br-btn ${showOnlyEdited ? "primary" : ""}`}
          onClick={() => setShowOnlyEdited((v) => !v)}
          title="Show only rows with overrides"
        >
          <Filter size={12} strokeWidth={1.6} />
          <span>{showOnlyEdited ? "Edited only" : "All rows"}</span>
        </button>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--fg-3)",
            padding: "0 6px",
          }}
        >
          {shownCount === totalCount
            ? `${totalCount} total`
            : `${shownCount} of ${totalCount}`}
        </span>
        <button
          className="br-btn primary"
          disabled={!activeType || exporting || rows.length === 0}
          onClick={onExport}
          title={
            !activeType
              ? "Select a supported deliverable"
              : rows.length === 0
                ? "Nothing to export — no entities for this deliverable"
                : exportErr || `Download ${EXPORT_FORMAT[activeType] || "xlsx"}`
          }
        >
          <Download size={12} strokeWidth={1.6} />
          <span>{exporting ? "Exporting…" : "Export"}</span>
        </button>
        <button
          className={`br-btn icon ${showDetail ? "active" : ""}`}
          onClick={() => setShowDetail((v) => !v)}
          title={showDetail ? "Hide detail panel" : "Show detail panel"}
        >
          <PanelRight size={13} strokeWidth={1.6} />
        </button>
      </header>

      <div className={`br-body ${showDetail ? "" : "no-detail"} ${showDetail && activeType === "datasheet" ? "ds-wide" : ""}`}>
        <aside className="br-nav">
          <div className="br-nav-head">
            <span>Deliverables</span>
            <span className="cnt">{DELIVERABLES.length}</span>
          </div>
          {DELIVERABLES.map((d) => {
            const supported = !!DELIVERABLE_KEY_TO_TYPE[d.key];
            const isActive = d.key === activeKey;
            return (
              <button
                key={d.key}
                className={`br-doc ${isActive ? "active" : ""}`}
                disabled={!supported}
                title={
                  supported
                    ? d.name
                    : `${d.name} — Coming soon (no backend generator yet)`
                }
                onClick={() => supported && setActiveKey(d.key)}
                style={
                  supported
                    ? undefined
                    : { opacity: 0.4, cursor: "not-allowed" }
                }
              >
                <DocTypeIcon name={d.icon} size={13} />
                <span className="nm">{d.name}</span>
                {!supported ? (
                  <span
                    className="completion"
                    style={{ fontSize: 8.5, letterSpacing: "0.12em" }}
                  >
                    SOON
                  </span>
                ) : (
                  <span className="completion">
                    {isActive && resp
                      ? rows.length
                      : tabCountFor(d.key) ?? "—"}
                  </span>
                )}
              </button>
            );
          })}
        </aside>

        <section className="br-center">
          <div className="br-center-head">
            <div>
              <span className="overline">Bulk Review · Editable Deliverable</span>
              <h2>
                {DELIVERABLES.find((d) => d.key === activeKey)?.name ?? "—"}
              </h2>
            </div>
            <div className="br-stats">
              <div className="stat">
                <strong>{totalCount}</strong>
                <span>Entities</span>
              </div>
              <div className="stat">
                <strong style={{ color: "var(--qong-magenta, #FF4DA8)" }}>
                  {rows.filter((r) =>
                    Object.values(r.values).some((v) => v.is_override),
                  ).length}
                </strong>
                <span>Edited</span>
              </div>
              <div className="stat">
                <strong>{editableColumns.length}</strong>
                <span>Editable Cols</span>
              </div>
              <button
                className={`br-btn${saveStatus === "saved" ? " primary" : ""}`}
                onClick={() => void saveAll()}
                disabled={saveStatus === "saving"}
                title={
                  Object.keys(editing).length > 0
                    ? `Save ${Object.keys(editing).length} unsaved cell(s) · Ctrl+S`
                    : "All changes saved · Ctrl+S"
                }
                style={{ marginLeft: 8 }}
              >
                <Save size={12} strokeWidth={1.6} />
                <span>
                  {saveStatus === "saving" ? "Saving…" : saveStatus === "saved" ? "Saved ✓" : "Save"}
                </span>
              </button>
            </div>
          </div>

          <div className="br-table-wrap">
            {loading && (
              <div className="br-empty">Loading entities…</div>
            )}
            {!loading && fetchError && (
              <div className="br-empty" style={{ color: "var(--error, #dc2626)" }}>
                {fetchError}
                <div style={{ marginTop: 12 }}>
                  <button className="br-btn small" onClick={() => void fetchRows()}>
                    Retry
                  </button>
                </div>
              </div>
            )}
            {!loading && !fetchError && !activeType && (
              <div className="br-empty">
                <strong>Coming soon.</strong> No backend generator for this
                deliverable yet.
              </div>
            )}
            {!loading && !fetchError && activeType && rows.length === 0 && (
              <div className="br-empty">
                No entities for this deliverable in job #{jobId}.
              </div>
            )}
            {!loading && !fetchError && activeType && rows.length > 0 && (
              <div className="br-table" style={{ gridTemplateColumns: gridTemplate }}>
                {/* Headers — double-click any cell to rename it (saved in localStorage) */}
                {visibleIdentityCols.map((c) => (
                  <div
                    key={`id-${c.field}`}
                    className="br-th"
                    style={{ cursor: "text" }}
                    onDoubleClick={() => startHeaderEdit(c.field, c.header)}
                    title="Double-click to rename column"
                  >
                    {editingHeader === c.field ? (
                      <input
                        autoFocus
                        value={headerDraft}
                        style={{ width: "100%", border: 0, outline: 0, background: "transparent", font: "inherit", color: "inherit", padding: 0 }}
                        onChange={(e) => setHeaderDraft(e.target.value)}
                        onBlur={commitHeaderEdit}
                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commitHeaderEdit(); } else if (e.key === "Escape") cancelHeaderEdit(); }}
                        onClick={(e) => e.stopPropagation()}
                      />
                    ) : getHeader(c.field, c.header)}
                  </div>
                ))}
                {editableColumns.map((c) => (
                  <div
                    key={`ed-${c.field}`}
                    className="br-th"
                    style={{ cursor: "text" }}
                    onDoubleClick={() => startHeaderEdit(c.field, c.header)}
                    title="Double-click to rename column"
                  >
                    {editingHeader === c.field ? (
                      <input
                        autoFocus
                        value={headerDraft}
                        style={{ width: "100%", border: 0, outline: 0, background: "transparent", font: "inherit", color: "inherit", padding: 0 }}
                        onChange={(e) => setHeaderDraft(e.target.value)}
                        onBlur={commitHeaderEdit}
                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commitHeaderEdit(); } else if (e.key === "Escape") cancelHeaderEdit(); }}
                        onClick={(e) => e.stopPropagation()}
                      />
                    ) : getHeader(c.field, c.header)}
                  </div>
                ))}
                <div className="br-th"></div>

                {filteredRows.map((r) => {
                  const isSel = r.entity_id === selectedId;
                  return (
                    <div
                      key={r.entity_id}
                      className={`br-row ${isSel ? "selected" : ""}`}
                      style={{ display: "contents" }}
                      onClick={() => setSelectedId(r.entity_id)}
                    >
                      {/* Identity cells — editable ones (tag, sub_class) use BulkCell;
                          pid_number + sheet_number stay display-only (backend READ_ONLY_FIELDS). */}
                      {visibleIdentityCols.map((c) => {
                        if (c.editable) {
                          // Construct fv: prefer values dict (has override tracking);
                          // fall back to raw entity property for sub_class which
                          // isn't in the schema template.
                          const fv = r.values[c.field as string] ?? {
                            value: r[c.field],
                            source: "pid" as const,
                            is_override: false,
                          };
                          const fakecol = { field: c.field as string, header: c.header, order: 0, editable: true };
                          return (
                            <BulkCell
                              key={`id-${r.entity_id}-${c.field}`}
                              entity={r}
                              col={fakecol}
                              fv={fv as import("../api").EntityFieldValue}
                              ck={cellKey(r.entity_id, c.field as string)}
                              editing={editing[cellKey(r.entity_id, c.field as string)]}
                              saving={!!saving[cellKey(r.entity_id, c.field as string)]}
                              error={cellError[cellKey(r.entity_id, c.field as string)]}
                              onBeginEdit={() => beginEdit(r, c.field as string)}
                              onChange={(v) => setEditingValue(r, c.field as string, v)}
                              onCancel={() => cancelEdit(r, c.field as string)}
                              onCommit={() => void commitEdit(r, c.field as string)}
                            />
                          );
                        }
                        const raw = r[c.field];
                        const display = raw === null || raw === undefined || raw === "" ? "—" : String(raw);
                        const isEmpty = display === "—";
                        const cls = ["br-td"];
                        if (c.field === "pid_number") cls.push("mono");
                        return (
                          <div
                            key={`id-${r.entity_id}-${c.field}`}
                            className={cls.join(" ")}
                            style={{ color: isEmpty ? "var(--fg-3)" : "var(--fg-2)", fontStyle: isEmpty ? "italic" : "normal" }}
                            title="Read-only — pipeline-extracted"
                          >
                            {display}
                          </div>
                        );
                      })}

                      {/* Editable cells — click to edit, blur/Enter to commit. */}
                      {editableColumns.map((col) => {
                        const isMasked = isSel && !vendorAccepted && VENDOR_FIELDS.has(col.field);
                        const fv: EntityFieldValue | undefined = isMasked ? undefined : r.values[col.field];
                        return (
                          <BulkCell
                            key={`ed-${r.entity_id}-${col.field}`}
                            entity={r}
                            col={col}
                            fv={fv}
                            ck={cellKey(r.entity_id, col.field)}
                            editing={editing[cellKey(r.entity_id, col.field)]}
                            saving={!!saving[cellKey(r.entity_id, col.field)]}
                            error={cellError[cellKey(r.entity_id, col.field)]}
                            onBeginEdit={() => beginEdit(r, col.field)}
                            onChange={(v) => setEditingValue(r, col.field, v)}
                            onCancel={() => cancelEdit(r, col.field)}
                            onCommit={() => void commitEdit(r, col.field)}
                          />
                        );
                      })}

                      {/* Per-row action: jump back into Studio with this entity. */}
                      <div
                        className="br-td"
                        style={{
                          textAlign: "center",
                          padding: "8px 6px",
                          cursor: "pointer",
                          color: "var(--fg-3)",
                        }}
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenEntity(r.entity_id, r.entity_class);
                        }}
                        title="Open this entity in Studio (datasheet drawer)"
                      >
                        <ArrowUpRight size={13} strokeWidth={1.6} />
                      </div>
                    </div>
                  );
                })}

                {filteredRows.length === 0 && (
                  <div className="br-empty" style={{ gridColumn: "1 / -1" }}>
                    {debouncedFilter || showOnlyEdited
                      ? "No entities match the current filter."
                      : "No entities to show."}
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        {showDetail && (
          <aside className="br-detail">
            <div className="row-hd">
              <span className="overline">
                {selectedRow
                  ? `Row · ${filteredRows.findIndex((r) => r.entity_id === selectedRow.entity_id) + 1} of ${filteredRows.length}`
                  : "No row selected"}
              </span>
              <div className="nav">
                <button
                  title="Previous row"
                  onClick={() => {
                    if (!selectedRow) return;
                    const idx = filteredRows.findIndex(
                      (r) => r.entity_id === selectedRow.entity_id,
                    );
                    if (idx > 0) setSelectedId(filteredRows[idx - 1].entity_id);
                  }}
                  disabled={!selectedRow}
                >
                  <ChevronUp size={13} strokeWidth={1.6} />
                </button>
                <button
                  title="Next row"
                  onClick={() => {
                    if (!selectedRow) return;
                    const idx = filteredRows.findIndex(
                      (r) => r.entity_id === selectedRow.entity_id,
                    );
                    if (idx >= 0 && idx < filteredRows.length - 1) {
                      setSelectedId(filteredRows[idx + 1].entity_id);
                    }
                  }}
                  disabled={!selectedRow}
                >
                  <ChevronDown size={13} strokeWidth={1.6} />
                </button>
                <button title="Close panel" onClick={() => setShowDetail(false)}>
                  <X size={13} strokeWidth={1.6} />
                </button>
              </div>
            </div>

            {selectedRow ? (
              <>
                <h3 style={{ color: "var(--qong-magenta, #FF4DA8)" }}>
                  {activeKey === "lines"
                    ? (valueToString(selectedRow.values["fields.line"]?.value) || selectedRow.tag || "Untagged")
                    : (selectedRow.tag || "Untagged")}
                </h3>
                {activeKey !== "lines" && (
                <div
                  className="row-meta"
                  style={{ display: "flex", alignItems: "center", gap: 6 }}
                >
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 9.5,
                      letterSpacing: "0.14em",
                      textTransform: "uppercase",
                      padding: "2px 6px",
                      borderRadius: 4,
                      background: "var(--bg-elev)",
                      border: "1px solid var(--border)",
                      color: "var(--fg-2)",
                    }}
                  >
                    {selectedRow.entity_class}
                  </span>
                  <span>{selectedRow.sub_class}</span>
                </div>
                )}
                <div
                  className="row-meta"
                  style={{ fontSize: 10.5, marginTop: 4, opacity: 0.7 }}
                >
                  {selectedRow.pid_number} · sheet {selectedRow.sheet_number}
                </div>

                {/* Datasheet deliverable: show the entity's FULL per-type
                    datasheet (all sections, chosen automatically by sub_class)
                    instead of the few list columns. Edits persist via PATCH.
                    Keyed by entity_id so internal state resets per row. */}
                {activeKey === "datasheet" ? (
                  <div className="group" style={{ marginLeft: -16, marginRight: -16 }}>
                    <DatasheetPanel
                      key={selectedRow.entity_id}
                      jobId={jobId}
                      entityId={selectedRow.entity_id}
                      onSaved={() => void fetchRows()}
                    />
                  </div>
                ) : (
                <div className="group">
                  <h4>Fields</h4>
                  <dl style={{ margin: 0 }}>
                    {schema.map((col) => {
                      // When PDF is open with pending vendor, hide vendor fields
                      const isVendorSelectionMode = pdfModalUrl && pendingVendorData;
                      if (isVendorSelectionMode && VENDOR_FIELDS.has(col.field)) {
                        return null;
                      }
                      const fv = selectedRow.values[col.field];
                      // Show vendor fields as empty until vendor is accepted this session
                      let v = VENDOR_FIELDS.has(col.field) && !vendorAccepted
                        ? ""
                        : valueToString(fv?.value);
                      // Display datasheet_ref as "TBD" instead of a raw URL
                      if (col.field === "fields.datasheet_ref" && v) {
                        v = "TBD";
                      }
                      const empty = v === "";
                      const overridden = !!fv?.is_override;
                      return (
                        <Fragment key={col.field}>
                        <div className="kv">
                          <span className="k">{col.header}</span>
                          <span
                            className={`v ${empty ? "miss" : ""}`}
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 6,
                            }}
                          >
                            {empty ? "—" : v}
                            {overridden && (
                              <span
                                title="This value was edited from its original P&ID-extracted value"
                                style={{
                                  width: 6,
                                  height: 6,
                                  borderRadius: "50%",
                                  background: "var(--qong-magenta, #FF4DA8)",
                                  display: "inline-block",
                                }}
                              />
                            )}
                            {!overridden && fv?.source === "pid" && !empty && (
                              <span
                                title="Pipeline-extracted from the P&ID"
                                style={{
                                  width: 6,
                                  height: 6,
                                  borderRadius: "50%",
                                  background: "var(--qong-cyan, #06b6d4)",
                                  display: "inline-block",
                                  opacity: 0.7,
                                }}
                              />
                            )}
                          </span>
                        </div>
                        {activeKey === "index" && col.field === "fields.pair_no" && (
                          <>
                            <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: "6px 0" }} />
                            <div className="kv" style={{ flexDirection: "column", gap: 4, alignItems: "stretch" }}>
                              <span className="k">Select Vendor</span>
                              {vendorLoading ? (
                                <span style={{ fontSize: 11, color: "var(--fg-3)", padding: "4px 0" }}>Loading vendors…</span>
                              ) : (() => {
                                  const hasVendors = vendorApiData && vendorApiData.length > 0;
                                  return (
                                    <select
                                      key={selectedRow?.entity_id}
                                      value={pendingVendorData ? String(pendingVendorData.product_id) : ""}
                                      disabled={vendorSaving || !hasVendors}
                                      onChange={(e) => { void handleVendorSelect(e.target.value); }}
                                      style={{
                                        width: "100%",
                                        height: 32,
                                        padding: "0 10px",
                                        background: "var(--surface)",
                                        border: "1px solid var(--border)",
                                        borderRadius: 8,
                                        color: "var(--fg-1)",
                                        fontSize: 12.5,
                                        fontFamily: "var(--font-sans)",
                                        outline: "none",
                                        cursor: hasVendors ? "pointer" : "not-allowed",
                                        appearance: "auto",
                                        opacity: vendorSaving ? 0.6 : 1,
                                      }}
                                    >
                                      <option value="">
                                        {hasVendors ? "-- Choose a Vendor --" : "-- No vendors found --"}
                                      </option>
                                      {vendorApiData && vendorApiData.map((v) => (
                                        <option key={String(v.product_id)} value={String(v.product_id)}>
                                          {String(v.manufacturer ?? "")}
                                        </option>
                                      ))}
                                    </select>
                                  );
                                })()}
                              {vendorSaving && (
                                <span style={{ fontSize: 11, color: "var(--fg-3)" }}>Applying vendor data…</span>
                              )}
                            </div>
                          </>
                        )}
                        </Fragment>
                      );
                    })}
                  </dl>
                </div>
                )}

                <div className="actions" style={{ marginTop: 16, display: activeKey === "datasheet" ? "none" : "flex", gap: 8 }}>
                  <button
                    className="br-btn small primary"
                    onClick={() => onOpenEntity(selectedRow.entity_id, selectedRow.entity_class)}
                  >
                    <ArrowUpRight size={11} strokeWidth={1.6} /> Open in Studio
                  </button>
                </div>
              </>
            ) : (
              <div className="row-meta" style={{ marginTop: 12 }}>
                Select a row to inspect its fields.
              </div>
            )}
          </aside>
        )}
      </div>
      {pdfModalUrl && (
        <PdfModal
          url={pdfModalUrl}
          onClose={() => setPdfModalUrl(null)}
          onAccept={handleVendorAccept}
          onDecline={handleVendorDecline}
        />
      )}
    </div>
  );
}

/** One editable cell. Click → input; Enter / blur → PATCH; Esc → revert.
 *  Renders a P&ID dot for pipeline-extracted, un-overridden cells, and an
 *  EDITED dot for cells with an override. Read-only `null` / `""` show "—". */
function BulkCell({
  entity,
  col,
  fv,
  editing,
  saving,
  error,
  onBeginEdit,
  onChange,
  onCancel,
  onCommit,
}: {
  entity: EntityRow;
  col: EntityColumn;
  fv: EntityFieldValue | undefined;
  ck: string;
  editing: string | undefined;
  saving: boolean;
  error: string | undefined;
  onBeginEdit: () => void;
  onChange: (v: string) => void;
  onCancel: () => void;
  onCommit: () => void;
}) {
  const display = valueToString(fv?.value);
  const isEmpty = display === "";
  const isOverride = !!fv?.is_override;
  const isPidSourced = fv?.source === "pid" && !isOverride && !isEmpty;
  const isEditing = editing !== undefined;

  // Auto-save: commit 10s after the last keystroke. onCommitRef keeps a
  // stable pointer so the timer closure always calls the latest callback.
  const autoSaveRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onCommitRef = useRef(onCommit);
  onCommitRef.current = onCommit;

  function resetAutoSave() {
    if (autoSaveRef.current) clearTimeout(autoSaveRef.current);
    autoSaveRef.current = setTimeout(() => onCommitRef.current(), 10_000);
  }

  useEffect(() => {
    if (!isEditing) {
      if (autoSaveRef.current) clearTimeout(autoSaveRef.current);
      return;
    }
    resetAutoSave();
    return () => { if (autoSaveRef.current) clearTimeout(autoSaveRef.current); };
  }, [isEditing]); // eslint-disable-line react-hooks/exhaustive-deps

  // Click-to-edit affordance: a single click flips the cell into an input,
  // pre-populated with the current value. We deliberately don't use a separate
  // "edit" icon — the whole cell is the affordance.
  return (
    <div
      className="br-td"
      style={{
        position: "relative",
        padding: isEditing ? "4px 6px" : "10px 12px",
        cursor: isEditing ? "text" : "pointer",
        background: isEditing ? "var(--bg-elev)" : undefined,
        boxShadow: error ? "inset 0 0 0 1px var(--error, #dc2626)" : undefined,
      }}
      onDoubleClick={(e) => {
        if (isEditing) return;
        e.stopPropagation();
        onBeginEdit();
      }}
      title={error || (isOverride ? "Edited — double-click to edit" : isPidSourced ? "P&ID-extracted — double-click to edit" : "Double-click to edit")}
    >
      {isEditing ? (
        <input
          autoFocus
          type="text"
          value={editing ?? ""}
          disabled={saving}
          onChange={(e) => { onChange(e.target.value); resetAutoSave(); }}
          onClick={(e) => e.stopPropagation()}
          onBlur={() => onCommit()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || (e.key === "s" && (e.ctrlKey || e.metaKey))) {
              e.preventDefault();
              onCommit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              onCancel();
            }
          }}
          style={{
            width: "100%",
            border: 0,
            outline: 0,
            background: "transparent",
            font: "inherit",
            color: "var(--fg-1)",
            padding: "6px 6px",
          }}
        />
      ) : (
        <>
          <span
            style={{
              color: isEmpty ? "var(--fg-3)" : "var(--fg-1)",
              fontStyle: isEmpty ? "italic" : "normal",
            }}
          >
            {isEmpty ? "—" : display}
          </span>
          {/* P&ID dot — top-right corner, small + subtle */}
          {isPidSourced && (
            <span
              style={{
                position: "absolute",
                top: 6,
                right: 6,
                width: 5,
                height: 5,
                borderRadius: "50%",
                background: "var(--qong-cyan, #06b6d4)",
                opacity: 0.7,
              }}
            />
          )}
          {/* EDITED dot — magenta, takes precedence over the P&ID dot */}
          {isOverride && (
            <span
              style={{
                position: "absolute",
                top: 6,
                right: 6,
                width: 5,
                height: 5,
                borderRadius: "50%",
                background: "var(--qong-magenta, #FF4DA8)",
              }}
            />
          )}
        </>
      )}
      {/* Make the entity prop "used" for ESLint — col + entity power the title
       *  attribute upstream, and entity is part of the prop API even though
       *  the cell itself doesn't render it. */}
      <span style={{ display: "none" }} aria-hidden>{entity.entity_id}{col.field}</span>
    </div>
  );
}
