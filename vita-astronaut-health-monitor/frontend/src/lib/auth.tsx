"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export type UserRole = "astronaut" | "officer" | "doctor" | "chief";
export interface AuthUser { login: string; role: UserRole; name: string; astronaut_id: string | null }
interface LoginResponse extends AuthUser { token: string }
interface AuthContextValue { user: AuthUser | null; ready: boolean; login: (login: string, password: string) => Promise<AuthUser>; logout: () => void }
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = sessionStorage.getItem("errno:auth-token");
    if (!token) {
      void Promise.resolve().then(() => setReady(true));
      return;
    }
    api.get<AuthUser>("/auth/me").then(setUser).catch(() => {
      sessionStorage.removeItem("errno:auth-token");
    }).finally(() => setReady(true));
  }, []);

  const login = useCallback(async (loginName: string, password: string) => {
    const session = await api.post<LoginResponse>("/auth/login", { login: loginName, password });
    queryClient.clear();
    sessionStorage.setItem("errno:auth-token", session.token);
    const identity: AuthUser = { login: session.login, role: session.role, name: session.name, astronaut_id: session.astronaut_id };
    setUser(identity);
    return identity;
  }, [queryClient]);

  const logout = useCallback(() => {
    sessionStorage.removeItem("errno:auth-token");
    setUser(null);
    queryClient.clear();
  }, [queryClient]);

  const value = useMemo(() => ({ user, ready, login, logout }), [user, ready, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

export function roleHome(role: UserRole) {
  return role === "astronaut" ? "/" : role === "officer" ? "/captain" : "/medic";
}
