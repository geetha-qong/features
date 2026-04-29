"""App configuration — reads from environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY: str = os.environ.get("SECRET_KEY", "change-me-in-production-please")
ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours

UPLOAD_DIR: Path = BASE_DIR / "uploads"
JOB_OUTPUT_DIR: Path = BASE_DIR / "job_outputs"
DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'webapp.db'}"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
JOB_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_job_dir(job) -> Path:
    """
    Return the output directory for a job.
    New layout: job_outputs/{user_id}/{job_id}/
    Legacy fallback: job_outputs/{job_id}/  (for jobs created before per-user folders)
    """
    new_path = JOB_OUTPUT_DIR / str(job.user_id) / str(job.id)
    if new_path.exists():
        return new_path
    legacy = JOB_OUTPUT_DIR / str(job.id)
    return legacy


def get_user_upload_dir(user_id: int) -> Path:
    """Return (and create) the upload directory for a specific user."""
    d = UPLOAD_DIR / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d
