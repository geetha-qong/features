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
        ("jobs", "output_inst_index_path", "TEXT"),
        ("jobs", "output_inst_datasheet_path", "TEXT"),
        ("users", "role", "TEXT DEFAULT 'user'"),
        ("users", "is_active", "INTEGER DEFAULT 1"),
        ("users", "credits_remaining", "INTEGER DEFAULT 10"),
        ("users", "tier", "TEXT DEFAULT 'trial'"),
        ("users", "organization", "TEXT"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
            except Exception:
                pass  # column already exists

    # Create new SaaS tables (idempotent)
    new_tables_sql = [
        """CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            key_prefix TEXT NOT NULL,
            key_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP,
            revoked_at TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS credit_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            delta INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            reason TEXT NOT NULL,
            job_id INTEGER REFERENCES jobs(id),
            meta TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS billing_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            credits INTEGER NOT NULL,
            price_usd_cents INTEGER NOT NULL,
            is_active INTEGER DEFAULT 1,
            stripe_price_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS user_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            category TEXT NOT NULL,
            subject TEXT NOT NULL,
            message TEXT NOT NULL,
            page_url TEXT,
            status TEXT DEFAULT 'new',
            admin_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
    ]
    with engine.connect() as conn:
        for sql in new_tables_sql:
            conn.execute(text(sql))
            conn.commit()

    # Seed default billing plans if none exist
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM billing_plans")).scalar()
        if count == 0:
            conn.execute(text("""
                INSERT INTO billing_plans (name, credits, price_usd_cents, is_active) VALUES
                ('Trial', 10, 0, 1),
                ('Starter', 100, 1900, 1),
                ('Pro', 1000, 14900, 1),
                ('Enterprise', 0, 0, 0)
            """))
            conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
