import { useState } from "react";
import {
  ArrowLeft,
  Check,
  Download,
  FileText,
  LayoutGrid,
  LogOut,
  MoreHorizontal,
  Settings,
  Share2,
} from "lucide-react";
import qongMark from "../design/assets/qong-mark.png";
import SettingsMenu from "../components/SettingsMenu";
import type { Sheet } from "./types";

interface Props {
  projectName: string;
  currentSheet: Sheet;
  sheetCount: number;
  userName: string;
  totalIssues: number;
  onBack: () => void;
  onSave: () => void;
  onBulkReview: () => void;
}

export default function StudioTopBar({
  projectName,
  currentSheet,
  sheetCount,
  userName,
  totalIssues,
  onBack,
  onSave,
  onBulkReview,
}: Props) {
  const [showMenu, setShowMenu] = useState(false);
  const reviewerSlug = userName.toLowerCase().replace(/\s+/g, ".");

  return (
    <header className="studio-top">
      <button className="studio-back" onClick={onBack} title="Back to projects">
        <ArrowLeft size={16} strokeWidth={1.6} />
      </button>
      <div className="studio-brand">
        <img src={qongMark} alt="" />
        <span>
          <span className="qm">QONG</span>&nbsp;Studio
        </span>
      </div>
      <div className="studio-divider"></div>
      <div className="studio-project">
        <div className="proj-name">{projectName}</div>
        <div className="proj-meta">
          <FileText size={11} strokeWidth={1.6} />
          <span className="strong">{currentSheet.name}</span>
          <span className="sep">·</span>
          <span>
            Sheet {currentSheet.id}/{sheetCount}
          </span>
          <span className="sep">|</span>
          <span>Reviewer:</span>
          <span className="strong">{reviewerSlug}</span>
        </div>
      </div>
      <div style={{ flex: 1 }}></div>
      <button className={`issue-badge ${totalIssues > 0 ? "active" : ""}`}>
        <span className="num">{totalIssues}</span>
        <span>issues</span>
      </button>
      <button className="btn btn-secondary btn-sm" onClick={onBulkReview} title="Open Bulk Review workbench">
        <LayoutGrid size={13} strokeWidth={1.6} /> Bulk Review
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
          <div className="more-menu" onMouseLeave={() => setShowMenu(false)}>
            <button>
              <Download size={13} strokeWidth={1.6} /> Export I/O list
            </button>
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
