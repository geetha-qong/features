# Adaptive, Project-Aware Engineering Line-Number Parser

**Date:** 2026-06-26
**Status:** Implemented (uncommitted), default-on in the Line List deliverable
**Module:** `line_parser.py` (repo root, pure-stdlib)

## Goal

Parse a complete engineering Line Number into its fields — Nominal Pipe Size,
Service/Fluid code, Line Sequence, Piping Class, Insulation Type — without
assuming a fixed segment layout. The convention is **learned from the current
project's own line numbers** and never reused across projects. Derived fields
are populated only when confident; otherwise left blank (never guessed).

## Rules implemented

1. **Preserve the complete Line No** exactly — parsing only derives fields.
2. **Nominal Pipe Size** = first segment, authoritative when confidently parsed
   (overrides a junk/placeholder explicit `fields.size` like "NOT DEFINED").
3. **Fractional sizes** (`1/2"`, `3/4"`, `1-1/2"`, `2-1/2"`) preserved verbatim
   — the size's own embedded hyphen is peeled before segment splitting, so
   `1/2"` never becomes `2` and the quote is never stripped.
4. **Service/Fluid** = explicit process name from the drawing if present
   (HCL ACID, FEED WATER…), else the first alpha segment between size and seq.
5. **Line Sequence** = digit-dominant segment with the longest digit run
   (`62151035`, `151045B`) — distinguishes a true sequence from a short
   area/unit code (`62`) even in the same line. Project's modal sequence index
   is only a fallback when a line has no digit-dominant segment at all.
6. **Piping Class** = segment immediately after the sequence; parenthesised
   classes (`AC(PFA)`, `BGA(PP)`) kept whole — never split on chars inside
   balanced parens.
7. **Insulation Type** = only a separate trailing segment after the class
   (`-PP`, `-ET`, `-H`); a value inside class parens (`BGA(PP)`) is NOT pulled
   out as insulation.
8. **Adaptive learning** (`learn_convention`): over the current job's lines,
   learns typical segment count + modal sequence index + class/size vocab. Used
   for consistency + confidence gating. Per-job only.
9. **Confidence-based population**: uncertain fields left blank; placeholder
   non-values ("NOT DEFINED", "XXXX", "N/A", "-", …) treated as empty so they
   never override real data.

## Integration

`webapp/deliverables/line_list.py`:
- `_parse_line_no` reimplemented via `line_parser.parse_line`; new
  `_parse_line_full` returns all five fields.
- `generate_line_list` (UI path) + `synthesize_recovered_line_entities`
  (export path) both `learn_convention` from the project's full line set and
  pass it to each parse. Size precedence updated per rule 2; `_real()` filters
  placeholder non-values.

## Verification (zero-API — pure re-parse)

- Gold spec examples: all pass (size/seq/class/insulation incl. `AC(PFA)`,
  `1/2"`, `151045B`-vs-`62`).
- Multi-job audit (jobs 10/11/12/13/24): size parsed 54/54, **0 duplicates**,
  class 39/54 / insulation 13 (remainder correctly blank, not guessed).

## Out of scope / untouched

`extractor.py`/`parser.py` extraction-time parsing (unchanged — this is a
deliverable-layer derivation), Neo4j, graph, `pipeline.py:15`, `detector.py`.
