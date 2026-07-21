import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, type PropsWithChildren } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { identityService } from "../../contexts/identity/application/services";
import type { Principal } from "../../contexts/identity/domain/models";

type AuthValue = {
  user: Principal | null;
  loading: boolean;
  refresh: () => Promise<unknown>;
  logout: () => Promise<void>;
  adminCapabilities: Set<string>;
  can: (code: string) => boolean;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["auth", "me"],
    queryFn: identityService.currentPrincipal,
    retry: false,
    staleTime: 30_000,
  });
  const capabilityQuery = useQuery({
    queryKey: ["auth", "admin-capabilities"],
    queryFn: identityService.adminCapabilities,
    enabled: Boolean(query.data?.user),
    retry: false,
    staleTime: 30_000,
  });
  const adminCapabilities = new Set(capabilityQuery.data?.capabilities ?? []);
  const platformAdmin = query.data?.user.roles.includes("platform-admin") ?? false;
  useEffect(() => {
    const expire = () => queryClient.setQueryData(["auth", "me"], null);
    window.addEventListener("enterprise-agent:unauthorized", expire);
    return () => window.removeEventListener("enterprise-agent:unauthorized", expire);
  }, [queryClient]);

  return (
    <AuthContext.Provider
      value={{
        user: query.data?.user ?? null,
        loading: query.isLoading,
        refresh: query.refetch,
        logout: async () => {
          await identityService.logout();
          queryClient.clear();
        },
        adminCapabilities,
        can: (code: string) => platformAdmin || adminCapabilities.has(code),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is missing");
  return value;
}

export function ProtectedRoute({ children }: PropsWithChildren) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="app-loading">正在恢复安全会话…</div>;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return children;
}
