import { useState } from "react";
import { useSearchParams } from "react-router";

import { useGlossaryTermsQuery } from "../hooks/useGlossaryQuery";
import type { GlossaryCategory } from "../lib/glossary-api";

const CATEGORY_LABELS: Record<GlossaryCategory, string> = {
  factor: "팩터",
  financial_metric: "재무지표",
  performance_metric: "성과지표",
  trading_order: "거래·주문",
  risk: "리스크",
  disclosure: "공시",
  market_regime: "시장·레짐",
};

const CATEGORIES = Object.keys(CATEGORY_LABELS) as GlossaryCategory[];

// Search + category browsing (SoT A5.11). Reads `?term=<key>` so <Term>'s
// "용어집에서 더 보기" link can deep-link into a highlighted entry.
function GlossaryPage() {
  const [searchParams] = useSearchParams();
  const highlightKey = searchParams.get("term");
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<GlossaryCategory | "">("");

  const { data: terms, isLoading } = useGlossaryTermsQuery({
    q: q || undefined,
    category: category || undefined,
  });

  return (
    <main className="min-h-screen bg-slate-950 p-6 text-slate-100">
      <div className="mx-auto max-w-2xl space-y-4">
        <h1 className="text-xl font-semibold">용어집</h1>

        <div className="flex gap-2">
          <input
            type="search"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="용어 검색…"
            className="flex-1 rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
          />
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value as GlossaryCategory | "")}
            className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
          >
            <option value="">전체 카테고리</option>
            {CATEGORIES.map((value) => (
              <option key={value} value={value}>
                {CATEGORY_LABELS[value]}
              </option>
            ))}
          </select>
        </div>

        {isLoading && <p className="text-sm text-slate-400">불러오는 중…</p>}
        {!isLoading && terms?.length === 0 && (
          <p className="text-sm text-slate-400">일치하는 용어가 없어요.</p>
        )}

        <ul className="space-y-3">
          {terms?.map((term) => (
            <li
              key={term.key}
              className={`rounded border p-4 ${
                term.key === highlightKey
                  ? "border-sky-500 bg-slate-900"
                  : "border-slate-800 bg-slate-900/50"
              }`}
            >
              <p className="font-medium">
                {term.term_ko} <span className="text-slate-400">({term.term_en})</span>
              </p>
              <p className="mt-1 text-sm text-slate-300">{term.definition}</p>
              <p className="mt-1 text-sm text-slate-400">{term.interpretation}</p>
              {term.caution && (
                <p className="mt-1 text-sm text-amber-400">주의: {term.caution}</p>
              )}
            </li>
          ))}
        </ul>
      </div>
    </main>
  );
}

export default GlossaryPage;
