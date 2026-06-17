import { useState } from "react";
import {
  ArrowLeft,
  Check,
  ChevronRight,
  Download,
  FileText,
  LayoutGrid,
  Table2,
  LogOut,
  MoreHorizontal,
  RefreshCw,
  Settings,
  Share2,
} from "lucide-react";
import qongMark from "../design/assets/qong-mark.png";
import SettingsMenu from "../components/SettingsMenu";
import SheetPicker from "./SheetPicker";
import type { Sheet } from "./types";
import type { RealSheet } from "./api";

interface Props {
  jobId: number;
  projectName: string;
  currentSheet: Sheet;
  sheets: Sheet[];
  sheetCount: number;
  activeSheet: number;
  onActivateSheet: (idx: number) => void;
  projectId: number;
  dark: boolean;
  realSheets?: RealSheet[];
  appliedBySheet: Record<number, number>;
  userName: string;
  onBack: () => void;
  onSave: () => void;
  onBulkReview: () => void;
  onAllData: () => void;
}

/** Available deliverable_type × file_format combos — matches the REGISTRY
 *  registrations in webapp/deliverables/{valve_list,instrument_index,equipment_list,datasheet}.py.
 *  POST /api/v1/jobs/{id}/export/{deliverable_type}/{file_format} → bytes. */
const DELIVERABLES: { type: string; format: "csv" | "xlsx"; label: string; ext: string }[] = [
  { type: "valve_list",        format: "csv",  label: "Valve List · CSV",         ext: "csv"  },
  { type: "valve_list",        format: "xlsx", label: "Valve List · XLSX",        ext: "xlsx" },
  { type: "instrument_index",  format: "csv",  label: "Instrument Index · CSV",   ext: "csv"  },
  { type: "instrument_index",  format: "xlsx", label: "Instrument Index · XLSX",  ext: "xlsx" },
  { type: "equipment_list",    format: "xlsx", label: "Equipment List · XLSX",    ext: "xlsx" },
  { type: "datasheet",         format: "xlsx", label: "Datasheet · XLSX",         ext: "xlsx" },
];

async function downloadDeliverable(jobId: number, type: string, format: string, ext: string) {
  const url = `/api/v1/jobs/${jobId}/export/${type}/${format}`;
  const res = await fetch(url, { method: "POST", credentials: "include" });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Export failed (HTTP ${res.status}): ${detail || "unknown"}`);
  }
  const blob = await res.blob();
  const blobUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = `job-${jobId}-${type}.${ext}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(blobUrl);
}

export default function StudioTopBar({
  jobId,
  projectName,
  currentSheet,
  sheets,
  sheetCount: _sheetCount,
  activeSheet,
  onActivateSheet,
  projectId,
  dark,
  realSheets,
  appliedBySheet,
  userName,
  onBack,
  onSave,
  onBulkReview,
  onAllData,
}: Props) {
  const [showMenu, setShowMenu] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [rerunning, setRerunning] = useState(false);
  const reviewerSlug = userName.toLowerCase().replace(/\s+/g, ".");

  // Re-process this job through the pipeline with the CURRENT model (re-detects
  // symbols + rebuilds the graph). User-initiated only (never auto). The rerun
  // endpoint is prefix-less (/jobs/{id}/rerun, NOT /api/v1), takes form-data, and
  // 303-redirects on success — redirect:"manual" → opaqueredirect(status 0)=ok.
  async function handleRerun() {
    if (rerunning) return;
    if (!window.confirm(
      "Re-process this job with the latest model? Current detections and graph " +
      "will be replaced (your saved tags/edits are preserved). This runs in the background."
    )) return;
    setRerunning(true);
    try {
      const body = new FormData();
      body.append("include_control_valves", "off");
      const res = await fetch(`/jobs/${jobId}/rerun`, {
        method: "POST", credentials: "include", body, redirect: "manual",
      });
      const ok = res.ok || res.type === "opaqueredirect" || res.status === 0;
      if (!ok) {
        alert(`Re-run failed (HTTP ${res.status})`);
        setRerunning(false);
        return;
      }
      // Job is now pending/processing — reload the route so the progress panel
      // shows (JobDetail re-evaluates status and polls to completion).
      window.location.assign(`/jobs/${jobId}`);
    } catch (e) {
      alert(`Re-run error: ${e instanceof Error ? e.message : String(e)}`);
      setRerunning(false);
    }
  }

  async function handleExport(type: string, format: string, ext: string) {
    const key = `${type}.${format}`;
    setExporting(key);
    setExportError(null);
    try {
      await downloadDeliverable(jobId, type, format, ext);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(null);
    }
  }

  return (
    <header className="studio-top">
      <button className="studio-back" onClick={onBack} title="Back to projects">
        <ArrowLeft size={16} strokeWidth={1.6} />
      </button>
      <button
        className="studio-brand"
        onClick={onBack}
        title="Go to dashboard"
        style={{ cursor: "pointer", background: "none", border: "none", padding: 0 }}
      >
        <img src={qongMark} alt="" />
        <span>
          <span className="qm">QONG</span>&nbsp;Studio
        </span>
      </button>
      <div className="studio-divider"></div>
      <div className="studio-project">
        <div className="proj-name">{projectName}</div>
        <div className="proj-meta">
          <FileText size={11} strokeWidth={1.6} />
          <span className="strong">{currentSheet.name}</span>
          <span className="sep">·</span>
          <SheetPicker
            sheets={sheets}
            activeSheet={activeSheet}
            onActivate={onActivateSheet}
            projectId={projectId}
            dark={dark}
            realSheets={realSheets}
            appliedBySheet={appliedBySheet}
          />
          <span className="sep">|</span>
          <span>Reviewer:</span>
          <span className="strong">{reviewerSlug}</span>
        </div>
      </div>
      <div style={{ flex: 1 }}></div>
      <button className="btn btn-secondary btn-sm" onClick={onAllData} title="See all extracted data for this job">
        <Table2 size={13} strokeWidth={1.6} /> All Data
      </button>
      <button className="btn btn-secondary btn-sm" onClick={onBulkReview} title="Open Bulk Review workbench">
        <LayoutGrid size={13} strokeWidth={1.6} /> Bulk Review
      </button>
      <button
        className="btn btn-secondary btn-sm"
        onClick={handleRerun}
        disabled={rerunning}
        title="Re-process this job with the latest detection model (re-detect symbols + rebuild graph)"
      >
        <RefreshCw size={13} strokeWidth={1.6} /> {rerunning ? "Re-processing…" : "Re-process"}
      </button>
      <button className="btn btn-primary btn-sm" onClick={onSave}>
        Save <Check size={13} strokeWidth={1.6} />
      </button>
      <SettingsMenu variant="dark-chrome" />
      <div className="more-wrap">
        <button className="icon-btn studio-ic" onClick={() => setShowMenu((v) => !v)}>
          <MoreHorizontal size={16} strokeWidth={1.6} />
        </button>
        {showMenu && (
          <div className="more-menu" onMouseLeave={() => { setShowMenu(false); setShowExport(false); }}>
            <button
              onClick={(e) => { e.stopPropagation(); setShowExport((v) => !v); }}
              aria-expanded={showExport}
              style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}
            >
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <Download size={13} strokeWidth={1.6} /> Export deliverable
              </span>
              <ChevronRight size={12} strokeWidth={1.6} style={{ transform: showExport ? "rotate(90deg)" : "none", transition: "transform 0.15s" }} />
            </button>
            {showExport && (
              <div style={{ borderLeft: "2px solid rgba(255,255,255,0.08)", marginLeft: 8, paddingLeft: 4 }}>
                {DELIVERABLES.map((d) => {
                  const key = `${d.type}.${d.format}`;
                  const busy = exporting === key;
                  return (
                    <button
                      key={key}
                      disabled={busy || exporting !== null}
                      onClick={() => void handleExport(d.type, d.format, d.ext)}
                      title={`POST /api/v1/jobs/${jobId}/export/${d.type}/${d.format}`}
                      style={{ opacity: busy ? 0.6 : 1, fontSize: 12 }}
                    >
                      <Download size={11} strokeWidth={1.6} /> {busy ? "Downloading…" : d.label}
                    </button>
                  );
                })}
                {exportError && (
                  <div style={{ padding: "4px 8px", color: "#ff6b6b", fontSize: 11, maxWidth: 240 }}>
                    {exportError}
                  </div>
                )}
              </div>
            )}
            <button>
              <Share2 size={13} strokeWidth={1.6} /> Share
            </button>
            <button>
              <Settings size={13} strokeWidth={1.6} /> Settings
            </button>
            <div className="sep"></div>
            <button onClick={onBack}>
              <LogOut size={13} strokeWidth={1.6} /> Exit studio
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
