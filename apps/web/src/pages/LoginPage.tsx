import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router";
import { z } from "zod";

import { authMeQueryKey } from "../hooks/useMeQuery";
import { login, type User } from "../lib/auth-api";

const loginSchema = z.object({
  email: z.string().min(1, "이메일을 입력하세요.").email("올바른 이메일 주소를 입력하세요."),
  password: z.string().min(1, "비밀번호를 입력하세요."),
});

type LoginFormValues = z.infer<typeof loginSchema>;

function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
  });

  const loginMutation = useMutation({
    mutationFn: (values: LoginFormValues) => login(values.email, values.password),
    onSuccess: (user) => {
      // Seeds the same cache entry useMeQuery owns, so its effect (the only
      // place the auth store is written) picks this up without a refetch.
      queryClient.setQueryData<User | null>(authMeQueryKey, user);
      navigate("/", { replace: true });
    },
  });

  const onSubmit = (values: LoginFormValues) => {
    loginMutation.reset();
    loginMutation.mutate(values);
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-100">
      <form
        onSubmit={(event) => void handleSubmit(onSubmit)(event)}
        noValidate
        className="w-full max-w-sm space-y-4 rounded-lg border border-slate-800 bg-slate-900 p-8"
      >
        <h1 className="text-xl font-semibold">QuantPilot 로그인</h1>

        <div className="space-y-1">
          <label htmlFor="email" className="block text-sm text-slate-300">
            이메일
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            {...register("email")}
          />
          {errors.email && <p className="text-sm text-red-400">{errors.email.message}</p>}
        </div>

        <div className="space-y-1">
          <label htmlFor="password" className="block text-sm text-slate-300">
            비밀번호
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            {...register("password")}
          />
          {errors.password && <p className="text-sm text-red-400">{errors.password.message}</p>}
        </div>

        {loginMutation.isError && (
          <p className="text-sm text-red-400">{loginMutation.error.message}</p>
        )}

        <button
          type="submit"
          disabled={loginMutation.isPending}
          className="w-full rounded bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          {loginMutation.isPending ? "로그인 중…" : "로그인"}
        </button>
      </form>
    </main>
  );
}

export default LoginPage;
