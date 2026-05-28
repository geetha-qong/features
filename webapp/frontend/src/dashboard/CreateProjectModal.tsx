import { useEffect, useRef, useState } from "react";
import { ArrowRight, FileText, UploadCloud, X } from "lucide-react";

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
  const inputRef = useRef<HTMLInputElement | null>(null);

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
    try {
      // Upload each file as its own job via POST /api/v1/jobs. The first file
      // becomes the named project, the rest are queued as additional jobs.
      for (const qf of files) {
        const fd = new FormData();
        fd.append("file", qf.file);
        const res = await fetch("/api/v1/jobs", {
          method: "POST",
          body: fd,
          credentials: "include",
        });
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
          {error && (
            <div
              className="err"
              style={{ color: "var(--error)", marginTop: 4, fontSize: 13 }}
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
