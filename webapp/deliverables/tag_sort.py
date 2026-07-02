"""ISA-5.1 instrument tag sort utilities.

Shared sort key used by:
  webapp/routers/entities.py          (GET /entities response order)
  webapp/deliverables/instrument_index.py  (CSV + XLSX row order)

Sort order:
  Primary   — natural-numeric tag number (area + sequence), so "FT-2" < "FT-10"
  Secondary — ISA function-suffix rank within the same loop/area
"""
import re
from typing import Tuple

# Ordered list of ISA function suffixes — list index IS the sort rank.
# "W" is index 0 but only ranks there for variable letter "T" (Thermowell).
_SUFFIX_ORDERED = [
    "W",    # Thermowell — T-variable only, see _suffix_rank()
    "E",    # Element
    "G",    # Gauge
    "T",    # Transmitter
    "I",    # Indicator
    "DIT",  # Differential Indicating Transmitter
    "IT",   # Indicating Transmitter
    "AH",   # Alarm High
    "AHH",  # Alarm High-High
    "AL",   # Alarm Low
    "ALL",  # Alarm Low-Low
]
_SUFFIX_RANK: dict = {s: i for i, s in enumerate(_SUFFIX_ORDERED)}
_UNKNOWN_RANK: int = len(_SUFFIX_ORDERED)  # unrecognised suffixes sort last


def _natural_parts(s: str) -> Tuple:
    """Split into ((type, value), ...) pairs for safe numeric-aware comparison.

    Each chunk is represented as (0, int) for digit runs or (1, str) for
    non-digit runs.  This prevents TypeError when Python compares a purely
    numeric tag segment (e.g. "6072A" → (0, 6072), ...) against a segment
    that starts with a letter (e.g. "X2014A" → (1, 'x'), ...) — without the
    type flag those would produce `'x' < 6072` which raises TypeError.

    Ensures "FT-2" < "FT-10" (numeric-aware), not the lexicographic reverse.
    """
    return tuple(
        (0, int(tok)) if tok.isdigit() else (1, tok.lower())
        for tok in re.split(r"(\d+)", s)
        if tok
    )


def _parse_isa_code(code: str) -> Tuple[str, str]:
    """Split ISA type code into (variable_letter, function_suffix).

    "FT"   → ("F", "T")
    "PDIT" → ("P", "DIT")
    "TW"   → ("T", "W")
    "P"    → ("P", "")
    """
    if not code:
        return "", ""
    return code[0].upper(), code[1:].upper()


def _suffix_rank(variable: str, suffix: str) -> int:
    """Return sort rank for (variable, suffix).

    Thermowell exception: "W" ranks 0 (first) only when variable == "T".
    For any other variable letter, "W" is unrecognised and sorts last.
    """
    if suffix == "W":
        return _SUFFIX_RANK["W"] if variable == "T" else _UNKNOWN_RANK
    return _SUFFIX_RANK.get(suffix, _UNKNOWN_RANK)


def tag_sort_key(tag) -> Tuple:
    """Composite sort key for a full instrument/valve tag string.

    Handles two common ISA tag formats:
      3-part  "{area}-{TYPE}-{seq}"  e.g. "62-FT-001"
      2-part  "{TYPE}-{seq}"         e.g. "FT-2"

    Returns (area_natural_key, seq_natural_key, function_suffix_rank).

    Examples of resulting order within the same loop:
      PG → PT → PDIT → PAH → PALL
      TW → TE → TG → TT → TI → TIT → TAL → TALL
      FE → FT → FAHH
    """
    if not tag:
        # Sentinel: flag=2 is greater than both numeric (0) and string (1) chunks,
        # so None/empty tags always sort after every real tag.
        return (((2,),), ((2,),), _UNKNOWN_RANK)

    parts = tag.strip().split("-")

    if len(parts) == 1:
        return (_natural_parts(tag), (), _UNKNOWN_RANK)
    elif len(parts) == 2:
        area_key: Tuple = ()
        type_code = parts[0]
        seq_key = _natural_parts(parts[1])
    else:
        area_key = _natural_parts(parts[0])
        type_code = parts[1]
        seq_key = _natural_parts("-".join(parts[2:]))

    variable, suffix = _parse_isa_code(type_code)
    return (area_key, seq_key, _suffix_rank(variable, suffix))
