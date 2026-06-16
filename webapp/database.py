"""SQLAlchemy engine, session, and base setup."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from webapp.config import DATABASE_URL

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_IS_SQLITE = DATABASE_URL.startswith("sqlite")


class Base(DeclarativeBase):
    pass


def _column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists. Avoids acquiring DDL locks for ALTERs we'd skip anyway."""
    if _IS_SQLITE:
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


def _column_is_timestamptz(conn, table: str, column: str) -> bool:
    """Postgres only. Returns True if the column is already `timestamp with time zone`."""
    if _IS_SQLITE:
        return True  # SQLite stores datetimes as TEXT; TZ is a no-op
    row = conn.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).first()
    return bool(row and row[0] == "timestamp with time zone")


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
        ("jobs", "output_annotated_pdf_path", "TEXT"),
        ("jobs", "gpu_detections", "TEXT"),
        ("users", "role", "TEXT DEFAULT 'user'"),
        ("users", "is_active", "INTEGER DEFAULT 1"),
        ("users", "credits_remaining", "INTEGER DEFAULT 10"),
        ("users", "tier", "TEXT DEFAULT 'trial'"),
        ("users", "organization", "TEXT"),
        ("users", "timezone", "TEXT"),
        ("jobs", "original_filename", "TEXT"),
        # Studio per-user shortcuts (FEATURES #38). Postgres JSONB; SQLite stores as TEXT.
        # Schemaless on purpose — frontend validates structure before PATCH.
        ("users", "shortcuts", "JSONB" if not _IS_SQLITE else "TEXT"),
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

    # Convert legacy `timestamp without time zone` columns to `timestamptz` (FEATURES #27).
    # Existing values are assumed to be UTC (matches `datetime.utcnow()` write convention)
    # and are re-tagged at TIME ZONE 'UTC'. Postgres only — SQLite ignores type.
    timestamptz_columns = [
        ("users", "created_at"),
        ("jobs", "created_at"),
        ("jobs", "completed_at"),
        ("job_runs", "started_at"),
        ("job_runs", "ended_at"),
        ("job_runs", "last_heartbeat_at"),
        ("feedback", "created_at"),
        ("api_keys", "created_at"),
        ("api_keys", "last_used_at"),
        ("api_keys", "revoked_at"),
        ("credit_transactions", "created_at"),
        ("billing_plans", "created_at"),
        ("entity_overrides", "edited_at"),
        ("user_feedback", "created_at"),
    ]
    if not _IS_SQLITE:
        for table, column in timestamptz_columns:
            try:
                with engine.connect() as conn:
                    if not _column_exists(conn, table, column):
                        continue
                    if _column_is_timestamptz(conn, table, column):
                        continue
                    conn.execute(text(
                        f"ALTER TABLE {table} ALTER COLUMN {column} "
                        f"TYPE timestamptz USING ({column} AT TIME ZONE 'UTC')"
                    ))
                    conn.commit()
                    print(f"[migration] {table}.{column} → timestamptz")
            except Exception as exc:
                # ALTER TYPE rewrites the column; if it fails we want to know,
                # not silently leave half-migrated state.
                print(f"[migration] ALTER {table}.{column} failed: {exc!r}")

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

    # Optional initial-admin bootstrap. SECURITY (CRITICAL finding): never
    # hard-code credentials and never reset a password on restart. The previous
    # code seeded admin/admin as super_admin and re-applied "admin" on every
    # boot — exploitable on any reachable env. We now ONLY create an admin when
    # both INITIAL_ADMIN_EMAIL and INITIAL_ADMIN_PASSWORD are set AND no
    # super_admin exists yet, and we never overwrite an existing user. Existing
    # envs (dev/qa/prod/local with a persisted volume) already have an admin, so
    # this is a no-op there; a brand-new DB sets the env vars to bootstrap.
    import os

    boot_email = os.environ.get("INITIAL_ADMIN_EMAIL")
    boot_pw = os.environ.get("INITIAL_ADMIN_PASSWORD")
    if boot_email and boot_pw:
        with engine.connect() as conn:
            has_admin = conn.execute(
                text("SELECT id FROM users WHERE role = 'super_admin' LIMIT 1")
            ).fetchone()
            if not has_admin:
                from webapp.auth import pwd_context

                conn.execute(
                    text(
                        """
                        INSERT INTO users (username, email, password_hash, role, is_active, credits_remaining)
                        VALUES (:u, :e, :ph, 'super_admin', TRUE, 999)
                        ON CONFLICT (username) DO NOTHING
                        """
                    ),
                    {"u": boot_email.split("@")[0], "e": boot_email, "ph": pwd_context.hash(boot_pw)},
                )
                conn.commit()
                print(f"[startup] Bootstrapped initial super_admin {boot_email} from INITIAL_ADMIN_* env")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
