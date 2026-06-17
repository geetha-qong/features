"""Current-model anchor for the self-learning loop.

The production YOLO version is pinned in ``models/MODEL_VERSION.txt`` (the
``current:`` line). This module exposes that version plus the date the current
model was *trained* — the anchor for "how many corrections have we collected
since the current model?" (the retrain-readiness counter, FEATURES self-learning
Phase 1).

Why a separate ``_TRAINED_AT`` map instead of parsing the registry's free-text
notes: the notes are human prose ("Trained 2026-06-15 on AWS g5.2xlarge …"), too
fragile to parse for a timestamp the learning math depends on. So the *version*
is read from the file (never drifts from what inference actually loads) while the
*trained-at date* is a small structured table here. **When you promote a new
model, add one row to ``_TRAINED_AT``** (and the registry file as usual).
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Repo-root/models/MODEL_VERSION.txt — three parents up from webapp/model_version.py
_REGISTRY = Path(__file__).resolve().parent.parent / "models" / "MODEL_VERSION.txt"

# Fallback if the registry file is unreadable (matches inference.py MODEL_PATH).
_FALLBACK_VERSION = "v1-11"

# Training dates per version (UTC). Append a row on each model promotion.
# Sourced from models/MODEL_VERSION.txt notes + FEATURES.md.
_TRAINED_AT = {
    "v1-11": datetime(2026, 6, 15, tzinfo=timezone.utc),
    "v1-10": datetime(2026, 6, 5, tzinfo=timezone.utc),
    "v1-9": datetime(2026, 5, 25, tzinfo=timezone.utc),
    "v1-8": datetime(2026, 5, 13, tzinfo=timezone.utc),
    "v1-7": datetime(2026, 5, 7, tzinfo=timezone.utc),
}


def current_version() -> str:
    """The production model version from ``models/MODEL_VERSION.txt`` (``current:``).

    Falls back to ``v1-11`` if the file is missing/unparsable so callers never
    crash on a fresh checkout.
    """
    try:
        for line in _REGISTRY.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("current:"):
                v = stripped.split(":", 1)[1].strip()
                if v:
                    return v
    except OSError:
        pass
    return _FALLBACK_VERSION


def current_model_trained_at() -> Optional[datetime]:
    """UTC datetime the current model was trained, or None if unknown.

    The anchor for "corrections since the current model" — count correction rows
    with ``created_at >= current_model_trained_at()``.
    """
    return _TRAINED_AT.get(current_version())


def model_trained_at(version: str) -> Optional[datetime]:
    """UTC training date for an explicit version, or None if not recorded."""
    return _TRAINED_AT.get(version)
