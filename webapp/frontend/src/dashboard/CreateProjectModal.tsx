import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, FileText, UploadCloud, X } from "lucide-react";
import { useAuth } from "../auth/AuthContext";

interface CreateProjectModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

interface QueuedFile {
  file: File;
  name: string;
  size: number;
}

export default function CreateProjectModal({ open, onClose, onCreated }: CreateProjectModalProps) {
  const [name, setName] = useState("");
  const [client, setClient] = useState("");
  const [discipline, setDiscipline] = useState("Process");
  const [files, setFiles] = useState<QueuedFile[]>([]);
  const [over, setOver] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const navigate = useNavigate();
  const { refresh } = useAuth();

  useEffect(() => {
    if (open) {
      setName("");
      setClient("");
      setDiscipline("Process");
      setFiles([]);
      setError(null);
    }
  }, [open]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && open) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  function addFiles(list: FileList | null) {
    if (!list) return;
    const arr: QueuedFile[] = Array.from(list).map((f) => ({ file: f, name: f.name, size: f.size }));
    setFiles((prev) => [...prev, ...arr]);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    if (files.length === 0) {
      setError("Drop at least one P&ID file to start extraction.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setSessionExpired(false);
    try {
      for (const qf of files) {
        const fd = new FormData();
        fd.append("file", qf.file);
        const res = await fetch("/api/v1/jobs", {
          method: "POST",
          body: fd,
          credentials: "include",
        });
        if (res.status === 401) {
          // Session expired — refresh AuthContext so the SPA reflects logged-out
          // state, then surface a friendly "session expired" UX (vs a raw 401).
          await refresh().catch(() => undefined);
          setSessionExpired(true);
          return;
        }
        if (res.status === 402) {
          throw new Error(
            "Not enough credits to process this PDF. Visit /account/billing or contact admin.",
          );
        }
        if (res.status === 422) {
          throw new Error("That file isn't a valid PDF.");
        }
        if (!res.ok) {
          const detail = await res.text().catch(() => "");
          throw new Error(`Upload failed (${res.status}): ${detail.slice(0, 200)}`);
        }
      }
      onCreated();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form className="modal" onSubmit={submit}>
        <div className="modal-head">
          <span className="overline">New Engagement</span>
          <h2>Create Project</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            <X size={16} strokeWidth={1.6} />
          </button>
        </div>
        <div className="modal-body">
          <div className="field">
            <label className="field-label">Project name</label>
            <input
              className="input"
              placeholder="e.g. Block 18 — Crude Train 2"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
            <div className="field">
              <label className="field-label">Client / Operator</label>
              <input
                className="input"
                placeholder="e.g. NorthSea EPC"
                value={client}
                onChange={(e) => setClient(e.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label">Primary discipline</label>
              <select
                className="input"
                value={discipline}
                onChange={(e) => setDiscipline(e.target.value)}
              >
                <option>Process</option>
                <option>Mechanical</option>
                <option>Instrumentation</option>
                <option>Electrical</option>
              </select>
            </div>
          </div>
          <div className="field">
            <label className="field-label">P&amp;ID Drawings</label>
            <div
              className={`dropzone ${over ? "over" : ""}`}
              onClick={() => inputRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                setOver(true);
              }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setOver(false);
                addFiles(e.dataTransfer.files);
              }}
            >
              <div className="ic">
                <UploadCloud size={20} strokeWidth={1.6} />
              </div>
              <strong>Drop P&amp;ID files here</strong>
              <span>PDF only · up to 50 MB each</span>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept="application/pdf,.pdf"
                style={{ display: "none" }}
                onChange={(e) => addFiles(e.target.files)}
              />
            </div>
            {files.length > 0 && (
              <div className="file-list">
                {files.map((f, i) => (
                  <div className="file" key={i}>
                    <span className="ic">
                      <FileText size={14} strokeWidth={1.6} />
                    </span>
                    <span className="nm">{f.name}</span>
                    <button
                      type="button"
                      className="rm"
                      onClick={() => setFiles(files.filter((_, j) => j !== i))}
                    >
                      <X size={14} strokeWidth={1.6} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
          {sessionExpired && (
            <div
              style={{
                background: "var(--warn-soft)",
                color: "var(--warn)",
                border: "1px solid var(--warn)",
                padding: 14,
                borderRadius: 8,
                marginTop: 8,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
              }}
              role="alert"
            >
              <div>
                <strong>Your session has expired.</strong> Sign in again to upload.
              </div>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => navigate("/signin")}
              >
                Sign in
              </button>
            </div>
          )}
          {error && !sessionExpired && (
            <div
              className="err"
              style={{ color: "var(--error)", marginTop: 4, fontSize: 13 }}
              role="alert"
            >
              {error}
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!name.trim() || submitting}
          >
            {submitting ? "Uploading…" : "Create & Extract"}{" "}
            <ArrowRight size={14} strokeWidth={1.6} />
          </button>
        </div>
      </form>
    </div>
  );
}
