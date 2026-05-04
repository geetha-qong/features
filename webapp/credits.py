"""Credits ledger — all balance changes go through this module.

Invariant: user.credits_remaining == SUM(delta) FROM credit_transactions WHERE user_id = user.id
Never call db.query(User).update(credits_remaining=...) directly — always use grant/deduct/refund.
"""
from __future__ import annotations

import json
from typing import Optional, TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from webapp.models import User


def check_balance(user: "User", required: int) -> bool:
    """Return True if user has enough credits."""
    return (user.credits_remaining or 0) >= required


def grant(
    user: "User",
    amount: int,
    reason: str,
    db: Session,
    admin_id: Optional[int] = None,
    job_id: Optional[int] = None,
) -> None:
    """Add credits to a user's balance and record in the ledger."""
    from webapp.models import CreditTransaction
    new_balance = (user.credits_remaining or 0) + amount
    txn = CreditTransaction(
        user_id=user.id,
        delta=amount,
        balance_after=new_balance,
        reason=reason,
        job_id=job_id,
        meta=json.dumps({"admin_id": admin_id}) if admin_id else None,
    )
    user.credits_remaining = new_balance
    db.add(txn)
    db.commit()


def deduct(
    user: "User",
    amount: int,
    reason: str,
    db: Session,
    job_id: Optional[int] = None,
) -> None:
    """Subtract credits from user balance and record in the ledger. Raises ValueError if insufficient."""
    from webapp.models import CreditTransaction
    current = user.credits_remaining or 0
    if current < amount:
        raise ValueError(f"Insufficient credits: have {current}, need {amount}")
    new_balance = current - amount
    txn = CreditTransaction(
        user_id=user.id,
        delta=-amount,
        balance_after=new_balance,
        reason=reason,
        job_id=job_id,
    )
    user.credits_remaining = new_balance
    db.add(txn)
    db.commit()


def refund(
    user: "User",
    amount: int,
    db: Session,
    job_id: Optional[int] = None,
) -> None:
    """Refund credits (e.g. after job failure). Calls grant with reason='refund'."""
    grant(user, amount, reason="refund", db=db, job_id=job_id)


def get_balance(user: "User") -> int:
    return user.credits_remaining or 0
