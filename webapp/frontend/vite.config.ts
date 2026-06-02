/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy /api/* to the FastAPI backend during development so the SPA
    // and the existing webapp share a single origin in the browser.
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // Auth endpoints live at top-level on the FastAPI backend.
      // The React SPA's sign-in screen is at /signin (not /login) so we
      // can proxy POST /login + GET /logout to FastAPI without conflicting
      // with any React Router route.
      "/login": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/logout": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // /jobs/:id has a URL collision: the SPA's React Router owns the HTML
      // route (Studio at /jobs/:jobId), while FastAPI owns the asset routes
      // (/jobs/:id/tiles/*, /pdf, /download*, /annotated-pdf, /status).
      // In dev both must work behind one origin. The bypass function lets
      // HTML requests fall through to Vite (so React Router gets the route)
      // while images / downloads / poll JSON proxy to FastAPI.
      "/jobs": {
        target: "http://localhost:8000",
        changeOrigin: true,
        bypass: (req) => {
          const accept = String(req.headers.accept || "");
          // Top-level navigation that wants HTML → let Vite serve the SPA.
          if (accept.indexOf("text/html") >= 0) return req.url;
          // Everything else (img, fetch with default Accept, JSON) → proxy.
          return undefined;
        },
      },
      // The Jinja /annotate page (annotator surface) is still backend-served.
      "/annotate": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // Backend-only HTML surfaces that the SPA might link to (e.g. /account
      // dropdown). Proxy so Vite doesn't serve the SPA over them.
      "/account": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  // BUILD_ID is set by the CI / Dockerfile multi-stage frontend at build time
  // (e.g. `BUILD_ID=$(git rev-parse --short HEAD) npm run build`). Falls back
  // to "dev" for local Vite dev server. Used by main.tsx to set
  // window.__QONG_BUILD__ for ops debugging + as a deterministic cache-bust
  // key. Replaces the hand-bumped constant pattern (FEATURES #18 cache-poison
  // workaround); now every CI deploy gets a fresh asset hash automatically.
  define: {
    __BUILD_ID__: JSON.stringify(process.env.BUILD_ID || "dev"),
  },
  // Vitest config — see https://vitest.dev/config/
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
