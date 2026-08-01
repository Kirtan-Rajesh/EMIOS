import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { v1Api } from "@/lib/api";
import type { AuthUser } from "@/types/api";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** Phase 1 (Login): resolves the current user from the httpOnly session
 * cookie on load, and exposes login/register/logout for the rest of the app.
 * The cookie itself (set/cleared by the backend - see app/api/v1/auth.py) is
 * never touched here; this component only tracks the resulting `user` state. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // No way to tell from JS whether the session cookie exists (that's the
    // point of httpOnly) - just ask the backend and treat a 401 as "not
    // logged in" rather than gating on a locally-readable token first.
    v1Api
      .me()
      .then((me) => setUser({ user_id: me.user_id, email: me.email }))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const res = await v1Api.login({ email, password });
    setUser(res.user);
  }

  async function register(email: string, password: string) {
    const res = await v1Api.register({ email, password });
    setUser(res.user);
  }

  async function logout() {
    try {
      await v1Api.logout();
    } catch (err) {
      // A bare try/finally would re-throw here after still clearing user
      // state below - silently skipping whatever the caller does next (e.g.
      // AppShell/SettingsPage's navigate("/login")) on nothing worse than a
      // network hiccup. The user ends up logged out client-side either way
      // (RequireAuth redirects once `user` is null), so this failing is not
      // worth surfacing as an error to the caller - just log it.
      console.error("Logout request failed - clearing local session anyway.", err);
    } finally {
      setUser(null);
    }
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
