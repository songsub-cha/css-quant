import { Navigate, Outlet } from "react-router";

import { useAuthStore } from "../stores/auth-store";

/**
 * Gate for authenticated routes. Reads `auth-store` synchronously (rather
 * than a query hook) because a route guard has to decide what to render
 * during this render pass, not after a refetch resolves.
 */
function ProtectedRoute() {
  const status = useAuthStore((state) => state.status);

  if (status === "checking") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-100">
        <p className="text-sm text-slate-400">확인 중…</p>
      </main>
    );
  }

  if (status === "unauthenticated") {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}

export default ProtectedRoute;
