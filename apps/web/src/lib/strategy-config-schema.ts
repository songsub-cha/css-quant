/**
 * Client-side Zod mirror of apps/api's `StrategyConfig` (Pydantic,
 * src/domain/strategy_config.py) — SoT A5.3 "저장 전 검증(Zod + Pydantic
 * 양쪽)". Every numeric leaf is kept as a raw `string` in the form (default
 * `""` for "not set") rather than `number`, so an emptied `<input>` maps to
 * a clean "unset" instead of `NaN` — the two cross-field `superRefine`
 * checks below reproduce `BuyRules`'s two `model_validator`s exactly:
 * `ma_alignment` (split here into `ma_alignment_short`/`_long` — two plain
 * number inputs are simpler to build than one array input) must be
 * strictly ascending, and `near_high_pct`/`near_high_lookback` must be set
 * together.
 */

import { z } from "zod";

import type {
  AssetType,
  Market,
  RebalanceFrequency,
  StrategyConfig,
  StrategyConfigWrite,
} from "./strategy-api";

export const MARKET_OPTIONS = ["KR"] as const satisfies readonly Market[];
export const ASSET_TYPE_OPTIONS = ["STOCK", "ETF"] as const satisfies readonly AssetType[];
export const REBALANCE_FREQUENCY_OPTIONS = [
  "DAILY",
  "WEEKLY",
  "MONTHLY",
  "QUARTERLY",
] as const satisfies readonly RebalanceFrequency[];

interface NumericStringFieldOptions {
  integer?: boolean;
  gt?: number;
  gte?: number;
  lte?: number;
  message?: string;
}

function numericStringField(opts: NumericStringFieldOptions = {}) {
  return z.string().refine((val) => {
    if (val === "") return true;
    const num = Number(val);
    if (!Number.isFinite(num)) return false;
    if (opts.integer && !Number.isInteger(num)) return false;
    if (opts.gt !== undefined && !(num > opts.gt)) return false;
    if (opts.gte !== undefined && !(num >= opts.gte)) return false;
    if (opts.lte !== undefined && !(num <= opts.lte)) return false;
    return true;
  }, opts.message ?? "값이 올바르지 않아요.");
}

const universeSchema = z.object({
  markets: z.array(z.enum(MARKET_OPTIONS)),
  asset_types: z.array(z.enum(ASSET_TYPE_OPTIONS)),
  sectors: z.string(),
  market_cap_min: numericStringField({ gt: 0, message: "0보다 커야 해요." }),
  avg_trading_value_min: numericStringField({ gt: 0, message: "0보다 커야 해요." }),
});

const aiFilterSchema = z.object({
  min_score: numericStringField({ gte: 0, lte: 100, message: "0~100 사이여야 해요." }),
  top_n: numericStringField({ integer: true, gt: 0, message: "1 이상의 정수여야 해요." }),
});

const buyRulesSchema = z.object({
  momentum_3m_min: numericStringField(),
  momentum_6m_min: numericStringField(),
  price_above_ma: numericStringField({ integer: true, gt: 0, message: "1 이상의 정수여야 해요." }),
  ma_alignment_short: numericStringField({
    integer: true,
    gt: 0,
    message: "1 이상의 정수여야 해요.",
  }),
  ma_alignment_long: numericStringField({
    integer: true,
    gt: 0,
    message: "1 이상의 정수여야 해요.",
  }),
  near_high_pct: numericStringField({ gt: 0, message: "0보다 커야 해요." }),
  near_high_lookback: numericStringField({
    integer: true,
    gt: 0,
    message: "1 이상의 정수여야 해요.",
  }),
  volatility_max_percentile: numericStringField({
    gte: 0,
    lte: 100,
    message: "0~100 사이여야 해요.",
  }),
});

const sellRulesSchema = z.object({
  stop_loss_pct: numericStringField({ gt: 0, message: "0보다 커야 해요." }),
  trailing_stop_pct: numericStringField({ gt: 0, message: "0보다 커야 해요." }),
  price_below_ma: numericStringField({ integer: true, gt: 0, message: "1 이상의 정수여야 해요." }),
  ai_score_below: numericStringField({ gte: 0, lte: 100, message: "0~100 사이여야 해요." }),
  momentum_below: numericStringField(),
  take_profit_pct: numericStringField({ gt: 0, message: "0보다 커야 해요." }),
  holding_days_max: numericStringField({ integer: true, gt: 0, message: "1 이상의 정수여야 해요." }),
});

const positionSizingSchema = z.object({
  max_weight_per_asset: numericStringField({ gt: 0, lte: 1, message: "0~1 사이여야 해요." }),
  max_positions: numericStringField({ integer: true, gt: 0, message: "1 이상의 정수여야 해요." }),
  min_cash_weight: numericStringField({ gte: 0, lte: 1, message: "0~1 사이여야 해요." }),
  max_participation_pct: numericStringField({ gt: 0, lte: 1, message: "0~1 사이여야 해요." }),
});

const rebalanceSchema = z.object({
  frequency: z.union([z.literal(""), z.enum(REBALANCE_FREQUENCY_OPTIONS)]),
});

export const strategyConfigFormSchema = z
  .object({
    universe: universeSchema,
    ai_filter: aiFilterSchema,
    buy_rules: buyRulesSchema,
    sell_rules: sellRulesSchema,
    position_sizing: positionSizingSchema,
    rebalance: rebalanceSchema,
  })
  .superRefine((data, ctx) => {
    const { ma_alignment_short, ma_alignment_long, near_high_pct, near_high_lookback } =
      data.buy_rules;

    const hasShort = ma_alignment_short !== "";
    const hasLong = ma_alignment_long !== "";
    if (hasShort !== hasLong) {
      ctx.addIssue({
        code: "custom",
        message: "이동평균 정렬은 두 값을 함께 입력해야 해요.",
        path: ["buy_rules", hasShort ? "ma_alignment_long" : "ma_alignment_short"],
      });
    } else if (hasShort && hasLong && Number(ma_alignment_short) >= Number(ma_alignment_long)) {
      ctx.addIssue({
        code: "custom",
        message: "짧은 이동평균 기간이 긴 기간보다 작아야 해요.",
        path: ["buy_rules", "ma_alignment_long"],
      });
    }

    const hasPct = near_high_pct !== "";
    const hasLookback = near_high_lookback !== "";
    if (hasPct !== hasLookback) {
      ctx.addIssue({
        code: "custom",
        message: "신고가 근접 비율과 기간은 함께 입력해야 해요.",
        path: ["buy_rules", hasPct ? "near_high_lookback" : "near_high_pct"],
      });
    }
  });

export type StrategyConfigFormValues = z.infer<typeof strategyConfigFormSchema>;

export const EMPTY_STRATEGY_CONFIG_FORM_VALUES: StrategyConfigFormValues = {
  universe: {
    markets: [],
    asset_types: [],
    sectors: "",
    market_cap_min: "",
    avg_trading_value_min: "",
  },
  ai_filter: { min_score: "", top_n: "" },
  buy_rules: {
    momentum_3m_min: "",
    momentum_6m_min: "",
    price_above_ma: "",
    ma_alignment_short: "",
    ma_alignment_long: "",
    near_high_pct: "",
    near_high_lookback: "",
    volatility_max_percentile: "",
  },
  sell_rules: {
    stop_loss_pct: "",
    trailing_stop_pct: "",
    price_below_ma: "",
    ai_score_below: "",
    momentum_below: "",
    take_profit_pct: "",
    holding_days_max: "",
  },
  position_sizing: {
    max_weight_per_asset: "",
    max_positions: "",
    min_cash_weight: "",
    max_participation_pct: "0.05",
  },
  rebalance: { frequency: "" },
};

function toStringOrEmpty(val: string | number | null | undefined): string {
  return val === null || val === undefined ? "" : String(val);
}

export function strategyConfigToFormValues(config: StrategyConfig): StrategyConfigFormValues {
  const [maShort, maLong] = config.buy_rules.ma_alignment ?? [];
  return {
    universe: {
      markets: config.universe.markets,
      asset_types: config.universe.asset_types,
      sectors: (config.universe.sectors ?? []).join(", "),
      market_cap_min: toStringOrEmpty(config.universe.market_cap_min),
      avg_trading_value_min: toStringOrEmpty(config.universe.avg_trading_value_min),
    },
    ai_filter: {
      min_score: toStringOrEmpty(config.ai_filter.min_score),
      top_n: toStringOrEmpty(config.ai_filter.top_n),
    },
    buy_rules: {
      momentum_3m_min: toStringOrEmpty(config.buy_rules.momentum_3m_min),
      momentum_6m_min: toStringOrEmpty(config.buy_rules.momentum_6m_min),
      price_above_ma: toStringOrEmpty(config.buy_rules.price_above_ma),
      ma_alignment_short: toStringOrEmpty(maShort),
      ma_alignment_long: toStringOrEmpty(maLong),
      near_high_pct: toStringOrEmpty(config.buy_rules.near_high_pct),
      near_high_lookback: toStringOrEmpty(config.buy_rules.near_high_lookback),
      volatility_max_percentile: toStringOrEmpty(config.buy_rules.volatility_max_percentile),
    },
    sell_rules: {
      stop_loss_pct: toStringOrEmpty(config.sell_rules.stop_loss_pct),
      trailing_stop_pct: toStringOrEmpty(config.sell_rules.trailing_stop_pct),
      price_below_ma: toStringOrEmpty(config.sell_rules.price_below_ma),
      ai_score_below: toStringOrEmpty(config.sell_rules.ai_score_below),
      momentum_below: toStringOrEmpty(config.sell_rules.momentum_below),
      take_profit_pct: toStringOrEmpty(config.sell_rules.take_profit_pct),
      holding_days_max: toStringOrEmpty(config.sell_rules.holding_days_max),
    },
    position_sizing: {
      max_weight_per_asset: toStringOrEmpty(config.position_sizing.max_weight_per_asset),
      max_positions: toStringOrEmpty(config.position_sizing.max_positions),
      min_cash_weight: toStringOrEmpty(config.position_sizing.min_cash_weight),
      max_participation_pct: config.position_sizing.max_participation_pct,
    },
    rebalance: {
      frequency: config.rebalance.frequency ?? "",
    },
  };
}

function toNumberOrUndefined(val: string): number | undefined {
  return val === "" ? undefined : Number(val);
}

export function formValuesToStrategyConfigWrite(
  values: StrategyConfigFormValues,
): StrategyConfigWrite {
  const sectors = values.universe.sectors
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);

  const maAlignment =
    values.buy_rules.ma_alignment_short !== "" && values.buy_rules.ma_alignment_long !== ""
      ? [Number(values.buy_rules.ma_alignment_short), Number(values.buy_rules.ma_alignment_long)]
      : undefined;

  return {
    universe: {
      markets: values.universe.markets,
      asset_types: values.universe.asset_types,
      sectors: sectors.length > 0 ? sectors : undefined,
      market_cap_min: toNumberOrUndefined(values.universe.market_cap_min),
      avg_trading_value_min: toNumberOrUndefined(values.universe.avg_trading_value_min),
    },
    ai_filter: {
      min_score: toNumberOrUndefined(values.ai_filter.min_score),
      top_n: toNumberOrUndefined(values.ai_filter.top_n),
    },
    buy_rules: {
      momentum_3m_min: toNumberOrUndefined(values.buy_rules.momentum_3m_min),
      momentum_6m_min: toNumberOrUndefined(values.buy_rules.momentum_6m_min),
      price_above_ma: toNumberOrUndefined(values.buy_rules.price_above_ma),
      ma_alignment: maAlignment,
      near_high_pct: toNumberOrUndefined(values.buy_rules.near_high_pct),
      near_high_lookback: toNumberOrUndefined(values.buy_rules.near_high_lookback),
      volatility_max_percentile: toNumberOrUndefined(values.buy_rules.volatility_max_percentile),
    },
    sell_rules: {
      stop_loss_pct: toNumberOrUndefined(values.sell_rules.stop_loss_pct),
      trailing_stop_pct: toNumberOrUndefined(values.sell_rules.trailing_stop_pct),
      price_below_ma: toNumberOrUndefined(values.sell_rules.price_below_ma),
      ai_score_below: toNumberOrUndefined(values.sell_rules.ai_score_below),
      momentum_below: toNumberOrUndefined(values.sell_rules.momentum_below),
      take_profit_pct: toNumberOrUndefined(values.sell_rules.take_profit_pct),
      holding_days_max: toNumberOrUndefined(values.sell_rules.holding_days_max),
    },
    position_sizing: {
      max_weight_per_asset: toNumberOrUndefined(values.position_sizing.max_weight_per_asset),
      max_positions: toNumberOrUndefined(values.position_sizing.max_positions),
      min_cash_weight: toNumberOrUndefined(values.position_sizing.min_cash_weight),
      max_participation_pct:
        values.position_sizing.max_participation_pct === ""
          ? 0.05
          : Number(values.position_sizing.max_participation_pct),
    },
    rebalance: {
      frequency: values.rebalance.frequency === "" ? undefined : values.rebalance.frequency,
    },
  };
}
