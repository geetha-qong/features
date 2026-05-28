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
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
