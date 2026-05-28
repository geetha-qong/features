import { useEffect, useMemo, useState } from "react";
import { Maximize, Minus, Plus } from "lucide-react";
import { useTheme } from "../theme/ThemeContext";
import PidCanvas from "./PidCanvas";
import PropertiesPanel from "./PropertiesPanel";
import SheetRail from "./SheetRail";
import StudioFoot from "./StudioFoot";
import StudioTopBar from "./StudioTopBar";
import { buildSheets } from "./buildSheets";
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

  // Lock body scroll while studio is mounted (full-bleed surface)
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  const current = sheets[activeSheet];
  const totalIssues = sheets.reduce((s, x) => s + (x.issues || 0), 0);
  const sel = DEMO_ELEMENT_DATA[selectedId] || DEMO_ELEMENT_DATA["PV-203"];
  const hasDatasheet = DATASHEET_TYPES.has(sel.type);

  const sessionEvents: SessionEvent[] = [
    { who: userName, when: "just now", what: "selected PV-203" },
    { who: userName, when: "2m ago", what: "confirmed FT-101 type" },
    { who: userName, when: "5m ago", what: "linked P-101 → V-101" },
  ];

  function onOpenDatasheet() {
    // Phase 2b will swap this for the real DatasheetDrawer
    // eslint-disable-next-line no-alert
    alert("Datasheet drawer arrives in Phase 2b — coming next session.");
  }

  function onBulkReview() {
    // Phase 2c will swap this for the BulkReviewScreen
    // eslint-disable-next-line no-alert
    alert("Bulk Review workbench arrives in Phase 2c — coming next session.");
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
    </div>
  );
}
