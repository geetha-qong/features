# Qong Studio — React frontend

React 19 + Vite + TypeScript SPA that consumes the FastAPI backend at
`webapp/` (deliverables subsystem + existing routes).

## Quick start

```bash
cd webapp/frontend
npm install
npm run dev          # Vite dev server on http://localhost:5173
                     # /api/* is proxied to http://localhost:8000 (FastAPI)
```

## Build

```bash
npm run build        # tsc + vite build -> dist/
npm run preview      # serve dist/ locally
```

## Plan B scope

This scaffold is Task 1 of Plan B Phase 1. Upcoming tasks:
- T2: integrate `design/QONG Design System/` (CSS tokens, fonts, assets)
- T3: React Router with placeholder routes
- T4: login screen (pixel-faithful to `design/qong-studio/QONG Studio _standalone_.html`)
- T5: auth API client (talks to existing `webapp/auth.py`)
- T6: marketing landing page (from `design/QONG Design System/ui_kits/marketing-site/`)

## Constraints from the MVP spec

- Existing valve-list customers must keep working — this SPA launches
  alongside the existing Jinja UI, not as a replacement.
- React 19 + Vite is locked per `docs/decisions/01-qong-studio-mvp-design.md`.
- Konva canvas (review interface) is Plan B.2, not this phase.
