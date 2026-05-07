"""SQLAlchemy engine, session, and base setup."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from webapp.config import DATABASE_URL

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def _column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists. Avoids acquiring DDL locks for ALTERs we'd skip anyway."""
    is_sqlite = DATABASE_URL.startswith("sqlite")
    if is_sqlite:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(r[1] == column for r in rows)
    # Postgres
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).first()
    return row is not None


def run_migrations():
    """Add new columns to existing tables if they don't exist yet.

    Important: probe column existence first so we don't issue ALTER TABLE for
    columns that already exist. ALTER acquires an ACCESS EXCLUSIVE lock on the
    table even when it ultimately errors with 'column already exists', which
    can deadlock against long-running cpu-worker transactions.
    """
    new_columns = [
        ("jobs", "processing_time", "REAL"),
        ("jobs", "processing_log", "TEXT"),
        ("jobs", "include_control_valves", "INTEGER DEFAULT 1"),
        ("jobs", "ls_project_id", "INTEGER"),
        ("jobs", "ls_synced", "INTEGER DEFAULT 0"),
        ("jobs", "output_inst_index_path", "TEXT"),
        ("jobs", "output_inst_datasheet_path", "TEXT"),
        ("jobs", "gpu_detections", "TEXT"),
        ("users", "role", "TEXT DEFAULT 'user'"),
        ("users", "is_active", "INTEGER DEFAULT 1"),
        ("users", "credits_remaining", "INTEGER DEFAULT 10"),
        ("users", "tier", "TEXT DEFAULT 'trial'"),
        ("users", "organization", "TEXT"),
        ("jobs", "original_filename", "TEXT"),
    ]
    for table, column, col_type in new_columns:
        try:
            with engine.connect() as conn:
                if _column_exists(conn, table, column):
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
        except Exception:
            pass  # racy — another worker added it concurrently

    # Create new SaaS tables via SQLAlchemy ORM (dialect-agnostic — works on SQLite + Postgres)
    from webapp import models  # noqa: F401 — registers tables on Base.metadata
    Base.metadata.create_all(engine)

    # Seed default billing plans if none exist
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM billing_plans")).scalar()
        if count == 0:
            conn.execute(text("""
                INSERT INTO billing_plans (name, credits, price_usd_cents, is_active) VALUES
                ('Trial', 10, 0, TRUE),
                ('Starter', 100, 1900, TRUE),
                ('Pro', 1000, 14900, TRUE),
                ('Enterprise', 0, 0, FALSE)
            """))
            conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
