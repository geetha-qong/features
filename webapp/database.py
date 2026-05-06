"""SQLAlchemy engine, session, and base setup."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from webapp.config import DATABASE_URL

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
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
    with engine.connect() as conn:
        for table, column, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
            except Exception:
                pass  # column already exists

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
