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
