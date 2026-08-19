import { useState } from "react";
import { Link, useNavigate } from "react-router";

import {
  useActivateStrategyMutation,
  useArchiveStrategyMutation,
  useCloneStrategyMutation,
  useCreateStrategyMutation,
  useDeleteStrategyMutation,
  usePauseStrategyMutation,
  useStrategiesQuery,
  useStrategyTemplatesQuery,
} from "../hooks/useStrategyQuery";
import type { ExecutionMode, StrategyStatus } from "../lib/strategy-api";

const STATUS_LABELS: Record<StrategyStatus, string> = {
  draft: "초안",
  active: "활성",
  paused: "일시정지",
  archived: "보관",
};

const EXECUTION_MODE_LABELS: Record<ExecutionMode, string> = {
  backtest: "백테스트",
  paper: "모의투자",
  live_approval: "실거래(승인)",
  live_auto: "실거래(자동)",
};

const EXECUTION_MODE_OPTIONS: ExecutionMode[] = ["backtest", "paper", "live_approval", "live_auto"];

const FILTERS: { value: StrategyStatus | ""; label: string }[] = [
  { value: "", label: "전체" },
  { value: "draft", label: "초안" },
  { value: "active", label: "활성" },
  { value: "paused", label: "일시정지" },
  { value: "archived", label: "보관" },
];

function StrategyListPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<StrategyStatus | "">("");
  const [blankName, setBlankName] = useState("");
  const [blankExecutionMode, setBlankExecutionMode] = useState<ExecutionMode>("backtest");

  const { data: strategies, isLoading } = useStrategiesQuery({ status: status || undefined });
  const { data: templates } = useStrategyTemplatesQuery();

  const createMutation = useCreateStrategyMutation();
  const cloneMutation = useCloneStrategyMutation();
  const activateMutation = useActivateStrategyMutation();
  const pauseMutation = usePauseStrategyMutation();
  const archiveMutation = useArchiveStrategyMutation();
  const deleteMutation = useDeleteStrategyMutation();

  const actionError =
    (deleteMutation.isError && deleteMutation.error.message) ||
    (cloneMutation.isError && cloneMutation.error.message) ||
    (activateMutation.isError && activateMutation.error.message) ||
    (pauseMutation.isError && pauseMutation.error.message) ||
    (archiveMutation.isError && archiveMutation.error.message) ||
    (createMutation.isError && createMutation.error.message) ||
    null;

  const isRowActionPending = (id: string) =>
    (cloneMutation.isPending && cloneMutation.variables === id) ||
    (activateMutation.isPending && activateMutation.variables === id) ||
    (pauseMutation.isPending && pauseMutation.variables === id) ||
    (archiveMutation.isPending && archiveMutation.variables === id) ||
    (deleteMutation.isPending && deleteMutation.variables === id);

  function createFromTemplate(templateKey: string) {
    const template = templates?.find((t) => t.key === templateKey);
    if (!template) return;
    createMutation.mutate(
      { name: template.name, execution_mode: "backtest", config: template.config },
      { onSuccess: (strategy) => navigate(`/strategies/${strategy.id}`) },
    );
  }

  function createBlankStrategy() {
    if (!blankName.trim()) return;
    createMutation.mutate(
      { name: blankName.trim(), execution_mode: blankExecutionMode },
      { onSuccess: (strategy) => navigate(`/strategies/${strategy.id}`) },
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 p-6 text-slate-100">
      <div className="mx-auto max-w-4xl space-y-6">
        <h1 className="text-xl font-semibold">전략</h1>

        {actionError && <p className="text-sm text-red-400">{actionError}</p>}

        <section className="space-y-3">
          <h2 className="text-sm font-medium text-slate-300">새 전략 만들기</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {templates?.map((template) => (
              <div
                key={template.key}
                className="rounded border border-slate-800 bg-slate-900/50 p-4"
              >
                <p className="font-medium">{template.name}</p>
                <p className="mt-1 text-sm text-slate-400">{template.description}</p>
                <button
                  type="button"
                  onClick={() => createFromTemplate(template.key)}
                  disabled={createMutation.isPending}
                  className="mt-3 rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
                >
                  이 템플릿으로 생성
                </button>
              </div>
            ))}

            <div className="rounded border border-dashed border-slate-700 bg-slate-900/30 p-4">
              <p className="font-medium">빈 전략에서 시작</p>
              <div className="mt-3 space-y-2">
                <input
                  type="text"
                  placeholder="전략 이름"
                  value={blankName}
                  onChange={(e) => setBlankName(e.target.value)}
                  className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-100"
                />
                <select
                  value={blankExecutionMode}
                  onChange={(e) => setBlankExecutionMode(e.target.value as ExecutionMode)}
                  className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-100"
                >
                  {EXECUTION_MODE_OPTIONS.map((mode) => (
                    <option key={mode} value={mode}>
                      {EXECUTION_MODE_LABELS[mode]}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={createBlankStrategy}
                  disabled={createMutation.isPending || !blankName.trim()}
                  className="w-full rounded bg-slate-800 px-3 py-1.5 text-sm font-medium hover:bg-slate-700 disabled:opacity-50"
                >
                  빈 전략 생성
                </button>
              </div>
            </div>
          </div>
        </section>

        <section className="space-y-3">
          <div className="flex gap-2">
            {FILTERS.map((filter) => (
              <button
                key={filter.value || "all"}
                type="button"
                onClick={() => setStatus(filter.value)}
                className={`rounded border px-3 py-1.5 text-sm ${
                  status === filter.value
                    ? "border-sky-500 bg-sky-500/10 text-sky-300"
                    : "border-slate-700 bg-slate-900 text-slate-300"
                }`}
              >
                {filter.label}
              </button>
            ))}
          </div>

          {isLoading && <p className="text-sm text-slate-400">불러오는 중…</p>}
          {!isLoading && strategies?.length === 0 && (
            <p className="text-sm text-slate-400">등록된 전략이 없어요.</p>
          )}

          <ul className="space-y-3">
            {strategies?.map((strategy) => {
              const pending = isRowActionPending(strategy.id);
              return (
                <li
                  key={strategy.id}
                  className="flex items-center justify-between rounded border border-slate-800 bg-slate-900/50 p-4"
                >
                  <div>
                    <p className="font-medium">
                      {strategy.name}{" "}
                      <span className="text-slate-400">
                        ({STATUS_LABELS[strategy.status]} · {EXECUTION_MODE_LABELS[strategy.execution_mode]} ·
                        v{strategy.version})
                      </span>
                    </p>
                    {strategy.description && (
                      <p className="mt-1 text-sm text-slate-400">{strategy.description}</p>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Link
                      to={`/strategies/${strategy.id}`}
                      className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium hover:bg-slate-700"
                    >
                      편집
                    </Link>
                    <button
                      type="button"
                      onClick={() => cloneMutation.mutate(strategy.id)}
                      disabled={pending}
                      className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium hover:bg-slate-700 disabled:opacity-50"
                    >
                      복제
                    </button>
                    {(strategy.status === "draft" || strategy.status === "paused") && (
                      <button
                        type="button"
                        onClick={() => activateMutation.mutate(strategy.id)}
                        disabled={pending}
                        className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium hover:bg-slate-700 disabled:opacity-50"
                      >
                        {strategy.status === "paused" ? "재개" : "활성화"}
                      </button>
                    )}
                    {strategy.status === "active" && (
                      <button
                        type="button"
                        onClick={() => pauseMutation.mutate(strategy.id)}
                        disabled={pending}
                        className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium hover:bg-slate-700 disabled:opacity-50"
                      >
                        일시정지
                      </button>
                    )}
                    {strategy.status !== "archived" && (
                      <button
                        type="button"
                        onClick={() => archiveMutation.mutate(strategy.id)}
                        disabled={pending}
                        className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium hover:bg-slate-700 disabled:opacity-50"
                      >
                        보관
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => deleteMutation.mutate(strategy.id)}
                      disabled={pending}
                      className="rounded bg-red-900/50 px-3 py-1.5 text-sm font-medium text-red-200 hover:bg-red-900 disabled:opacity-50"
                    >
                      삭제
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      </div>
    </main>
  );
}

export default StrategyListPage;
