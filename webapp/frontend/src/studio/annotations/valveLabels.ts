/**
 * Valve sub_class label lookup for the palette.
 *
 * Sourced from the generated taxonomy module (taxonomy.generated.ts →
 * DISPLAY_NAME_BY_SUB, from webapp/taxonomy.json) — the single source of truth.
 * Previously this file (and buildElements.ts) kept private hand-maintained
 * copies that had drifted (e.g. DB = "Double Block" here vs "Diaphragm Valve"
 * in buildElements). They now both read the taxonomy so a code always renders
 * the same name everywhere. PalettePanel does `VALVE_SUB_CLASS_LABELS[sub] ?? sub`
 * and only looks up valve codes, so the extra instrument/equipment keys are
 * harmless.
 */
import { DISPLAY_NAME_BY_SUB } from "../taxonomy.generated";

export const VALVE_SUB_CLASS_LABELS: Record<string, string> = DISPLAY_NAME_BY_SUB;
