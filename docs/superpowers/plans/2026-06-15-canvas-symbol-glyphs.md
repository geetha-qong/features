# Canvas Symbol Glyphs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the plain detection/annotation rectangles on the Studio canvas with the real P&ID symbol glyphs, colored per class like Label Studio (model = solid outline, manual = dashed), reusing the palette's existing colors.

**Architecture:** Frontend-only. Extract the palette's per-class color table into a shared module; add a positioned glyph wrapper + a YOLO-label→glyph-kind mapper to `PidSymbol.tsx`; render glyphs in `PidCanvas.tsx` Layers 1 (model) and 2 (user) with an invisible hit-rect + class-colored solid/dashed outline + pink select box. Glyphs already honor `currentColor`, so coloring = setting `color` on the wrapper. No backend/API/DB change.

**Tech Stack:** React + TypeScript, inline SVG, Vitest. Type-check `npx tsc --noEmit`, tests `npx vitest run`, both from `webapp/frontend/`.

---

## File Structure

- **Create** `webapp/frontend/src/studio/paletteColors.ts` — single source of truth for per-class colors; `colorForSubClass()` + `colorForKind()`.
- **Modify** `webapp/frontend/src/studio/annotations/PalettePanel.tsx` — import colors from the new module (remove the inline color duplication).
- **Modify** `webapp/frontend/src/studio/PidSymbol.tsx` — add `labelToSymKind()` (YOLO label → glyph kind) and `PidGlyphAt` (positioned, color-aware wrapper).
- **Modify** `webapp/frontend/src/studio/PidCanvas.tsx` — Layer 1 (~L783) and Layer 2 (~L836): render glyphs instead of bare rects.
- **Tests** `webapp/frontend/src/studio/__tests__/paletteColors.test.ts`, `__tests__/glyphMapping.test.ts`.

Tasks 1 and 2 are independent (disjoint files) → can run in parallel. Task 3 depends on 1+2. Task 4 is live verification.

---

## Task 1: Shared palette color module

**Files:**
- Create: `webapp/frontend/src/studio/paletteColors.ts`
- Modify: `webapp/frontend/src/studio/annotations/PalettePanel.tsx` (read its existing color table first; it lists `{ sub, key?, color }` per category — Valves, Instruments, Equipment, etc.)
- Test: `webapp/frontend/src/studio/__tests__/paletteColors.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// __tests__/paletteColors.test.ts
import { describe, it, expect } from "vitest";
import { colorForSubClass, colorForKind, NEUTRAL_COLOR } from "../paletteColors";

describe("paletteColors", () => {
  it("returns the palette color for a known sub-class", () => {
    expect(colorForSubClass("valve", "BV")).toBe("#86D8C4");
    expect(colorForSubClass("valve", "BF")).toBe("#FF6B6B");
    expect(colorForSubClass("instrument", "FT")).toBe("#E5CBA0");
  });
  it("falls back to a neutral color for unknown sub-class", () => {
    expect(colorForSubClass("valve", "ZZZ")).toBe(NEUTRAL_COLOR);
    expect(colorForSubClass(undefined, undefined)).toBe(NEUTRAL_COLOR);
  });
  it("maps a glyph kind to the same palette color", () => {
    // valve_bv shares BV's color; inst_field shares an instrument color
    expect(colorForKind("valve_bv")).toBe("#86D8C4");
    expect(colorForKind("valve_bf")).toBe("#FF6B6B");
  });
  it("falls back to neutral for an unknown kind", () => {
    expect(colorForKind("totally_unknown")).toBe(NEUTRAL_COLOR);
  });
});
```

- [ ] **Step 2: Run the test, verify it fails** — `npx vitest run src/studio/__tests__/paletteColors.test.ts` → FAIL (module not found).

- [ ] **Step 3: Implement `paletteColors.ts`**

Read the existing color table in `annotations/PalettePanel.tsx` and MOVE it here verbatim (same sub codes + hex). Shape:

```ts
import { subClassToSymKind } from "./PidSymbol";

export const NEUTRAL_COLOR = "#9498AE";

export interface PaletteEntry { sub: string; label?: string; key?: string; color: string; }

// MOVED from PalettePanel.tsx — keep the exact entries/hex. Group by entity_class.
export const PALETTE: Record<string, PaletteEntry[]> = {
  valve: [
    { sub: "BV", key: "2", color: "#86D8C4" },
    { sub: "BF", key: "1", color: "#FF6B6B" },
    { sub: "GT", key: "s", color: "#7EC9C2" },
    // ... (copy ALL remaining valve entries from PalettePanel)
  ],
  instrument: [
    { sub: "FT", label: "Flow Tx", key: "8", color: "#E5CBA0" },
    // ... (copy ALL remaining instrument entries)
  ],
  equipment: [
    { sub: "Pump", label: "Pump", key: "e", color: "#8CCC76" },
    // ... (copy remaining)
  ],
  // ...any other categories present in PalettePanel
};

const SUB_INDEX = new Map<string, string>(); // "valve|BV" -> hex
for (const [cls, entries] of Object.entries(PALETTE))
  for (const e of entries) SUB_INDEX.set(`${cls}|${e.sub}`, e.color);

export function colorForSubClass(entityClass?: string, sub?: string): string {
  if (!entityClass || !sub) return NEUTRAL_COLOR;
  return SUB_INDEX.get(`${entityClass}|${sub}`) ?? NEUTRAL_COLOR;
}

// Derive kind -> color by running each palette sub through the shared mapper.
const KIND_INDEX = new Map<string, string>();
for (const [cls, entries] of Object.entries(PALETTE))
  for (const e of entries) {
    const kind = subClassToSymKind(cls, e.sub);
    if (!KIND_INDEX.has(kind)) KIND_INDEX.set(kind, e.color);
  }

export function colorForKind(kind?: string): string {
  if (!kind) return NEUTRAL_COLOR;
  return KIND_INDEX.get(kind) ?? NEUTRAL_COLOR;
}
```

> Note: if `subClassToSymKind("valve","BV")` returns `"valve_bv"`, the `colorForKind("valve_bv")` test passes. If the mapper's output differs, adjust the test's expected kind to match the real mapper output (verify by reading `subClassToSymKind`).

- [ ] **Step 4: Refactor `PalettePanel.tsx`** to import `PALETTE`/colors from `paletteColors.ts` instead of its inline table. Keep the rendered output identical (same colors/hotkeys). Run `npx tsc --noEmit` → clean.

- [ ] **Step 5: Run tests** — `npx vitest run src/studio/__tests__/paletteColors.test.ts` → PASS. Run full `npx vitest run` → all green.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(studio): shared palette color map (paletteColors.ts), reused by palette"`

---

## Task 2: `labelToSymKind` + `PidGlyphAt` in PidSymbol.tsx

**Files:**
- Modify: `webapp/frontend/src/studio/PidSymbol.tsx`
- Test: `webapp/frontend/src/studio/__tests__/glyphMapping.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// __tests__/glyphMapping.test.ts
import { describe, it, expect } from "vitest";
import { labelToSymKind } from "../PidSymbol";

describe("labelToSymKind (YOLO label -> glyph kind)", () => {
  it("passes through labels that already are glyph kinds", () => {
    expect(labelToSymKind("valve_bf")).toBe("valve_bf");
    expect(labelToSymKind("inst_field")).toBe("inst_field");
    expect(labelToSymKind("arrow_up")).toBe("arrow_up");
    expect(labelToSymKind("Motor")).toBe("Motor");
  });
  it("normalizes the slash/space pump label", () => {
    expect(labelToSymKind("Pump/Dwg Pump")).toBe("pump");
  });
  it("falls back to valve_gen for unknown labels", () => {
    expect(labelToSymKind("nonsense_label")).toBe("valve_gen");
    expect(labelToSymKind(undefined)).toBe("valve_gen");
  });
});
```

- [ ] **Step 2: Run, verify fail** — `npx vitest run src/studio/__tests__/glyphMapping.test.ts` → FAIL (no export).

- [ ] **Step 3: Implement in `PidSymbol.tsx`.** The 23 YOLO class names already line up with glyph kinds (see `CLASS_NAMES` in `webapp/inference.py` / the exporter). Add the set of valid kinds + the mapper. Use the existing list of `kind`s that `glyphBody` handles.

```ts
// Kinds glyphBody() knows how to draw (keep in sync with glyphBody's switch).
const KNOWN_KINDS = new Set<string>([
  "valve_gen","valve_gt","valve_bf","valve_bv","valve_ncbv","valve_db","valve_ck",
  "valve_gl","valve_cv","valve_pneuctrl","valve_relief_safety","valve_3way",
  "valve_3way_relief","valve_needle","valve_transfer","valve_reflex_gt",
  "inst_field","inst_field-R","inst_local_panel","inst_bpcs","inst_sis",
  "DCS","PLC","interlock","interlock-R","SIS-R","Motor","pump","lamp",
  "lamp_local_mounted","arrow_right","arrow_left","arrow_up","arrow_down",
  "connector_in","connector_out","connector_io",
]);

const LABEL_ALIASES: Record<string, string> = {
  "Pump/Dwg Pump": "pump",
  "Pump": "pump",
};

export function labelToSymKind(label?: string): string {
  if (!label) return "valve_gen";
  if (LABEL_ALIASES[label]) return LABEL_ALIASES[label];
  if (KNOWN_KINDS.has(label)) return label;
  return "valve_gen";
}
```

- [ ] **Step 4: Add `PidGlyphAt`** — a positioned, color-aware wrapper that drops into the page-coordinate SVG and scales with zoom. It nests the existing `PidSymbol` inside an outer `<svg>` placed at the bbox, and sets `color` (glyphs use `currentColor`). Append to `PidSymbol.tsx`:

```tsx
export function PidGlyphAt({
  kind, x, y, w, h, color,
}: { kind: string; x: number; y: number; w: number; h: number; color: string }) {
  return (
    <svg
      x={x} y={y} width={w} height={h}
      viewBox="0 0 30 26" preserveAspectRatio="xMidYMid meet"
      style={{ color, overflow: "visible", pointerEvents: "none" }}
      aria-hidden="true"
    >
      <PidSymbol kind={kind} />
    </svg>
  );
}
```

> A nested `<svg>` with `x/y/width/height` positions in the parent SVG's user units, so it lives in page-pixel space and scales with the canvas zoom automatically. `color` cascades into the glyph's `currentColor` strokes/fills.

- [ ] **Step 5: Run tests** — `npx vitest run src/studio/__tests__/glyphMapping.test.ts` → PASS. `npx tsc --noEmit` → clean.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(studio): labelToSymKind + PidGlyphAt positioned glyph wrapper"`

---

## Task 3: Render glyphs on the canvas (PidCanvas.tsx)

**Depends on Tasks 1 & 2.**

**Files:**
- Modify: `webapp/frontend/src/studio/PidCanvas.tsx` (Layer 1 ~L783 model detections; Layer 2 ~L836 user annotations)

- [ ] **Step 1: Imports** — add to PidCanvas:
```ts
import { PidGlyphAt, labelToSymKind, subClassToSymKind } from "./PidSymbol";
import { colorForKind, colorForSubClass } from "./paletteColors";
```

- [ ] **Step 2: Layer 1 (model detections).** Inside the existing `pageDetections.map(...)` (where `[x1,y1,x2,y2] = d.pageBbox`), REPLACE the single `<rect>` (the visible detection box, ~L784) with this group. Keep the existing label-text + collision logic below it unchanged.

```tsx
const kind = labelToSymKind(d.label);
const klass = colorForKind(kind);
const w = x2 - x1, h = y2 - y1;
return (
  <g key={`det-${i}`}>
    {/* class-colored glyph, scales with zoom */}
    <PidGlyphAt kind={kind} x={x1} y={y1} w={w} h={h} color={klass} />
    {/* model = solid thin outline in the class color */}
    <rect
      x={x1} y={y1} width={w} height={h}
      fill="none" stroke={klass}
      vectorEffect="non-scaling-stroke" strokeWidth={isSelected ? 2.5 : 1}
      opacity={isSelected ? 1 : 0.6}
    />
    {/* invisible hit-target preserves click/select */}
    <rect
      x={x1} y={y1} width={w} height={h} fill="transparent"
      style={{ pointerEvents: clickable && mode === "select" ? "auto" : "none",
               cursor: clickable && mode === "select" ? "pointer" : cursor }}
      onClick={clickable && mode === "select"
        ? (ev) => { ev.stopPropagation(); onSelect(d.entity_id as string, d.entity_class); }
        : undefined}
    />
    {/* selection highlight box (pink) */}
    {isSelected && (
      <rect x={x1} y={y1} width={w} height={h} fill="rgba(255,77,168,0.12)"
            stroke="#FF4DA8" vectorEffect="non-scaling-stroke" strokeWidth={2.5} />
    )}
    {/* ...keep the existing label <text> block here unchanged... */}
  </g>
);
```

- [ ] **Step 3: Layer 2 (user annotations).** Same pattern, but kind/color from the annotation's class and a **dashed** outline:
```tsx
const kind = subClassToSymKind(a.entity_class, a.sub_class);
const klass = colorForSubClass(a.entity_class, a.sub_class);
// glyph + invisible hit-rect + select box identical to Layer 1, EXCEPT the
// status outline is dashed (manual):
<rect x={x1} y={y1} width={w} height={h} fill="none" stroke={klass}
      strokeDasharray="4 3" vectorEffect="non-scaling-stroke"
      strokeWidth={isSelected ? 2.5 : 1} opacity={isSelected ? 1 : 0.7} />
```
Keep the existing Layer-2 label text + status logic. (Read the current Layer-2 code to match its variable names — it may use `d`/`a`; preserve them.)

- [ ] **Step 4: Fallback** — if `kind` resolves to `valve_gen` AND the original label was unmapped, that's acceptable (generic valve). Do NOT remove the bare-rect path for graph-node-only items; only Layers 1 & 2 change.

- [ ] **Step 5: Type-check + tests** — `npx tsc --noEmit` → clean; `npx vitest run` → all green (existing PidCanvas-related tests must still pass).

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(studio): render P&ID glyphs on canvas (class color; solid=model, dashed=manual)"`

---

## Task 4: Verify on dev (live)

- [ ] **Step 1:** Confirm no active cpu-worker job on dev (deploy kills running jobs). Push `dev` → wait for deploy (bundle hash change).
- [ ] **Step 2 (Playwright on dev, job 1):** detections now render colored glyphs (not bare rects); zoom in → glyphs crisp + scale; multiple classes show distinct colors; clicking a glyph still selects (sidebar updates).
- [ ] **Step 3 (verify existing connect→save loop):** switch to Draw-Edge, connect two elements, reload the page → the edge persists (proves `graph_corrections` round-trip). Screenshot.
- [ ] **Step 4:** Close browser. Append FEATURES entry (#45) summarizing the glyph rendering + that connections/save were verified (already existed).
