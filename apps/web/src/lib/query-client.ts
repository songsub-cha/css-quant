import { QueryClient } from "@tanstack/react-query";

// App-wide singleton, provided once in main.tsx. Queries default to no
// retries — auth checks (GET /auth/me) should fail fast to "unauthenticated"
// rather than silently retrying against a 401.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});
