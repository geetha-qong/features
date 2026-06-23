import React from "react";
import ReactDOM from "react-dom/client";
import "./design/global.css";
import App from "./App";
import { AuthProvider } from "./auth/AuthContext";

// Build identifier — injected at build time by Vite's `define` from the
// BUILD_ID env var (see vite.config.ts). Set by CI to the short git SHA so
// every deploy yields fresh asset hashes (replaces the hand-bumped constant
// previously used as a Cloudflare cache-poison workaround). Visible in the
// browser console as `window.__QONG_BUILD__` for ops debugging.
declare const __BUILD_ID__: string;
(window as Window & { __QONG_BUILD__?: string }).__QONG_BUILD__ = __BUILD_ID__;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </React.StrictMode>
);
