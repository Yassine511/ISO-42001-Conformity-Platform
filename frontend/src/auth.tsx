import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api, UNAUTHORIZED_EVENT, type Organization, type SessionInfo, type User } from "./api";

/** M10 session layer. The session itself lives in an httpOnly cookie the JS
    never sees; this context only mirrors WHO is signed in (bootstrapped from
    GET /api/auth/me) so routes can guard and the shell can render the user.
    Any 401 from the API layer fires UNAUTHORIZED_EVENT and drops the mirror,
    which sends RequireAuth back to /login. */

interface AuthContextValue {
  user: User | null;
  organizations: Organization[];
  /** true until the initial /me bootstrap settles — guards must wait. */
  loading: boolean;
  login: (email: string, password: string) => Promise<SessionInfo>;
  signup: (body: {
    email: string;
    password: string;
    display_name: string;
    organization_name: string;
  }) => Promise<SessionInfo>;
  acceptInvitation: (
    token: string,
    body: { password: string; display_name?: string },
  ) => Promise<SessionInfo>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((s) => {
        if (!cancelled) setSession(s);
      })
      .catch(() => {
        // anonymous (or backend unreachable) — the public pages still render
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    const onUnauthorized = () => setSession(null);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => {
      cancelled = true;
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const s = await api.login(email, password);
    setSession(s);
    return s;
  }, []);

  const signup = useCallback(async (body: Parameters<AuthContextValue["signup"]>[0]) => {
    const s = await api.signup(body);
    setSession(s);
    return s;
  }, []);

  const acceptInvitation = useCallback(
    async (token: string, body: { password: string; display_name?: string }) => {
      const s = await api.acceptInvitation(token, body);
      setSession(s);
      return s;
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setSession(null);
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: session?.user ?? null,
      organizations: session?.organizations ?? [],
      loading,
      login,
      signup,
      acceptInvitation,
      logout,
    }),
    [session, loading, login, signup, acceptInvitation, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth doit être utilisé sous <AuthProvider>.");
  return ctx;
}

/** Post-login landing: the user's (first) organization dashboard. */
export function homeOf(organizations: Organization[]): string {
  return organizations.length > 0 ? `/organizations/${organizations[0].id}` : "/";
}

/** Route guard for /organizations/*: waits for the /me bootstrap, then either
    renders or redirects to /login remembering where we were headed. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <p className="p-6 text-sm text-muted-foreground" aria-live="polite">
        Chargement…
      </p>
    );
  }
  if (!user) {
    return <Navigate replace to="/login" state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}
