import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";

/**
 * Route-level guard. Wraps protected routes (dashboard, projects, jobs,
 * admin/*) so logged-out users never see them — they get bounced to
 * /signin with a `next` query param so we can route back after login.
 *
 * Behavior:
 *   - loading  → render nothing (avoids the brief flash of protected
 *                content while AuthContext.refresh() resolves).
 *   - !user    → <Navigate replace to="/signin?next=<current-path>">
 *   - user     → <Outlet> (renders the child route).
 *
 * Public surfaces (marketing `/`, `/signin`) sit outside this guard.
 */
export default function RequireAuth() {
  const { user, loading } = useAuth();
  const loc = useLocation();

  if (loading) return null;

  if (!user) {
    const next = encodeURIComponent(loc.pathname + loc.search);
    return <Navigate to={`/signin?next=${next}`} replace />;
  }

  return <Outlet />;
}
