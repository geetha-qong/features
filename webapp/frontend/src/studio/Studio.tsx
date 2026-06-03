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
import { getJobDetections, getJobSheets, type JobDetectionsResp, type JobSheetsResp } from "./api";
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
  const [activeDeliverableType] = useState<string>("datasheet");

  // Real backend data — falls back to prototype when unavailable so the studio
  // never breaks on jobs without tiles/detections (e.g. seed data, brand-new
  // uploads still being processed).
  const [sheetsResp, setSheetsResp] = useState<JobSheetsResp | null>(null);
  const [detResp, setDetResp] = useState<JobDetectionsResp | null>(null);

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
    return () => {
      cancelled = true;
    };
  }, [project.id]);

  const realSheets = sheetsResp?.sheets;
  const activeTileUrl =
    realSheets && realSheets[activeSheet]?.url ? realSheets[activeSheet].url : null;

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
  const sel = DEMO_ELEMENT_DATA[selectedId] || DEMO_ELEMENT_DATA["PV-203"];
  const hasDatasheet = DATASHEET_TYPES.has(sel.type);

  const sessionEvents: SessionEvent[] = [
    { who: userName, when: "just now", what: "selected PV-203" },
    { who: userName, when: "2m ago", what: "confirmed FT-101 type" },
    { who: userName, when: "5m ago", what: "linked P-101 → V-101" },
  ];

  function onOpenDatasheet() {
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
        onOpenEntity={(entityId) => {
          // BulkReview row → Studio drawer. `entityId` is the canonical UUID
          // (string). Studio's `selectedId` is happy to hold either a UUID
          // (D1.5+ canvas selections) or a prototype tag, so this just works.
          setSelectedId(entityId);
          setMode("studio");
          setDatasheetOpen(true);
        }}
      />
    );
  }

  return (
    <div className="studio" data-screen-label="03 Project Studio">
      <StudioTopBar
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
            onSelect={setSelectedId}
            zoom={zoom}
            setZoom={setZoom}
            pan={pan}
            setPan={setPan}
            dark={dark}
            tileImageUrl={activeTileUrl}
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
          elements={DEMO_ELEMENT_DATA}
          selectedId={selectedId}
          onSelect={setSelectedId}
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
        fallbackTag={sel.tag}
        fallbackType={sel.type}
        onBulkReview={onBulkReview}
        totalCount={detResp?.valves.length ?? 68}
      />
    </div>
  );
}
