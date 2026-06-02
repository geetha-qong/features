import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

/**
 * Root `/` route — there is no public marketing page on this instance.
 * The qongsystems.com marketing site is hosted separately. Here `/` just
 * funnels visitors to the right place: active session → /dashboard, anon →
 * /signin. While the auth context is still resolving on first paint, render
 * nothing (the redirect runs as soon as the boolean settles).
 */
export default function RootRedirect() {
  const { user, loading } = useAuth();
  if (loading) return null;
  return <Navigate to={user ? "/dashboard" : "/signin"} replace />;
}
