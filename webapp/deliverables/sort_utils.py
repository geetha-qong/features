"""Shared sort key for the instrument-index loop sequence (ISA function ladder).

Process engineers read an instrument index by **loop number** (the tag's numeric
part), and within each loop by the **ISA function ladder** (sensing element first,
alarms / final elements last). Validated with the user against the real job-43
(28 instruments) and job-55 (18) sets — see FEATURES #117.

Sort key (ascending): ``(area, loop_number, loop_suffix, function_rank,
alarm_rank, tag)``

- ``area`` = leading digits of the tag; ``loop_number``/``loop_suffix`` come from
  the last ``-`` segment (``62-PDIT-151025`` -> loop 151025; ``61-FIC-00099A`` ->
  loop 99, suffix "A" so parallel A/B trains group together).
- ``function_rank`` is keyed on the ISA **type code** — the first all-alphabetic
  ``-`` segment of the tag (``62-FE-151010`` -> ``FE``; ``422-11-PT-006A`` -> ``PT``).

Function ladder (first → last), on the code's function letters (the code minus
its leading measured-variable letter). Classification checks run in an order
that routes combined codes correctly (T before C before I, so ``FIT``→transmitter
and ``FIC``→controller):

    TW (thermowell — temperature only)
    → E element → G gauge → T transmitter family → I indicator → C controller
    → A alarm (suffix order H, HH, L, LL)
    → final element (valve V / computing relay Y) → switch (S) → other

The public signature ``instrument_sort_key(tag: str) -> Tuple`` is unchanged, so
the existing callers (``instrument_index.py`` generators, ``entities.py`` row
sort) pick up this ordering automatically.
"""

import re
from typing import Tuple

_ALARM_SUFFIX_ORDER = {"H": 0, "HH": 1, "L": 2, "LL": 3}

_BUCKET_RANK = {
    "thermowell": 0,
    "element": 1,
    "gauge": 2,
    "transmitter": 3,
    "indicator": 4,
    "controller": 5,
    "alarm": 6,
    "final_element": 7,
    "switch": 8,
    "other": 9,
}

_BIG = 10 ** 12  # tags with no parseable loop number / area sort to the end


def _extract_code(tag: str) -> str:
    """First all-alphabetic ``-`` segment — the ISA type code.

    ``62-FE-151010`` -> ``FE``; ``422-11-PT-006A`` -> ``PT``; ``61-PG-XXXXX`` ->
    ``PG`` (the ``XXXXX`` loop placeholder is a later segment). ``''`` if none.
    """
    for seg in (tag or "").split("-"):
        if seg.isalpha():
            return seg.upper()
    return ""


def classify(code: str) -> Tuple[str, str]:
    """``(bucket, alarm_suffix)`` for an ISA type code.

    First letter = measured variable; remainder = function/modifier letters.
    """
    code = (code or "").upper()
    if not code:
        return ("other", "")
    var, rem = code[0], code[1:]
    if var == "T" and rem == "W":
        return ("thermowell", "")
    if "T" in rem:
        return ("transmitter", "")
    if "C" in rem:
        return ("controller", "")
    if "V" in rem or "Y" in rem:
        return ("final_element", "")
    if "S" in rem:
        return ("switch", "")
    if "A" in rem:
        m = re.search(r"A(HH|LL|H|L)?", rem)
        return ("alarm", m.group(1) if m and m.group(1) else "")
    if "E" in rem:
        return ("element", "")
    if "G" in rem:
        return ("gauge", "")
    if "I" in rem:
        return ("indicator", "")
    return ("other", "")


def _function_rank(code: str) -> Tuple[int, int]:
    bucket, suffix = classify(code)
    return (_BUCKET_RANK[bucket], _ALARM_SUFFIX_ORDER.get(suffix, 0))


def instrument_sort_key(tag: str) -> Tuple:
    """Loop-sequence sort key for an instrument tag.

    Stable for unparseable / blank tags (they sort to the end via the sentinel
    area/loop, then by the raw tag string).
    """
    tag = tag or ""
    segs = tag.split("-")
    area_m = re.match(r"(\d+)", tag)
    area = int(area_m.group(1)) if area_m else _BIG
    last = segs[-1] if segs else ""
    loop_m = re.match(r"(\d+)", last)
    loop_number = int(loop_m.group(1)) if loop_m else _BIG
    loop_suffix = last[loop_m.end():] if loop_m else last
    frank, arank = _function_rank(_extract_code(tag))
    return (area, loop_number, loop_suffix, frank, arank, tag)
