import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, CheckCheck, Maximize, Minus, Network, PanelRightOpen, Plus, Tag } from "lucide-react";
import { useTheme } from "../theme/ThemeContext";
import BulkReviewScreen from "./bulk-review/BulkReviewScreen";
import DatasheetDrawer from "./datasheet/DatasheetDrawer";
import PidCanvas from "./PidCanvas";
import PropertiesPanel from "./PropertiesPanel";
import StudioFoot from "./StudioFoot";
import StudioTopBar from "./StudioTopBar";
import { buildSheets } from "./buildSheets";
import {
  applySheet,
  getAppliedSheets,
  getDetectionsTagged,
  getEntities,
  getJobDetections,
  getJobGraph,
  getJobSheets,
  ocrBbox,
  rejectAutoEdge,
  rejectNode,
  unrejectNode,
  type EntitiesResponse,
  type EntityRow,
  type JobDetectionsResp,
  type JobSheetsResp,
} from "./api";
import { buildElementsForTile, buildEntityIndex } from "./buildElements";
import { computeTileOffsets } from "./PidCanvas";
import type { CanvasElement, GraphNode, JobGraph, ProjectLike } from "./types";
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
import { cachedFetch, STALE_MS, invalidateJob } from "../queryCache";

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

// ── On-demand zoom-aware page-render sizing (FEATURES #43) ──────────────────
export const HI_DPI_BASELINE_PX = 8000; // initial / minimum render width (fit view)
export const HI_DPI_MAX_PX = 12000;     // must match the cap in jobs.py:serve_page_full
export const HI_DPI_BUCKET_PX = 2000;   // round the target up to this step

/**
 * Pixel width the page should be rendered at for the current zoom, so the
 * canvas shows true vector pixels instead of upscaling a fixed raster.
 * target = viewportWidth × zoom × devicePixelRatio, rounded UP to a bucket
 * (so a wheel-notch doesn't spawn a render per frame) and clamped to
 * [BASELINE, MAX]. Pure so the bucketing/clamp is unit-testable.
 */
export function targetRenderWidth(
  viewportWidthPx: number,
  zoom: number,
  devicePixelRatio: number,
): number {
  const raw = viewportWidthPx * zoom * devicePixelRatio;
  const bucketed = Math.ceil(raw / HI_DPI_BUCKET_PX) * HI_DPI_BUCKET_PX;
  return Math.max(HI_DPI_BASELINE_PX, Math.min(HI_DPI_MAX_PX, bucketed));
}

// Page index a detection belongs to (FEATURES bug #2/#3). Tiles are named
// `tile_p{page}_r{r}_c{c}.png`, so the page is encoded in the filename; fall
// back to an explicit `page` field, else null. Used to filter the sidebar's
// element list to the active sheet so it matches what the canvas draws (the
// canvas already filters per-page via tile→offset matching).
export function detectionPage(d: { tile?: string; page?: number }): number | null {
  const m = (d.tile ?? "").match(/tile_p(\d+)/);
  if (m) return parseInt(m[1], 10);
  if (typeof d.page === "number") return d.page;
  return null;
}

export default function Studio({ project, userName, onBack }: Props) {
  const navigate = useNavigate();
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
  // Orphan detection: YOLO found it + OCR read the tag, but it's not in canonical.
  const [orphanDet, setOrphanDet] = useState<{ tag: string; label: string } | null>(null);
  const [naturalSize, setNaturalSize] = useState<{ w: number; h: number } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  // Ref so the renderWidthPx preload callback can read the live zoom value
  // without it being stale in the closure.
  const currentZoomRef = useRef(zoom);
  useEffect(() => { currentZoomRef.current = zoom; }, [zoom]);

  const handleOrphanSelect = (tag: string, label: string) => {
    setOrphanDet({ tag, label });
    setSelectedId("");
  };

  const handleSelect = (id: string, entityClass?: string, panToElement = false) => {
    setOrphanDet(null);
    setAdoptTarget(null);
    setSelectedId(id);
    setSelectedClass(entityClass);
    // Pan canvas to center on the element when triggered from sidebar.
    // Uses a DOM-delta approach: read where the element currently is on screen,
    // compute the delta to the viewport center, add to current pan. Works at
    // any zoom level and is immune to stale closure values.
    if (panToElement && naturalSize && detResp?.detections) {
      const det = detResp.detections.find(
        (d) =>
          (d.entity_id as string | undefined) === id &&
          (detectionPage(d) === null || detectionPage(d) === activePageIndex),
      );
      if (det?.bbox && det?.tile) {
        const tw = detResp?.tiling_width ?? naturalSize.w;
        const th = detResp?.tiling_height ?? naturalSize.h;
        const offsets = computeTileOffsets({ w: tw, h: th }, activePageIndex);
        const off = offsets.get(det.tile as string);
        if (off) {
          const [bx1, by1, bx2, by2] = det.bbox as number[];
          // Element center in natural-image space
          const cx = ((bx1 + bx2) / 2 + off.x0) * (naturalSize.w / tw);
          const cy = ((by1 + by2) / 2 + off.y0) * (naturalSize.h / th);

          const canvasWrap = document.querySelector(".canvas-wrap") as HTMLElement | null;
          const canvasInner = document.querySelector(".canvas-inner") as HTMLElement | null;
          if (canvasWrap && canvasInner) {
            const wrapRect = canvasWrap.getBoundingClientRect();
            const innerRect = canvasInner.getBoundingClientRect();
            const z = currentZoomRef.current;
            const s = Math.min(wrapRect.width / naturalSize.w, wrapRect.height / naturalSize.h);

            // Element's current screen position (relative to wrap top-left)
            const elScreenX = (innerRect.left - wrapRect.left) + cx * s * z;
            const elScreenY = (innerRect.top  - wrapRect.top)  + cy * s * z;

            // Delta needed to bring element to viewport center
            const dx = wrapRect.width  / 2 - elScreenX;
            const dy = wrapRect.height / 2 - elScreenY;

            setPan((prev) => ({ x: prev.x + dx, y: prev.y + dy }));
          }
        }
      }
    }
  };
  // jumpToEntity — called by SearchBar when user selects a result.
  // Selects the entity and fires the sonar highlight ring — does NOT pan or zoom
  // so the canvas stays fixed at the user's current position.
  const jumpToEntity = (entityId: string, entityClass: string) => {
    setSelectedId(entityId);
    setSelectedClass(entityClass);
    setSearchActiveId(entityId);
    setSearchJumpKey((k) => k + 1);
  };

  // jumpToSheet — called by SearchBar text-search results.
  // Finds the realSheets entry whose filename matches tile_p{pageIndex}_ and
  // activates it so the canvas switches to that drawing page.
  const jumpToSheet = (pageIndex: number) => {
    if (!realSheets) return;
    const idx = realSheets.findIndex((s) =>
      s.filename ? s.filename.includes(`tile_p${pageIndex}_`) : false,
    );
    if (idx >= 0) setActiveSheet(idx);
  };

  const [datasheetOpen, setDatasheetOpen] = useState(false);
  const [mode, setMode] = useState<"studio" | "bulk">("studio");
  // Track if BulkReview has ever been opened — used for lazy mount (CSS hide/show).
  const bulkEverOpened = useRef(false);
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
  const [activeDeliverableType] = useState<string>("instrument_index");

  // Real backend data — falls back to prototype when unavailable so the studio
  // never breaks on jobs without tiles/detections (e.g. seed data, brand-new
  // uploads still being processed).
  const [sheetsResp, setSheetsResp] = useState<JobSheetsResp | null>(null);
  // True until the sheets fetch resolves (success OR error). Drives the canvas
  // loader so the legacy prototype "sample PID" no longer flashes on refresh.
  const [sheetsLoading, setSheetsLoading] = useState(true);
  const [detResp, setDetResp] = useState<JobDetectionsResp | null>(null);
  // Canonical entities by deliverable type. Fetched once per job — feeds the
  // dynamic right-panel rows so clicking a real bbox surfaces the matched
  // tag / sub_class / confidence instead of the DEMO_ELEMENT_DATA stand-in.
  const [valveEntitiesResp, setValveEntitiesResp] = useState<EntitiesResponse | null>(null);
  const [instEntitiesResp, setInstEntitiesResp] = useState<EntitiesResponse | null>(null);
  const [equipEntitiesResp, setEquipEntitiesResp] = useState<EntitiesResponse | null>(null);
  const [lineEntitiesResp] = useState<EntitiesResponse | null>(null);
  // Auto-extracted process graph (Stream 3). Null when unavailable (404/409) —
  // the canvas + chip + toggle quietly disable in that case.
  const [graph, setGraph] = useState<JobGraph | null>(null);
  const [showGraph, setShowGraph] = useState(false);
  // Selected graph edge — tracks which edge the user clicked (for deletion).
  const [selectedGraphEdge, setSelectedGraphEdge] = useState<{ id: string; method: string } | null>(null);
  // Labels off by default: glyphs only, label on hover/select — keeps dense
  // drawings readable. Toggle shows every element's label at once.
  const [showAllLabels, setShowAllLabels] = useState(false);
  // Selected graph node — clicking a node in the graph overlay shows its connections.
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState<string | null>(null);
  // Type-B node adopt target — a graph node with no entity_id that the user clicked.
  // Cleared when another selection is made, on successful adoption, or on Escape.
  const [adoptTarget, setAdoptTarget] = useState<GraphNode | null>(null);

  // ── Search state (search bar → canvas sonar ring + dim highlights) ─────────
  // searchHighlightIds: all entity_ids matching the current query (dim ring on canvas)
  // searchActiveId: the entity the user most recently jumped to (full sonar pulse)
  // searchJumpKey: increments on every jump to re-trigger the CSS animation
  const [searchHighlightIds, setSearchHighlightIds] = useState<string[]>([]);
  const [searchActiveId, setSearchActiveId] = useState<string | null>(null);
  const [searchJumpKey, setSearchJumpKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    // Priority 1+2: sheets and detections — render canvas immediately.
    setSheetsLoading(true);
    cachedFetch(`/jobs/${project.id}/sheets`, () => getJobSheets(project.id), STALE_MS.sheets)
      .then((r) => { if (!cancelled) setSheetsResp(r); })
      .catch(() => { if (!cancelled) setSheetsResp(null); })
      .finally(() => { if (!cancelled) setSheetsLoading(false); });

    cachedFetch(`/jobs/${project.id}/detections`, () => getJobDetections(project.id), STALE_MS.detections)
      .then((r) => { if (!cancelled) setDetResp(r); })
      .catch(() => { if (!cancelled) setDetResp(null); });

    // Priority 3: OCR tags — the pipeline now runs in the background on the
    // cpu-worker (FEATURES #122). The endpoint returns ocr_status="pending"
    // while the job runs, so we poll until it's "ready"/"empty", then merge
    // the OCR-resolved tags onto the canvas. Non-blocking: the canvas already
    // rendered from the plain `detections` call above. We bypass cachedFetch
    // here so the transient "pending" response is never cached.
    (async () => {
      const POLL_MS = 4000;
      const MAX_ATTEMPTS = 60; // ~4 min ceiling, then give up quietly
      for (let attempt = 0; attempt < MAX_ATTEMPTS && !cancelled; attempt++) {
        let ocr;
        try {
          ocr = await getDetectionsTagged(project.id);
        } catch {
          return; // network/auth error — canvas still works without tags
        }
        if (cancelled) return;
        if (ocr.detections.length > 0) {
          setDetResp((prev) => (prev ? { ...prev, detections: ocr.detections } : prev));
        }
        if (ocr.ocr_status !== "pending") return; // ready / empty / legacy → done
        await new Promise((r) => setTimeout(r, POLL_MS));
      }
    })();

    // Priority 4: entity lists — non-blocking, feed the sidebar counts.
    Promise.all([
      cachedFetch(`/jobs/${project.id}/entities/valve_list`, () => getEntities(project.id, "valve_list"), STALE_MS.entities).catch(() => null),
      cachedFetch(`/jobs/${project.id}/entities/instrument_index`, () => getEntities(project.id, "instrument_index"), STALE_MS.entities).catch(() => null),
      cachedFetch(`/jobs/${project.id}/entities/equipment_list`, () => getEntities(project.id, "equipment_list"), STALE_MS.entities).catch(() => null),
    ]).then(([valves, insts, equip]) => {
      if (!cancelled) {
        setValveEntitiesResp(valves as EntitiesResponse | null);
        setInstEntitiesResp(insts as EntitiesResponse | null);
        setEquipEntitiesResp(equip as EntitiesResponse | null);
      }
    });

    // Priority 5: process graph — lazy, lowest priority. Load after a short
    // delay so it never competes with canvas resources on initial render.
    const graphTimer = setTimeout(() => {
      if (cancelled) return;
      cachedFetch(`/jobs/${project.id}/graph`, () => getJobGraph(project.id), STALE_MS.graph)
        .then((g) => { if (!cancelled) setGraph(g); })
        .catch(() => { if (!cancelled) setGraph(null); });
    }, 1500);

    return () => {
      cancelled = true;
      clearTimeout(graphTimer);
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
  // ── On-demand zoom-aware re-render (FEATURES #43) ────────────────────────
  // The page is a single raster the canvas upscales via `transform: scale()`
  // (PidCanvas). Past the source's native pixels that upscale blurs — and the
  // 8000px baseline is fixed regardless of zoom or devicePixelRatio, so deep
  // zoom on a Retina/4K display pixelates. Fix: when the zoom level needs more
  // pixels than we currently hold, re-request the page at exactly that width.
  // The backend (jobs.py serve_page_full ?w=) renders true vector pixels and
  // caches per-width, so each tier costs one render then a hot file.
  //
  // Width target = viewportWidth × zoom × devicePixelRatio, bucketed up to
  // BUCKET_PX steps (so a wheel-notch doesn't spawn a render per frame) and
  // clamped to [BASELINE, MAX]. Monotonic-increase: once sharpened we keep the
  // bigger render (it downscales cleanly for the fit view), so zooming back out
  // never re-flickers. Reset to baseline on page change.
  const [renderWidthPx, setRenderWidthPx] = useState(HI_DPI_BASELINE_PX);

  // Reset to baseline when the active page changes (new page = fit view).
  useEffect(() => {
    setRenderWidthPx(HI_DPI_BASELINE_PX);
  }, [activePageIndex]);

  // Sharpen on zoom-in (debounced + preloaded to avoid a blank flash).
  useEffect(() => {
    const wanted = targetRenderWidth(
      window.innerWidth || 1280,
      zoom,
      window.devicePixelRatio || 1,
    );
    if (wanted === renderWidthPx) return;

    if (wanted > renderWidthPx) {
      // Zoom-in: preload the higher-res render before swapping so there's no
      // blank flash. Also guard the onload: if the user has already zoomed
      // back out by the time the image arrives, skip the upgrade — avoids the
      // "slow loading" flash when zooming in then immediately back out.
      const t = setTimeout(() => {
        const pre = new Image();
        pre.onload = () => {
          const nowNeeded = targetRenderWidth(
            window.innerWidth || 1280,
            currentZoomRef.current,
            window.devicePixelRatio || 1,
          );
          if (nowNeeded >= wanted) setRenderWidthPx(wanted);
        };
        pre.src = `/jobs/${project.id}/page/${activePageIndex}/full?w=${wanted}`;
      }, 280);
      return () => clearTimeout(t);
    } else if (wanted < renderWidthPx * 0.5) {
      // Zoom-out past 50% of the current render tier: step the render width
      // back down so the browser works with a smaller image (faster compositing
      // and no VRAM waste). Preload before swapping so the downgrade is seamless.
      const t = setTimeout(() => {
        const pre = new Image();
        pre.onload = () => {
          // Only downgrade if still zoomed out enough (user might re-zoom in).
          const nowNeeded = targetRenderWidth(
            window.innerWidth || 1280,
            currentZoomRef.current,
            window.devicePixelRatio || 1,
          );
          if (nowNeeded < renderWidthPx * 0.75) setRenderWidthPx(wanted);
        };
        pre.src = `/jobs/${project.id}/page/${activePageIndex}/full?w=${wanted}`;
      }, 400);
      return () => clearTimeout(t);
    }
  }, [zoom, activePageIndex, project.id, renderWidthPx]);

  const activePageFullUrl = realSheets && realSheets.length > 0
    ? `/jobs/${project.id}/page/${activePageIndex}/full?w=${renderWidthPx}`
    : null;

  // ── FEATURES #38: marking + edge drawing state ──────────────────────────
  const [canvasMode, setCanvasMode] = useState<CanvasMode>("select");
  const [activeMarkClass, setActiveMarkClass] = useState<
    { entity_class: string; sub_class: string } | null
  >(null);
  const [activeLineType, setActiveLineType] = useState<LineType>("process_pipe");
  const [pendingEdgeForMetadata, setPendingEdgeForMetadata] = useState<EdgeLite | null>(null);

  const { annotations, create: createAnnotation, patch: patchAnnotation, remove: removeAnnotation } = useAnnotations(project.id);
  const { edges, create: createEdge, patch: patchEdge, remove: removeEdge } = useEdges(project.id);
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

  async function onDropMark(
    bbox: [number, number, number, number],
    sub_class: string,
    entity_class: string,
    bboxNorm?: [number, number, number, number],
  ) {
    // entity_class comes from PalettePanel (string-typed at the canvas boundary)
    // but the backend only accepts the EntityClass union. Reject anything else
    // up-front rather than narrow with `as`.
    if (entity_class !== "valve" && entity_class !== "instrument" && entity_class !== "equipment" && entity_class !== "annotation") return;
    // linked_detection_index is null: the backend resolves the claim server-side
    // (page-space, tile-offset-corrected) so any tile works, not just the top-left.
    const row = await createAnnotation({
      entity_class,
      sub_class,
      bbox,
      sheet_number: activeSheetNumber,
      linked_detection_index: null,
    });
    // At-mark-time AI tag read: the user framed the tag in their box, so OCR that
    // exact region and pre-fill the tag (visible on the canvas label + flows to
    // exports via the annotation→canonical sync). Best-effort + editable — if the
    // read is wrong the user fixes it in the drawer. Non-blocking on failure.
    if (row && bboxNorm) {
      try {
        const r = await ocrBbox(project.id, bboxNorm);
        if (r.found && r.text) {
          await patchAnnotation(row.entity_id, { tag: r.text });
        }
      } catch {
        /* OCR is a bonus — never break the mark flow */
      }
    }
    // The backend now surfaces a user-added symbol as a real graph node, so
    // refresh the graph + deliverable counts: the node appears in the overlay
    // and becomes a valid edge endpoint in draw-edge mode. Non-blocking.
    void refreshGraphAndCounts();
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
  // Node-corrections (2026-06-28): the selected node may be a detected (auto)
  // graph node rather than a user annotation. Resolve its graph entry by
  // entity_id so we can (a) widen the Remove gate to detected nodes and (b)
  // surface a Restore action when it's already soft-rejected.
  const selectedGraphNode = useMemo(
    () => graph?.nodes.find((n) => n.entity_id === selectedId) ?? null,
    [graph, selectedId],
  );
  // Already soft-rejected (ghosted) — swap Remove for Restore.
  const selectedIsRejected = selectedGraphNode?.rejected === true;
  // All soft-rejected nodes, for the sidebar "Removed" section — a persistent,
  // overlay-independent Restore path (the Undo toast is transient and a rejected
  // node leaves the main elements list).
  const removedNodes = useMemo(
    () =>
      (graph?.nodes ?? [])
        .filter((n) => n.rejected && n.entity_id)
        .map((n) => ({ entity_id: n.entity_id as string, tag: n.tag || n.entity_id || "element" })),
    [graph],
  );
  // A canonical entity surfaced in the deliverable lists (valve/instrument/
  // equipment) — even one with NO matching YOLO detection on the active page
  // (the "injected" sidebar rows). Without this, selecting such a row via the
  // sidebar left the Remove button hidden because it isn't in detResp yet IS a
  // real, removable canonical entity. Reject-by-entity_id works for these too.
  const entityInCanonical = (id: string | null): boolean =>
    !!id &&
    (!!valveEntitiesResp?.entities.some((e) => e.entity_id === id) ||
      !!instEntitiesResp?.entities.some((e) => e.entity_id === id) ||
      !!equipEntitiesResp?.entities.some((e) => e.entity_id === id));

  // The Remove action is now available for ANY real selected node: a user
  // annotation, a detected graph node, a matched detection on the canvas, OR a
  // canonical entity from the deliverable lists (selectedId is a canonical
  // entity_id, not a prototype tag).
  const selectedIsRealEntity =
    !!selectedAnnotation ||
    !!selectedGraphNode ||
    !!detResp?.detections?.some(
      (d) => (d.entity_id as string | undefined) === selectedId,
    ) ||
    entityInCanonical(selectedId);
  const canRemoveSelected = selectedIsRealEntity && !selectedIsRejected;

  // Normalized [x0,y0,x1,y1] (0..1 of source page) of the selected DETECTION,
  // for the drawer's "Read tag (OCR)" button. Detection bboxes are tile-local in
  // the tiling source resolution; map to source-page coords (computeTileOffsets
  // at the tiling dims) then normalize. Null when the selection isn't a detection
  // with a real bbox + tile (e.g. annotations, prototype tags).
  const ocrBboxNorm = useMemo<[number, number, number, number] | null>(() => {
    const tw = detResp?.tiling_width;
    const th = detResp?.tiling_height;
    if (!tw || !th) return null;
    const d = detResp?.detections?.find(
      (x) => (x.entity_id as string | undefined) === selectedId,
    );
    if (!d || !Array.isArray(d.bbox) || d.bbox.length !== 4 || !d.tile) return null;
    const offs = computeTileOffsets({ w: tw, h: th }, activePageIndex);
    const off = offs.get(d.tile as string);
    if (!off) return null;
    const [x1, y1, x2, y2] = d.bbox as number[];
    return [
      (x1 + off.x0) / tw,
      (y1 + off.y0) / th,
      (x2 + off.x0) / tw,
      (y2 + off.y0) / th,
    ];
  }, [detResp, selectedId, activePageIndex]);

  // After any node add/remove/restore, re-pull the graph (node + edge set) and
  // the deliverable entity lists (valve/instrument/equipment) so the canvas
  // overlay AND the sidebar/Bulk-Review counts both reflect the change. Fetched
  // fresh (bypassing cachedFetch) so a just-mutated count is never stale.
  async function refreshGraphAndCounts() {
    const [g, valves, insts, equip] = await Promise.all([
      getJobGraph(project.id).catch(() => null),
      getEntities(project.id, "valve_list").catch(() => null),
      getEntities(project.id, "instrument_index").catch(() => null),
      getEntities(project.id, "equipment_list").catch(() => null),
    ]);
    setGraph(g);
    if (valves) setValveEntitiesResp(valves);
    if (insts) setInstEntitiesResp(insts);
    if (equip) setEquipEntitiesResp(equip);
  }

  // Adopt a type-B graph node (entity_id == null): create a claiming UserAnnotation
  // linked to that detection, then best-effort OCR for the tag. Mirrors onDropMark.
  async function adoptNode(node: GraphNode): Promise<string | null> {
    // Bail early if the node has no bbox — we must never write [0,0,0,0].
    if (!node.bbox) {
      showToast("Cannot adopt: node has no bounding box");
      return null;
    }
    const [entity_class, sub_raw] = (node.class ?? "").split("_");
    if (entity_class !== "valve" && entity_class !== "instrument" && entity_class !== "equipment") {
      showToast("Cannot adopt: unknown class");
      return null;
    }
    const sub_class = (sub_raw ?? "").toUpperCase();
    // Preserve the node's bbox exactly.  linked_detection_index is null: the
    // backend resolves the claim server-side (page-space, tile-offset-corrected)
    // so the correct detection is claimed regardless of which tile it lives in.
    const bbox = node.bbox as [number, number, number, number];
    const row = await createAnnotation({
      entity_class: entity_class as "valve" | "instrument" | "equipment",
      sub_class,
      bbox,
      sheet_number: activeSheetNumber,
      linked_detection_index: null,
    });
    if (!row) return null;
    // Best-effort OCR: use the ocrBboxNorm pattern — normalize bbox by
    // page dimensions (graph.page_width × page_height when available, else
    // natural image size) so the OCR endpoint receives a 0..1 range.
    try {
      const pw = graph?.page_width ?? naturalSize?.w ?? 0;
      const ph = graph?.page_height ?? naturalSize?.h ?? 0;
      if (pw > 0 && ph > 0) {
        const [bx1, by1, bx2, by2] = bbox;
        const norm: [number, number, number, number] = [bx1 / pw, by1 / ph, bx2 / pw, by2 / ph];
        const r = await ocrBbox(project.id, norm);
        if (r.found && r.text) await patchAnnotation(row.entity_id, { tag: r.text });
      }
    } catch {
      /* OCR is a bonus — never break the adopt flow */
    }
    setAdoptTarget(null);
    await refreshGraphAndCounts();
    showToast(`Adopted as ${sub_class}`);
    return row.entity_id;
  }

  // Remove the selected node — unified entry from the Properties panel and the
  // Delete/Backspace shortcut. User-added → hard-delete the annotation. Detected
  // (auto) → soft-reject (reversible) and show an Undo toast.
  async function handleRemoveNode(entityId: string | null) {
    if (!entityId) return;
    // Guard: only operate on a REAL entity. selectedId can still be the prototype
    // default ("PV-203") before any canvas selection — rejecting that would write
    // a dangling EntityOverride. Mirror selectedIsRealEntity.
    const isRealEntity =
      annotations.some((a) => a.entity_id === entityId) ||
      !!graph?.nodes.some((n) => n.entity_id === entityId) ||
      !!detResp?.detections?.some(
        (d) => (d.entity_id as string | undefined) === entityId,
      ) ||
      entityInCanonical(entityId);
    if (!isRealEntity) return;
    const ann = annotations.find((a) => a.entity_id === entityId);
    const friendly =
      ann?.tag ??
      ann?.placeholder_tag ??
      graph?.nodes.find((n) => n.entity_id === entityId)?.tag ??
      panelElements[entityId]?.tag ??
      "element";

    if (ann && ann.source === "user") {
      // Hard delete (existing path). Keep the confirm — it's irreversible.
      const ok = window.confirm(`Delete ${friendly}? This can't be undone.`);
      if (!ok) return;
      const success = await removeAnnotation(entityId);
      if (success) {
        setSelectedId("");
        setSelectedClass(undefined);
        await refreshGraphAndCounts();
        showToast(`Deleted ${friendly}`);
      } else {
        showToast(`Failed to delete ${friendly}`);
      }
      return;
    }

    // Detected node → soft reject (reversible via Undo / Restore).
    try {
      await rejectNode(project.id, entityId);
    } catch {
      showToast(`Failed to remove ${friendly}`);
      return;
    }
    await refreshGraphAndCounts();
    showToast(`Removed ${friendly}`, {
      label: "Undo",
      run: () => void handleRestoreNode(entityId, friendly),
    });
  }

  // Restore (un-reject) a previously soft-rejected detected node.
  async function handleRestoreNode(entityId: string | null, friendly?: string) {
    if (!entityId) return;
    const name =
      friendly ??
      graph?.nodes.find((n) => n.entity_id === entityId)?.tag ??
      panelElements[entityId]?.tag ??
      "element";
    try {
      await unrejectNode(project.id, entityId);
    } catch {
      showToast(`Failed to restore ${name}`);
      return;
    }
    await refreshGraphAndCounts();
    showToast(`Restored ${name}`);
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
      directed: line_type !== "plain_pipe",
    });
    if (created) setPendingEdgeForMetadata(created);
    // Refresh graph so the new user edge appears in GraphLayer — enables
    // clicking it for deletion via the "Delete pipe" button.
    const updated = await getJobGraph(project.id);
    setGraph(updated);
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
        // Node-corrections (2026-06-28): the keyboard delete now removes ANY
        // selected node, unified with the panel's Remove button. User-added →
        // hard-delete; detected → soft-reject (reversible Undo). handleRemoveNode
        // routes by source, so the shortcut and the click stay consistent.
        void handleRemoveNode(selectedId);
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

  // F key → reset view (fit to screen)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "f" || e.key === "F") {
        // Ignore if focus is inside an input/textarea/contenteditable
        const tag = (e.target as HTMLElement)?.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement)?.isContentEditable) return;
        setZoom(1);
        setPan({ x: 0, y: 0 });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setZoom, setPan]);

  // Graph edge click — select for deletion. Click same edge again to deselect.
  const handleGraphEdgeClick = (edgeId: string, method: string) => {
    setSelectedGraphEdge((prev) =>
      prev?.id === edgeId ? null : { id: edgeId, method }
    );
  };

  // Graph node click — show connection panel. Click same node again to dismiss.
  const handleGraphNodeClick = (nodeId: string) => {
    setSelectedGraphNodeId((prev) => (prev === nodeId ? null : nodeId));
    // Also drive the main selection so the Properties panel (Selected Element
    // card + Edit/Remove) reflects the clicked node. Without this, graph-node
    // clicks only updated the connection tooltip — leaving floating / user-added
    // nodes (which aren't in the "Elements on P&ID" sidebar list) unreachable
    // for edit or removal. selectedGraphNode keys off selectedId, so set it here.
    const node = graph?.nodes.find((n) => n.id === nodeId);
    if (node?.entity_id) {
      handleSelect(node.entity_id, node.class ?? undefined);
    }
  };

  // Connections for the currently selected graph node.
  const selectedNodeConnections = useMemo(() => {
    if (!selectedGraphNodeId || !graph) return null;
    const node = graph.nodes.find((n) => n.id === selectedGraphNodeId);
    if (!node) return null;
    const tagById = new Map(graph.nodes.map((n) => [n.id, n.tag ?? n.class ?? n.id]));
    const connected = graph.edges
      .filter((e) => e.source === selectedGraphNodeId || e.target === selectedGraphNodeId)
      .map((e) => {
        const otherId = e.source === selectedGraphNodeId ? e.target : e.source;
        return { edgeId: e.id, tag: tagById.get(otherId) ?? otherId, method: e.method, directed: e.directed };
      });
    return { node, connected };
  }, [selectedGraphNodeId, graph]);

  // Delete the currently selected graph edge.
  // User-drawn edges: remove via useEdges hook.
  // Auto edges (opencv/llm_fallback): reject via API then refresh graph.
  const handleDeleteSelectedEdge = async () => {
    if (!selectedGraphEdge) return;
    const { id, method } = selectedGraphEdge;
    setSelectedGraphEdge(null);
    if (method === "user_added") {
      await removeEdge(id);
    } else {
      // Auto edge — store a rejection record so it's filtered from the graph
      await rejectAutoEdge(project.id, id);
    }
    // Refresh graph for both user and auto edge deletions so the canvas updates
    const updated = await getJobGraph(project.id);
    setGraph(updated);
  };

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

  // ── Dynamic element panel data (Phase A of "make it more dynamic") ─────
  // entityIndex: every canonical entity for this job, keyed by entity_id.
  // realElements: rows for the active tile only, built from live detections
  //               that have an entity_id (i.e. matched by the D1.5 matcher).
  // panelElements: real when present, prototype fallback otherwise — keeps
  //               the studio renderable on brand-new uploads / legacy jobs.
  const entityIndex = useMemo(
    () => buildEntityIndex([valveEntitiesResp, instEntitiesResp, equipEntitiesResp]),
    [valveEntitiesResp, instEntitiesResp, equipEntitiesResp],
  );

  // Flat list of all EntityRow objects across all three deliverable types,
  // deduplicated by entity_id (the same physical instrument can appear in both
  // valve_list and instrument_index, causing duplicate search results).
  const allEntities = useMemo(() => {
    const seen = new Set<string>();
    const out: EntityRow[] = [];
    for (const e of [
      ...(valveEntitiesResp?.entities ?? []),
      ...(instEntitiesResp?.entities ?? []),
      ...(equipEntitiesResp?.entities ?? []),
    ]) {
      if (!seen.has(e.entity_id)) {
        seen.add(e.entity_id);
        out.push(e);
      }
    }
    return out;
  }, [valveEntitiesResp, instEntitiesResp, equipEntitiesResp]);
  // Bug fix: the sidebar element list previously counted ALL job detections,
  // while the canvas only draws the active sheet's (PidCanvas filters by
  // tile→page). That made "elements on sheet" disagree with what's on screen
  // and with per-sheet expectations. Filter the sidebar's input to the active
  // page so the two views match. (Detections with no resolvable page are kept,
  // so single-page/legacy jobs are unaffected.)
  const activePageDetections = useMemo(
    () =>
      (detResp?.detections ?? []).filter((d) => {
        const pg = detectionPage(d);
        return pg === null || pg === activePageIndex;
      }),
    [detResp, activePageIndex],
  );
  const realElements = useMemo(
    () => buildElementsForTile(activePageDetections, entityIndex),
    [activePageDetections, entityIndex],
  );
  const hasRealElements = Object.keys(realElements).length > 0;
  const panelElements = hasRealElements ? realElements : DEMO_ELEMENT_DATA;

  // When real data first lands and the user hasn't picked anything yet,
  // jump selectedId to the first matched detection on the active tile so
  // the right panel shows live data immediately (instead of PV-203 demo).
  // Auto-jump removed: no default pink bbox on load. User must click to select.

  const sel = panelElements[selectedId] || Object.values(panelElements)[0];
  const hasDatasheet = DATASHEET_TYPES.has(sel.type) || sel.entityClass === "valve" || sel.entityClass === "instrument";

  // ── Redesign Jun 2026 — Apply / Properties strip / toast ───────────────
  // `appliedBySheet` is UI-only state: the design treats "Apply" as a
  // reviewer's intent ("I'm done with this sheet") rather than a backend
  // mutation. Annotations are already persisted on creation, so Apply just
  // updates a per-sheet count badge (shown in the SheetPicker dropdown) and
  // flips the toolbar button to its "Applied" confirmation state.
  const [appliedBySheet, setAppliedBySheet] = useState<Record<number, number>>({});
  // Persisted Apply state (design 2026-06-13 §1b). On load we learn WHICH sheets
  // were applied (and when); the per-sheet mark-count at apply-time isn't
  // persisted, so we seed the count from the live annotation count for that
  // sheet. That keeps the picker badge meaningful and the re-arm rule intact
  // (`currentApplied === applyCount` stays true until the user changes marks).
  useEffect(() => {
    let cancelled = false;
    getAppliedSheets(project.id)
      .then((r) => {
        if (cancelled) return;
        const countBySheet: Record<number, number> = {};
        for (const a of annotations) {
          countBySheet[a.sheet_number] = (countBySheet[a.sheet_number] ?? 0) + 1;
        }
        const seed: Record<number, number> = {};
        for (const k of Object.keys(r.applied)) {
          const n = Number(k);
          // Positive sentinel (>=1) so the sheet reads as "applied" even when
          // it currently has zero live marks.
          seed[n] = countBySheet[n] ?? 1;
        }
        // Don't clobber any apply the user did during this session before the
        // seed landed — existing session state wins.
        setAppliedBySheet((s) => ({ ...seed, ...s }));
      })
      .catch(() => {
        /* non-fatal — Apply stays session-only if the fetch fails */
      });
    return () => {
      cancelled = true;
    };
    // Seed once per job. `annotations` may still be loading on first run; we
    // intentionally don't re-run on every annotation change (that would clobber
    // user re-arms). Seeding once at mount is sufficient for the reload case.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id]);
  const [propsOpen, setPropsOpen] = useState(true);
  // Toast can carry an optional action (e.g. "Undo" after a node reject).
  const [toast, setToast] = useState<
    { msg: string; action?: { label: string; run: () => void } } | null
  >(null);
  const toastTimer = useRef<number | null>(null);
  const showToast = (
    msg: string,
    action?: { label: string; run: () => void },
  ) => {
    setToast({ msg, action });
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    // Give actionable toasts a little longer so the user can hit Undo.
    toastTimer.current = window.setTimeout(() => setToast(null), action ? 5000 : 2600);
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
    // Optimistic UI first — the badge flips immediately.
    setAppliedBySheet((s) => ({ ...s, [current.id]: applyCount }));
    // Persist (design 2026-06-13 §1b). `current.id` is the per-sheet key the
    // UI already uses; it's sent as sheet_number so reloads re-seed correctly.
    // Fire-and-forget: a failed write only means the apply is session-only.
    void applySheet(project.id, current.id).catch(() => {});
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

  // Lazy-mount BulkReview: mount once when first opened, then keep alive via CSS
  // so Studio canvas never unmounts and re-fetches when the user navigates back.
  if (mode === "bulk") bulkEverOpened.current = true;

  const bulkReviewJsx = bulkEverOpened.current ? (
    <div style={mode !== "bulk" ? { display: "none" } : undefined}>
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
    </div>
  ) : null;

  return (
    <>
      {bulkReviewJsx}
    <div style={mode === "bulk" ? { display: "none" } : undefined} className="studio" data-screen-label="03 Project Studio">
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
        onAllData={() => navigate(`/jobs/${project.id}/data`)}
        searchEntities={allEntities}
        onSearchJump={jumpToEntity}
        onSearchResultsChange={setSearchHighlightIds}
        onSearchActiveChange={setSearchActiveId}
        onSearchJumpToSheet={jumpToSheet}
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

        <section className="canvas-col" data-canvas-mode={canvasMode}>
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
            {selectedGraphEdge && (
              <button
                type="button"
                className="graph-toggle active"
                style={{ color: "var(--qong-red, #EF4444)" }}
                onClick={handleDeleteSelectedEdge}
                title={`Delete selected ${selectedGraphEdge.method === "user_added" ? "user-drawn" : "auto-detected"} pipe`}
              >
                Delete pipe
              </button>
            )}
            {graph && (
              <button
                type="button"
                className={`graph-toggle ${showGraph ? "active" : ""}`}
                onClick={() => setShowGraph((v) => !v)}
                aria-pressed={showGraph}
                data-active={showGraph}
                title={showGraph ? "Hide process graph" : "Show process graph (nodes + edges)"}
              >
                <Network size={15} strokeWidth={1.8} />
                Graph
              </button>
            )}
            <button
              type="button"
              className={`graph-toggle ${showAllLabels ? "active" : ""}`}
              onClick={() => setShowAllLabels((v) => !v)}
              aria-pressed={showAllLabels}
              data-active={showAllLabels}
              title={
                showAllLabels
                  ? "Hide labels (show only on hover/select)"
                  : "Show all element labels"
              }
            >
              <Tag size={15} strokeWidth={1.8} />
              Labels
            </button>
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
            tilingWidth={detResp?.tiling_width ?? null}
            tilingHeight={detResp?.tiling_height ?? null}
            valveCount={detResp?.valves.length ?? 0}
            valveCountTotal={detResp?.valve_count ?? 0}
            mode={canvasMode}
            userAnnotations={sheetAnnotations}
            edges={sheetEdges}
            onDropMark={onDropMark}
            onEdgeDrawn={onEdgeDrawn}
            activeLineType={activeLineType}
            activeMarkClass={activeMarkClass}
            graph={graph}
            showGraph={showGraph}
            showAllLabels={showAllLabels}
            selectedGraphEdgeId={selectedGraphEdge?.id ?? null}
            onGraphEdgeClick={handleGraphEdgeClick}
            onGraphNodeClick={handleGraphNodeClick}
            selectedGraphNodeId={selectedGraphNodeId}
            onAdoptTarget={(node) => { setAdoptTarget(node); setOrphanDet(null); }}
            onAdoptForConnect={adoptNode}
            onNaturalSize={(w, h) => setNaturalSize({ w, h })}
            jobId={project.id}
            searchHighlightIds={searchHighlightIds}
            searchActiveId={searchActiveId}
            searchJumpKey={searchJumpKey}
            loading={sheetsLoading}
            onOrphanSelect={handleOrphanSelect}
          />
          <div className="zoom-ctl">
            <button
              onClick={() => {
                const newZ = Math.min(6, +(zoom + 0.2).toFixed(2));
                const factor = newZ / zoom;
                setZoom(newZ);
                setPan((p) => ({ x: p.x * factor, y: p.y * factor }));
              }}
              title="Zoom in (or scroll up)"
            >
              <Plus size={14} strokeWidth={1.6} />
            </button>
            <button
              onClick={() => {
                const newZ = Math.max(0.3, +(zoom - 0.2).toFixed(2));
                const factor = newZ / zoom;
                setZoom(newZ);
                setPan((p) => ({ x: p.x * factor, y: p.y * factor }));
              }}
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

          {/* Graph node connection panel — appears when user clicks a node in the graph overlay. */}
          {showGraph && selectedNodeConnections && (
            <div
              style={{
                position: "absolute",
                bottom: "52px",
                left: "16px",
                zIndex: 60,
                background: "var(--surface-raised, #1a1f2e)",
                border: "1px solid var(--border, #2a3040)",
                borderRadius: "8px",
                padding: "12px 14px",
                minWidth: "220px",
                maxWidth: "320px",
                boxShadow: "0 4px 24px rgba(0,0,0,0.5)",
                fontFamily: "monospace",
                fontSize: "12px",
                color: "var(--text, #e2e8f0)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <span style={{ fontWeight: 700, fontSize: "13px", color: "#ffffff" }}>
                  {selectedNodeConnections.node.tag ?? selectedNodeConnections.node.class ?? selectedNodeConnections.node.id}
                </span>
                <button
                  type="button"
                  onClick={() => setSelectedGraphNodeId(null)}
                  style={{ background: "none", border: "none", color: "var(--text-muted, #94a3b8)", cursor: "pointer", fontSize: "16px", lineHeight: 1, padding: "0 0 0 8px" }}
                  title="Close"
                >×</button>
              </div>
              <div style={{ color: "var(--text-muted, #94a3b8)", fontSize: "11px", marginBottom: "8px" }}>
                {selectedNodeConnections.node.class ?? "unknown class"}
                {selectedNodeConnections.connected.length === 0 && " · no connections"}
              </div>
              {selectedNodeConnections.connected.length > 0 && (
                <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "4px" }}>
                  {selectedNodeConnections.connected.map((c, i) => (
                    <li key={i} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <span style={{
                        width: "8px", height: "8px", borderRadius: "50%", flexShrink: 0,
                        background: c.method === "user_added" ? "var(--scan-cyan, #22d3ee)" : c.method === "llm_fallback" ? "var(--warn, #f59e0b)" : "var(--ok, #22c55e)",
                      }} />
                      <span style={{ color: "#ffffff" }}>{c.tag}</span>
                      <span style={{ color: "var(--text-muted, #64748b)", fontSize: "10px" }}>
                        {c.method === "user_added" ? "user" : c.method === "llm_fallback" ? "ai" : "auto"}
                        {c.directed ? " →" : " —"}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {toast && (
            <div className="studio-toast" role="status">
              <CheckCheck size={15} strokeWidth={2} /> {toast.msg}
              {toast.action && (
                <button
                  type="button"
                  onClick={() => {
                    const run = toast.action!.run;
                    if (toastTimer.current) window.clearTimeout(toastTimer.current);
                    setToast(null);
                    run();
                  }}
                  style={{
                    marginLeft: 10,
                    background: "none",
                    border: "none",
                    color: "var(--qong-pink, #FF4DA8)",
                    fontWeight: 700,
                    cursor: "pointer",
                    padding: 0,
                    font: "inherit",
                  }}
                >
                  {toast.action.label}
                </button>
              )}
            </div>
          )}
        </section>

        {propsOpen && orphanDet ? (
          <div className="props-panel" style={{ padding: "20px 16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1, opacity: 0.5, textTransform: "uppercase" }}>Detected Symbol</span>
              <button
                type="button"
                onClick={() => setOrphanDet(null)}
                title="Close"
                style={{ background: "none", border: "none", cursor: "pointer", opacity: 0.5, padding: 2 }}
              >✕</button>
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>{orphanDet.tag}</div>
            <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 16 }}>{orphanDet.label.replace("inst_", "").replace("valve_", "").toUpperCase()}</div>
            <div style={{ fontSize: 12, padding: "10px 12px", background: "rgba(245,158,11,0.12)", borderRadius: 6, borderLeft: "3px solid #F59E0B", lineHeight: 1.5 }}>
              YOLO detected this symbol and read its tag, but the extraction pipeline didn't pick it up, so it isn't a tracked entity yet. To add it to the graph and deliverables, switch to Graph mode, click this symbol, and choose “Confirm as …”. No re-processing needed.
            </div>
          </div>
        ) : propsOpen ? (
          <PropertiesPanel
            elements={panelElements}
            selectedId={selectedId}
            onSelect={(id, ec) => handleSelect(id, ec, true)}
            hasDatasheet={hasDatasheet}
            onOpenDatasheet={onOpenDatasheet}
            onCollapse={() => setPropsOpen(false)}
            canRemove={canRemoveSelected}
            onRemove={() => void handleRemoveNode(selectedId)}
            isRejected={selectedIsRejected}
            onRestore={() => void handleRestoreNode(selectedId)}
            removedNodes={removedNodes}
            onRestoreNode={(id) => void handleRestoreNode(id)}
            adoptTarget={adoptTarget}
            onAdopt={(node) => void adoptNode(node)}
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
        totalCount={instEntitiesResp?.entities.length ?? detResp?.valves.length ?? 0}
        entityCounts={{
          valve_list:       valveEntitiesResp?.entities.length ?? detResp?.valves.length ?? 0,
          instrument_index: instEntitiesResp?.entities.length ?? 0,
          equipment_list:   equipEntitiesResp?.entities.length ?? 0,
          line_list:        lineEntitiesResp?.entities.length ?? 0,
        }}
        ocrBboxNorm={ocrBboxNorm}
        onSaved={() => {
          // A drawer edit (tag or field) wrote an EntityOverride server-side.
          // Drop the stale cached entity fetches and re-pull fresh so the
          // "Selected Element" card, sidebar, and canvas reflect the new value
          // immediately — otherwise the panel keeps showing the pre-edit tag
          // (entityIndex is memoised over stale state).
          invalidateJob(project.id);
          void refreshGraphAndCounts();
        }}
      />
    </div>
    </>
  );
}
