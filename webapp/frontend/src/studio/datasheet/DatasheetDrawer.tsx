import { useEffect, useMemo, useState } from "react";
import { Check, ChevronDown, ChevronRight, Download, Info, LayoutGrid, X } from "lucide-react";
import DSField from "./DSField";
import DocTypeIcon from "./DocTypeIcon";
import {
  DOC_TYPES,
  SCHEMAS,
  defaultValues,
  type DocTypeKey,
} from "./schemas";
import type { CanvasElement } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  element: CanvasElement | null;
  onBulkReview?: () => void;
  totalCount?: number;
}

export default function DatasheetDrawer({ open, onClose, element, onBulkReview, totalCount = 68 }: Props) {
  const [docType, setDocType] = useState<DocTypeKey>("datasheet");
  const [showDocPicker, setShowDocPicker] = useState(false);
  const sections = SCHEMAS[docType] || SCHEMAS.datasheet;
  const defaults = useMemo(
    () => defaultValues(element?.tag || "", element?.type || "", docType),
    [element, docType],
  );
  const [values, setValues] = useState<Record<string, string>>(defaults);
  const [unlocked, setUnlocked] = useState<Record<string, boolean>>({});
  const [expanded, setExpanded] = useState<Record<number, boolean>>({ 0: true, 1: true });

  useEffect(() => {
    setValues(defaults);
    setUnlocked({});
    setExpanded({ 0: true, 1: true });
  }, [defaults]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !element) return null;

  const totalFields = sections.reduce((s, sec) => s + sec.fields.length, 0);
  const filled = sections.reduce(
    (s, sec) => s + sec.fields.filter((f) => values[f.key] && values[f.key] !== "").length,
    0,
  );
  const completion = Math.round((filled / totalFields) * 100);

  const currentDoc = DOC_TYPES.find((d) => d.key === docType) || DOC_TYPES[0];

  function update(key: string, val: string) {
    setValues((v) => ({ ...v, [key]: val }));
  }

  return (
    <div
      className="ds-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside className="ds-drawer" data-comment-anchor="datasheet-drawer">
        <header className="ds-head">
          <div className="ds-head-top">
            <button className="ds-doc-picker" onClick={() => setShowDocPicker((v) => !v)}>
              <DocTypeIcon name={currentDoc.icon} size={14} />
              <span>{currentDoc.name}</span>
              <ChevronDown size={12} strokeWidth={1.6} />
            </button>
            {showDocPicker && (
              <div className="ds-doc-menu" onMouseLeave={() => setShowDocPicker(false)}>
                {DOC_TYPES.map((d) => (
                  <button
                    key={d.key}
                    className={d.key === docType ? "active" : ""}
                    onClick={() => {
                      setDocType(d.key);
                      setShowDocPicker(false);
                    }}
                  >
                    <DocTypeIcon name={d.icon} size={13} />
                    <span>{d.name}</span>
                    {d.key === docType && <Check size={13} strokeWidth={1.6} />}
                  </button>
                ))}
              </div>
            )}
            <div style={{ flex: 1 }}></div>
            {onBulkReview && (
              <button
                className="ds-bulk-btn"
                onClick={onBulkReview}
                title="Review all instruments in workbench"
              >
                <LayoutGrid size={12} strokeWidth={1.6} />
                <span>Bulk Review</span>
                <span className="num">{totalCount}</span>
              </button>
            )}
            <button className="ds-close" onClick={onClose} title="Close datasheet">
              <X size={16} strokeWidth={1.6} />
            </button>
          </div>
          <div className="ds-head-bot">
            <div className="ds-title-wrap">
              <span className="overline">{element.type}</span>
              <h2>{element.tag}</h2>
            </div>
            <div className="ds-progress">
              <div className="ds-progress-meta">
                <span>
                  {filled} of {totalFields} fields
                </span>
                <span className="pct">{completion}%</span>
              </div>
              <div className="ds-progress-bar">
                <div className="ds-progress-fill" style={{ width: `${completion}%` }}></div>
              </div>
            </div>
          </div>
        </header>

        <div className="ds-body">
          {sections.map((sec, i) => {
            const isOpen = !!expanded[i];
            const filledInSec = sec.fields.filter((f) => values[f.key] && values[f.key] !== "").length;
            return (
              <section
                key={`${sec.title}-${docType}`}
                className={`ds-section ${isOpen ? "open" : "collapsed"}`}
                id={`ds-sec-${i}`}
              >
                <button
                  type="button"
                  className="ds-section-head"
                  onClick={() => setExpanded((e) => ({ ...e, [i]: !e[i] }))}
                >
                  <span className="num">{String(i + 1).padStart(2, "0")}</span>
                  <h3>{sec.title}</h3>
                  <span className="ds-section-meta">
                    {filledInSec}/{sec.fields.length}
                  </span>
                  {isOpen ? (
                    <ChevronDown size={14} strokeWidth={1.6} />
                  ) : (
                    <ChevronRight size={14} strokeWidth={1.6} />
                  )}
                </button>
                {isOpen && (
                  <div className="ds-fields">
                    {sec.fields.map((f) => (
                      <DSField
                        key={f.key}
                        field={f}
                        value={values[f.key]}
                        onChange={(v) => update(f.key, v)}
                        locked={!!f.extracted && !unlocked[f.key]}
                        onUnlock={() => setUnlocked((u) => ({ ...u, [f.key]: true }))}
                      />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>

        <footer className="ds-foot">
          <div className="ds-foot-info">
            <Info size={13} strokeWidth={1.6} />
            <span>{totalFields - filled} fields remaining</span>
          </div>
          <div style={{ flex: 1 }}></div>
          <button className="btn btn-secondary btn-sm" onClick={onClose}>
            Save Draft
          </button>
          <button className="btn btn-primary btn-sm">
            <Download size={12} strokeWidth={1.6} /> Export
          </button>
        </footer>
      </aside>
    </div>
  );
}
