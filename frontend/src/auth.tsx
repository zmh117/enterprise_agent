import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, type PropsWithChildren } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { api } from "./lib/api";
import type { Principal } from "./lib/types";

type AuthValue = {
  user: Principal | null;
  loading: boolean;
  refresh: () => Promise<unknown>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api<{ user: Principal }>("/api/auth/me"),
    retry: false,
    staleTime: 30_000,
  });

  return (
    <AuthContext.Provider
      value={{
        user: query.data?.user ?? null,
        loading: query.isLoading,
        refresh: query.refetch,
        logout: async () => {
          await api("/api/auth/logout", { method: "POST" });
          queryClient.clear();
        },
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
