# REVIEW_UI_SPEC.md

The review UI is core product, not scaffolding. This spec defines what it must do, how it must feel, and what it must capture. If anything in this file conflicts with `PROJECT_VISION.md`, the vision file wins.

## Goals, in priority order

1. **Reach 99% topological correctness on a sheet in under 15 minutes.** Topology — the directed graph of components and their connections — is the deliverable. Symbol cosmetics matter less.
2. **Capture every reviewer action as a training signal** for the corresponding detection model.
3. **Feel responsive on a 4K P&ID** (12000 x 8500 px source resolution) on a mid-range developer laptop.
4. **Be usable for an eight-hour shift** without finger or wrist strain.

## User profile

A drafter or junior process engineer, 25–35 years old, who sits at this UI all day. They are comfortable with CAD-style tools but not with web development. They use a mouse, not a touchpad. They expect keyboard shortcuts to work the way AutoCAD or SolidWorks shortcuts work. They WILL judge the tool harshly if it feels laggy.

## Layout (refer to the mockup)

Three regions:

- **Top bar (44 px):** file name, current sheet position (3 / 24), issue count badge, save button. Auto-save runs every 30 seconds and on every confirmed correction.
- **Canvas (flex, fills remaining width):** the P&ID rendered with detection overlays. Pan with middle-mouse drag, zoom with scroll wheel, fit-to-view with double-click on empty space.
- **Sidebar (244 px fixed):** three stacked panels:
  - Selected element (top) — shows when something is selected, hides cleanly when nothing is.
  - Issues (middle) — sorted by severity, scrollable when over five.
  - Session stats (bottom) — corrected, confirmed, time elapsed.
- **Bottom bar (34 px):** keyboard shortcuts cheat sheet, auto-save indicator.

The canvas takes the visual weight. The sidebar is calm.

## Canvas rendering rules

The canvas is rendered with **Konva** via `react-konva`. Plain SVG and DOM-based approaches do not scale to large P&IDs — they choke at around 1,000 elements. Konva uses the Canvas 2D API and handles up to ~5,000 interactive elements smoothly, which covers oil-and-gas P&IDs by a wide margin (typical 200–3,000, dense 5,000–10,000). Konva's built-in drag, transformer, and hit-detection primitives shorten the build by weeks compared to a WebGL alternative. If we ever see real customer sheets above ~10,000 overlay elements, the migration path is PixiJS — but plan for that day to never come.

Layers, drawn back-to-front:
1. Base raster of the P&ID (the original PDF page rendered to PNG, partitioned into tiles).
2. Symbol bounding boxes (only shown when "show symbols" toggle is on; off by default for less clutter).
3. Detected lines as polyline overlays, color-encoded by confidence.
4. Direction markers (arrowheads on lines that have a detected direction).
5. Junction dots at line endpoints.
6. Validation issue overlays (subtle background tint over the bounding region of an issue).
7. Selection highlight (purple stroke and resize handles).
8. Hover preview (faint outline that follows the cursor).

## Visual encoding (the rules the reviewer will internalize)

| Element | Encoding |
|---|---|
| Process line, high confidence | Teal stroke (#0F6E56), solid, 2 px |
| Process line, low confidence (<0.6) | Amber stroke (#BA7517), solid, 2 px |
| Signal line | Same color rules, but dashed |
| Direction known | Arrowhead at downstream end |
| Direction unknown | No arrowhead. Inline label "direction unsure" with amber color |
| Symbol bbox | Hidden by default. When shown: gray stroke at default confidence, amber stroke when <0.6 |
| Selected element | Purple stroke (#534AB7), 2 px, with corner resize handles |
| Hover element | Thin purple stroke (#7F77DD), 1 px |
| Orphan node | Light red tint over bounding region |
| Issue region | Light amber tint over bounding region, with leader to sidebar issue |

**Never** use color alone to signal meaning. Every color-encoded state also has a textual label in the sidebar or in a hover tooltip. The reviewer may have color vision deficiency.

## Interactions

**Mouse:**
- Left click on element → select
- Left click on empty → deselect
- Click and drag on element → move (only for symbols)
- Click and drag on line endpoint → extend or shrink line
- Right click on element → context menu (confirm, change class, delete, mark as bad detection)
- Middle-mouse drag → pan canvas
- Scroll wheel → zoom around cursor
- Double click empty → fit to view

**Keyboard (all single-key, no modifiers):**

| Key | Action |
|---|---|
| K | Switch to select mode |
| E | Enter edit mode for selected element |
| D | Flip direction of selected line |
| L | Switch to line-draw mode (draw a new line) |
| Space | Confirm current detection as-is, advance to next issue |
| N | Jump to next issue in sidebar |
| P | Jump to previous issue |
| Delete | Delete selected element (with undo) |
| Z (no modifier) | Undo |
| Y | Redo |
| F | Toggle symbol bounding box visibility |
| H | Toggle low-confidence highlighting |
| ? | Show keyboard shortcut overlay |
| Esc | Cancel current action, deselect |

These are the AutoCAD-adjacent muscle memory. Do not rebind them to anything cute.

## Selected-element panel

When an element is selected, the panel shows:
- Tag (e.g. `PV-203`), monospace, bold
- Class pill (e.g. "control valve") with the detector's prediction
- Confidence as a number, two decimals
- Upstream connections (clickable, jump to that element)
- Downstream connections (clickable)
- Confirm button — accepts current detection, logs as positive training sample
- Edit button — opens inline editor for class and tag
- "Mark as bad detection" link — logs as hard negative, deletes from current sheet

The reviewer should be able to do 80% of the work without ever opening the edit dialog. The Confirm button is the most-used key in the UI.

## Issues panel

Issues are sorted by severity (high to low) then by reading order on the sheet (top to bottom, left to right). Each issue is a card:
- Severity strip on the left edge (red 2 px for high, amber 2 px for medium, gray for low)
- Issue title, sentence case
- One-line description
- Clicking the card pans and zooms the canvas to that issue's bounding region

Severity rules:
- **High:** orphan node, broken graph path, cycle in a flow that should be acyclic, missing direction on a process line connected to two pieces of equipment.
- **Medium:** low-confidence symbol, low-confidence tag, signal line crossing a process line with no junction.
- **Low:** symbol bbox slightly off, tag text uncertain by 1–2 characters.

## Performance requirements

| Metric | Target |
|---|---|
| First paint after opening a sheet | < 800 ms |
| Selecting an element to highlight appearing | < 50 ms (must feel instant) |
| Pan at 60 fps with 10,000 overlay elements | yes |
| Zoom at 60 fps | yes |
| Undo / redo | < 100 ms |
| Save and advance to next sheet | < 2 s, including server round trip |

If any of these drop below target, the UI feels broken. They are not optional.

## Data model (what gets captured)

Every correction is a `ReviewEvent` with this shape:

```python
class ReviewEvent(BaseModel):
    event_id: UUID                       # primary key
    sheet_id: UUID                       # which P&ID
    reviewer_id: str                     # who
    timestamp: datetime                  # when
    action: Literal[
        "confirm", "edit_class", "edit_tag",
        "delete", "create", "move", "resize",
        "flip_direction", "connect", "disconnect",
        "mark_bad_detection"
    ]
    target_type: Literal["symbol", "line", "junction", "text", "edge"]
    target_id: UUID                      # which element
    before: dict                         # the model's prediction
    after: dict                          # the reviewer's correction
    confidence_before: float | None      # what the model said
    time_to_action_ms: int               # from element selected to action taken
    keystroke_used: str | None           # which shortcut, if any
```

This shape is final. Adding new actions extends the `action` literal — do not rename existing values. Downstream training pipelines depend on this contract.

## What goes to the active-learning pipeline

Every `ReviewEvent` is also written to a separate, append-only `training_events` table. See `ACTIVE_LEARNING_SPEC.md` for what the trainer does with it.

## Tech stack

- **Renderer:** Konva 9.x via `react-konva`
- **Framework:** React 19 + Vite. Not Inertia, not Laravel — this is a standalone SPA that talks to FastAPI over REST + WebSocket.
- **State:** Zustand for client state, TanStack Query for server state.
- **PDF tiling:** PDF.js to rasterize source PDFs to tiled PNGs server-side on ingestion.
- **WebSocket:** for live status of pipeline jobs and for multi-reviewer awareness (future).
- **Testing:** Vitest for unit, Playwright for end-to-end. End-to-end tests must run against a real P&ID fixture in CI.

## Non-goals for the UI

- We do NOT build collaborative real-time multi-cursor editing in v1.
- We do NOT build a 3D view of the graph in v1.
- We do NOT build mobile or tablet support.
- We do NOT support importing arbitrary CAD formats from the UI. Ingestion happens server-side and the UI never touches raw DWG.
- We do NOT build a public sharing or comment-thread feature.

If a request lands that asks for any of the above, push back as per `CLAUDE.md`.

## Acceptance criteria for v1

The UI ships when a reviewer, with the keyboard shortcuts memorized, can take a freshly-detected sheet from "raw model output" to "topologically correct DEXPI export" in 15 minutes on at least 80% of held-out test sheets. That is the bar. Pretty animations do not count; correction throughput does.
