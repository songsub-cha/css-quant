import { http, HttpResponse } from "msw";

import type { GlossaryTerm } from "../../lib/glossary-api";
import type { ScoreRankingItem } from "../../lib/scores-api";
import type { Strategy, StrategyConfig, StrategyStatus, StrategyTemplate } from "../../lib/strategy-api";
import type { WatchlistItem } from "../../lib/watchlist-api";

export const FIXTURE_TERMS: GlossaryTerm[] = [
  {
    key: "per",
    term_ko: "PER(주가수익비율)",
    term_en: "PER (Price-to-Earnings Ratio)",
    category: "financial_metric",
    definition: "주가를 주당순이익으로 나눈 값으로, 이익 대비 주가가 비싼지 싼지를 보여줘요.",
    interpretation: "낮을수록 이익 대비 저평가, 높을수록 고평가로 해석돼요.",
    caution: "낮은 PER이 실적 악화를 미리 반영한 '밸류 트랩'일 수 있어요.",
    in_system: "Value 팩터의 입력 지표 중 하나예요.",
    direction: "lower_is_better",
    related: ["value_factor"],
  },
  {
    key: "momentum_factor",
    term_ko: "모멘텀 팩터",
    term_en: "Momentum Factor",
    category: "factor",
    definition: "최근 일정 기간 동안 주가가 얼마나 올랐는지를 측정하는 지표예요.",
    interpretation: "백분위가 높을수록 최근 상승세가 강한 종목이에요.",
    caution: null,
    in_system: "AI 점수 5개 팩터 중 하나예요.",
    direction: "higher_is_better",
    related: [],
  },
  {
    key: "kill_switch",
    term_ko: "누적 손실 킬 스위치",
    term_en: "Cumulative Loss Kill Switch",
    category: "risk",
    definition: "포트폴리오 가치가 고점 대비 일정 비율 이상 떨어지면 전략을 자동으로 멈춰요.",
    interpretation: "큰 손실이 더 커지기 전에 자동으로 제동을 걸어요.",
    caution: null,
    in_system: "리스크 엔진의 자동 정지 조건 중 하나예요.",
    direction: "lower_is_better",
    related: [],
  },
];

export const FIXTURE_SCORE_DATE = "2026-08-19";

export const FIXTURE_SCORES: readonly ScoreRankingItem[] = [
  {
    asset_id: "ast_00000000-0000-7000-8000-000000000001",
    ticker: "005930",
    name: "삼성전자",
    regime: "NORMAL",
    total_score: "82.50",
    momentum_score: "78.00",
    quality_score: "85.00",
    value_score: "70.00",
    liquidity_score: "95.00",
    risk_score: "60.00",
    summary: "모멘텀과 유동성이 강해요.",
    positive_reasons: ["최근 3개월 상승세가 뚜렷해요.", "거래대금이 충분해요."],
    risk_reasons: ["밸류에이션이 다소 높아요."],
  },
  {
    asset_id: "ast_00000000-0000-7000-8000-000000000002",
    ticker: "000660",
    name: "SK하이닉스",
    regime: "DEFENSIVE",
    total_score: "55.00",
    momentum_score: "40.00",
    quality_score: "60.00",
    value_score: "65.00",
    liquidity_score: "80.00",
    risk_score: "50.00",
    summary: null,
    positive_reasons: null,
    risk_reasons: null,
  },
];

export const FIXTURE_WATCHLIST_ITEMS: readonly WatchlistItem[] = [
  {
    id: "wl_00000000-0000-7000-8000-000000000001",
    asset_id: "ast_00000000-0000-7000-8000-000000000001",
    ticker: "005930",
    name: "삼성전자",
    kind: "watch",
    note: "관심 종목",
    created_at: "2026-08-01T00:00:00Z",
  },
  {
    id: "wl_00000000-0000-7000-8000-000000000002",
    asset_id: "ast_00000000-0000-7000-8000-000000000002",
    ticker: "000660",
    name: "SK하이닉스",
    kind: "exclude",
    note: null,
    created_at: "2026-08-02T00:00:00Z",
  },
];

// Mutable copy so DELETE (unlike glossary's read-only fixtures) actually
// removes a row that a following GET refetch stops returning.
// resetWatchlistItems() restores it between tests.
let watchlistItems: WatchlistItem[] = [...FIXTURE_WATCHLIST_ITEMS];

export function resetWatchlistItems(): void {
  watchlistItems = [...FIXTURE_WATCHLIST_ITEMS];
}

function emptyStrategyConfig(): StrategyConfig {
  return {
    universe: {
      markets: [],
      asset_types: [],
      sectors: null,
      market_cap_min: null,
      avg_trading_value_min: null,
    },
    ai_filter: { min_score: null, top_n: null },
    buy_rules: {
      momentum_3m_min: null,
      momentum_6m_min: null,
      price_above_ma: null,
      ma_alignment: null,
      near_high_pct: null,
      near_high_lookback: null,
      volatility_max_percentile: null,
    },
    sell_rules: {
      stop_loss_pct: null,
      trailing_stop_pct: null,
      price_below_ma: null,
      ai_score_below: null,
      momentum_below: null,
      take_profit_pct: null,
      holding_days_max: null,
    },
    position_sizing: {
      max_weight_per_asset: null,
      max_positions: null,
      min_cash_weight: null,
      max_participation_pct: "0.05",
    },
    rebalance: { frequency: null },
  };
}

// SoT A7.1's four hardcoded backend templates (apps/api's strategy_template.py) — only
// the shape matters here, not exact numeric parity, since the frontend just forwards
// `template.config` verbatim on creation.
export const FIXTURE_STRATEGY_TEMPLATES: readonly StrategyTemplate[] = [
  {
    key: "trend_following",
    name: "추세추종",
    description: "이동평균 정렬과 신고가 근접으로 상승 추세 종목을 매수합니다.",
    config: {
      ...emptyStrategyConfig(),
      universe: {
        markets: ["KR"],
        asset_types: ["STOCK"],
        sectors: null,
        market_cap_min: "500000000000",
        avg_trading_value_min: "3000000000",
      },
      ai_filter: { min_score: "70", top_n: 15 },
      buy_rules: {
        ...emptyStrategyConfig().buy_rules,
        ma_alignment: [20, 60],
        price_above_ma: 20,
        near_high_pct: "5",
        near_high_lookback: 60,
      },
      sell_rules: {
        ...emptyStrategyConfig().sell_rules,
        stop_loss_pct: "8",
        trailing_stop_pct: "12",
        price_below_ma: 50,
      },
      rebalance: { frequency: "WEEKLY" },
    },
  },
  {
    key: "ai_momentum",
    name: "AI 모멘텀",
    description: "AI 점수와 모멘텀을 함께 활용해 종목을 선별합니다.",
    config: {
      ...emptyStrategyConfig(),
      universe: { markets: ["KR"], asset_types: ["STOCK"], sectors: null, market_cap_min: null, avg_trading_value_min: null },
      ai_filter: { min_score: "75", top_n: 10 },
      sell_rules: { ...emptyStrategyConfig().sell_rules, stop_loss_pct: "8", ai_score_below: "55" },
      rebalance: { frequency: "MONTHLY" },
    },
  },
  {
    key: "low_volatility_etf",
    name: "저변동성 ETF",
    description: "변동성이 낮은 ETF만을 대상으로 기술적 조건만으로 운용합니다.",
    config: {
      ...emptyStrategyConfig(),
      universe: { markets: ["KR"], asset_types: ["ETF"], sectors: null, market_cap_min: null, avg_trading_value_min: null },
      buy_rules: { ...emptyStrategyConfig().buy_rules, volatility_max_percentile: "50", price_above_ma: 60 },
      sell_rules: { ...emptyStrategyConfig().sell_rules, stop_loss_pct: "5", trailing_stop_pct: "8" },
      rebalance: { frequency: "MONTHLY" },
    },
  },
  {
    key: "large_cap_quality",
    name: "대형주 퀄리티",
    description: "AI 점수가 높은 대형주를 장기 보유합니다.",
    config: {
      ...emptyStrategyConfig(),
      universe: { markets: ["KR"], asset_types: ["STOCK"], sectors: null, market_cap_min: null, avg_trading_value_min: null },
      ai_filter: { min_score: "70", top_n: null },
      sell_rules: { ...emptyStrategyConfig().sell_rules, stop_loss_pct: "10", ai_score_below: "50" },
      rebalance: { frequency: "QUARTERLY" },
    },
  },
];

export const FIXTURE_STRATEGIES: readonly Strategy[] = [
  {
    id: "str_00000000-0000-7000-8000-000000000001",
    name: "내 추세추종 전략",
    description: "장기 보유용 추세추종",
    status: "draft",
    execution_mode: "backtest",
    config: { ...emptyStrategyConfig(), rebalance: { frequency: "WEEKLY" } },
    version: 1,
    created_at: "2026-08-10T00:00:00Z",
    updated_at: "2026-08-10T00:00:00Z",
  },
  {
    id: "str_00000000-0000-7000-8000-000000000002",
    name: "AI 모멘텀 실전",
    description: null,
    status: "active",
    execution_mode: "paper",
    config: { ...emptyStrategyConfig(), ai_filter: { min_score: "75", top_n: 10 } },
    version: 2,
    created_at: "2026-08-11T00:00:00Z",
    updated_at: "2026-08-12T00:00:00Z",
  },
];

let strategies: Strategy[] = FIXTURE_STRATEGIES.map((s) => structuredClone(s));
let strategySeq = strategies.length;

export function resetStrategies(): void {
  strategies = FIXTURE_STRATEGIES.map((s) => structuredClone(s));
  strategySeq = strategies.length;
}

const STRATEGY_ALLOWED_TRANSITIONS: Record<StrategyStatus, ReadonlySet<StrategyStatus>> = {
  draft: new Set<StrategyStatus>(["active", "archived"]),
  active: new Set<StrategyStatus>(["paused", "archived"]),
  paused: new Set<StrategyStatus>(["active", "archived"]),
  archived: new Set<StrategyStatus>([]),
};

function strategyNotFoundResponse() {
  return HttpResponse.json(
    {
      type: "about:blank",
      title: "Strategy Not Found",
      status: 404,
      detail: "Strategy not found.",
      code: "STRATEGY_NOT_FOUND",
    },
    { status: 404, headers: { "Content-Type": "application/problem+json" } },
  );
}

function strategyInvalidTransitionResponse(detail: string) {
  return HttpResponse.json(
    {
      type: "about:blank",
      title: "Strategy Invalid Transition",
      status: 409,
      detail,
      code: "STRATEGY_INVALID_TRANSITION",
    },
    { status: 409, headers: { "Content-Type": "application/problem+json" } },
  );
}

function transitionStrategy(id: string, target: StrategyStatus) {
  const strategy = strategies.find((s) => s.id === id);
  if (!strategy) return strategyNotFoundResponse();
  if (!STRATEGY_ALLOWED_TRANSITIONS[strategy.status].has(target)) {
    return strategyInvalidTransitionResponse(
      `Cannot transition strategy from ${strategy.status} to ${target}.`,
    );
  }
  strategy.status = target;
  strategy.updated_at = "2026-08-19T00:00:00Z";
  return HttpResponse.json(strategy);
}

export const handlers = [
  http.get("/api/v1/strategies/templates", () => {
    return HttpResponse.json(FIXTURE_STRATEGY_TEMPLATES);
  }),

  http.get("/api/v1/strategies", ({ request }) => {
    const url = new URL(request.url);
    const status = url.searchParams.get("status");
    let result = strategies;
    if (status) {
      result = result.filter((s) => s.status === status);
    }
    return HttpResponse.json(result);
  }),

  http.post("/api/v1/strategies", async ({ request }) => {
    const body = (await request.json()) as {
      name: string;
      description?: string | null;
      execution_mode: Strategy["execution_mode"];
      config?: Partial<StrategyConfig>;
    };
    strategySeq += 1;
    const now = "2026-08-19T00:00:00Z";
    const created: Strategy = {
      id: `str_00000000-0000-7000-8000-${String(strategySeq).padStart(12, "0")}`,
      name: body.name,
      description: body.description ?? null,
      status: "draft",
      execution_mode: body.execution_mode,
      config: { ...emptyStrategyConfig(), ...body.config } as StrategyConfig,
      version: 1,
      created_at: now,
      updated_at: now,
    };
    strategies = [...strategies, created];
    return HttpResponse.json(created, { status: 201 });
  }),

  http.get("/api/v1/strategies/:id", ({ params }) => {
    const strategy = strategies.find((s) => s.id === params.id);
    if (!strategy) return strategyNotFoundResponse();
    return HttpResponse.json(strategy);
  }),

  http.patch("/api/v1/strategies/:id", async ({ params, request }) => {
    const strategy = strategies.find((s) => s.id === params.id);
    if (!strategy) return strategyNotFoundResponse();
    const body = (await request.json()) as {
      name?: string;
      description?: string | null;
      execution_mode?: Strategy["execution_mode"];
      config?: StrategyConfig;
    };
    if (body.name !== undefined) strategy.name = body.name;
    if (body.description !== undefined) strategy.description = body.description;
    if (body.execution_mode !== undefined) strategy.execution_mode = body.execution_mode;
    if (body.config !== undefined) strategy.config = body.config;
    strategy.updated_at = "2026-08-19T00:00:00Z";
    return HttpResponse.json(strategy);
  }),

  http.delete("/api/v1/strategies/:id", ({ params }) => {
    const strategy = strategies.find((s) => s.id === params.id);
    if (!strategy) return strategyNotFoundResponse();
    if (strategy.status === "active") {
      return strategyInvalidTransitionResponse(
        "Cannot delete an active strategy — pause or archive it first.",
      );
    }
    strategies = strategies.filter((s) => s.id !== params.id);
    return new HttpResponse(null, { status: 204 });
  }),

  http.post("/api/v1/strategies/:id/activate", ({ params }) =>
    transitionStrategy(params.id as string, "active"),
  ),

  http.post("/api/v1/strategies/:id/pause", ({ params }) =>
    transitionStrategy(params.id as string, "paused"),
  ),

  http.post("/api/v1/strategies/:id/archive", ({ params }) =>
    transitionStrategy(params.id as string, "archived"),
  ),

  http.post("/api/v1/strategies/:id/clone", ({ params }) => {
    const original = strategies.find((s) => s.id === params.id);
    if (!original) return strategyNotFoundResponse();
    strategySeq += 1;
    const now = "2026-08-19T00:00:00Z";
    const cloned: Strategy = {
      ...structuredClone(original),
      id: `str_00000000-0000-7000-8000-${String(strategySeq).padStart(12, "0")}`,
      name: `${original.name} (복제)`,
      status: "draft",
      version: 1,
      created_at: now,
      updated_at: now,
    };
    strategies = [...strategies, cloned];
    return HttpResponse.json(cloned, { status: 201 });
  }),

  http.get("/api/v1/scores", () => {
    return HttpResponse.json({ score_date: FIXTURE_SCORE_DATE, scores: FIXTURE_SCORES });
  }),

  http.get("/api/v1/watchlist", ({ request }) => {
    const url = new URL(request.url);
    const kind = url.searchParams.get("kind");

    let result = watchlistItems;
    if (kind) {
      result = result.filter((item) => item.kind === kind);
    }
    return HttpResponse.json(result);
  }),

  http.delete("/api/v1/watchlist/:assetId", ({ params }) => {
    watchlistItems = watchlistItems.filter((item) => item.asset_id !== params.assetId);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get("/api/v1/glossary", ({ request }) => {
    const url = new URL(request.url);
    const category = url.searchParams.get("category");
    const q = url.searchParams.get("q");

    let result = FIXTURE_TERMS;
    if (category) {
      result = result.filter((term) => term.category === category);
    }
    if (q) {
      const needle = q.toLowerCase();
      result = result.filter(
        (term) =>
          term.key.toLowerCase().includes(needle) ||
          term.term_ko.toLowerCase().includes(needle) ||
          term.term_en.toLowerCase().includes(needle) ||
          term.definition.toLowerCase().includes(needle),
      );
    }
    return HttpResponse.json(result);
  }),

  http.get("/api/v1/glossary/:key", ({ params }) => {
    const term = FIXTURE_TERMS.find((t) => t.key === params.key);
    if (!term) {
      return HttpResponse.json(
        {
          type: "about:blank",
          title: "Glossary Term Not Found",
          status: 404,
          detail: "Glossary term not found.",
          code: "GLOSSARY_TERM_NOT_FOUND",
        },
        { status: 404, headers: { "Content-Type": "application/problem+json" } },
      );
    }
    return HttpResponse.json(term);
  }),
];
