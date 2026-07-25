import { create } from "zustand";

import type { User } from "../lib/auth-api";

export type AuthStatus = "checking" | "authenticated" | "unauthenticated";

interface AuthState {
  status: AuthStatus;
  user: User | null;
  setAuthenticated: (user: User) => void;
  setUnauthenticated: () => void;
}

/**
 * Derived, client-side view of the server-owned auth state (SoT B5). The
 * source of truth is the TanStack Query cache for GET /auth/me — this store
 * only exists because `ProtectedRoute` needs a value it can read
 * synchronously during render, which a query hook can't provide mid-render.
 * Only `useMeQuery` (src/hooks/useMeQuery.ts) calls these setters, so the
 * store never drifts from the query cache it mirrors.
 */
export const useAuthStore = create<AuthState>((set) => ({
  status: "checking",
  user: null,
  setAuthenticated: (user) => set({ status: "authenticated", user }),
  setUnauthenticated: () => set({ status: "unauthenticated", user: null }),
}));
