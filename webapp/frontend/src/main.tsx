import React from "react";
import ReactDOM from "react-dom/client";
import "./design/global.css";
import App from "./App";
import { AuthProvider } from "./auth/AuthContext";

// Build identifier — bumped by hand when we need to force a fresh Vite
// content hash (e.g. Cloudflare has cached a wrong response under the
// previous hash and we need new asset URLs). Survives JS minification
// because it's a side-effect assignment, not a comment. Visible in the
// browser console as `window.__QONG_BUILD__` for ops debugging.
(window as Window & { __QONG_BUILD__?: string }).__QONG_BUILD__ = "2026-06-01T12:20Z";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </React.StrictMode>
);
