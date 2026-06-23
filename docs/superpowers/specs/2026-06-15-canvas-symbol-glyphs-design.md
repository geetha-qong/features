# Canvas symbol glyphs — replace detection rectangles with P&ID symbols

**Date:** 2026-06-15
**Status:** design approved, pre-implementation
**Track:** team / dev

## Problem

On the Studio canvas, model detections and user-marked symbols render as plain
SVG `<rect>` boxes. The 37 real P&ID glyphs (`PidSymbol`) and the class→glyph
mapping already exist but are only used in the palette and the side panel —
never on the canvas. Reviewers want to see the actual symbol on the drawing
(like the palette), color-coded per class the way Label Studio colors labels.

## Scope

**In scope (new work, frontend-only):**
- Render the real `PidSymbol` glyph on the canvas for (a) model detections and
  (b) user-marked symbols, replacing the plain rectangles.
- Color each glyph by its palette class color (multi-color, LS-style), from a
  shared color map reused by palette + canvas + sidebar.

**Out of scope (already built — verify only, do not rebuild):**
- Auto-detect (YOLO v1-11 → `Job.gpu_detections`).
- Manual marking ("Mark Symbol" drag-to-create → `user_annotations`).
- Connections ("Draw Edge" 2-click + snap → `graph_corrections`, reload via
  `GET /jobs/{id}/edges`, graph merge auto+user).
- DB persistence for marks and edges.
- We will **verify** the connect→save→reload loop live on dev as acceptance.

**Explicitly deferred:** PR #1 ("Qong studio updated features", swaraj) overlaps
`PidCanvas`/`Studio`/`buildElements`/`PropertiesPanel`. It will be rebased onto
the post-glyph `dev` by its author; we do not merge it here.

## Approved design decisions

1. **Placement:** glyph drawn at the detection's bbox in page coordinates —
   overlays the real symbol and scales with zoom (tiny at fit, clear zoomed).
2. **Color = class:** glyph stroke uses the palette color for its class
   (multi-color, like Label Studio), from a shared map.
3. **Model vs manual:** model-detected glyphs use a **solid** outline,
   manually-added ones a **dashed** outline (both in the class color).
4. **Selection:** pink highlight box around the glyph (unchanged behavior).
5. **Clickability:** an invisible `<rect>` over the bbox stays the click target,
   preserving `onSelect` and the padded hit-area.

## Architecture / components

### 1. Shared color map (new module)
`webapp/frontend/src/studio/paletteColors.ts`
- Extract the per-sub-class color table currently inline in
  `annotations/PalettePanel.tsx` (e.g. `BV #86D8C4`, `BF #FF6B6B`,
  `FT #E5CBA0`, `Pump #8CCC76`).
- Exports `colorForClass(entityClass: string, subClass?: string): string`
  (with a sensible per-category fallback for unmapped values).
- `PalettePanel` is refactored to import from here (single source of truth).

### 2. Positioned glyph wrapper
`webapp/frontend/src/studio/PidSymbol.tsx`
- Add `PidGlyphAt({ kind, x, y, w, h, color, dashed })` that renders the
  existing glyph inside a nested `<svg x y width height viewBox="0 0 30 26"
  preserveAspectRatio="xMidYMid meet">`, so it drops into the page-coordinate
  SVG and scales with zoom automatically. `color` sets `stroke`/`currentColor`;
  `dashed` toggles `stroke-dasharray`.
- Keep existing `PidSymbol` API (palette/side-panel) untouched.

### 3. Class → glyph kind
- **User annotations:** carry `entity_class` + `sub_class` → existing
  `subClassToSymKind(entity_class, sub_class)`.
- **Model detections:** carry raw YOLO `label` (e.g. `valve_bf`, `inst_field`,
  `Motor`, `arrow_up`) which already aligns with `PidSymbol` kinds. Add
  `labelToSymKind(label)` (normalize cases like `Pump/Dwg Pump` → `pump`),
  falling back to `valve_gen` / a neutral box for unmapped labels.
- **No backend/API change:** the data needed is already on the wire (model =
  `label`; user = `entity_class`+`sub_class`).

### 4. Canvas render (PidCanvas.tsx)
- **Layer 1 (model detections, ~L783):** per detection render
  `<g>`: invisible hit-`<rect>` (click target) + `PidGlyphAt` (class color,
  solid) + existing label text/collision logic + pink box when selected.
- **Layer 2 (user annotations, ~L836):** same, but glyph dashed; color from
  `colorForClass(entity_class, sub_class)`.
- Keep the existing label rendering + collision-avoidance.
- Unmapped/zero-glyph elements fall back to the current `<rect>` so nothing
  silently disappears.

## Data flow

YOLO/`gpu_detections` → `DetectionItem.label` → `labelToSymKind` → glyph kind →
`PidGlyphAt` at `pageBbox` (already computed from `natural` dims). User marks →
`user_annotations.{entity_class,sub_class,bbox}` → `subClassToSymKind` +
`colorForClass` → dashed glyph. No persistence change; reload path unchanged.

## Testing

- **Unit (vitest):** `labelToSymKind` (known labels + fallback); `colorForClass`
  (known class + fallback); a render test asserting a detection produces a glyph
  (`<svg>`/path) not a bare `<rect>`, and that a user annotation renders dashed.
- **Live on dev (Playwright):** detections show colored glyphs; zoom stays
  crisp; click still selects; draw a connection + reload → it persists
  (verifies the existing edge pipeline end-to-end).

## Tradeoffs / residual

- **Tiny at fit:** with scale-with-zoom, glyphs are small at fit-view (they sit
  on the equally-small real symbols); labels stay visible to keep the page
  readable. Follow-up if needed: a minimum on-screen glyph size.
- **Perf:** ~100s of inline-SVG glyphs per page is fine; if a page ever has
  1000s, consider virtualizing to the viewport. Not addressed now.
