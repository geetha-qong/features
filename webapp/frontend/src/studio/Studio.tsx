import { useEffect, useMemo, useState } from "react";
import { Maximize, Minus, Plus } from "lucide-react";
import { useTheme } from "../theme/ThemeContext";
import BulkReviewScreen from "./bulk-review/BulkReviewScreen";
import DatasheetDrawer from "./datasheet/DatasheetDrawer";
import PidCanvas from "./PidCanvas";
import PropertiesPanel from "./PropertiesPanel";
import SheetRail from "./SheetRail";
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
        sheetCount={sheets.length}
        userName={userName}
        totalIssues={totalIssues}
        onBack={onBack}
        onSave={onBack}
        onBulkReview={onBulkReview}
      />

      <div className="studio-body">
        <SheetRail
          sheets={sheets}
          activeSheet={activeSheet}
          onActivate={setActiveSheet}
          projectId={project.id}
          dark={dark}
          realSheets={realSheets}
        />

        <section className="canvas-col">
          <PidCanvas
            selectedId={selectedId}
            onSelect={handleSelect}
            zoom={zoom}
            setZoom={setZoom}
            pan={pan}
            setPan={setPan}
            dark={dark}
            tileImageUrl={activeTileUrl}
            tileFilename={activeTileFilename}
            detections={detResp?.detections}
            valveCount={detResp?.valves.length ?? 0}
            valveCountTotal={detResp?.valve_count ?? 0}
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
        </section>

        <PropertiesPanel
          elements={panelElements}
          selectedId={selectedId}
          onSelect={handleSelect}
          sessionEvents={sessionEvents}
          hasDatasheet={hasDatasheet}
          onOpenDatasheet={onOpenDatasheet}
        />
      </div>

      <StudioFoot />

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
