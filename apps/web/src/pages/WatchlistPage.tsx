import { useState } from "react";

import { useRemoveWatchlistItemMutation, useWatchlistItemsQuery } from "../hooks/useWatchlistQuery";
import type { WatchlistKind } from "../lib/watchlist-api";

const KIND_LABELS: Record<WatchlistKind, string> = {
  watch: "관심",
  exclude: "제외",
};

const FILTERS: { value: WatchlistKind | ""; label: string }[] = [
  { value: "", label: "전체" },
  { value: "watch", label: "관심" },
  { value: "exclude", label: "제외" },
];

// Read + remove only (SoT 이슈 #73) — adding a watch/exclude entry needs an
// asset-picker screen that doesn't exist yet (see #68), so that action is
// deferred to whichever screen adds one.
function WatchlistPage() {
  const [kind, setKind] = useState<WatchlistKind | "">("");
  const { data: items, isLoading } = useWatchlistItemsQuery({ kind: kind || undefined });
  const removeMutation = useRemoveWatchlistItemMutation();

  return (
    <main className="min-h-screen bg-slate-950 p-6 text-slate-100">
      <div className="mx-auto max-w-2xl space-y-4">
        <h1 className="text-xl font-semibold">관심/제외 목록</h1>

        <div className="flex gap-2">
          {FILTERS.map((filter) => (
            <button
              key={filter.value || "all"}
              type="button"
              onClick={() => setKind(filter.value)}
              className={`rounded border px-3 py-1.5 text-sm ${
                kind === filter.value
                  ? "border-sky-500 bg-sky-500/10 text-sky-300"
                  : "border-slate-700 bg-slate-900 text-slate-300"
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>

        {removeMutation.isError && (
          <p className="text-sm text-red-400">{removeMutation.error.message}</p>
        )}

        {isLoading && <p className="text-sm text-slate-400">불러오는 중…</p>}
        {!isLoading && items?.length === 0 && (
          <p className="text-sm text-slate-400">등록된 종목이 없어요.</p>
        )}

        <ul className="space-y-3">
          {items?.map((item) => {
            const isRemoving =
              removeMutation.isPending && removeMutation.variables === item.asset_id;
            return (
              <li
                key={item.id}
                className="flex items-center justify-between rounded border border-slate-800 bg-slate-900/50 p-4"
              >
                <div>
                  <p className="font-medium">
                    {item.name} <span className="text-slate-400">({item.ticker})</span>
                  </p>
                  <p className="mt-1 text-sm text-slate-400">
                    <span className={item.kind === "watch" ? "text-sky-400" : "text-amber-400"}>
                      {KIND_LABELS[item.kind]}
                    </span>
                    {item.note && <span className="ml-2">{item.note}</span>}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => removeMutation.mutate(item.asset_id)}
                  disabled={isRemoving}
                  className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium hover:bg-slate-700 disabled:opacity-50"
                >
                  {isRemoving ? "해제 중…" : "해제"}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </main>
  );
}

export default WatchlistPage;
