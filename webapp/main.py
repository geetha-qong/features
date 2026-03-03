"""FastAPI application entry point."""
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from webapp.database import Base, engine, run_migrations
from webapp.routers import auth, dashboard, jobs, feedback

# Create all DB tables and run column migrations on startup
Base.metadata.create_all(bind=engine)
run_migrations()

app = FastAPI(title="P&ID Valve Extractor")

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
