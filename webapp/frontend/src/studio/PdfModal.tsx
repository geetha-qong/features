import { useEffect, useRef, useState } from "react";

interface PdfModalProps {
  url: string;
  onClose: () => void;
  onAccept?: () => void;
  onDecline?: () => void;
}

export function PdfModal({ url, onClose, onAccept, onDecline }: PdfModalProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const createdBlob = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    setBlobUrl(null);

    const fetchUrl = `/api/v1/vendor-datasheet?url=${encodeURIComponent(url)}`;
    fetch(fetchUrl, { credentials: "include" })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        const objectUrl = URL.createObjectURL(blob);
        createdBlob.current = objectUrl;
        setBlobUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      if (createdBlob.current) {
        URL.revokeObjectURL(createdBlob.current);
        createdBlob.current = null;
      }
    };
  }, [url]);

  // Close on Escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.55)",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      {/* modal-dialog modal-dialog-centered */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "min(860px, 92vw)",
          height: "min(90vh, 900px)",
          background: "var(--surface)",
          borderRadius: 10,
          border: "1px solid var(--border)",
          boxShadow: "0 24px 64px rgba(0,0,0,0.45)",
          overflow: "hidden",
        }}
      >
        {/* modal-header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-start",
            padding: "14px 18px",
            borderBottom: "1px solid var(--border)",
            flexShrink: 0,
          }}
        >
          <span style={{ fontWeight: 700, fontSize: 14, color: "var(--fg-1)", fontFamily: "var(--font-display)" }}>
            Instrument Datasheet
          </span>
        </div>

        {/* modal-body */}
        <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
          {loading && (
            <div style={{
              position: "absolute", inset: 0, display: "flex",
              alignItems: "center", justifyContent: "center",
              color: "var(--fg-3)", fontSize: 13,
            }}>
              Loading PDF…
            </div>
          )}
          {error && (
            <div style={{
              position: "absolute", inset: 0, display: "flex",
              alignItems: "center", justifyContent: "center",
              color: "var(--fg-3)", fontSize: 13,
            }}>
              Failed to load PDF.
            </div>
          )}
          {blobUrl && (
            <iframe
              src={blobUrl}
              title="Instrument Datasheet PDF"
              style={{ width: "100%", height: "100%", border: "none" }}
            />
          )}
        </div>

        {/* modal-footer */}
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 10,
            padding: "10px 18px",
            borderTop: "1px solid var(--border)",
            flexShrink: 0,
          }}
        >
          {onDecline && onAccept ? (
            <>
              <button
                type="button"
                onClick={() => { onDecline(); onClose(); }}
                style={{
                  padding: "6px 18px",
                  background: "var(--surface-raised, var(--surface))",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  cursor: "pointer",
                  fontSize: 12.5,
                  fontFamily: "var(--font-sans)",
                  color: "var(--fg-1)",
                  fontWeight: 500,
                }}
              >
                Decline
              </button>
              <button
                type="button"
                onClick={() => { onAccept(); onClose(); }}
                style={{
                  padding: "6px 18px",
                  background: "var(--qong-magenta, #FF4DA8)",
                  border: "1px solid var(--qong-magenta, #FF4DA8)",
                  borderRadius: 6,
                  cursor: "pointer",
                  fontSize: 12.5,
                  fontFamily: "var(--font-sans)",
                  color: "white",
                  fontWeight: 600,
                }}
              >
                Accept
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: "6px 18px",
                background: "var(--surface-raised, var(--surface))",
                border: "1px solid var(--border)",
                borderRadius: 6,
                cursor: "pointer",
                fontSize: 12.5,
                fontFamily: "var(--font-sans)",
                color: "var(--fg-1)",
                fontWeight: 500,
              }}
            >
              Close
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
