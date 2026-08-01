import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/lib/auth-context";

/** Route guard for everything except /login - redirects unauthenticated
 * visitors to the login page (Phase 1). */
export function RequireAuth() {
  const { user, loading } = useAuth();

  if (loading) {
    return <div className="p-8 text-center text-sm text-muted-foreground">Loading...</div>;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}
