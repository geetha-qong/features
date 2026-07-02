/**
 * LineListView — pipe line list for a job, sourced from canonical.json.
 *
 * Fetches GET /api/v1/jobs/{jobId}/line-list and renders all 24 columns.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";

interface Props {
  jobId: number;
  projectName: string;
  onBack: () => void;
}

interface LineRow {
  "Line No": string;
  "From": string;
  "To": string;
  "Fluid": string;
  "Phase": string;
  "Pressure (psig)": string;
  "Temp (°F)": string;
  "Density (lb/ft³)": string;
  "Vise (cP)": string;
  "Flow Rate BPD": string;
  "Flow Rate MMSCFD": string;
  "Flow Rate lb/h": string;
  "Velocity (ft/s)": string;
  "Nominal Pipe Size": string;
  "Piping Class": string;
  "Design Press": string;
  "Design T.Max": string;
  "Material": string;
  "Insulation Type": string;
  "Insulation/Protection": string;
  "P&ID Number": string;
  "Test Pressure": string;
  "Remarks": string;
  "Rev": string;
}

const COLUMNS: (keyof LineRow)[] = [
  "Line No", "From", "To", "Fluid", "Phase",
  "Pressure (psig)", "Temp (°F)", "Density (lb/ft³)", "Vise (cP)",
  "Flow Rate BPD", "Flow Rate MMSCFD", "Flow Rate lb/h",
  "Velocity (ft/s)", "Nominal Pipe Size", "Piping Class",
  "Design Press", "Design T.Max", "Material",
  "Insulation Type", "Insulation/Protection",
  "P&ID Number", "Test Pressure", "Remarks", "Rev",
];

export default function LineListView({ jobId, projectName, onBack }: Props) {
  const [rows, setRows] = useState<LineRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reqIdRef = useRef(0);

  const fetchLines = useCallback(async () => {
    const myReq = ++reqIdRef.current;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/jobs/${jobId}/line-list`, {
        credentials: "include",
        redirect: "manual",
        cache: "no-cache",
      });
      if (res.status === 0 || res.type === "opaqueredirect") {
        throw new Error("Not authenticated");
      }
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json() as { rows: LineRow[]; count: number };
      if (myReq !== reqIdRef.current) return;
      setRows(data.rows);
    } catch (e) {
      if (myReq !== reqIdRef.current) return;
      setError(e instanceof Error ? e.message : "Failed to load line list");
      setRows([]);
    } finally {
      if (myReq === reqIdRef.current) setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    void fetchLines();
  }, [fetchLines]);

  return (
    <div className="bulk-review alldata" data-screen-label="Line List">
      <header className="br-top">
        <button className="br-back" onClick={onBack} title="Back to Studio">
          <ArrowLeft size={14} strokeWidth={1.6} />
          <span>Back to Studio</span>
        </button>
        <div className="br-divider"></div>
        <div className="br-crumbs">
          <span>{projectName}</span>
          <span className="sep">›</span>
          <span className="strong">Line List</span>
        </div>
        <div style={{ flex: 1 }} />
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--fg-3)",
            padding: "0 6px",
          }}
        >
          {!loading && !error ? `${rows.length} lines` : ""}
        </span>
      </header>

      <div className="alldata-table-wrap">
        {loading && <div className="br-empty">Loading line list…</div>}

        {!loading && error && (
          <div className="br-empty" style={{ color: "var(--error, #dc2626)" }}>
            {error}
            <div style={{ marginTop: 12 }}>
              <button className="br-btn small" onClick={() => void fetchLines()}>
                Retry
              </button>
            </div>
          </div>
        )}

        {!loading && !error && rows.length === 0 && (
          <div className="br-empty">
            No line data for job #{jobId} yet. Process the P&amp;ID to populate the line list.
          </div>
        )}

        {!loading && !error && rows.length > 0 && (
          <table className="alldata-table">
            <thead>
              <tr>
                {COLUMNS.map((col) => (
                  <th
                    key={col}
                    style={{
                      background: "#FFD700",
                      color: "#1a1a1a",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={`${row["Line No"]}-${i}`}>
                  {COLUMNS.map((col) => (
                    <td key={col} className={col === "Line No" ? "mono tag" : undefined}>
                      {row[col] || ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
