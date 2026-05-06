"""FastAPI application entry point."""
from pathlib import Path
import time
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from webapp.database import Base, engine, run_migrations, SessionLocal
from webapp.routers import auth, dashboard, jobs, feedback
from webapp.routers import admin as admin_router
from webapp.routers import account as account_router
from webapp.routers import api_v1 as api_v1_router
from webapp.config import JOB_OUTPUT_DIR, get_job_dir

# Create all DB tables and run column migrations on startup
Base.metadata.create_all(bind=engine)
run_migrations()


def _reset_stale_jobs() -> None:
    from webapp import models
    db = SessionLocal()
    try:
        stale = (
            db.query(models.Job)
            .filter(models.Job.status == "processing")
            .all()
        )
        for job in stale:
            job.status = "failed"
            job.error_msg = "Job was interrupted by a server restart. Please re-run."
        if stale:
            db.commit()
            print(f"[startup] Reset {len(stale)} stale job(s) to 'failed': {[j.id for j in stale]}")
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


_reset_stale_jobs()
_ensure_super_admin()

app = FastAPI(title="Qong — P&ID Valve Extractor")

# Serve static assets (logo, etc.)
_imgs_dir = Path(__file__).parent / "imgs"
app.mount("/imgs", StaticFiles(directory=_imgs_dir), name="imgs")

# Register routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(jobs.router)
app.include_router(feedback.router)
app.include_router(admin_router.router)
app.include_router(account_router.router)
app.include_router(api_v1_router.router)


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


@app.get("/")
async def root(request: Request):
    token = request.cookies.get("access_token")
    if token:
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login")


@app.get("/jobs/{job_id}/tiles/{filename}")
async def serve_tile(job_id: int, filename: str):
    """Serve tile PNG images — used by Label Studio to load task images."""
    from fastapi import HTTPException
    from webapp import models
    from webapp.database import SessionLocal
    db = SessionLocal()
    try:
        job = db.query(models.Job).filter(models.Job.id == job_id).first()
    finally:
        db.close()
    if not job:
        raise HTTPException(status_code=404, detail="Tile not found")
    tile_path = get_job_dir(job) / "tmp" / filename
    if not tile_path.exists() or tile_path.suffix != ".png":
        raise HTTPException(status_code=404, detail="Tile not found")
    return FileResponse(str(tile_path), media_type="image/png")
