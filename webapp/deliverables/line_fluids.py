"""Drawing-scoped fluid/phase propagation for the Line List.

The Vision pass only sets fluid_type (and the phase derived from it) when a
flow-continuation banner is physically visible for a pipe. Interior lines, or
lines whose banner wasn't captured, are left blank ("-") by the strict EPC rule.

This helper raises coverage WITHOUT inventing data: within a single P&ID it
looks at which fluid names were actually observed (from banners) for each
fluid-code letter, and applies the dominant observed (fluid, phase) pair to
other lines on the same drawing that share the letter but have no fluid.

It is evidence-based and noise-tolerant:
  * Observations are counted per DISTINCT line number, not per valve, so several
    valves on one line don't over-count, and one mislabeled valve can't swing a
    letter on its own.
  * A letter resolves to a fluid only when that fluid holds a clear majority
    (>= 60%) of the distinct lines that carried a banner for the letter. A
    genuinely split letter (no clear winner) is left untouched.
  * Blank fields are only ever FILLED, never overwritten — a banner-extracted
    value always wins.

Applied at read time (entities API) and at export time (line_list generators)
so the UI and the downloaded deliverable always agree. Never persisted to
canonical.json — the source of truth stays exactly what the pipeline extracted.
"""

from collections import Counter
from typing import Dict, List, Tuple

_MAJORITY = 0.6  # fraction of distinct banner-carrying lines a fluid must hold


def _norm(value) -> str:
    return (str(value).strip() if value else "")


def propagate_line_fluids(entities: List) -> None:
    """Fill blank fluid_type/phase on valve entities in-place via drawing-scoped
    evidence. Mutates `entity.fields` dicts; returns nothing.

    `entities` is a list of CanonicalEntity (must expose `.entity_class`,
    `.pid_number`, and a mutable `.fields` dict).
    """
    # (pid, code) -> Counter of observed fluids, weighted by distinct line.
    # Guard against double-counting valves on the same line with a seen-set.
    fluid_votes: Dict[Tuple[str, str], Counter] = {}
    seen_line: set = set()
    # (pid, code, fluid) -> a representative phase observed with that fluid
    phase_for: Dict[Tuple[str, str, str], str] = {}

    for e in entities:
        if getattr(e, "entity_class", None) != "valve":
            continue
        fields = getattr(e, "fields", None)
        if not isinstance(fields, dict):
            continue
        code = _norm(fields.get("fluid_code")).upper()
        fluid = _norm(fields.get("fluid_type"))
        if not code or not fluid:
            continue
        pid = getattr(e, "pid_number", "") or ""
        line = _norm(fields.get("line"))
        dedup = (pid, code, fluid, line)
        if line and dedup in seen_line:
            continue
        seen_line.add(dedup)
        fluid_votes.setdefault((pid, code), Counter())[fluid] += 1
        phase = _norm(fields.get("phase"))
        if phase:
            phase_for.setdefault((pid, code, fluid), phase)

    # Resolve each letter to its dominant fluid when there's a clear majority.
    resolved: Dict[Tuple[str, str], str] = {}
    for key, votes in fluid_votes.items():
        total = sum(votes.values())
        fluid, count = votes.most_common(1)[0]
        if total and count / total >= _MAJORITY:
            resolved[key] = fluid
    if not resolved:
        return

    for e in entities:
        if getattr(e, "entity_class", None) != "valve":
            continue
        fields = getattr(e, "fields", None)
        if not isinstance(fields, dict):
            continue
        if _norm(fields.get("fluid_type")):
            continue  # already has a banner-extracted fluid — never overwrite
        pid = getattr(e, "pid_number", "") or ""
        code = _norm(fields.get("fluid_code")).upper()
        fluid = resolved.get((pid, code))
        if not fluid:
            continue
        fields["fluid_type"] = fluid
        if not _norm(fields.get("phase")):
            ph = phase_for.get((pid, code, fluid))
            if ph:
                fields["phase"] = ph
