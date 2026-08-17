import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";

import { authMeQueryKey } from "../hooks/useMeQuery";
import { logout, type User } from "../lib/auth-api";
import { useAuthStore } from "../stores/auth-store";

// Deliberately empty aside from identity + logout (SoT A8 Phase 1 "빈
// 대시보드" — proves the auth loop end to end, no widgets yet).
function DashboardPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);

  const logoutMutation = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.setQueryData<User | null>(authMeQueryKey, null);
      navigate("/login", { replace: true });
    },
  });

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-950 text-slate-100">
      <p className="text-lg">{user?.email}</p>
      <Link to="/glossary" className="text-sm text-sky-400 hover:underline">
        용어집
      </Link>
      <button
        type="button"
        onClick={() => logoutMutation.mutate()}
        disabled={logoutMutation.isPending}
        className="rounded bg-slate-800 px-4 py-2 text-sm font-medium hover:bg-slate-700 disabled:opacity-50"
      >
        {logoutMutation.isPending ? "로그아웃 중…" : "로그아웃"}
      </button>
    </main>
  );
}

export default DashboardPage;
