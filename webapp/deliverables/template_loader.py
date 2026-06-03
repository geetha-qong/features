"""Loads customer template JSON files from disk and caches parsed configs.

Two layers:
1. **JSON on disk** (`customer_templates/<slug>.json`) — canonical, version-controlled.
   `TemplateLoader.load(slug)` parses + caches these.
2. **DB-side overrides** (`CustomerTemplateOverride` rows) — admin-editable
   label / order / hidden state per (slug, deliverable_type, column_key).
   Applied on top of the JSON by `merged_template_dict()` and
   `TemplateLoader.load_merged()`.

Generators that want admin overrides applied (e.g. CSV column headers,
sheet column ordering) should call `load_merged(slug, db)`. The existing
non-DB callers (`load`, `load_with_fallback`) continue to return the
JSON-only `TemplateConfig` untouched — useful in CLI / non-request
contexts where no `Session` is available.
"""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from webapp.deliverables.template import TemplateConfig

if TYPE_CHECKING:  # pragma: no cover — type-only import to avoid circulars
    from sqlalchemy.orm import Session

TEMPLATE_DIR = Path(__file__).parent / "customer_templates"


class TemplateNotFound(KeyError):
    pass


class TemplateLoader:
    def __init__(self, template_dir: Path = TEMPLATE_DIR) -> None:
        self._template_dir = template_dir
        self._cache: Dict[str, TemplateConfig] = {}
        self._raw_cache: Dict[str, Dict[str, Any]] = {}

    def load(self, slug: str) -> TemplateConfig:
        if slug in self._cache:
            return self._cache[slug]
        raw = self._load_raw(slug)
        cfg = TemplateConfig.model_validate(raw)
        self._cache[slug] = cfg
        return cfg

    def load_with_fallback(self, slug: str, fallback: str = "default") -> TemplateConfig:
        try:
            return self.load(slug)
        except TemplateNotFound:
            return self.load(fallback)

    def _load_raw(self, slug: str) -> Dict[str, Any]:
        """Return the parsed JSON as a plain dict (deepcopy each call so callers
        can mutate without poisoning the cache).
        """
        if slug not in self._raw_cache:
            path = self._template_dir / f"{slug}.json"
            if not path.exists():
                raise TemplateNotFound(slug)
            self._raw_cache[slug] = json.loads(path.read_text())
        return deepcopy(self._raw_cache[slug])

    def available_slugs(self) -> List[str]:
        """Filesystem-scan: every `*.json` in the templates dir is a slug."""
        if not self._template_dir.exists():
            return []
        return sorted(p.stem for p in self._template_dir.glob("*.json"))

    def load_merged(
        self,
        slug: str,
        db: "Optional[Session]" = None,
        fallback: str = "default",
    ) -> TemplateConfig:
        """Like `load_with_fallback` but applies admin overrides from the DB.

        If `db is None` (CLI / non-request context) the JSON template is
        returned untouched — `merged_template_dict` enforces the same fallback.
        """
        merged = merged_template_dict(slug, db, loader=self, fallback=fallback)
        return TemplateConfig.model_validate(merged)


def merged_template_dict(
    slug: str,
    db: "Optional[Session]" = None,
    loader: Optional[TemplateLoader] = None,
    fallback: str = "default",
) -> Dict[str, Any]:
    """Return the JSON template for `slug` with DB overrides applied.

    Output shape matches the on-disk JSON exactly (same keys, same column
    dicts) so it round-trips through `TemplateConfig.model_validate`.
    Each column dict additionally carries `is_overridden: bool` so an admin
    UI can render a "Reset" affordance per column.

    Override semantics (per column row in the matching deliverable):
      - `label_override` (not null)  → swap `header`
      - `column_order`   (not null)  → swap `order`
      - `hidden = true`              → drop the column from the merged output

    Reordering rule: columns with an overridden `column_order` sort by that
    value first; columns without overrides retain their original JSON order
    (NULL-last, stable). Then `order` is renormalized to 1..N for cleanliness.
    """
    _loader = loader or TemplateLoader()
    try:
        merged = _loader._load_raw(slug)
    except TemplateNotFound:
        merged = _loader._load_raw(fallback)

    # Pull all overrides for this slug in one query
    override_map: Dict[tuple, Any] = {}
    if db is not None:
        # Local import keeps the module importable in non-DB contexts
        # (e.g. CLI tools that build a TemplateLoader without an engine).
        from webapp.models import CustomerTemplateOverride

        rows = (
            db.query(CustomerTemplateOverride)
            .filter(CustomerTemplateOverride.customer_template_slug == slug)
            .all()
        )
        for row in rows:
            override_map[(row.deliverable_type, row.column_key)] = row

    deliverables = merged.get("deliverables", {}) or {}
    for d_type, d_cfg in deliverables.items():
        cols = d_cfg.get("columns", []) or []
        new_cols: List[Dict[str, Any]] = []
        for original_idx, col in enumerate(cols):
            key = col.get("field")
            row = override_map.get((d_type, key))
            is_overridden = row is not None
            if row is not None:
                if row.hidden:
                    continue  # drop hidden columns from the merged output
                if row.label_override:
                    col["header"] = row.label_override
                if row.column_order is not None:
                    col["order"] = row.column_order
            col["is_overridden"] = is_overridden
            col["_orig_idx"] = original_idx  # tiebreaker for stable sort
            new_cols.append(col)

        # Stable sort by (order, original_idx). Columns whose `order` came
        # from the JSON are unchanged; overridden ones float to the right slot.
        new_cols.sort(key=lambda c: (c.get("order", 1_000_000), c.get("_orig_idx", 0)))

        # Renormalize order to 1..N and strip the bookkeeping field.
        for i, c in enumerate(new_cols, start=1):
            c["order"] = i
            c.pop("_orig_idx", None)

        d_cfg["columns"] = new_cols

    return merged
