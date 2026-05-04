"""Test credits ledger invariant: SUM(delta) == credits change for all operations."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from webapp.database import Base
from webapp import models, credits


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    # credit_transactions is a raw-SQL table in run_migrations; create it manually here
    with engine.connect() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS credit_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            delta INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            reason TEXT NOT NULL,
            job_id INTEGER,
            meta TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""))
        conn.commit()
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def user(db_session):
    u = models.User(username="testuser", password_hash="x", credits_remaining=10)
    db_session.add(u)
    db_session.commit()
    return u


def _ledger_sum(user, db) -> int:
    return db.execute(
        text("SELECT COALESCE(SUM(delta), 0) FROM credit_transactions WHERE user_id = :uid"),
        {"uid": user.id},
    ).scalar()


def test_grant_updates_balance_and_ledger(db_session, user):
    credits.grant(user, 50, reason="admin_grant", db=db_session, admin_id=1)
    assert user.credits_remaining == 60
    assert _ledger_sum(user, db_session) == 50


def test_deduct_updates_balance_and_ledger(db_session, user):
    credits.deduct(user, 3, reason="job_consumed", db=db_session, job_id=1)
    assert user.credits_remaining == 7
    assert _ledger_sum(user, db_session) == -3


def test_refund_adds_back(db_session, user):
    credits.deduct(user, 5, reason="job_consumed", db=db_session, job_id=1)
    credits.refund(user, 5, db=db_session, job_id=1)
    assert user.credits_remaining == 10
    assert _ledger_sum(user, db_session) == 0  # -5 + 5 = 0


def test_deduct_insufficient_raises(db_session, user):
    with pytest.raises(ValueError, match="Insufficient credits"):
        credits.deduct(user, 999, reason="job_consumed", db=db_session)
    assert user.credits_remaining == 10  # unchanged


def test_check_balance(db_session, user):
    assert credits.check_balance(user, 10) is True
    assert credits.check_balance(user, 11) is False


def test_grant_and_deduct_invariant(db_session, user):
    credits.grant(user, 90, reason="purchase", db=db_session)        # balance = 100
    credits.deduct(user, 30, reason="job_consumed", db=db_session, job_id=1)  # balance = 70
    credits.deduct(user, 20, reason="job_consumed", db=db_session, job_id=2)  # balance = 50
    credits.refund(user, 10, db=db_session, job_id=2)                         # balance = 60
    assert user.credits_remaining == 60
    # Ledger sum (initial 10 not in ledger): +90 -30 -20 +10 = 50
    assert _ledger_sum(user, db_session) == 50


def test_get_balance(db_session, user):
    assert credits.get_balance(user) == 10
    credits.grant(user, 5, reason="admin_grant", db=db_session)
    assert credits.get_balance(user) == 15
