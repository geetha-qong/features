"""App configuration — reads from environment variables."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

_SECRET_FALLBACK = "change-me-in-production-please"
SECRET_KEY: str = os.environ.get("SECRET_KEY", _SECRET_FALLBACK)
if SECRET_KEY == _SECRET_FALLBACK or len(SECRET_KEY) < 32:
    sys.stderr.write(
        "FATAL: SECRET_KEY env var missing or shorter than 32 chars. "
        "Generate one with: python3 -c 'import secrets; print(secrets.token_hex(32))'\n"
    )
    sys.exit(1)

ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours

# Cookie security: set to "0" only for local HTTP dev
COOKIE_SECURE: bool = os.environ.get("COOKIE_SECURE", "1") != "0"

# Password / username policy
MIN_PASSWORD_LENGTH: int = int(os.environ.get("MIN_PASSWORD_LENGTH", "8"))

UPLOAD_DIR: Path = BASE_DIR / "uploads"
JOB_OUTPUT_DIR: Path = BASE_DIR / "job_outputs"
_DB_DIR = BASE_DIR / "data"
DATABASE_URL: str = os.environ.get("DATABASE_URL", f"sqlite:///{_DB_DIR / 'webapp.db'}")
if DATABASE_URL.startswith("sqlite"):
    _DB_DIR.mkdir(parents=True, exist_ok=True)

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
