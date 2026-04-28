"""SQLAlchemy engine, session, and base setup."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from webapp.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # needed for SQLite
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def run_migrations():
    """Add new columns to existing tables if they don't exist yet."""
    new_columns = [
        ("jobs", "processing_time", "REAL"),
        ("jobs", "processing_log", "TEXT"),
        ("jobs", "include_control_valves", "INTEGER DEFAULT 1"),
        ("jobs", "ls_project_id", "INTEGER"),
        ("jobs", "ls_synced", "INTEGER DEFAULT 0"),
        ("users", "role", "TEXT DEFAULT 'user'"),
        ("users", "is_active", "INTEGER DEFAULT 1"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
            except Exception:
                pass  # column already exists


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
