import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Plus,
  Search,
  SlidersHorizontal,
  LayoutGrid,
  List,
  PanelLeft,
  Folders,
  User as UserIcon,
  Star,
  Archive,
  Activity,
  CheckCircle2,
  File as FileIcon,
  GitBranch,
  Cpu,
  Zap,
  FolderPlus,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import CreateProjectModal from "../dashboard/CreateProjectModal";
import ProjectCard from "../dashboard/ProjectCard";
import ProjectRow from "../dashboard/ProjectRow";
import { toProjectTile, type ApiJob, type ProjectStatus, type ProjectTile } from "../dashboard/types";
import { useUserTimezone } from "../util/datetime";

type Layout = "grid" | "list" | "sidebar";
type Filter = "all" | "mine" | ProjectStatus;
type SortKey = "newest" | "oldest" | "name-az" | "name-za";

const SORT_LABELS: Record<SortKey, string> = {
  newest:   "Newest first",
  oldest:   "Oldest first",
  "name-az": "Name A → Z",
  "name-za": "Name Z → A",
};

const LAYOUT_KEY = "qong.dashboard.layout";

function readLayout(): Layout {
  if (typeof window === "undefined") return "grid";
  const v = window.localStorage.getItem(LAYOUT_KEY);
  return v === "list" || v === "sidebar" ? v : "grid";
}

export default function Dashboard() {
  const { user } = useAuth();
  const tz = useUserTimezone();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectTile[]>([]);
  const [loading, setLoading] = useState(true);
  const hasLoadedOnce = useRef(false);
  const [layout, setLayoutState] = useState<Layout>(readLayout);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [sort, setSort] = useState<SortKey>("newest");
  const [sortOpen, setSortOpen] = useState(false);
  // FEATURES #41: upload no longer auto-navigates to the job detail page.
  // The user stays on the listing, sees the new card appear with an
  // "Extracting" pill, and a toast confirms the upload.
  const [toast, setToast] = useState<string | null>(null);
  // When the user clicks a job that's still extracting we show an inline
  // "still processing" toast keyed off the job id so they understand why
  // nothing happened (rather than dumping them into a Studio that would
  // render demo data).
  const [pendingFocusJobId, setPendingFocusJobId] = useState<number | null>(null);

  function setLayout(v: Layout) {
    setLayoutState(v);
    window.localStorage.setItem(LAYOUT_KEY, v);
  }

  useEffect(() => {
    let cancelled = false;
    // Only show the full-page spinner on the very first load. Background polls
    // (the 4s interval below, active while any job is Preparing) must NOT set
    // loading=true — that swaps the card grid for a spinner every 4s, making the
    // whole dashboard flicker for as long as any job stays Preparing.
    if (!hasLoadedOnce.current) setLoading(true);
    fetch("/api/v1/jobs", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: { jobs: ApiJob[] }) => {
        if (cancelled) return;
        hasLoadedOnce.current = true;
        setProjects(data.jobs.map((j) => toProjectTile(j, tz)));
      })
      .catch((err) => {
        if (cancelled) return;
        // eslint-disable-next-line no-console
        console.error("Failed to load jobs", err);
        setProjects([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey, tz]);

  // Auto-poll the listing every 4s while ANY job is still processing.
  // Stops as soon as everything is in a terminal state, so an idle dashboard
  // makes zero background traffic. Also handles the "I uploaded one job and
  // closed the tab" case — coming back lands you on a fresh listing.
  useEffect(() => {
    const hasRunning = projects.some(
      (p) => p.status === "run" || p.status === "draft",
    );
    if (!hasRunning) return;
    const id = window.setInterval(() => setReloadKey((k) => k + 1), 4000);
    return () => window.clearInterval(id);
  }, [projects]);

  // If we're waiting for a specific job to flip to "ok", jump into it the
  // moment it does. Lets the user click a not-ready card, see the toast,
  // and have the app auto-open the studio once processing finishes — no
  // second click needed.
  useEffect(() => {
    if (pendingFocusJobId == null) return;
    const j = projects.find((p) => p.id === pendingFocusJobId);
    if (j && j.status === "ok") {
      setPendingFocusJobId(null);
      setToast(null);
      navigate(`/jobs/${j.id}`);
    }
  }, [projects, pendingFocusJobId, navigate]);

  // Auto-dismiss toast after a few seconds. Skipped when we're holding it
  // open as the "waiting for processing" indicator (pendingFocusJobId set).
  useEffect(() => {
    if (!toast || pendingFocusJobId != null) return;
    const t = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(t);
  }, [toast, pendingFocusJobId]);

  const counts = useMemo(
    () => ({
      all: projects.length,
      run: projects.filter((p) => p.status === "run").length,
      ok: projects.filter((p) => p.status === "ok").length,
      draft: projects.filter((p) => p.status === "draft").length,
    }),
    [projects],
  );
  const totalPids = useMemo(() => projects.reduce((s, p) => s + p.pidCount, 0), [projects]);

  const filtered = useMemo(() => {
    let list = projects;
    if (filter === "mine") list = list.filter((p) => p.team[0]?.name === user?.username);
    else if (filter !== "all") list = list.filter((p) => p.status === filter);
    if (query) {
      const q = query.toLowerCase();
      list = list.filter((p) => p.name.toLowerCase().includes(q) || p.client.toLowerCase().includes(q));
    }
    list = [...list].sort((a, b) => {
      if (sort === "newest") return (b.createdAt ?? "").localeCompare(a.createdAt ?? "");
      if (sort === "oldest") return (a.createdAt ?? "").localeCompare(b.createdAt ?? "");
      if (sort === "name-az") return a.name.localeCompare(b.name);
      if (sort === "name-za") return b.name.localeCompare(a.name);
      return 0;
    });
    return list;
  }, [projects, filter, query, user, sort]);

  const showSidebar = layout === "sidebar";
  const userName = user?.username || "guest";
  const isEmpty = !loading && projects.length === 0;

  function openProject(p: ProjectTile) {
    // Only ready jobs open the Studio. Anything else (still processing,
    // failed, or never-uploaded draft) shows a toast and — if extracting —
    // arms a "jump in when ready" handoff so the user doesn't have to
    // watch the list manually.
    if (p.status === "ok") {
      setPendingFocusJobId(null);
      navigate(`/jobs/${p.id}`);
      return;
    }
    if (p.status === "fail") {
      setPendingFocusJobId(null);
      setToast(`"${p.name}" failed to process. Re-upload to retry.`);
      return;
    }
    // Still extracting / draft — keep them on the listing and arm the
    // auto-open on completion.
    setPendingFocusJobId(p.id);
    setToast(`"${p.name}" is still extracting. We'll open it as soon as it's ready.`);
  }

  function onCreate() {
    setCreating(true);
  }

  return (
    <div className="projects-shell">
      {showSidebar && (
        <aside className="projects-sidebar">
          <div className="sidebar-new">
            <button className="btn btn-primary btn-block" onClick={onCreate}>
              <Plus size={14} strokeWidth={1.6} />
              New Project
            </button>
          </div>
          <div className="sidebar-section">
            <div className="head">Workspace</div>
            <div className={`sidebar-item ${filter === "all" ? "active" : ""}`} onClick={() => setFilter("all")}>
              <Folders size={16} strokeWidth={1.6} />
              <span>All projects</span>
              <span className="count">{counts.all}</span>
            </div>
            <div className={`sidebar-item ${filter === "mine" ? "active" : ""}`} onClick={() => setFilter("mine")}>
              <UserIcon size={16} strokeWidth={1.6} />
              <span>My projects</span>
            </div>
            <div className="sidebar-item">
              <Star size={16} strokeWidth={1.6} />
              <span>Starred</span>
            </div>
            <div className="sidebar-item">
              <Archive size={16} strokeWidth={1.6} />
              <span>Archived</span>
            </div>
          </div>
          <div className="sidebar-section">
            <div className="head">Status</div>
            <div className={`sidebar-item ${filter === "run" ? "active" : ""}`} onClick={() => setFilter("run")}>
              <Activity size={16} strokeWidth={1.6} />
              <span>Preparing</span>
              <span className="count">{counts.run}</span>
            </div>
            <div className={`sidebar-item ${filter === "ok" ? "active" : ""}`} onClick={() => setFilter("ok")}>
              <CheckCircle2 size={16} strokeWidth={1.6} />
              <span>Done</span>
              <span className="count">{counts.ok}</span>
            </div>
            <div className={`sidebar-item ${filter === "draft" ? "active" : ""}`} onClick={() => setFilter("draft")}>
              <FileIcon size={16} strokeWidth={1.6} />
              <span>Draft</span>
              <span className="count">{counts.draft}</span>
            </div>
          </div>
          <div className="sidebar-section">
            <div className="head">Disciplines</div>
            <div className="sidebar-item">
              <GitBranch size={16} strokeWidth={1.6} />
              <span>Process</span>
            </div>
            <div className="sidebar-item">
              <Cpu size={16} strokeWidth={1.6} />
              <span>Instrumentation</span>
            </div>
            <div className="sidebar-item">
              <Zap size={16} strokeWidth={1.6} />
              <span>Electrical</span>
            </div>
          </div>
        </aside>
      )}

      <main className="projects-main">
        <div className="projects-header">
          <div className="titlewrap">
            <span className="overline">Workspace · {userName}</span>
            <h1>Projects</h1>
            <p className="sub">Every P&amp;ID, deliverable and revision — one source of truth.</p>
          </div>
          {!showSidebar && (
            <button className="btn btn-primary" onClick={onCreate}>
              <Plus size={14} strokeWidth={1.6} />
              New Project
            </button>
          )}
        </div>

        <div className="stat-strip">
          <div className="stat">
            <div className="num accent">{projects.length}</div>
            <span className="lbl">Active projects</span>
          </div>
          <div className="stat">
            <div className="num">{totalPids}</div>
            <span className="lbl">P&amp;IDs ingested</span>
          </div>
          <div className="stat">
            <div className="num">{counts.run}</div>
            <span className="lbl">Currently extracting</span>
          </div>
          <div className="stat">
            <div className="num">{counts.ok}</div>
            <span className="lbl">Done</span>
          </div>
        </div>

        <div className="toolbar">
          <div className="input-with-icon search">
            <span className="ic" style={{ color: "var(--fg-3)" }}>
              <Search size={16} strokeWidth={1.6} />
            </span>
            <input
              className="input"
              placeholder="Search projects, clients, tags…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ height: 40 }}
            />
          </div>
          {!showSidebar && (
            <div className="filters">
              <button className={`chip ${filter === "all" ? "active" : ""}`} onClick={() => setFilter("all")}>
                All<span className="count">{counts.all}</span>
              </button>
              <button className={`chip ${filter === "run" ? "active" : ""}`} onClick={() => setFilter("run")}>
                Preparing<span className="count">{counts.run}</span>
              </button>
              <button className={`chip ${filter === "ok" ? "active" : ""}`} onClick={() => setFilter("ok")}>
                Done<span className="count">{counts.ok}</span>
              </button>
              <button className={`chip ${filter === "draft" ? "active" : ""}`} onClick={() => setFilter("draft")}>
                Draft<span className="count">{counts.draft}</span>
              </button>
            </div>
          )}
          <div style={{ flex: 1 }}></div>
          <div className="layout-toggle" role="group" aria-label="Layout">
            <button className={layout === "grid" ? "active" : ""} onClick={() => setLayout("grid")} title="Grid">
              <LayoutGrid size={14} strokeWidth={1.6} />
            </button>
            <button className={layout === "list" ? "active" : ""} onClick={() => setLayout("list")} title="List">
              <List size={14} strokeWidth={1.6} />
            </button>
            <button className={layout === "sidebar" ? "active" : ""} onClick={() => setLayout("sidebar")} title="Sidebar">
              <PanelLeft size={14} strokeWidth={1.6} />
            </button>
          </div>
          <div style={{ position: "relative" }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setSortOpen((o) => !o)}
              aria-haspopup="listbox"
              aria-expanded={sortOpen}
            >
              <SlidersHorizontal size={14} strokeWidth={1.6} /> Sort
            </button>
            {sortOpen && (
              <div
                role="listbox"
                style={{
                  position: "absolute",
                  right: 0,
                  top: "calc(100% + 4px)",
                  zIndex: 200,
                  background: "var(--surface-1, #1e1e2e)",
                  border: "1px solid var(--border, rgba(255,255,255,0.1))",
                  borderRadius: 8,
                  padding: "4px 0",
                  minWidth: 160,
                  boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
                }}
              >
                {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
                  <div
                    key={k}
                    role="option"
                    aria-selected={sort === k}
                    onClick={() => { setSort(k); setSortOpen(false); }}
                    style={{
                      padding: "7px 14px",
                      cursor: "pointer",
                      fontSize: 13,
                      color: sort === k ? "var(--accent, #8B3FCE)" : "var(--fg-1, #fff)",
                      fontWeight: sort === k ? 600 : 400,
                      background: "transparent",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.06)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                  >
                    {SORT_LABELS[k]}
                  </div>
                ))}
              </div>
            )}
            {sortOpen && (
              <div
                style={{ position: "fixed", inset: 0, zIndex: 199 }}
                onClick={() => setSortOpen(false)}
              />
            )}
          </div>
        </div>

        {loading ? (
          <div className="empty-state">
            <div className="ic">
              <Activity size={28} strokeWidth={1.6} />
            </div>
            <h3>Loading projects…</h3>
          </div>
        ) : isEmpty || filtered.length === 0 ? (
          <div className="empty-state">
            <div className="ic">
              <FolderPlus size={28} strokeWidth={1.6} />
            </div>
            <h3>{isEmpty ? "No projects yet" : "No matching projects"}</h3>
            <p>
              {isEmpty
                ? "Spin up your first engagement — drop in a P&ID and QONG starts extracting instruments, valves and tags within seconds."
                : "Try a different search term or clear the active filter."}
            </p>
            <button className="btn btn-primary" onClick={onCreate}>
              <Plus size={14} strokeWidth={1.6} />
              Create your first project
            </button>
          </div>
        ) : layout === "list" ? (
          <div className="projects-list">
            <div className="list-head">
              <div>Project</div>
              <div>Client</div>
              <div>Last modified</div>
              <div>Team</div>
              <div></div>
            </div>
            {filtered.map((p) => (
              <ProjectRow key={p.id} project={p} onOpen={() => openProject(p)} />
            ))}
          </div>
        ) : (
          <div className="projects-grid">
            {filtered.map((p) => (
              <ProjectCard key={p.id} project={p} onOpen={() => openProject(p)} />
            ))}
          </div>
        )}
      </main>

      <CreateProjectModal
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(firstJobId) => {
          // FEATURES #41: do NOT navigate into the studio after upload —
          // the job is still extracting, and the old behaviour was dumping
          // users into a page rendered with sample data while the real
          // pipeline ran in the background. Now we just refresh the listing
          // (the new tile will appear with an "Extracting" pill) and toast
          // the user. If they want to open it as soon as it's ready, they
          // can click the tile — `openProject` arms an auto-open on done.
          setReloadKey((k) => k + 1);
          setCreating(false);
          if (firstJobId != null) {
            setPendingFocusJobId(firstJobId);
            setToast(
              "Upload started. We'll open the project as soon as extraction finishes.",
            );
          } else {
            setToast("Upload received. Watch the list for the new tile.");
          }
        }}
      />

      {toast && (
        <div className="dashboard-toast" role="status">
          <Activity size={15} strokeWidth={1.8} />
          <span>{toast}</span>
          <button
            type="button"
            className="dashboard-toast-close"
            onClick={() => {
              setToast(null);
              setPendingFocusJobId(null);
            }}
            aria-label="Dismiss"
          >×</button>
        </div>
      )}
    </div>
  );
}
