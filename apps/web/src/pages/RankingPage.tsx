import { useState } from "react";

import { useScoresQuery } from "../hooks/useScoresQuery";
import type { RegimeStatus, ScoreRankingItem } from "../lib/scores-api";

const REGIME_LABELS: Record<RegimeStatus, string> = {
  NORMAL: "정상",
  DEFENSIVE: "방어",
};

type SubScoreKey = "momentum_score" | "quality_score" | "value_score" | "liquidity_score" | "risk_score";

const SUB_SCORE_LABELS: { key: SubScoreKey; label: string }[] = [
  { key: "momentum_score", label: "모멘텀" },
  { key: "quality_score", label: "퀄리티" },
  { key: "value_score", label: "밸류" },
  { key: "liquidity_score", label: "유동성" },
  { key: "risk_score", label: "리스크" },
];

function ScoreReasons({ item }: { item: ScoreRankingItem }) {
  if (item.summary === null && item.positive_reasons === null && item.risk_reasons === null) {
    return <p className="text-sm text-slate-400">설명 없음</p>;
  }

  return (
    <div className="space-y-2 text-sm">
      {item.summary && <p>{item.summary}</p>}
      {item.positive_reasons && item.positive_reasons.length > 0 && (
        <ul className="list-inside list-disc text-sky-300">
          {item.positive_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {item.risk_reasons && item.risk_reasons.length > 0 && (
        <ul className="list-inside list-disc text-amber-300">
          {item.risk_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// AI 점수 랭킹 화면 (SoT A5.2) — GET /api/v1/scores가 이미 total_score
// 내림차순으로 정렬해 반환하므로 프론트에서 재정렬하지 않는다.
function RankingPage() {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const { data, isLoading, isError, error } = useScoresQuery();

  return (
    <main className="min-h-screen bg-slate-950 p-6 text-slate-100">
      <div className="mx-auto max-w-3xl space-y-4">
        <h1 className="text-xl font-semibold">AI 점수 랭킹</h1>

        {isLoading && <p className="text-sm text-slate-400">불러오는 중…</p>}
        {isError && <p className="text-sm text-red-400">{error.message}</p>}

        {!isLoading && !isError && data?.score_date === null && (
          <p className="text-sm text-slate-400">
            아직 계산된 점수가 없어요. 점수 파이프라인이 처음 실행되면 이곳에 순위가 표시돼요.
          </p>
        )}

        {!isLoading && !isError && data && data.score_date !== null && (
          <ul className="space-y-3">
            {data.scores.map((item) => {
              const isExpanded = expandedId === item.asset_id;
              return (
                <li
                  key={item.asset_id}
                  className="rounded border border-slate-800 bg-slate-900/50 p-4"
                >
                  <button
                    type="button"
                    onClick={() => setExpandedId(isExpanded ? null : item.asset_id)}
                    className="flex w-full items-center justify-between text-left"
                  >
                    <div>
                      <p className="font-medium">
                        {item.name} <span className="text-slate-400">({item.ticker})</span>
                      </p>
                      <span
                        className={`mt-1 inline-block text-sm ${
                          item.regime === "NORMAL" ? "text-sky-400" : "text-amber-400"
                        }`}
                      >
                        {REGIME_LABELS[item.regime]}
                      </span>
                    </div>
                    <span className="text-lg font-semibold">{item.total_score}</span>
                  </button>

                  {isExpanded && (
                    <div className="mt-4 space-y-3 border-t border-slate-800 pt-4">
                      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                        {SUB_SCORE_LABELS.map(({ key, label }) => (
                          <div key={key}>
                            <dt className="text-xs text-slate-400">{label}</dt>
                            <dd className="text-sm">{item[key]}</dd>
                          </div>
                        ))}
                      </dl>

                      <ScoreReasons item={item} />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </main>
  );
}

export default RankingPage;
