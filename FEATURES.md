# FEATURES — Append-only decision log

> Every meaningful feature, model swap, threshold change, architecture decision, bugfix, experiment, or business decision gets one entry here. **Newest first. Never edit past entries — mark superseded with `SUPERSEDED BY #NN`.** Recording the *reasoning* matters more than the choice.

**Why this file exists:** so we don't repeat ourselves. Every Claude Code session, every team standup, every "why did we decide that?" question — answer is here. Convention adopted from the QS-60 vision pack (see `docs/onboarding/`).

**Format for each entry** (keep under 200 words; long discussions go in `docs/decisions/NN-title.md` and link here):

```
## [YYYY-MM-DD] #NN — <short title, sentence case>

**Type:** feature | model-swap | threshold-tune | architecture | bugfix | experiment | decision | business
**Stage:** ingestion | preprocess | symbols | lines | direction | text | associate | graph | validate | review | export | training | infra | webapp
**Status:** shipped | experimental | reverted | superseded-by-#NN

**Why:** 2–4 sentences. What problem, where the request originated. Origin matters more than description.

**What:** What was built or changed. Files touched. Public interfaces added or modified.

**Result (if measurable):** Numbers, not adjectives.

**Notes:** Weird things next session should know. Hardcoded values that should become config. Dead ends. Links.
```

---

## [2026-05-30] #16 — AWS QA environment provisioned at qa.qongsystems.com (TLS live, app bring-up paused)

**Type:** infra
**Stage:** infra
**Status:** experimental — TLS live, docker compose not yet running

**Why:** `feature/digital-twin` is 14 commits ahead of `dev` (Phase 1–4 SPA cutover, deliverable reorder, admin port, %PDF- magic byte, two design specs). Deploying directly to `dev.qongsystems.com` on GCP risks current customers who use it for valve list extraction. Need a parallel URL to validate the branch end-to-end before promoting. AWS chosen because the team is migrating off GCP — QA also doubles as the AWS-learning lab. Cloud-agnostic shape (no RDS/ECS/ALB) so the pattern transfers cleanly to dev/prod later.

**What:** Single `t3.medium` EC2 (`i-04be6af1fb7929a0c`) in `ap-south-1`, IMDSv2-required, IAM role `may26-ec2-ssm-role`, public IP `43.205.96.86`, 30 GB encrypted root + 50 GB gp3 data EBS (`vol-06bdf1fab12bd2971`) at `/mnt/qong-data`. nginx 1.24 terminates TLS using a Cloudflare Origin Certificate (SAN `qa.qongsystems.com` + `*.qongsystems.com`, valid until 2041). Cloudflare proxy ON, SSL mode Full (strict), nginx allowlist restricts ingress to CF IP ranges only. SG `sg-0ece96660d8ee00bc` opens 443 from anywhere; no public 22 (SSM only). Reuses shared VPC `vpc-0c9453aafa64f6e40` and the existing `may26-ec2-ssm-role` instance profile. SSM Parameter Store namespace `/may26aws/qong-qa/*` for secrets (6 SecureString params, 5 of 6 populated). Specs at `docs/superpowers/specs/2026-05-29-aws-qa-environment-design.md`.

**Result (if measurable):** `https://qa.qongsystems.com/healthz` returns `200 ok` through the full Cloudflare→nginx stack. `/` returns 503 placeholder (docker compose not yet up). Monthly cost: ~$36/mo running, ~$6/mo if stopped.

**Notes:** Bring-up paused mid-session. ONE blocker before docker compose can come up: `/may26aws/qong-qa/openrouter-api-key` still holds the placeholder value `PLACEHOLDER_REPLACE_VIA_CONSOLE`. Once set, PHASE 2 (clone + override compose + render `.env.qa` from SSM + `docker compose up` + swap nginx 503 for `proxy_pass http://127.0.0.1:8000`) runs in ~15 min. EC2 deploy key SHA256 fingerprint `g49BJAfltEoDkdnpokihv7Bt31X6sWF2vsSEfH72rvA` added to `Qong-Systems/qong_product` deploy keys by user. **Origin Certificate private key was pasted in chat — rotate the cert** after end-to-end test passes; blast radius is limited (CF-edge↔origin only, no public CA trust) but best practice is to rotate. AWS account `449901518037` is treated as production per `../../../may26aws/CLAUDE.md` PROD RULES; every mutation in future sessions still needs same-turn user approval. Resource inventory should be appended to `may26aws/CLAUDE.md` once bring-up succeeds so the account-wide registry stays accurate. Full handoff in `SESSION_STATE.md`.

---

## [2026-05-28] #15 — Phase 3: Admin features ported to React with full test coverage

**Type:** feature
**Stage:** webapp
**Status:** shipped (React UI lives alongside legacy Jinja; Jinja deletion deferred to a follow-up after prod SPA deployment)

**Why:** User asked: *"on our main branch, we had created admin login with feature to add new users and approve and give them role. is that converted into new react ui?"* — answer was no, only customer-facing surfaces were ported in Phase 1+2. They then said: *"spin up phase 3, and port with testing and make sure we don't miss old users or projects."* So Phase 3 ports the 6 admin surfaces from Jinja to React, with full E2E + component-test coverage, and verified data continuity (every existing User/Job/Plan/Feedback row surfaces in the new UI).

**What — backend:**
- **`webapp/routers/api_v1_admin.py`** (NEW, 19 endpoints) — JSON API mirroring the legacy Jinja /admin/* forms. Cookie auth via existing `require_super_admin` dep. Endpoints: users CRUD + role/tier/activate/deactivate/grant-credits, dashboard KPIs, credits ledger, feedback list+update, plans list+create+toggle, label-studio list+sync-labels+sync-job. Same SQLAlchemy queries — zero schema changes.
- **`webapp/routers/api_v1.py`** — `/api/v1/account` now returns `id`, `email`, and `role` (was only username/credits/tier). Fixed a real bug surfaced by Playwright A/B test: AuthContext fell back to `data.tier` when `data.role` was missing, treating super_admin as "trial" and 403-ing the admin out of /admin/*. SECURITY: role must come from the server explicitly — never derived from tier or any other client-readable field.
- **`webapp/main.py`** — registers the new api_v1_admin router.

**What — frontend:**
- **`webapp/frontend/src/admin/types.ts`** — TS interfaces for all admin resources.
- **`webapp/frontend/src/admin/api.ts`** — typed fetch helpers for every endpoint. `HttpError` class, opaque-redirect detection for 401 handling, cookie credentials.
- **`webapp/frontend/src/admin/AdminLayout.tsx`** — left rail with 6 admin nav links + role gate (renders 403 page if `user.role !== "super_admin"`).
- **6 surface components:**
  - `AdminUsers.tsx` + `CreateUserModal.tsx` + `EditUserModal.tsx` — list, create, edit (role/tier/activate/deactivate/grant-credits/delete with self-deletion blocked).
  - `AdminDashboard.tsx` — KPI stat-strip (8 cards) + recent transactions table.
  - `AdminFeedback.tsx` — status-filter chips + items list + per-item status dropdown + admin notes. Reuses the iter-2 security fix: only renders an `<a href>` when page_url starts with http(s).
  - `AdminCredits.tsx` — read-only ledger with username search + sign filter (granted/consumed/all).
  - `AdminPlans.tsx` + inline `CreatePlanModal` — list/create/toggle.
  - `AdminLabelStudio.tsx` — completed-jobs table with LS-stats column + sync-job action + global sync-labels action. Banner when LS not configured.
- **`webapp/frontend/src/auth/AuthContext.tsx`** — role now read strictly from `data.role` (never tier).
- **`webapp/frontend/src/routes/Layout.tsx`** — Shield icon in nav for super_admin only, links to /admin.
- **`webapp/frontend/src/App.tsx`** — `/admin/*` nested routes under AdminLayout.

**Tests:**
- **`tests/e2e/test_admin_api.py`** (NEW, 43 tests) — every endpoint × {super_admin success, regular user 403, no auth 303}; business rules (cannot demote/deactivate/delete self, invalid role/tier/amount rejected, feedback filter validation, plan toggle round-trip, LS configured/unconfigured paths). All 43 pass.
- **`tests/unit/test_api_v1.py`** — existing 7 tests still pass (account endpoint shape change is backwards-compatible).
- **Vitest + React Testing Library wired** in `vite.config.ts` (`test:` block) + `src/test/setup.ts` (RTL cleanup + jest-dom). Added devDeps: `vitest`, `@testing-library/{react,jest-dom,user-event}`, `jsdom`.
- **6 component test files** (`src/admin/Admin*.test.tsx`) — 17 tests total covering: table renders, search/filter behaviour, modal opens, API calls fire with correct arguments, error banners, defense-in-depth (`javascript:` page_url not rendered as href).
- Total: 157 backend tests pass, 18 frontend component tests pass (smoke + 6 admin surfaces).

**Result (if measurable):**
- TypeScript build: 0 errors.
- Vite production bundle: 402 KB JS / 79 KB CSS (gzip 115 / 14 KB). +37 KB JS vs Phase 2 (the admin surfaces + lucide icons + Vitest infra in dev).
- A/B verified against legacy Jinja: both admin and seeded alice appear in /admin/users with identical data (role, tier, credits, status); seeded feedback appears with the safe https URL link.

**Notes:**
- **Legacy Jinja /admin/* routes NOT deleted in this commit.** User chose "Delete Jinja routes + templates after the React port is verified" — but verification is currently dev-only. The SPA isn't wired into prod yet (prod still serves Jinja at dev.qongsystems.com). Deleting Jinja now would 404 prod admin access. Plan: prod-deploy the SPA, A/B verify once more, then a separate small commit drops the 6 Jinja templates + the legacy route handlers from `webapp/routers/admin.py`.
- **The `/annotate` route stays** — it's annotator-role (not super_admin) and the Phase 3 port covers only super_admin surfaces. Annotators continue to use the Jinja landing.
- **The role-bug fix in `/api/v1/account`** is *also* relevant for the future deactivate-doesn't-revoke-session security finding noted in the security review. When that fix lands, `get_current_user` will need to check `is_active`; this endpoint's response will then accurately reflect it.
- **Dependency continuity check:** existing `webapp/credits.py:grant()` is reused by the grant-credits endpoint (same ledger row creation as the legacy Jinja). Existing `webapp/label_studio_client.py` helpers (is_configured, get_or_create_project, push_tiles, delete_all_tasks, sync_all_label_configs, get_project_stats) all reused unchanged.
- **Files touched/created:** ~25 files. New: 1 backend router, 1 backend E2E test file, 6 admin React components + 3 modal components, 6 component test files, 1 Vitest setup file, 1 admin scaffolding (types + api + AdminLayout). Modified: `webapp/main.py`, `webapp/routers/api_v1.py`, `webapp/frontend/src/App.tsx`, `webapp/frontend/src/auth/AuthContext.tsx`, `webapp/frontend/src/routes/Layout.tsx`, `webapp/frontend/vite.config.ts`, `webapp/frontend/package.json` (+ lock).

---

## [2026-05-28] #14 — QONG Studio Phase 2b+2c: DatasheetDrawer + BulkReviewScreen

**Type:** feature
**Stage:** webapp
**Status:** shipped

**Why:** Phase 2a (#13) shipped the Studio visual shell with stub buttons for Open Datasheet and Bulk Review. This commit lands the two real surfaces those buttons open, completing the full design loop the user committed to in chat2.md (Studio → drawer → bulk-review → back to studio with element selected + drawer reopened).

**What:**
- **DatasheetDrawer** (`webapp/frontend/src/studio/datasheet/`):
  - `schemas.ts` — 10 per-doc-type field schemas (datasheet, index, narrative, cande, io, valves, lines, equip, loop, tags); `defaultValues()` returns per-element + per-doc-type seed data. `FieldDef` with `w` hint (xs/sm/md/full = 1/2/3/4 grid cols), `extracted` + `conf` for confidence pills.
  - `DocTypeIcon.tsx` — maps icon names (`file-text`, `list-checks`, `scroll-text`, `git-merge`, etc.) to lucide-react components.
  - `DSField.tsx` — single field with locked-vs-input modes, P&ID badge for extracted fields, confidence pill, pencil to unlock for manual override, "Manual" hint for non-extracted empty fields.
  - `DatasheetDrawer.tsx` — full drawer: doc-type picker (swaps schema), Bulk Review pill (count badge), close (Esc + outside-click), title + completion progress, **vertical accordion** sections (sections 0+1 open by default per chat2.md decision to replace horizontal scroll), Save Draft + Export footer. Backdrop blocks the studio behind.
- **BulkReviewScreen** (`webapp/frontend/src/studio/bulk-review/`):
  - `deliverables.ts` — `DELIVERABLES` list (10 docs with done/total counts), `COLUMNS` per-deliverable table column schemas, `DETAIL_GROUPS` per-deliverable right-panel field groups.
  - `buildRows.ts` — 14 demo instruments (PV-203, FT-101, V-101, PT-201, TT-301, LT-401, FV-101, PSV-022, XV-501, P-101, E-104, FT-202, PT-301, TV-204), enriched per-deliverable.
  - `BulkReviewScreen.tsx` — workbench top bar (Back to Studio, breadcrumb, search, Filter, Export, toggleable panel-right), left deliverables nav with completion bars, center table with grid-template-columns reshaping per deliverable + stat strip (Total/Complete/Review/Missing), right detail panel with Open in Studio action.
- **Studio.tsx wiring**:
  - Real `DatasheetDrawer` mounted (no more alert stub).
  - `mode: "studio" | "bulk"` state. When `bulk`, renders `BulkReviewScreen` full-screen.
  - `onBulkReview` closes the drawer and switches to bulk mode (triggered by both the studio top-bar "Bulk Review" button and the drawer's BULK REVIEW pill).
  - `onOpenInStudio(id)` callback from bulk-review: sets `selectedId` to the picked tag, returns to studio mode, and reopens the drawer — matches v3 design behavior verbatim.

**Result (if measurable):**
- TypeScript build clean. Vite bundle 366 KB JS / 79 KB CSS (gzipped 108/14 KB), up from 2a's 331/78 KB.
- Verified the full loop end-to-end with Playwright + a seeded job (Block-18-Crude-Train-2.pdf): Studio → click Open Datasheet → drawer shows Control Valve PV-203 with 14/21 fields (67%) → click BULK REVIEW pill → workbench shows 14 instruments with PV-203 row pre-selected → click FT-101 row → right panel updates → click Open in Studio → studio reopens with FT-101 selected + drawer reopened with Flow Transmitter schema and per-element defaults (Reflux header flow, Differential Pressure 4-20mA HART, P-12-102-CS150 line).

**Notes:**
- **`1fr` column compression on narrow viewport.** In Bulk Review, the "Type" column uses `w: "1fr"` in the datasheet schema but ends up compressed to ~30px on a 1200px viewport because the parent grid's free-space calculation doesn't expand 1fr when other fixed cols sum near the container width. Minor visual bug — not breaking. Likely the bundle's CSS expects a wider viewport (1600+). Easy follow-up: switch `.br-table-wrap` to `overflow-x: auto` and let the table extend; or tighten fixed widths.
- **All bulk-review demo data is canonical to the design** — same 14 base rows from `bulk-review.jsx`, including the `sel: true` flag on PV-203 (selects it on initial load) and `missing: true` flags on LT-401, E-104, PT-301 (which makes Missing count = 3 in the stat strip).
- **DatasheetDrawer uses `useMemo` for defaults** — when element OR docType changes, defaults recompute, then `useEffect([defaults])` resets the form. This is the v3 design's pattern and it works correctly.
- **Backdrop click-to-close + Esc** both wired on the drawer. Bulk Review doesn't have a backdrop (it's a full-screen replacement).
- **`display: contents` on bulk-review rows** — each `.br-row` uses `display: contents` so its children become direct grid items of the parent `.br-table`. That's why selection styling has to be applied to individual cells (via inline style `color: var(--qong-magenta)`) rather than the row container.
- **No backend changes** — both surfaces are pure UI on top of the existing /api/v1/jobs/{job_id} endpoint. Real wiring to per-instrument data (instead of the 14-row demo set) is a separate piece of work (call it Phase 2d) — would need a `/api/v1/jobs/{id}/instruments` endpoint and the pipeline_runner to write canonical.json with per-instrument entries (we already have a `canonical.py` model from Plan A).
- **Files modified vs Phase 2a:** `webapp/frontend/src/studio/Studio.tsx` (drawer + bulk-review wiring) and 6 new files under `studio/datasheet/` + `studio/bulk-review/`. The studio.css from 2a already contains all the styles for the drawer + bulk-review (was the v3 superset).

---

## [2026-05-28] #13 — QONG Studio design bundle Phase 2a: Studio visual shell

**Type:** feature
**Stage:** webapp
**Status:** shipped

**Why:** Phase 1 (#12) shipped Dashboard + Login + theme. User then exported an updated design bundle (`design/qong-studio-v3/`) with the Studio screen polished: "Bulk Review" button added before "Save" in the top bar, "Save & continue" renamed to "Save", Issues panel replaced with "Elements on Sheet" (lists all detected elements with bidirectional canvas-list selection), and the prior horizontal datasheet tabs replaced with a vertical accordion. v3 also adds two new surfaces (DatasheetDrawer rewrite + BulkReviewScreen) but those are Phase 2b/2c. Phase 2a is the Studio visual shell on its own — clicking a tile on the Dashboard opens this Studio.

**What:**
- **Studio component split** under `webapp/frontend/src/studio/`:
  - `types.ts` — Sheet, CanvasElement, SessionEvent, ProjectLike interfaces.
  - `buildSheets.ts` — deterministic sheet generator (8–28 per project, status distribution).
  - `SheetGlyph.tsx` — small SVG glyph for sheet rail thumbnails (theme-aware grid).
  - `PidCanvas.tsx` — center canvas: prototype V-101/FT-101/P-101/PV-203/E-104 elements with edges; pan via mouse drag (3px threshold to distinguish click vs pan), wheel zoom (0.3×–4×), `.canvas-inner.animated` for smooth button-driven transitions; theme-aware colors for fill/stroke/text/grid.
  - `SheetRail.tsx` — left rail: head (Sheets count), search, All/Issues/Pending tabs, sheet-tile list with status badges.
  - `StudioTopBar.tsx` — back btn, QONG mark, project + sheet meta + reviewer slug, issue badge, **Bulk Review** secondary btn (new), **Save** primary btn (was "Save & continue"), `SettingsMenu variant="dark-chrome"`, more-menu (Export I/O / Share / Settings / Exit).
  - `PropertiesPanel.tsx` — Selected Element card (tag, type, confidence bar, inflow/outflow, Confirm/Edit, Open Datasheet) + **Elements on Sheet** list (replaces Issues; bidirectional select with canvas) + This Session activity.
  - `StudioFoot.tsx` — keyboard shortcut bar + auto-save indicator.
  - `Studio.tsx` — orchestrator. Reads `theme` from ThemeContext, locks body scroll while mounted, manages selection/zoom/pan state, stubs Open Datasheet + Bulk Review with alert (Phase 2b/2c).
- **Route wiring** — `routes/JobDetail.tsx` rewritten to fetch `GET /api/v1/jobs/{job_id}` and render Studio. `routes/ReviewCanvas.tsx` collapses to a thin alias re-exporting JobDetail (legacy URL preserved). Old JobDetail placeholder (deliverable download grid) removed — those URLs are still reachable directly via `/api/v1/jobs/{id}/export/{type}/{fmt}` from Plan A.
- **Layout full-bleed routes** — `routes/Layout.tsx` now matches `/jobs/:jobId(/review)?` via regex so the Studio's own header replaces the app-nav. Existing `/` and `/signin` exact matches still apply.
- **Studio CSS** — `webapp/frontend/src/design/studio.css` updated to v3 (2016 → 2507 lines): adds `.element-row`, accordion `.ds-section`, `.bulk-review`, `.studio-top` polish, dark-scope override under `.studio` (drawer shows in dark even when theme is light, per user "in A, background is darkmode, drawer shud also show in dark mode").

**Result (if measurable):**
- TypeScript build clean. Vite bundle 331 KB JS / 78 KB CSS (gzip 99 KB / 14 KB) — up from Phase 1's 309/68 KB.
- Verified visually with a seeded job (Block-18-Crude-Train-2.pdf): three-pane layout, theme-aware studio chrome, sheet rail with 8 mock tiles, pan/zoom canvas with bidirectional selection, properties panel rendering all 5 detected elements with confidence pills.

**Notes:**
- **Phase 2b** (next session): port `datasheet.jsx` (459 LOC, +140 vs v2). Drawer widened to 720px, 4-col grid (`grid-auto-flow: dense`), vertical accordion sections (01 + 02 open by default, rest collapsed), 10 distinct deliverable schemas (each doc-type swaps the field set), Bulk Review pill in drawer header, dark-mode override.
- **Phase 2c** (next session): port `bulk-review.jsx` (466 LOC, new). Full-screen workbench: deliverables nav (10 docs), instrument table with per-deliverable column schema, toggleable right detail panel (default open, `panel-right` button in top bar), "Open in Studio" returns with element selected + drawer reopened.
- **Studio canvas elements are prototype** — V-101, FT-101, P-101, PV-203, E-104 are hardcoded in `PidCanvas.tsx` (DEMO_ELEMENTS export). Real wiring to job detections is a separate piece of work (Phase 2b or later); requires either parsing the existing valve-list CSV or storing detection JSON on Job.
- **Body scroll lock** added in `Studio.tsx` useEffect — Studio is a single-viewport surface, prevents the page from scrolling behind the studio chrome.
- **Datasheet types** that get an "Open Datasheet" button: Control Valve, Flow Transmitter, Block Valve, Centrifugal Pump (set in Studio.tsx). Exchangers and pumps without the magic types don't show the button — matches the design's behavior.
- **`Datasheet Explorations.html`** in v3 bundle (uses `design-canvas.jsx` + `explorations.jsx`) is a SEPARATE bundle — NOT in QONG Studio.html scope. Skipped from Phase 2 entirely; treated as research/mockup material.
- **lucide icons added** vs Phase 1: `arrow-left`, `arrow-up-right`, `chevron-down`, `chevron-up`, `download`, `git-pull-request`, `info`, `layout-grid`, `log-in`, `log-out`, `maximize`, `panel-right`, `pencil`, `radio`, `scan-search`, `settings-2`, `boxes`, `circle-dot`, `filter`, `share-2`, `keyboard`. All present in lucide-react 1.17.0.
- **Production-continuity rule confirmed:** `/jobs/:jobId` (React SPA) now renders Studio. The legacy FastAPI Jinja `/jobs/{id}` HTML route in `webapp/routers/jobs.py:111` is untouched — direct URL access outside the SPA (legacy customers, email links, the dashboard route in `webapp/routers/dashboard.py`) continues to render the old Jinja template. When a user navigates from the new Dashboard tile click, the SPA's `/jobs/:jobId` wins (BrowserRouter handles it before the FastAPI server responds).
- **Files modified:** `webapp/frontend/src/design/studio.css` (v2→v3), `webapp/frontend/src/routes/{JobDetail,ReviewCanvas,Layout}.tsx`, plus new files under `webapp/frontend/src/studio/`. No backend changes (existing `GET /api/v1/jobs/{job_id}` already provided what Studio needs).

---

## [2026-05-28] #12 — QONG Studio design bundle Phase 1: Dashboard + Login + theme system

**Type:** feature
**Stage:** webapp
**Status:** shipped

**Why:** User exported a fresh design bundle from Claude Design (`design/qong-studio-v2/`) covering 4 surfaces (Login, Projects/Dashboard, Studio, Datasheet drawer) plus a Settings popover with light/dark theming. Previous Dashboard.tsx was an "Awaiting design" placeholder. User explicitly asked for projects-as-tiles dashboard now, full design later. Phase 1 ships Dashboard + Login refresh + theming infrastructure; Studio + Datasheet deferred to Phase 2.

**What:**
- **Design tokens unchanged** — existing `webapp/frontend/src/design/tokens.css` was already identical to the bundle's `colors_and_type.css` (full semantic layer for `--fg`, `--surface`, `--border`, both light + dark themes). Only fix: `global.css` no longer hardcodes body bg/color so theme attribute wins.
- **Studio CSS imported** — copied bundle's `app.css` (2016 lines) verbatim to `webapp/frontend/src/design/studio.css`; imported from `global.css`.
- **Theme system** — new `webapp/frontend/src/theme/ThemeContext.tsx` with localStorage persistence (key `qong.theme`), prefers-color-scheme fallback. `App.tsx` wraps router with `<ThemeProvider>`. SettingsMenu in nav lets user toggle.
- **Shared components** — `components/BrandRow.tsx`, `components/SettingsMenu.tsx` (gear icon + iOS-style toggle popover), `components/PidThumb.tsx` (generative SVG P&ID thumbnail per seed).
- **New backend endpoint** — `GET /api/v1/jobs` in `webapp/routers/api_v1.py` returns `{jobs: [{id, name, pid_no, status, valve_count, created_at, owner_username}]}` for the current user (or all jobs for super_admin). Joins User for owner_username — no ORM relationship existed.
- **Dashboard rebuilt** — `routes/Dashboard.tsx` replaces placeholder with full ProjectsPage: stats strip, search + filter chips, sidebar OR grid OR list (layout persisted to localStorage `qong.dashboard.layout`), `ProjectCard`/`ProjectRow` components, empty state, loading state. Wired to `/api/v1/jobs`.
- **CreateProjectModal** — `dashboard/CreateProjectModal.tsx` with name/client/discipline + drag-drop PDF dropzone; uploads via existing `POST /api/v1/jobs` (one job per file, sequentially); ESC closes.
- **Login refreshed** — `routes/Login.tsx` rewritten to use bundle's `.login-screen`/`.login-brand`/`.login-card`/`.extract-viz`/`.airgap-chip` classes instead of inline styles. Keeps existing auth wiring (`useAuth().login()` POST `/login`). Variant A (Split) only; Variant B deferred.
- **Layout nav** — `routes/Layout.tsx` rebuilt to use bundle's `.app-nav`/`.breadcrumbs`/`.icon-btn`/`.nav-actions` classes; includes `<SettingsMenu />` so users can flip theme from any page.

**Result (if measurable):**
- TypeScript build: 0 errors. Bundle: 309 KB JS / 68 KB CSS (gzipped 94 KB JS / 12 KB CSS).
- Curl verification: `GET /api/v1/jobs` returns 200 with `{"jobs": []}` for admin (no jobs in dev DB); `POST /login` → 303; Vite proxy forwards `/api/v1/jobs` correctly.
- 4 of 7 designed surfaces remain placeholders: Studio (Phase 2), Datasheet drawer (Phase 2), Projects route (delegates to Dashboard), Login Variant B (Cinematic — Phase 2 maybe).

**Notes:**
- **Design bundle staged** at `design/qong-studio-v2/` (extracted from gzip tarball at `/tmp/qong-design-bundle/`). Source files: `project/{app.jsx,screens.jsx,studio.jsx,datasheet.jsx,app.css}` + `design-system/`. Keep this folder around — Phase 2 needs `studio.jsx` and `datasheet.jsx`.
- **lucide-react 1.16.0 → 1.17.0** — bumped to get modern icon names (`chevron-right`, `panel-left`, `git-branch`, `cpu`, `zap`, `arrow-up-right`). 1.17.0 is the actual latest on npm (3924 icons) despite the suspicious version number.
- **Vite binds to IPv6 only by default** (`::1`, not `127.0.0.1`). Curl tests must use `http://localhost:5173` (IPv6 resolver hits) or `http://[::1]:5173`. Bit me during smoke test.
- **One Job = one tile** in the Dashboard — no `projects` table added (user confirmed in scoping). When agency MVP needs multi-PID-per-project, that's a separate plan (FK migration, endpoint changes).
- **Body of CreateProjectModal uploads files sequentially**, not in parallel. Simpler error handling; can parallelize when we hit volume.
- **Owner_username via outer join** — Job model has no SQLAlchemy `relationship("User")` defined, so `job.user.username` would NameError. The dashboard endpoint does `db.query(Job, User.username).outerjoin(User)` instead. Worth adding a real relationship if more endpoints need it.
- **Project name maps to original_filename** with `.pdf` stripped; client maps to owner_username. When the projects-table refactor happens, both get proper fields.
- **Files modified:** `webapp/routers/api_v1.py` (+30 lines), `webapp/frontend/src/{design/global.css,design/studio.css (new),theme/ThemeContext.tsx (new),components/{BrandRow,SettingsMenu,PidThumb}.tsx (new),dashboard/{types.ts,ProjectCard,ProjectRow,CreateProjectModal}.tsx (new),routes/{Dashboard,Login,Layout}.tsx,App.tsx}`. Two files inflated (Login from inline-styles to design classes, Dashboard from 15 → 290 LOC); rest are net-new.

---

## [2026-05-28] #11 — Marketing landing page ported into React SPA (Plan B Phase 1 Task 6)

**Type:** feature
**Stage:** webapp
**Status:** shipped

**Why:** Plan B Phase 1 final task. The Home route was a placeholder; the team needed a full marketing-site composition in the SPA so sales/demo links (`/`) show the real brand. Also needed to prove the JSX design-system UI kit (in `design/QONG Design System/ui_kits/marketing-site/`) ports cleanly to TypeScript.

**What:** Created `webapp/frontend/src/marketing/` with 7 files: `Drive.tsx`, `Social.tsx`, `Hero.tsx`, `Sections.tsx` (About, Features, Problems, Process, CoreEngine, Advantages, Sectors, FAQ, CTAStrip), `Footer.tsx`, `MarketingNav.tsx`, `marketing.css`. Replaced `routes/Home.tsx` entirely. Added `/` to `FULL_BLEED_ROUTES` in `Layout.tsx` so the marketing page is edge-to-edge. Commit `41db788`.

**Result (if measurable):** tsc + vite build clean. Bundle size 283 KB JS / 18 KB CSS (grew ~18 KB from marketing components). "Beyond Plant", "Oil & Gas", "Instrument Index" present in the JS bundle.

**Notes:** Drive mockup animates via a `setInterval` — functional, not a real product. CTA buttons link to `/signin` or `mailto:hello@qongsystems.com`. Nav links for About/Careers/Contact do in-page anchor scroll only (not separate routes — those are post-Phase-1 surfaces).

---

## [2026-05-28] #10 — Deliverables subsystem shipped (Valve List / Instrument Index / Equipment List / Datasheet generators + per-customer templates)

**Type:** feature
**Stage:** webapp, export
**Status:** shipped

**Why:** Per `docs/decisions/01-qong-studio-mvp-design.md` Plan A. The MVP
customer experience hinges on four deliverables in per-EPC templates;
this subsystem is the production path for all four.

**What:** `webapp/deliverables/` package — Pydantic canonical schema
(v1.0.0), per-customer JSON template format, generator registry, six
concrete generators (Valve List CSV+XLSX, Instrument Index CSV+XLSX,
Equipment List XLSX, Datasheet XLSX with 11-section IDS structure) and
the `POST /api/v1/jobs/{id}/export/{type}/{format}` endpoint. Three
customer templates landed: default (matches production columns +
TNB-style Instrument Index), ronesans (sheet-name + font overrides),
muk (subsetted columns). Pipeline-side `canonical.json` writing is
intentionally out of scope for this plan — a follow-up plan will wire
the extraction pipeline to emit canonical.json next to valve_list.csv.

**Result:** End-to-end test passes: given a hand-crafted canonical.json
fixture, the endpoint returns valid CSV/XLSX in the expected template
(matching the customer reference files `parser.py:to_csv_dict`,
`TNB-26E009A001_Instrument index R0.pdf`, `23E065AJ01_ASV_IDS.xlsx`).
~56 unit tests + 5 E2E tests, all green.

**Notes:** The customer_template_slug "default" is the fallback; jobs
whose project sets no template still produce a usable deliverable.
Companion entry to #09 (ValveListCSVGenerator) — #10 covers the
remaining 5 generators + the API endpoint + the registry wiring.

---

## [2026-05-28] #09 — ValveListCSVGenerator: stdlib csv.writer, CRLF fixture, self-registers in REGISTRY

**Type:** feature
**Stage:** export
**Status:** shipped

**Why:** Plan `2026-05-27-deliverables-template-engine.md` Task 9 — first concrete deliverable generator to exercise the Generator/REGISTRY/TemplateLoader/field_resolver stack end-to-end. Needed to prove byte-exact output before XLSX variant is added.

**What:** New file `webapp/deliverables/valve_list.py` — `ValveListCSVGenerator(Generator)` filters entities to `entity_class == "valve"`, orders columns by `ColumnDef.order`, writes CRLF CSV via `csv.writer`, self-registers in `REGISTRY` at import time. Fixture `tests/unit/deliverables/fixtures/expected_valve_list_default.csv` (315 bytes, 3 CRLF lines) pinned via Python csv.writer for byte-exact comparison. `.gitattributes` added so git checks out the fixture with `eol=crlf` on all platforms.

**Result:** 4 pytest tests pass: byte-equality fixture, filter-to-valves-only (instrument/equipment rows excluded), trailing-space header preservation, class attrs. Commit `ac2cde8`.

**Notes:** `.gitattributes` `eol=crlf` rule is critical — without it a fresh clone on Linux/Mac would check out LF and the byte-equality test would fail. The `"8""-G-62151004-AC-PP"` double-double-quote is csv-module standard escaping; do not hand-edit that fixture.

---

## [2026-05-27] #08 — Qong Studio MVP scope locked: agency beachhead, 4 deliverables, Aug '26, Level-2 vendor inclusion via separate Laravel portal

**Type:** decision, architecture
**Stage:** infra, webapp
**Status:** shipped (design doc); implementation plan to follow

**Why:** The 9-month phased plan in `docs/onboarding/ARCHITECTURE.md` §5 was written before the MVP shape was sharpened around a beachhead persona and the marketplace revenue model. Brainstorm session 2026-05-27 surfaced: (a) the customer is P&ID-digitization **agencies**, not big-oil or individual engineers; (b) the Datasheet deliverable specifically needs vendor data to be a complete product, which means at least Level-2 vendor inclusion is required for MVP; (c) Omprakash is the team capacity bottleneck — the only way to fit Level-2 in 14 weeks is for Tarunkumar to own the vendor portal as a separate Laravel app, freeing Omprakash to focus on Qong Studio canvas + templates + deliverable generators. Without this scoping, the team would spend 6 months building a maximalist version of what only needs to be focused.

**What:** Wrote `docs/decisions/01-qong-studio-mvp-design.md` — the authoritative MVP spec. Locks four deliverables (Valve List, Instrument Index, Datasheet, Equipment List), per-customer template engine (3-5 hardcoded JSON templates), Qong Studio React/Konva canvas, free-for-design-partners MVP with manual invoicing on paid signups, separate Laravel vendor portal owned by Tarunkumar, vendor data living in Qong's Postgres as single source of truth with Laravel calling Qong's REST API. Explicit deferral list: Line List + topology + Cable Schedule + JB Schedule + Manuals + Cause & Effect + Control Narrative → FLEDGE Oct '27; Stripe + in-house quote management + customer-editable template editor + collaborative review → v1.5 (Q4 '26 / Q1 '27); SSO + on-prem + DGX Spark → post-MVP. Sprint 1 work in QS-48/50/52/54/56/60/62/64/65/66/68 continues unchanged; this design doc tells subsequent sprints what they're building toward.

**Result:** Per-person FTE-week budget now balances: Omprakash 14/14, Geetha 13/14, Swaraj 9/14, Tarunkumar partial-FT. Capacity gap that the brainstorm started with (32 weeks of work on Omprakash) is closed without slipping the Aug '26 target.

**Notes:** Reversible only by formal supersession with a new `docs/decisions/NN-...md` entry — not by drift. Several items intentionally left as open questions in the design doc §8 to resolve in the implementation-plan step (seed vendor list, Laravel build-or-contract call, hosting topology, org-role schema, PaddleOCR upgrade scope, design-partner agency list). FEATURES.md entries #04 (no DEXPI), #03 (Konva), #06 (no GPU queue) all remain load-bearing for this design.

---

## [2026-05-27] #07 — QS-60 vision pack lands in `docs/onboarding/`; root discipline files stay canonical

**Type:** decision, architecture
**Stage:** infra
**Status:** shipped

**Why:** QS-60 (Omprakash onboarding) produced a 10-file "full-project-guide" pack — `PROJECT_VISION.md`, `ARCHITECTURE.md`, `REVIEW_UI_SPEC.md`, `ACTIVE_LEARNING_SPEC.md`, `DATASETS.md`, `REFERENCES.md`, `README.md`, plus its own copies of `CLAUDE.md` / `FEATURES.md` / `SESSION_STATE.md`. Sitting at repo root as `full-project-guide/`, the latter three would silently shadow the live root discipline files during any `Read CLAUDE.md` lookup. Risk: a future session reads the pack's template SESSION_STATE.md (dated 2026-05-25 "initial seed") instead of the real one and wipes the actual handoff. The pack is reference material, not active state.

**What:** Moved 7 vision/spec files from `full-project-guide/` to `docs/onboarding/`. Deleted the 3 conflicting duplicates. Removed empty `full-project-guide/`. Patched `docs/onboarding/README.md` to point new joiners at the live root `CLAUDE.md` instead of its (deleted) sibling. Also: deleted loose root one-offs `intern_jd.html`, `intern_offer_letter.html`, `readfirst.txt`. Committed `ref/` (5.4 MB customer PDFs for the Ronesans/Ebara instrument-index investigation), `patent.md`, and `Dockerfile.{mcp,trainer}` (already wired into `docker-compose.yml`; fresh clones could not build without them). `.gitignore` extended for `/*.pt`, `datasets/**/*.cache`, `annotate/exports/*.zip`.

**Result:** N/A (docs reorg). Repo size unchanged on disk; no large binaries now tracked.

**Notes:** `data_room/` additions (investor HTML pack) left untracked for now — owned by Vrushab, not core eng. `yolov8s.pt` (22 MB base weights) and `annotate/exports/*.zip` (24 MB LS export) intentionally ignored — regenerable. The vision pack still describes the *future* monorepo layout (`pipeline/`, `api/`, `web/`, etc.) which doesn't match today's flat layout — that's expected, it's the north-star doc.

---

## [2026-05-26] #06 — No backend GPU job queue; shared IAM role + per-user IAM users + runs.jsonl

**Type:** architecture, decision
**Stage:** training, infra
**Status:** shipped (rollout in Sprint 1 via QS-48 + QS-52)

**Why:** Training cadence is 1-3 runs/week (manual ad-hoc) growing to weekly automated by Sprint 4. Building a backend queue (REST endpoint + UI + status polling) is ~1-2 weeks of work for no benefit at this volume — there's no real concurrency to coordinate, and AWS spot/on-demand instances don't care about parallel launches.

**What:**
- One shared IAM role `qong-trainer-burst` with EC2 + S3 + SSM permissions
- Four IAM users (`tarunkumar`, `geetha`, `swaraj`, `omprakash`) — each with MFA — assume the shared role
- `s3://qong-training-artifacts/runs.jsonl` is the team-visible log of every training run: `aws_train_burst.sh` appends one line at start (status=running) and one at end (status=success/failed + cost + model artifact). Anyone reads with `aws s3 cp s3://.../runs.jsonl - | jq`.
- CloudTrail provides full per-user audit for free.
- Instance type: **on-demand** g5.xlarge for now (~$1/hr, no termination risk). Switch to spot in Sprint 4 when checkpointing is added.

**Result:** ~3 hours of additional work in Sprint 1 (folded into QS-48 + QS-52 — no new tickets) vs ~1-2 weeks for a real queue. Equivalent visibility for the team via the runs.jsonl log.

**Notes:** Revisit if/when training runs exceed ~5/day AND coordination problems appear (e.g., same experiment launched twice). Probably never at team size 4. The Sprint 4 active-learning loop will use the same shared role + runs.jsonl, so we're not building this twice.

---

## [2026-05-26] #05 — Project Jira (SCRUM) + Confluence wired; Sprint 1 ready

**Type:** infra
**Stage:** infra
**Status:** shipped

**Why:** Need a single board the whole team (lead + 3 interns + CEO as customer-tester) coordinates from. Pure-doc planning doesn't survive a multi-month project.

**What:** Created 8 Jira epics in SCRUM project (project name "QS-Customers"; key will be renamed SCRUM→QS via admin UI), 11 Sprint 1 stories balanced 3/2/3/3 across Tarunkumar/Omprakash/Geetha/Swaraj. Two Confluence pages: full technical plan (SD space) + customer-flow exec summary (Q space).

**Result:** Sprint 1 stories visible at https://qongsystems.atlassian.net/browse/SCRUM-48 ... SCRUM-68. All assignees set with Atlassian account IDs.

**Notes:** Project rename SCRUM→QS pending — admin must do via Project Settings → Details → Key. Old issue links auto-redirect after rename. Vrushab (CEO) is *not* in Jira as a developer; he's the customer-tester from Sprint 3 onwards.

---

## [2026-05-26] #04 — No DEXPI XML export — proprietary deliverables only

**Type:** business decision
**Stage:** export
**Status:** shipped

**Why:** The earlier architecture spec (`full-project-guide/`) treated DEXPI 2.0 as the canonical output format. Strategic reversal: providing a clean industry-standard exit format makes it easy for customers to migrate off our platform. We want lock-in.

**What:** All customer deliverables stay in proprietary CSV / PDF / XLSX. The graph data model + queryable graph stay internal. No `pydexpi` integration. Sprint 15-16 deliverables (BOM, equipment list, loop trace) are derived from the graph but exported in our formats only.

**Notes:** Reversible later if a paying customer specifically demands DEXPI for procurement integration. Document any such request and weigh per-customer.

---

## [2026-05-26] #03 — Frontend stack locked: React 19 + Vite + react-konva + Zustand + TanStack Query

**Type:** architecture
**Stage:** review (UI)
**Status:** shipped

**Why:** Review UI is the product wedge. Spec targets `<800ms first paint, 60fps pan/zoom` on 4K P&IDs — needs a real SPA, not server-rendered templates. Konva chosen over PixiJS because real P&IDs peak at 5K–10K elements (well within Konva's smooth range); PixiJS only wins above 10K and costs 6–8 weeks WebGL ramp-up.

**What:** New directory `webapp/frontend/` will contain the React app. Mounted at `/jobs/{id}/review` via FastAPI static-files. Pydantic-derived TS types from `webapp/schemas/`. Vitest unit tests + Playwright E2E. Stack lifted directly from `full-project-guide/REVIEW_UI_SPEC.md` + decision #03 in `full-project-guide/FEATURES.md`.

**Notes:** Omprakash (sole web dev) owns the entire frontend. Risk: 8-10 week MVP slips to 12 weeks if React learning curve hits hard. Lead pair-programs with him 2hr/week to mitigate + learn alongside.

---

## [2026-05-26] #02 — AWS burst-mode EC2 replaces Windows GPU + Tailscale for training

**Type:** infra
**Stage:** training
**Status:** shipped (rollout in Sprint 1)

**Why:** Windows GPU + Tailscale is a single point of failure with a fragile connection. After v1-9 training run today (multiple hours of Tailscale debugging), the cost-of-fragility is unacceptable for a team that will retrain weekly via active learning.

**What:** AWS account + IAM role `qong-trainer-burst` + S3 bucket `qong-training-artifacts` (ap-south-1 / Mumbai) + EC2 launch template `qong-train-burst` (g5.xlarge spot, ~$0.30/hr, NVIDIA A10G 24GB VRAM, Ubuntu 22.04 + CUDA 12 AMI). New `scripts/aws_train_burst.sh` does spin-up → SCP dataset → SSM-run train_gpu.py → SCP model back → terminate. SSM (not SSH) for instance access — no key management.

**Result (target):** v1-10 retraining completes in 60-90 min for $5-15 per run. Documented in Sprint 1 SCRUM-52.

**Notes:** Windows GPU stays as fallback for 30 days then decommissioned. Tailscale link removed once decommissioning is confirmed.

---

## [2026-05-26] #01 — Digital twin platform project kicked off — human-in-the-loop wedge

**Type:** architecture, business decision
**Stage:** webapp, review, training
**Status:** shipped (planning + Sprint 1 ready)

**Why:** Customer feedback: the current valve-list extraction is good but customers do the work twice — they get a CSV, then manually fix what's missing. They want all deliverables in one sitting: valve list + instrument index + datasheets + future BOM / loop trace / equipment list. End-state: ship as on-premises **Qong Box** appliance once models are good enough.

**What:** Single-product trajectory in same repo. New branch `feature/digital-twin` from `dev`. Existing valve-list flow keeps running for paying customers throughout. 8-10 week MVP across Sprints 1-5 = shadow graph + review UI + active learning loop. Post-MVP Months 3-6 = multi-page + cross-page, pipe tracing + flow direction, new deliverables (BOM, equipment list, loop trace), production switchover from API to graph-derived outputs.

Plan: `/Users/maahedev/.claude/plans/async-soaring-puppy.md` (also in Confluence SD space).

**Notes:** **Auto-improving model loop** is built in Sprint 4 (Weeks 7-8), not Sprint 1. Sprint 1 lands the *plumbing* (ReviewEvent + TrainingEvent schemas + LS migration). Until Sprint 4 ships, model retraining stays manual. Headline metric is graph isomorphism (`networkx.is_isomorphic`) not symbol mAP.
