"""FastAPI application entry point."""
from datetime import datetime, timedelta
from pathlib import Path
import time
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from webapp.database import Base, engine, run_migrations, SessionLocal
from webapp.routers import auth, jobs, feedback
from webapp.routers import annotate as annotate_router
from webapp.routers import api_v1 as api_v1_router
from webapp.routers import api_v1_admin as api_v1_admin_router
from webapp.routers import exports as exports_router
from webapp.routers import entities as entities_router
from webapp.routers import webhooks as webhooks_router
# Studio marking + graph annotation surface (FEATURES #38)
from webapp.routers import annotations as annotations_router
from webapp.routers import edges as edges_router
from webapp.routers import shortcuts as shortcuts_router
from webapp.routers import sheets as sheets_router
# Process-graph read API (graph-extraction, 2026-06-13)
from webapp.routers import graph as graph_router
import webapp.deliverables  # noqa: F401 — populates generator registry
from webapp.config import JOB_OUTPUT_DIR, get_job_dir
from webapp.watchdog import start_watchdog

# Create all DB tables and run column migrations on startup
Base.metadata.create_all(bind=engine)
run_migrations()

# Stuck-job cutoff: anything in 'processing' for longer than this is reaped on
# startup. The largest jobs we've measured (12-page Ebara P&ID, 108 tiles) take
# ~30 min — 90 minutes leaves headroom for a slower model or retry without
# false-positives.
STALE_JOB_CUTOFF_MINUTES = 90


def _reset_stale_jobs() -> None:
    """Mark jobs that were 'processing' for too long as failed.

    With RQ, in-flight jobs survive web restarts (the work is on cpu-worker).
    Only reap jobs older than the cutoff so we don't kill recently-restarted
    work that's still legitimately running.
    """
    from webapp import models
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=STALE_JOB_CUTOFF_MINUTES)
        stale = (
            db.query(models.Job)
            .filter(
                models.Job.status == "processing",
                models.Job.created_at < cutoff,
            )
            .all()
        )
        for job in stale:
            job.status = "failed"
            job.error_msg = (
                f"Job exceeded {STALE_JOB_CUTOFF_MINUTES}-minute timeout — "
                "the worker either crashed or got stuck. Please re-run."
            )
            job.completed_at = datetime.utcnow()
        if stale:
            db.commit()
            print(f"[startup] Reaped {len(stale)} stale job(s): {[j.id for j in stale]}")
    finally:
        db.close()


def _ensure_super_admin() -> None:
    """Promote the 'admin' user to super_admin if no super_admin exists yet."""
    from webapp import models
    db = SessionLocal()
    try:
        has_super = db.query(models.User).filter(models.User.role == "super_admin").first()
        if has_super:
            return
        # Promote 'admin' account if it exists, otherwise promote oldest user
        candidate = (
            db.query(models.User).filter(models.User.username == "admin").first()
            or db.query(models.User).order_by(models.User.id).first()
        )
        if candidate:
            candidate.role = "super_admin"
            db.commit()
            print(f"[startup] Promoted '{candidate.username}' to super_admin")
    finally:
        db.close()


def _reconcile_ls_webhooks() -> None:
    """Best-effort: attach the auto-tile webhook to any LS project that's
    missing it, and enqueue tiling for leftover PDF tasks. Covers LS Import UI
    projects that bypass `get_or_create_project`. Failures are swallowed so a
    flaky LS or network blip can't block webapp boot."""
    try:
        from webapp.label_studio_client import reconcile_project_webhooks
        reconcile_project_webhooks(enqueue_pdf_backlog=True)
    except Exception as e:
        print(f"[startup] LS webhook reconcile skipped: {e!r}")


_reset_stale_jobs()
_ensure_super_admin()
_reconcile_ls_webhooks()

app = FastAPI(title="Qong — P&ID Valve Extractor")

# Heartbeat-watchdog: reaps JobRuns whose pipeline-runner stopped beating.
start_watchdog(app)

# Serve static assets (logo, etc.)
_imgs_dir = Path(__file__).parent / "imgs"
app.mount("/imgs", StaticFiles(directory=_imgs_dir), name="imgs")

# Register routers
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(feedback.router)
app.include_router(annotate_router.router)
app.include_router(api_v1_router.router)
app.include_router(api_v1_admin_router.router)
app.include_router(exports_router.router)
app.include_router(entities_router.router)
app.include_router(webhooks_router.router)
# Studio marking + graph annotation. Must be registered BEFORE the SPA catch-all
# mount below — otherwise unauthenticated GETs return text/html (the SPA shell)
# instead of the expected JSON 401, breaking deploy-polling and curl-driven QA.
app.include_router(annotations_router.router)
app.include_router(edges_router.router)
app.include_router(shortcuts_router.router)
app.include_router(sheets_router.router)
app.include_router(graph_router.router)


@app.get("/healthz")
async def healthz():
    """Health check — used by uptime monitors and restore scripts."""
    status = {"status": "ok", "timestamp": int(time.time())}
    try:
        db = SessionLocal()
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db.close()
        status["db"] = "ok"
    except Exception as e:
        status["db"] = f"error: {e}"
        status["status"] = "degraded"
    return JSONResponse(status, status_code=200 if status["status"] == "ok" else 503)


# The `/jobs/{job_id}/tiles/{filename}` route is in webapp/routers/jobs.py
# (registered via app.include_router(jobs.router) earlier in this file).
# We do NOT redefine it here — that handler was previously shadowed because
# router registrations come before app.get(...) calls. The CORS headers for
# LS live in the jobs.py router definition.


# ── SPA static mount + catch-all ──────────────────────────────────────────────
# Serves the Vite-built React SPA from webapp/frontend/dist/. Mount registered
# AFTER all API/auth routers so explicit FastAPI routes win; the catch-all
# only fires for paths the backend doesn't claim — letting React Router
# handle /, /dashboard, /admin/*, /jobs/:id, /signin, etc.
_SPA_DIST = Path(__file__).parent / "frontend" / "dist"
# Mount unconditionally with check_dir=False so registration doesn't depend on
# whether dist/ exists at import time. If the SPA isn't built yet, StaticFiles
# returns a real 404 for /assets/* — which is correct: a 404 with no body, not
# the catch-all serving index.html as text/html (browsers refuse to load HTML
# as an ES module, breaking SPA bootstrap entirely — bug we hit on QA bring-up).
app.mount(
    "/assets",
    StaticFiles(directory=str(_SPA_DIST / "assets"), check_dir=False),
    name="spa_assets",
)


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    """Serve real dist/ files (favicon.svg, robots.txt, etc.) directly, and
    fall back to dist/index.html for any other GET so React Router can handle
    SPA navigation (refresh on /admin/users, /jobs/123, etc.). API and
    explicit routes registered above this point win because FastAPI matches
    in order.

    The `try_files`-style dist-root passthrough was added 2026-06-02 — the
    favicon work surfaced that anything at dist root (not under /assets/) was
    being served as index.html. With this passthrough, Vite's public/ files
    get the right Content-Type automatically.
    """
    if full_path:
        # Path traversal guard: resolve the candidate and ensure it stays
        # inside _SPA_DIST. Without this, e.g. `/../etc/passwd` would escape.
        dist_root = _SPA_DIST.resolve()
        try:
            candidate = (_SPA_DIST / full_path).resolve()
            candidate.relative_to(dist_root)
        except (ValueError, OSError):
            candidate = None
        if candidate is not None and candidate.is_file():
            # FileResponse auto-detects MIME type from the extension. .svg →
            # image/svg+xml, .png → image/png, .txt → text/plain, etc.
            return FileResponse(str(candidate))

    index = _SPA_DIST / "index.html"
    if index.exists():
        # index.html must NOT be cached by the browser: it's the bootstrap that
        # references the content-hashed asset bundles (index-<hash>.js/.css).
        # If a browser holds a stale index.html it loads the OLD bundle after a
        # deploy — the "hard-refresh to see changes" problem. no-cache forces a
        # revalidation on every load so the new asset hashes are always picked
        # up; the hashed assets themselves stay long-cached (immutable). Set
        # post-construction (Starlette can drop a `headers=` kwarg depending on
        # media type — see the FileResponse gotcha in CLAUDE.md).
        resp = FileResponse(str(index), media_type="text/html")
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp
    # Local dev without a build: tell the user to run `npm run build` or use
    # Vite dev server (port 5173). Don't surprise them with a 404.
    return JSONResponse(
        status_code=503,
        content={
            "error": "SPA not built",
            "hint": "Run `cd webapp/frontend && npm run build` to populate dist/, "
                    "or use Vite dev server at http://localhost:5173/.",
        },
    )
