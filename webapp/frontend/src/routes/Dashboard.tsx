import { useEffect, useMemo, useState } from "react";
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

type Layout = "grid" | "list" | "sidebar";
type Filter = "all" | "mine" | ProjectStatus;

const LAYOUT_KEY = "qong.dashboard.layout";

function readLayout(): Layout {
  if (typeof window === "undefined") return "grid";
  const v = window.localStorage.getItem(LAYOUT_KEY);
  return v === "list" || v === "sidebar" ? v : "grid";
}

export default function Dashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectTile[]>([]);
  const [loading, setLoading] = useState(true);
  const [layout, setLayoutState] = useState<Layout>(readLayout);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  function setLayout(v: Layout) {
    setLayoutState(v);
    window.localStorage.setItem(LAYOUT_KEY, v);
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch("/api/v1/jobs", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: { jobs: ApiJob[] }) => {
        if (cancelled) return;
        setProjects(data.jobs.map(toProjectTile));
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
  }, [reloadKey]);

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
    return list;
  }, [projects, filter, query, user]);

  const showSidebar = layout === "sidebar";
  const userName = user?.username || "guest";
  const isEmpty = !loading && projects.length === 0;

  function openProject(p: ProjectTile) {
    navigate(`/jobs/${p.id}`);
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
              <span>Extracting</span>
              <span className="count">{counts.run}</span>
            </div>
            <div className={`sidebar-item ${filter === "ok" ? "active" : ""}`} onClick={() => setFilter("ok")}>
              <CheckCircle2 size={16} strokeWidth={1.6} />
              <span>Synced</span>
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
            <span className="lbl">Synced</span>
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
                Extracting<span className="count">{counts.run}</span>
              </button>
              <button className={`chip ${filter === "ok" ? "active" : ""}`} onClick={() => setFilter("ok")}>
                Synced<span className="count">{counts.ok}</span>
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
          <button className="btn btn-secondary btn-sm">
            <SlidersHorizontal size={14} strokeWidth={1.6} /> Sort
          </button>
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
        onCreated={() => setReloadKey((k) => k + 1)}
      />
    </div>
  );
}
