"""FastAPI application entry point."""
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from webapp.database import Base, engine, run_migrations, SessionLocal
from webapp.routers import auth, dashboard, jobs, feedback

# Create all DB tables and run column migrations on startup
Base.metadata.create_all(bind=engine)
run_migrations()

# On every startup, any job still marked 'processing' was killed mid-run
# (server restart / deploy during pipeline). Mark them failed so users can re-run.
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

_reset_stale_jobs()

app = FastAPI(title="Qong — P&ID Valve Extractor")

# Serve static assets (logo, etc.)
_imgs_dir = Path(__file__).parent / "imgs"
app.mount("/imgs", StaticFiles(directory=_imgs_dir), name="imgs")

# Register routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(jobs.router)
app.include_router(feedback.router)


@app.get("/")
async def root(request: Request):
    token = request.cookies.get("access_token")
    if token:
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login")
