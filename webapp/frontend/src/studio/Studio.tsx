import { useEffect, useMemo, useRef, useState } from "react";
import { Check, CheckCheck, Maximize, Minus, PanelRightOpen, Plus } from "lucide-react";
import { useTheme } from "../theme/ThemeContext";
import BulkReviewScreen from "./bulk-review/BulkReviewScreen";
import DatasheetDrawer from "./datasheet/DatasheetDrawer";
import PidCanvas from "./PidCanvas";
import PropertiesPanel from "./PropertiesPanel";
import StudioFoot from "./StudioFoot";
import StudioTopBar from "./StudioTopBar";
import { buildSheets } from "./buildSheets";
import {
  getEntities,
  getJobDetections,
  getJobSheets,
  type EntitiesResponse,
  type JobDetectionsResp,
  type JobSheetsResp,
} from "./api";
import { buildElementsForTile, buildEntityIndex } from "./buildElements";
import type { CanvasElement, ProjectLike, SessionEvent } from "./types";
// FEATURES #38 — marking + edge drawing wiring
import type { CanvasMode, LineType, UserAnnotationLite, EdgeLite } from "./PidCanvas";
import PalettePanel from "./annotations/PalettePanel";
import ModeToolbar from "./annotations/ModeToolbar";
import { useAnnotations } from "./annotations/useAnnotations";
import LineTypeToolbar from "./edges/LineTypeToolbar";
import { EdgeMetadataDrawer } from "./edges/EdgeMetadataDrawer";
import { useEdges } from "./edges/useEdges";
import { useShortcuts } from "./shortcuts/useShortcuts";
import { useShortcutDispatcher } from "./shortcuts/useShortcutDispatcher";
import type { ShortcutBinding } from "./shortcuts/api";

/**
 * Studio — full-bleed P&ID reviewer. Three-pane: sheet rail · canvas · properties.
 *
 * Phase 2a: visual shell with prototype canvas data. Real wiring to Job rows
 * (real sheets per PDF, real detections) is Phase 2b. Datasheet drawer +
 * Bulk Review workbench are Phase 2b/2c.
 */
interface Props {
  project: ProjectLike;
  userName: string;
  onBack: () => void;
}

const DEMO_ELEMENT_DATA: Record<string, CanvasElement> = {
  "PV-203": {
    tag: "PV-203",
    type: "Control Valve",
    confidence: 0.71,
    lines: ["Inflow from P-101", "Outflow to E-104 (uncertain)"],
  },
  "V-101": {
    tag: "V-101",
    type: "Block Valve",
    confidence: 0.94,
    lines: ["Inflow from header", "Outflow to FT-101"],
  },
  "FT-101": {
    tag: "FT-101",
    type: "Flow Transmitter",
    confidence: 0.88,
    lines: ["Mounted on header", "Signal to DCS"],
  },
  "P-101": {
    tag: "P-101",
    type: "Centrifugal Pump",
    confidence: 0.92,
    lines: ["Suction from sump", "Discharge to PV-203"],
  },
  "E-104": {
    tag: "E-104",
    type: "Shell & Tube Exchanger",
    confidence: 0.66,
    lines: ["No upstream edge", "Outlet to drum D-201"],
  },
};

const DATASHEET_TYPES = new Set(["Control Valve", "Flow Transmitter", "Block Valve", "Centrifugal Pump"]);

export default function Studio({ project, userName, onBack }: Props) {
  const { theme } = useTheme();
  const dark = theme === "dark";

  const sheets = useMemo(() => buildSheets(project), [project]);
  const defaultSheetIdx = sheets.findIndex((s) => s.status === "issues");
  const [activeSheet, setActiveSheet] = useState(defaultSheetIdx >= 0 ? defaultSheetIdx : 2);
  const [selectedId, setSelectedId] = useState<string>("PV-203");
  // entity_class for the currently-selected detection (post-D1.5). Undefined
  // for prototype SVG clicks. Drives the DatasheetDrawer's initial doctype so
  // clicking a valve opens Valve List, not Instrument Index.
  const [selectedClass, setSelectedClass] = useState<string | undefined>(undefined);
  const handleSelect = (id: string, entityClass?: string) => {
    setSelectedId(id);
    setSelectedClass(entityClass);
  };
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [datasheetOpen, setDatasheetOpen] = useState(false);
  const [mode, setMode] = useState<"studio" | "bulk">("studio");
  // The deliverable_type the workbench opens with. Today we default to
  // "datasheet" — same as the DatasheetDrawer's initial DocType, so the two
  // surfaces stay in sync when the user toggles between them. Lifting this
  // to state (rather than a const) preserves the seam for D6+: a future
  // sidebar tab in Studio that lets the user pick which deliverable to
  // review would call a setter here. The workbench's own tab-switcher is
  // local-state by design (tab changes shouldn't pollute Studio).
  // Default to Valve List in Bulk Review — most jobs have valves first, and
  // it's the deliverable customers always see (Instrument Index only populates
  // when the instrumentation pass detects instruments, which on some P&IDs is
  // 0). Was "datasheet" — too narrow as a starting point.
  const [activeDeliverableType] = useState<string>("valve_list");

  // Real backend data — falls back to prototype when unavailable so the studio
  // never breaks on jobs without tiles/detections (e.g. seed data, brand-new
  // uploads still being processed).
  const [sheetsResp, setSheetsResp] = useState<JobSheetsResp | null>(null);
  const [detResp, setDetResp] = useState<JobDetectionsResp | null>(null);
  // Canonical entities by deliverable type. Fetched once per job — feeds the
  // dynamic right-panel rows so clicking a real bbox surfaces the matched
  // tag / sub_class / confidence instead of the DEMO_ELEMENT_DATA stand-in.
  // Two calls (one per deliverable type) — equipment_list is added when
  // equipment detections start landing in canonical, currently always empty.
  const [valveEntitiesResp, setValveEntitiesResp] = useState<EntitiesResponse | null>(null);
  const [instEntitiesResp, setInstEntitiesResp] = useState<EntitiesResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    getJobSheets(project.id)
      .then((r) => {
        if (!cancelled) setSheetsResp(r);
      })
      .catch(() => {
        if (!cancelled) setSheetsResp(null);
      });
    getJobDetections(project.id)
      .then((r) => {
        if (!cancelled) setDetResp(r);
      })
      .catch(() => {
        if (!cancelled) setDetResp(null);
      });
    // Best-effort entity fetches — 404 just means the job has no canonical
    // (legacy, brand new) and the panel will fall through to prototype.
    getEntities(project.id, "valve_list")
      .then((r) => {
        if (!cancelled) setValveEntitiesResp(r);
      })
      .catch(() => {
        if (!cancelled) setValveEntitiesResp(null);
      });
    getEntities(project.id, "instrument_index")
      .then((r) => {
        if (!cancelled) setInstEntitiesResp(r);
      })
      .catch(() => {
        if (!cancelled) setInstEntitiesResp(null);
      });
    return () => {
      cancelled = true;
    };
  }, [project.id]);

  const realSheets = sheetsResp?.sheets;
  const activeTileUrl =
    realSheets && realSheets[activeSheet]?.url ? realSheets[activeSheet].url : null;
  // Tile filename (e.g. "tile_p0_r1_c2.png") — DetectionOverlay uses this to
  // filter `detections` down to the bboxes that actually belong to this tile.
  const activeTileFilename =
    realSheets && realSheets[activeSheet]?.filename ? realSheets[activeSheet].filename : null;

  // FEATURES #38 Phase 2: full-page render takes precedence over per-tile mode.
  // Derive the page index from the active tile filename ("tile_p0_r1_c2.png" → 0).
  // The page-full image URL is deterministic; no extra fetch needed.
  const activePageIndex = useMemo(() => {
    if (!activeTileFilename) return 0;
    const m = activeTileFilename.match(/tile_p(\d+)_/);
    return m ? parseInt(m[1], 10) : 0;
  }, [activeTileFilename]);
  // Best-effort: assume page-full exists; PidCanvas falls back to tile mode if
  // the <img> 404s (browser shows broken image — surfaced via onError in v2).
  //
  // FEATURES #41 — Hi-DPI render. Earlier we sized the request to the user's
  // viewport, but that left 2K-non-Retina laptops getting the 4x baseline
  // (still soft after browser downsample). The simplest fix that works for
  // everyone: ALWAYS request the same hi-DPI render. The backend caches it
  // per-job-per-page so we only pay the ~1.5s re-render cost once per page,
  // and every subsequent user gets a hot file. 5500 px wide gives crisp
  // text on every display from 1080p to 5K iMac without exploding storage
  // (~1.2 MB per page-full).
  const HI_DPI_TARGET_PX = 5500;
  const activePageFullUrl = realSheets && realSheets.length > 0
    ? `/jobs/${project.id}/page/${activePageIndex}/full?w=${HI_DPI_TARGET_PX}`
    : null;

  // ── FEATURES #38: marking + edge drawing state ──────────────────────────
  const [canvasMode, setCanvasMode] = useState<CanvasMode>("select");
  const [activeMarkClass, setActiveMarkClass] = useState<
    { entity_class: string; sub_class: string } | null
  >(null);
  const [activeLineType, setActiveLineType] = useState<LineType>("process_pipe");
  const [pendingEdgeForMetadata, setPendingEdgeForMetadata] = useState<EdgeLite | null>(null);

  const { annotations, create: createAnnotation, remove: removeAnnotation } = useAnnotations(project.id);
  const { edges, create: createEdge, patch: patchEdge } = useEdges(project.id);
  const { shortcuts } = useShortcuts();

  // Filter to current sheet — both stores carry sheet_number for multi-page jobs.
  const activeSheetNumber = activePageIndex + 1;
  const sheetAnnotations: UserAnnotationLite[] = useMemo(
    () => annotations.filter((a) => a.sheet_number === activeSheetNumber),
    [annotations, activeSheetNumber],
  );
  const sheetEdges: EdgeLite[] = useMemo(
    () => edges.filter((e) => e.sheet_number === activeSheetNumber),
    [edges, activeSheetNumber],
  );

  function onDropMark(
    bbox: [number, number, number, number],
    sub_class: string,
    entity_class: string,
  ) {
    // entity_class comes from PalettePanel (string-typed at the canvas boundary)
    // but the backend only accepts the EntityClass union. Reject anything else
    // up-front rather than narrow with `as`.
    if (entity_class !== "valve" && entity_class !== "instrument" && entity_class !== "equipment") return;
    void createAnnotation({
      entity_class,
      sub_class,
      bbox,
      sheet_number: activeSheetNumber,
      linked_detection_index: null,
    });
    // Stay armed for rapid placement; press Esc or click the palette button
    // again to disarm.
  }

  // Resolve a selectedId → its UserAnnotation row (or null if it's a model
  // detection / prototype tag). Used to decide whether the Delete affordances
  // should be active.
  const selectedAnnotation = useMemo(
    () => annotations.find((a) => a.entity_id === selectedId) ?? null,
    [annotations, selectedId],
  );
  const canDeleteSelected = selectedAnnotation?.source === "user";

  async function handleDeleteAnnotation(entityId: string | null) {
    if (!entityId) return;
    const target = annotations.find((a) => a.entity_id === entityId);
    if (!target || target.source !== "user") {
      // Quietly bail if there's nothing user-added to delete. Surfaces the
      // "model detections aren't deletable here" contract without throwing.
      return;
    }
    const friendly =
      target.tag ??
      target.placeholder_tag ??
      target.sub_class ??
      "annotation";
    const ok = window.confirm(`Delete ${friendly}? This can't be undone.`);
    if (!ok) return;
    const success = await removeAnnotation(entityId);
    if (success) {
      // Clear selection so the panel doesn't show a stale row.
      setSelectedId("");
      setSelectedClass(undefined);
      showToast(`Deleted ${friendly}`);
    } else {
      showToast(`Failed to delete ${friendly}`);
    }
  }

  async function onEdgeDrawn(
    source_entity_id: string,
    target_entity_id: string,
    polyline: Array<[number, number]>,
    line_type: LineType,
  ) {
    const created = await createEdge({
      line_type,
      source_entity_id,
      target_entity_id,
      polyline,
      sheet_number: activeSheetNumber,
    });
    if (created) setPendingEdgeForMetadata(created);
  }

  function dispatchShortcut(binding: ShortcutBinding) {
    switch (binding.action) {
      case "select-class":
        if (binding.entity_class && binding.sub_class) {
          setActiveMarkClass({
            entity_class: binding.entity_class,
            sub_class: binding.sub_class,
          });
          setCanvasMode("mark-symbol");
        }
        break;
      case "mode":
        if (binding.mode === "select" || binding.mode === "mark-symbol" || binding.mode === "draw-edge") {
          setCanvasMode(binding.mode as CanvasMode);
        }
        break;
      case "cancel":
        setCanvasMode("select");
        setActiveMarkClass(null);
        setPendingEdgeForMetadata(null);
        break;
      case "delete-selected":
        // FEATURES #41: delete the selected entity if (and only if) it's a
        // user-added annotation. Model detections aren't deletable through
        // this path — they belong to the canonical entity store, which has
        // its own reject-confirm lifecycle (status="user_rejected"). For a
        // user-added mark, fire the same flow the panel's Delete button
        // uses so the keyboard shortcut and the click stay consistent.
        void handleDeleteAnnotation(selectedId);
        break;
    }
  }

  // Disable the dispatcher while the datasheet drawer or edge metadata
  // drawer is open (those own their own keyboard focus). useShortcuts
  // returns an empty map while loading, so the dispatcher safely runs
  // from the first render — it just won't match anything yet.
  useShortcutDispatcher(shortcuts, dispatchShortcut, {
    enabled: !datasheetOpen && !pendingEdgeForMetadata,
  });

  // Lock body scroll while studio is mounted (full-bleed surface)
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  // When the backend returns more sheets than the prototype-builder produced
  // (e.g. a job with 9 detected tiles vs `buildSheets` returning 8), clicking
  // the extra tile would set activeSheet beyond `sheets.length`, leaving
  // `sheets[activeSheet]` undefined — StudioTopBar then crashes on
  // `currentSheet.name` and the whole tree unmounts (white page). Synthesise
  // a Sheet from the real-sheet metadata as a fallback. Last-resort: first
  // sheet so this can never be undefined.
  const current =
    sheets[activeSheet] ??
    (realSheets && realSheets[activeSheet]
      ? {
          id: realSheets[activeSheet].id,
          name: realSheets[activeSheet].label,
          label: realSheets[activeSheet].label,
          status: "ok" as const,
          issues: 0,
        }
      : sheets[0]);
  const totalIssues = sheets.reduce((s, x) => s + (x.issues || 0), 0);

  // ── Dynamic element panel data (Phase A of "make it more dynamic") ─────
  // entityIndex: every canonical entity for this job, keyed by entity_id.
  // realElements: rows for the active tile only, built from live detections
  //               that have an entity_id (i.e. matched by the D1.5 matcher).
  // panelElements: real when present, prototype fallback otherwise — keeps
  //               the studio renderable on brand-new uploads / legacy jobs.
  const entityIndex = useMemo(
    () => buildEntityIndex([valveEntitiesResp, instEntitiesResp]),
    [valveEntitiesResp, instEntitiesResp],
  );
  const realElements = useMemo(
    () => buildElementsForTile(detResp?.detections, entityIndex, activeTileFilename),
    [detResp, entityIndex, activeTileFilename],
  );
  const hasRealElements = Object.keys(realElements).length > 0;
  const panelElements = hasRealElements ? realElements : DEMO_ELEMENT_DATA;

  // When real data first lands and the user hasn't picked anything yet,
  // jump selectedId to the first matched detection on the active tile so
  // the right panel shows live data immediately (instead of PV-203 demo).
  useEffect(() => {
    if (!hasRealElements) return;
    if (!DEMO_ELEMENT_DATA[selectedId]) return; // user already picked something real
    const [firstId, firstEl] = Object.entries(realElements)[0];
    setSelectedId(firstId);
    setSelectedClass(firstEl.entityClass);
  }, [hasRealElements, realElements, selectedId]);

  const sel = panelElements[selectedId] || Object.values(panelElements)[0];
  const hasDatasheet = DATASHEET_TYPES.has(sel.type) || sel.entityClass === "valve" || sel.entityClass === "instrument";

  const sessionEvents: SessionEvent[] = [
    { who: userName, when: "just now", what: "selected PV-203" },
    { who: userName, when: "2m ago", what: "confirmed FT-101 type" },
    { who: userName, when: "5m ago", what: "linked P-101 → V-101" },
  ];

  // ── Redesign Jun 2026 — Apply / Properties strip / toast ───────────────
  // `appliedBySheet` is UI-only state: the design treats "Apply" as a
  // reviewer's intent ("I'm done with this sheet") rather than a backend
  // mutation. Annotations are already persisted on creation, so Apply just
  // updates a per-sheet count badge (shown in the SheetPicker dropdown) and
  // flips the toolbar button to its "Applied" confirmation state.
  const [appliedBySheet, setAppliedBySheet] = useState<Record<number, number>>({});
  const [propsOpen, setPropsOpen] = useState(true);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);
  const showToast = (msg: string) => {
    setToast(msg);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  };
  useEffect(
    () => () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    },
    [],
  );

  const applyCount = sheetAnnotations.length;
  const currentApplied = appliedBySheet[current.id] ?? 0;
  // Re-arm the Apply button whenever the user adds/removes marks after applying.
  const applied = currentApplied > 0 && currentApplied === applyCount;
  function handleApply() {
    if (!applyCount) return;
    setAppliedBySheet((s) => ({ ...s, [current.id]: applyCount }));
    showToast(
      `Applied ${applyCount} mark${applyCount === 1 ? "" : "s"} to ${current.name.replace(".pdf", "")}`,
    );
  }

  // Export Deliverables — wired from PropertiesPanel rows. Each row maps to a
  // deliverable_type/file_format pair on the existing
  // POST /api/v1/jobs/{id}/export/{deliverable_type}/{file_format} endpoint.
  // Format is "xlsx" for everything except valve_list which has a CSV variant
  // we keep around for legacy customers. Errors surface as a toast — the
  // current panel doesn't have a per-row error slot yet (follow-up).
  const EXPORT_FORMAT: Record<string, "csv" | "xlsx"> = {
    valve_list: "csv",
    instrument_index: "xlsx",
    equipment_list: "xlsx",
    datasheet: "xlsx",
  };
  async function onExportDeliverable(type: string) {
    const format = EXPORT_FORMAT[type] || "xlsx";
    // Soft-block unknown deliverable types — the prototype shipped 6 (Control
    // Narrative, Cause & Effect, I/O List) that the backend doesn't generate
    // yet. Surface clearly rather than 404.
    if (!EXPORT_FORMAT[type]) {
      showToast(`"${type}" export isn't available yet`);
      return;
    }
    const url = `/api/v1/jobs/${project.id}/export/${type}/${format}`;
    showToast(`Preparing ${type.replace("_", " ")} (${format.toUpperCase()})…`);
    try {
      const res = await fetch(url, { method: "POST", credentials: "include" });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        showToast(`Export failed (HTTP ${res.status}) ${detail.slice(0, 60)}`);
        return;
      }
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = `job-${project.id}-${type}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      showToast(`${type.replace("_", " ")} downloaded`);
    } catch (e) {
      showToast(`Export error: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  function onOpenDatasheet() {
    // If the user hasn't picked a real bbox yet, selectedId is still the
    // prototype default ("PV-203" etc.). Auto-select the first detection
    // that the D1.5 matcher attached an entity_id to, so the drawer opens
    // on real data instead of erroring out on a prototype tag. Falls
    // through to the prototype if there are no real detections (e.g.
    // brand-new upload still processing) — drawer's "pick an entity"
    // empty state then takes over.
    if (DEMO_ELEMENT_DATA[selectedId]) {
      const firstReal = detResp?.detections?.find(
        (d) => d.entity_id && d.entity_class,
      );
      if (firstReal?.entity_id) {
        handleSelect(firstReal.entity_id, firstReal.entity_class);
      }
    }
    setDatasheetOpen(true);
  }

  function onBulkReview() {
    setDatasheetOpen(false);
    setMode("bulk");
  }

  if (mode === "bulk") {
    return (
      <BulkReviewScreen
        jobId={project.id}
        projectName={project.name}
        initialDeliverableType={activeDeliverableType}
        onBack={() => setMode("studio")}
        onOpenEntity={(entityId, entityClass) => {
          // BulkReview row → Studio drawer. `entityId` is the canonical UUID
          // (string). Studio's `selectedId` is happy to hold either a UUID
          // (D1.5+ canvas selections) or a prototype tag, so this just works.
          // `entityClass` drives the drawer's initial deliverable_type.
          handleSelect(entityId, entityClass);
          setMode("studio");
          setDatasheetOpen(true);
        }}
      />
    );
  }

  return (
    <div className="studio" data-screen-label="03 Project Studio">
      <StudioTopBar
        jobId={project.id}
        projectName={project.name}
        currentSheet={current}
        sheets={sheets}
        sheetCount={sheets.length}
        activeSheet={activeSheet}
        onActivateSheet={setActiveSheet}
        projectId={project.id}
        dark={dark}
        realSheets={realSheets}
        appliedBySheet={appliedBySheet}
        userName={userName}
        onBack={onBack}
        onSave={onBack}
        onBulkReview={onBulkReview}
      />

      <div className={`studio-body studio-body--draw ${propsOpen ? "with-props" : "with-strip"}`}>
        <PalettePanel
          activeMarkClass={activeMarkClass}
          onChange={(next) => {
            setActiveMarkClass(next);
            // Arming a class auto-enters mark-symbol mode; disarming returns to select.
            setCanvasMode(next ? "mark-symbol" : "select");
          }}
          dark={dark}
        />

        <section className="canvas-col">
          <div className="canvas-toolbar">
            <ModeToolbar mode={canvasMode} setMode={setCanvasMode} dark={dark} />
            {canvasMode === "draw-edge" && (
              <LineTypeToolbar
                activeLineType={activeLineType}
                setActiveLineType={setActiveLineType}
                dark={dark}
              />
            )}
            <div className="canvas-toolbar-spring" />
            {totalIssues > 0 && (
              <span className="canvas-toolbar-issues" title={`${totalIssues} issues across this project`}>
                <span className="num">{totalIssues}</span> issues
              </span>
            )}
            <button
              type="button"
              className={`dx-apply ${applied ? "done" : ""}`}
              onClick={handleApply}
              disabled={!applyCount}
              title={
                applyCount
                  ? `Apply ${applyCount} mark${applyCount === 1 ? "" : "s"} to this sheet`
                  : "Draw at least one box to apply"
              }
            >
              {applied ? <CheckCheck size={16} strokeWidth={2} /> : <Check size={16} strokeWidth={2} />}
              {applied ? "Applied" : `Apply${applyCount ? ` · ${applyCount}` : ""}`}
            </button>
          </div>
          <PidCanvas
            selectedId={selectedId}
            onSelect={handleSelect}
            zoom={zoom}
            setZoom={setZoom}
            pan={pan}
            setPan={setPan}
            dark={dark}
            pageFullUrl={activePageFullUrl}
            pageIndex={activePageIndex}
            tileImageUrl={activeTileUrl}
            tileFilename={activeTileFilename}
            detections={detResp?.detections}
            valveCount={detResp?.valves.length ?? 0}
            valveCountTotal={detResp?.valve_count ?? 0}
            mode={canvasMode}
            userAnnotations={sheetAnnotations}
            edges={sheetEdges}
            onDropMark={onDropMark}
            onEdgeDrawn={onEdgeDrawn}
            activeLineType={activeLineType}
            activeMarkClass={activeMarkClass}
          />
          <div className="zoom-ctl">
            <button
              onClick={() => setZoom((z) => Math.min(4, +(z + 0.2).toFixed(2)))}
              title="Zoom in (or scroll up)"
            >
              <Plus size={14} strokeWidth={1.6} />
            </button>
            <button
              onClick={() => setZoom((z) => Math.max(0.3, +(z - 0.2).toFixed(2)))}
              title="Zoom out (or scroll down)"
            >
              <Minus size={14} strokeWidth={1.6} />
            </button>
            <button
              onClick={() => {
                setZoom(1);
                setPan({ x: 0, y: 0 });
              }}
              title="Reset view"
            >
              <Maximize size={14} strokeWidth={1.6} />
            </button>
          </div>
          <div className="zoom-readout">{Math.round(zoom * 100)}%</div>
          {toast && (
            <div className="studio-toast" role="status">
              <CheckCheck size={15} strokeWidth={2} /> {toast}
            </div>
          )}
        </section>

        {propsOpen ? (
          <PropertiesPanel
            elements={panelElements}
            selectedId={selectedId}
            onSelect={handleSelect}
            sessionEvents={sessionEvents}
            hasDatasheet={hasDatasheet}
            onOpenDatasheet={onOpenDatasheet}
            onCollapse={() => setPropsOpen(false)}
            onExportDeliverable={onExportDeliverable}
            canDelete={canDeleteSelected}
            onDelete={() => void handleDeleteAnnotation(selectedId)}
          />
        ) : (
          <button
            type="button"
            className="props-strip"
            onClick={() => setPropsOpen(true)}
            title="Show details panel"
            aria-label="Show details panel"
          >
            <PanelRightOpen size={17} strokeWidth={1.6} />
            <span className="props-strip-label">Details</span>
            {totalIssues > 0 && <span className="props-strip-badge">{totalIssues}</span>}
          </button>
        )}
      </div>

      <StudioFoot />

      {pendingEdgeForMetadata && (
        <EdgeMetadataDrawer
          edge={pendingEdgeForMetadata}
          onSave={async (patch) => {
            await patchEdge(pendingEdgeForMetadata.edge_id, patch);
            setPendingEdgeForMetadata(null);
          }}
          onClose={() => setPendingEdgeForMetadata(null)}
        />
      )}

      <DatasheetDrawer
        open={datasheetOpen}
        onClose={() => setDatasheetOpen(false)}
        jobId={project.id}
        /* selectedId may be a prototype tag ("PV-203") OR a real UUID entity_id
         * (post-D1.5, PidCanvas's DetectionOverlay fires onSelect(entity_id)).
         * The drawer's GET will simply 404-equivalent ("not in canonical") on
         * prototype IDs, and render the "Entity not found" panel — no crash. */
        entityId={selectedId}
        entityClass={selectedClass}
        fallbackTag={sel.tag}
        fallbackType={sel.type}
        onBulkReview={onBulkReview}
        totalCount={detResp?.valves.length ?? 68}
      />
    </div>
  );
}
