import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import type { ApiError } from "../lib/api-client";
import { fetchMe, type User } from "../lib/auth-api";
import { useAuthStore } from "../stores/auth-store";

export const authMeQueryKey = ["auth", "me"] as const;

/**
 * Single source of truth for "am I logged in": owns the GET /auth/me
 * query and is the only hook that writes to the Zustand auth store, so the
 * two never disagree. Mounted once at the app root (see App.tsx).
 *
 * Login/logout seed this same query cache entry (`queryClient.setQueryData`)
 * instead of poking the store directly — that keeps this effect the single
 * place authentication state actually changes.
 */
export function useMeQuery() {
  const query = useQuery<User | null, ApiError>({
    queryKey: authMeQueryKey,
    queryFn: fetchMe,
    retry: false,
  });
  const setAuthenticated = useAuthStore((state) => state.setAuthenticated);
  const setUnauthenticated = useAuthStore((state) => state.setUnauthenticated);

  useEffect(() => {
    if (query.data) {
      setAuthenticated(query.data);
    } else if (query.isError || query.data === null) {
      setUnauthenticated();
    }
  }, [query.data, query.isError, setAuthenticated, setUnauthenticated]);

  return query;
}
