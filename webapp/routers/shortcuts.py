"""Per-user Studio keyboard-shortcut keymap.

Studio (the in-house annotation/review UI) binds keys to actions: select an
entity-class swatch, switch modes (select / mark-symbol / draw-edge), cancel,
delete selected. The defaults below are good for the team's muscle memory but
each user can override any subset.

Why a dedicated endpoint instead of stuffing this in the existing /account
PATCH:
  - Reset semantics matter — POST /reset is a clear, low-ambiguity action and
    we don't want to overload PATCH /account with a magic null sentinel.
  - The merge-on-read shape (defaults under user-set keys) is opinionated and
    deserves its own contract, separate from the account profile.
  - Future bindings (per-customer template hotkeys, per-deliverable overlays)
    plug in here without touching account.

Storage: `User.shortcuts` is a JSON column. `None` means "use defaults".
A non-null value is a partial map that is merged on top of DEFAULTS at read
time so a user's customisations survive when we add new default bindings.

PATCH is WHOLE-OBJECT REPLACE (the request body's `shortcuts` becomes the
stored value verbatim). It's not a deep merge; clients should send the full
desired state. The "merged with defaults" behaviour is only on the way out.

Auth: every endpoint depends on `get_current_user` — same cookie-JWT pattern
used by webapp/routers/entities.py. No IDOR concerns here because each
endpoint is scoped to the caller's own User row (`/me/...`).
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db


router = APIRouter(prefix="/api/v1/users", tags=["shortcuts"])


# --- defaults ------------------------------------------------------------

# Default Studio keymap. Lowercase letters select entity-class swatches,
# digits switch modes, named keys handle global edit actions. Modifier chords
# are intentionally absent — see PATCH validation for why.
DEFAULT_SHORTCUTS: Dict[str, Dict[str, Any]] = {
    # ── Valves ──────────────────────────────────────────────────────────────
    "v": {"action": "select-class", "entity_class": "valve",      "sub_class": "BV"},
    "g": {"action": "select-class", "entity_class": "valve",      "sub_class": "GT"},
    "b": {"action": "select-class", "entity_class": "valve",      "sub_class": "BF"},
    "c": {"action": "select-class", "entity_class": "valve",      "sub_class": "CV"},
    "k": {"action": "select-class", "entity_class": "valve",      "sub_class": "CK"},
    "r": {"action": "select-class", "entity_class": "valve",      "sub_class": "RELIEF_SAFETY"},
    "w": {"action": "select-class", "entity_class": "valve",      "sub_class": "3WAY_RELIEF"},
    # ── Instruments ─────────────────────────────────────────────────────────
    "f": {"action": "select-class", "entity_class": "instrument", "sub_class": "FT"},
    "p": {"action": "select-class", "entity_class": "instrument", "sub_class": "PT"},
    "t": {"action": "select-class", "entity_class": "instrument", "sub_class": "TT"},
    "l": {"action": "select-class", "entity_class": "instrument", "sub_class": "LT"},
    "i": {"action": "select-class", "entity_class": "instrument", "sub_class": "interlock"},
    "q": {"action": "select-class", "entity_class": "instrument", "sub_class": "BPCS"},
    "s": {"action": "select-class", "entity_class": "instrument", "sub_class": "SIS"},
    # ── Equipment ───────────────────────────────────────────────────────────
    "m": {"action": "select-class", "entity_class": "equipment",  "sub_class": "Motor"},
    # ── Annotations ─────────────────────────────────────────────────────────
    "u": {"action": "select-class", "entity_class": "annotation", "sub_class": "arrow_up"},
    "d": {"action": "select-class", "entity_class": "annotation", "sub_class": "arrow_down"},
    "a": {"action": "select-class", "entity_class": "annotation", "sub_class": "arrow_left"},
    "e": {"action": "select-class", "entity_class": "annotation", "sub_class": "arrow_right"},
    "n": {"action": "select-class", "entity_class": "annotation", "sub_class": "connector_in"},
    "o": {"action": "select-class", "entity_class": "annotation", "sub_class": "connector_out"},
    # ── Modes & global actions ───────────────────────────────────────────────
    "1": {"action": "mode",         "mode": "select"},
    "2": {"action": "mode",         "mode": "mark-symbol"},
    "3": {"action": "mode",         "mode": "draw-edge"},
    "Escape": {"action": "cancel"},
    "Delete": {"action": "delete-selected"},
}


# Whitelist of accepted action values. Adding a new action requires both this
# set AND a matching validation branch in `_validate_binding`.
ALLOWED_ACTIONS = {"select-class", "mode", "cancel", "delete-selected"}

# Mode values are constrained because Studio has exactly three tool modes
# right now. If we add a fourth (e.g. "measure"), update both this set and the
# frontend's mode-switcher.
ALLOWED_MODES = {"select", "mark-symbol", "draw-edge"}

# Multi-char key names we accept verbatim. Anything else longer than 1 char
# is rejected so we don't silently store `"Backspace": ...` and have the
# frontend never look it up.
NAMED_KEYS = {"Escape", "Delete", "Tab", "Enter", "Space"}


# --- pydantic models -----------------------------------------------------


class ShortcutBinding(BaseModel):
    """One key → action binding.

    Field set varies by action — we accept the union here and validate the
    per-action requirements in `_validate_binding`. Keeping the schema permissive
    at the Pydantic layer means the 400 messages are useful instead of generic
    "missing field" envelope errors.
    """
    action: str
    entity_class: Optional[str] = None
    sub_class: Optional[str] = None
    mode: Optional[str] = None

    class Config:
        # Forward-compat: if Studio adds extra metadata to a binding (e.g.
        # `description`, `icon`) we don't want every old client to 400.
        extra = "allow"


class ShortcutsPatch(BaseModel):
    shortcuts: Dict[str, ShortcutBinding]


class ShortcutsResponse(BaseModel):
    # Use a plain dict here so we don't tie the response schema to the input
    # schema during gradual evolution — frontend already treats this as opaque
    # JSON keyed by the key string.
    shortcuts: Dict[str, dict]


# --- helpers -------------------------------------------------------------


def _validate_key(key: str) -> None:
    """Reject keys we can't safely bind in the browser.

    Modifier chords (anything containing '+') are forbidden because the
    frontend would have to intercept browser/OS shortcuts (Ctrl+S, Cmd+R)
    which leads to "why doesn't save work?" support tickets. We can revisit
    when there's a need for a managed-chord story.
    """
    if "+" in key:
        raise HTTPException(
            status_code=400,
            detail=f"key '{key}': modifier chords reserved for browser; bind plain keys only",
        )
    if len(key) > 1 and key not in NAMED_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"key '{key}': must be a single character or one of {sorted(NAMED_KEYS)}",
        )
    if len(key) == 0:
        raise HTTPException(status_code=400, detail="key is empty")


def _validate_binding(key: str, binding: ShortcutBinding) -> None:
    """Per-action shape check. Runs after pydantic parsing succeeded."""
    if binding.action not in ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"key '{key}': unknown action '{binding.action}'. "
                f"Allowed: {sorted(ALLOWED_ACTIONS)}"
            ),
        )
    if binding.action == "select-class":
        if not binding.entity_class or not binding.sub_class:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"key '{key}': action 'select-class' requires "
                    f"entity_class + sub_class"
                ),
            )
    elif binding.action == "mode":
        if binding.mode not in ALLOWED_MODES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"key '{key}': action 'mode' requires mode in "
                    f"{sorted(ALLOWED_MODES)}, got {binding.mode!r}"
                ),
            )
    # "cancel" and "delete-selected" take no extra fields — anything extra is
    # passed through (extra=allow) but ignored by the frontend.


def _merged_with_defaults(stored: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Return defaults overlaid with whatever the user has stored.

    User-set keys win; defaults fill the gaps. This means adding a new default
    binding in a release immediately reaches users who'd customised other keys
    — no migration needed.
    """
    merged: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in DEFAULT_SHORTCUTS.items()}
    if stored:
        for k, v in stored.items():
            # Re-dict to avoid sharing references with the stored JSON column
            merged[k] = dict(v) if isinstance(v, dict) else v
    return merged


# --- endpoints -----------------------------------------------------------


@router.get(
    "/me/shortcuts",
    response_model=ShortcutsResponse,
    responses={
        200: {"description": "User's keymap merged with system defaults"},
    },
)
def get_my_shortcuts(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> ShortcutsResponse:
    return ShortcutsResponse(shortcuts=_merged_with_defaults(current_user.shortcuts))


@router.patch(
    "/me/shortcuts",
    response_model=ShortcutsResponse,
    responses={
        200: {"description": "Updated keymap (the stored value, not the merged view)"},
        400: {"description": "Invalid key name, unknown action, or missing required fields"},
    },
)
def patch_my_shortcuts(
    payload: ShortcutsPatch,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> ShortcutsResponse:
    # Validate every binding BEFORE writing — atomicity for the caller.
    for key, binding in payload.shortcuts.items():
        _validate_key(key)
        _validate_binding(key, binding)

    # Whole-object replace. Dump back to plain dicts so the JSON column
    # doesn't hold pydantic model state.
    serialised: Dict[str, Dict[str, Any]] = {
        k: b.model_dump(exclude_none=True) for k, b in payload.shortcuts.items()
    }
    current_user.shortcuts = serialised
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    # Return the stored value as the response (NOT merged with defaults) so
    # the client sees exactly what it just set. GET returns the merged view.
    return ShortcutsResponse(shortcuts=dict(serialised))


@router.post(
    "/me/shortcuts/reset",
    response_model=ShortcutsResponse,
    responses={
        200: {"description": "Shortcuts cleared; defaults returned"},
    },
)
def reset_my_shortcuts(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> ShortcutsResponse:
    current_user.shortcuts = None
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return ShortcutsResponse(shortcuts=_merged_with_defaults(None))
