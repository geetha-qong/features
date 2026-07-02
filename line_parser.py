"""Adaptive, project-aware engineering Line Number parser.

Parses a complete engineering line number into its fields (nominal pipe size,
service/fluid code, line sequence number, piping class, insulation type)
WITHOUT assuming a fixed segment layout. The convention is LEARNED from all the
line numbers in the *current* project/drawing — never carried across projects.

Hard rules (from spec 2026-06-26):
  * Preserve the complete Line No exactly as shown — parsing is derivation only.
  * Fractional sizes (1/2", 3/4", 1-1/2", 2-1/2") preserved verbatim; never
    turn 1/2" into 2, never strip the quote.
  * Parenthesised piping classes (AC(PFA), BGA(PP)) stay intact — never split
    on characters inside balanced parentheses, and do NOT treat a value inside
    the class parens as a separate Insulation Type.
  * Insulation Type only when it is a separate trailing segment after the class.
  * Confidence-based: leave a derived field BLANK rather than guess. Never
    invent fluid / piping class / insulation / material.

Pure-stdlib (re only) so it imports without the web stack and is unit-testable
on the host. No OCR, no API calls, no detector import.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional

# Leading nominal-pipe-size token. Ordered alternation so the fractional forms
# that EMBED a hyphen (1-1/2") are matched before a bare integer, otherwise the
# size's own hyphen would be mistaken for a segment separator.
#   20"   1/2"   3/4"   1-1/2"   2-1/2"   300 (mm, no quote)
_SIZE_RE = re.compile(r'^\s*(\d+-\d+/\d+"?|\d+/\d+"?|\d+")|^\s*(\d+)(?=-)')

# A segment that is the line SEQUENCE number: digit-dominant, optional trailing
# letter(s) — 62151035, 151045B, 62151007.
_SEQ_RE = re.compile(r'^\d{2,}[A-Z]{0,2}$', re.IGNORECASE)

# A "size-only" leading check used when validating a token is purely a size.
_SIZE_ONLY_RE = re.compile(r'^(\d+-\d+/\d+|\d+/\d+|\d+)"?$')


def _peel_size(line_no: str) -> tuple:
    """Return (size_token, remainder) preserving the exact size notation.

    Handles fractional sizes whose own hyphen (1-1/2") must not be treated as a
    segment break. ``size_token`` is "" if the line doesn't start with a size.
    """
    s = line_no.strip()
    m = _SIZE_RE.match(s)
    if not m:
        return "", s
    size = (m.group(1) or m.group(2) or "").strip()
    rest = s[m.end():]
    # Drop the single separating hyphen after the size, if present.
    if rest.startswith("-"):
        rest = rest[1:]
    return size, rest


def tokenize(line_no: str) -> List[str]:
    """Split a line number into segments. The leading size (incl. fractional)
    is peeled first; the remainder is split on '-' ONLY at paren depth 0 so
    AC(PFA) / BGA(PP) stay whole."""
    size, rest = _peel_size(line_no)
    segs: List[str] = []
    if size:
        segs.append(size)
    if not rest:
        return segs
    depth = 0
    cur = ""
    for ch in rest:
        if ch == "(":
            depth += 1
            cur += ch
        elif ch == ")":
            depth = max(0, depth - 1)
            cur += ch
        elif ch == "-" and depth == 0:
            segs.append(cur)
            cur = ""
        else:
            cur += ch
    segs.append(cur)
    return [s for s in segs if s != ""]


def _seq_index(segs: List[str]) -> int:
    """Index of the line-sequence segment: the digit-dominant segment with the
    longest digit run. -1 if none. Segment 0 (size) is excluded."""
    best_idx = -1
    best_digits = 0
    for i in range(1, len(segs)):
        seg = segs[i]
        if _SEQ_RE.match(seg):
            digits = sum(c.isdigit() for c in seg)
            if digits > best_digits:
                best_digits = digits
                best_idx = i
    return best_idx


def learn_convention(line_numbers: List[str]) -> Dict[str, Any]:
    """Analyse all line numbers in the CURRENT project and learn the most
    consistent layout: the typical segment count and the typical (modal) index
    of the sequence segment. Used to parse consistently and to gate confidence.
    """
    seg_counts: Counter = Counter()
    seq_indices: Counter = Counter()
    sizes: set = set()
    classes: set = set()
    n = 0
    for ln in line_numbers or []:
        if not (ln and isinstance(ln, str) and "-" in ln):
            continue
        segs = tokenize(ln)
        if len(segs) < 3:
            continue
        n += 1
        seg_counts[len(segs)] += 1
        si = _seq_index(segs)
        if si >= 0:
            seq_indices[si] += 1
            if si + 1 < len(segs):
                classes.add(segs[si + 1])
        if segs and _SIZE_ONLY_RE.match(segs[0]):
            sizes.add(segs[0])
    typical_seg_count = seg_counts.most_common(1)[0][0] if seg_counts else 0
    modal_seq_index = seq_indices.most_common(1)[0][0] if seq_indices else -1
    # consistency = how dominant the modal sequence index is across the project.
    consistency = (seq_indices.most_common(1)[0][1] / n) if (n and seq_indices) else 0.0
    return {
        "sample_size": n,
        "typical_seg_count": typical_seg_count,
        "modal_seq_index": modal_seq_index,
        "seq_index_consistency": round(consistency, 2),
        "class_vocab": classes,
        "size_vocab": sizes,
    }


def parse_line(line_no: str,
               convention: Optional[Dict[str, Any]] = None,
               explicit_service: Optional[str] = None) -> Dict[str, Any]:
    """Parse one line number into derived fields per the (optional) learned
    convention. Returns dict with the complete line preserved plus derived
    fields; uncertain fields are left "" (never guessed)."""
    out: Dict[str, Any] = {
        "line": line_no,           # complete, exactly as given (rule 1)
        "size": "",
        "fluid_code": "",
        "sequence": "",
        "piping_class": "",
        "insulation_type": "",
        "_low_confidence": [],     # fields we declined to populate confidently
    }
    if not (line_no and isinstance(line_no, str)):
        return out
    segs = tokenize(line_no)
    if not segs:
        return out

    # ── Size (rule 2 + fractional preservation) ────────────────────────────
    if _SIZE_ONLY_RE.match(segs[0]):
        out["size"] = segs[0]            # exact notation, quotes & fractions kept
    else:
        out["_low_confidence"].append("size")

    # ── Sequence (adaptive) ────────────────────────────────────────────────
    # The longest digit run is authoritative — it correctly distinguishes a
    # true sequence (151045B) from a short numeric area/unit code (62) even when
    # they share a line. The project's modal index only fills in when this line
    # has NO digit-dominant segment at all (e.g. all-placeholder XXXX lines),
    # never overriding a clear local winner.
    seq_idx = _seq_index(segs)
    if seq_idx < 0 and convention and convention.get("modal_seq_index", -1) >= 0:
        mi = convention["modal_seq_index"]
        if 0 <= mi < len(segs) and _SEQ_RE.match(segs[mi]):
            seq_idx = mi
    if seq_idx >= 0:
        out["sequence"] = segs[seq_idx]
    else:
        out["_low_confidence"].append("sequence")

    # ── Fluid / service code ───────────────────────────────────────────────
    # Explicit process/service name from the drawing wins (rule: HCL ACID, etc.)
    if explicit_service and explicit_service.strip():
        out["fluid_code"] = explicit_service.strip()
    else:
        # Otherwise the service code = first alpha segment between size & seq.
        end = seq_idx if seq_idx > 0 else len(segs)
        svc = ""
        for i in range(1, end):
            if re.match(r'^[A-Za-z][A-Za-z0-9]*$', segs[i]):
                svc = segs[i]
                break
        out["fluid_code"] = svc
        if not svc:
            out["_low_confidence"].append("fluid_code")

    # ── Piping class = segment immediately AFTER the sequence ──────────────
    if seq_idx >= 0 and seq_idx + 1 < len(segs):
        out["piping_class"] = segs[seq_idx + 1]   # AC(PFA)/BGA(PP) kept whole
        # ── Insulation = a SEPARATE trailing segment after the class ───────
        if seq_idx + 2 < len(segs):
            out["insulation_type"] = segs[seq_idx + 2]
        # If the class carries parens (BGA(PP)) we deliberately do NOT pull a
        # value out of it as insulation (spec rule).
    else:
        out["_low_confidence"].append("piping_class")

    return out


if __name__ == "__main__":  # pragma: no cover — quick manual check
    import json
    samples = [
        '1/2"-CL-62-DB-151045B-ASE',
        '20"-W-62151007-AC(PFA)-H',
        '2"-P-62151035-BEA-PP',
        '4"-P-62151019-BGA-ET',
        '50-ABL-XXXX-AS2LC',
    ]
    conv = learn_convention(samples)
    print("convention:", json.dumps({k: (sorted(v) if isinstance(v, set) else v)
                                      for k, v in conv.items()}))
    for s in samples:
        print(s, "->", json.dumps(parse_line(s, conv)))
