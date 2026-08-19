import { describe, expect, it } from "vitest";

import {
  EMPTY_STRATEGY_CONFIG_FORM_VALUES,
  formValuesToStrategyConfigWrite,
  strategyConfigFormSchema,
  strategyConfigToFormValues,
} from "./strategy-config-schema";
import type { StrategyConfig } from "./strategy-api";

function validValues() {
  return structuredClone(EMPTY_STRATEGY_CONFIG_FORM_VALUES);
}

describe("strategyConfigFormSchema", () => {
  it("accepts a fully-empty config (SoT A5.3 '빈 전략에서 시작한다')", () => {
    const result = strategyConfigFormSchema.safeParse(validValues());
    expect(result.success).toBe(true);
  });

  it("rejects ma_alignment that isn't strictly ascending (mirrors BuyRules._validate_ma_alignment)", () => {
    const values = validValues();
    values.buy_rules.ma_alignment_short = "60";
    values.buy_rules.ma_alignment_long = "20";

    const result = strategyConfigFormSchema.safeParse(values);

    expect(result.success).toBe(false);
    if (!result.success) {
      const issue = result.error.issues.find(
        (i) => i.path.join(".") === "buy_rules.ma_alignment_long",
      );
      expect(issue).toBeDefined();
    }
  });

  it("rejects ma_alignment with only one side set", () => {
    const values = validValues();
    values.buy_rules.ma_alignment_short = "20";

    const result = strategyConfigFormSchema.safeParse(values);

    expect(result.success).toBe(false);
    if (!result.success) {
      const issue = result.error.issues.find(
        (i) => i.path.join(".") === "buy_rules.ma_alignment_long",
      );
      expect(issue?.message).toBe("이동평균 정렬은 두 값을 함께 입력해야 해요.");
    }
  });

  it("accepts a valid ascending ma_alignment pair", () => {
    const values = validValues();
    values.buy_rules.ma_alignment_short = "20";
    values.buy_rules.ma_alignment_long = "60";

    expect(strategyConfigFormSchema.safeParse(values).success).toBe(true);
  });

  it("rejects near_high_pct set without near_high_lookback (mirrors BuyRules._validate_near_high_co_presence)", () => {
    const values = validValues();
    values.buy_rules.near_high_pct = "5";

    const result = strategyConfigFormSchema.safeParse(values);

    expect(result.success).toBe(false);
    if (!result.success) {
      const issue = result.error.issues.find(
        (i) => i.path.join(".") === "buy_rules.near_high_lookback",
      );
      expect(issue).toBeDefined();
    }
  });

  it("rejects near_high_lookback set without near_high_pct", () => {
    const values = validValues();
    values.buy_rules.near_high_lookback = "60";

    const result = strategyConfigFormSchema.safeParse(values);

    expect(result.success).toBe(false);
    if (!result.success) {
      const issue = result.error.issues.find(
        (i) => i.path.join(".") === "buy_rules.near_high_pct",
      );
      expect(issue).toBeDefined();
    }
  });

  it("rejects an out-of-range percentile field", () => {
    const values = validValues();
    values.buy_rules.volatility_max_percentile = "150";

    expect(strategyConfigFormSchema.safeParse(values).success).toBe(false);
  });

  it("rejects a non-integer count field", () => {
    const values = validValues();
    values.ai_filter.top_n = "1.5";

    expect(strategyConfigFormSchema.safeParse(values).success).toBe(false);
  });
});

describe("strategyConfigToFormValues / formValuesToStrategyConfigWrite round-trip", () => {
  const responseConfig: StrategyConfig = {
    universe: {
      markets: ["KR"],
      asset_types: ["STOCK"],
      sectors: ["반도체", "2차전지"],
      market_cap_min: "500000000000",
      avg_trading_value_min: null,
    },
    ai_filter: { min_score: "70", top_n: 15 },
    buy_rules: {
      momentum_3m_min: "0",
      momentum_6m_min: null,
      price_above_ma: 20,
      ma_alignment: [20, 60],
      near_high_pct: "5",
      near_high_lookback: 60,
      volatility_max_percentile: null,
    },
    sell_rules: {
      stop_loss_pct: "8",
      trailing_stop_pct: "12",
      price_below_ma: 50,
      ai_score_below: null,
      momentum_below: null,
      take_profit_pct: null,
      holding_days_max: null,
    },
    position_sizing: {
      max_weight_per_asset: "0.07",
      max_positions: 12,
      min_cash_weight: "0.10",
      max_participation_pct: "0.05",
    },
    rebalance: { frequency: "WEEKLY" },
  };

  it("converts a response config into form values with ma_alignment split into two fields", () => {
    const values = strategyConfigToFormValues(responseConfig);

    expect(values.buy_rules.ma_alignment_short).toBe("20");
    expect(values.buy_rules.ma_alignment_long).toBe("60");
    expect(values.universe.sectors).toBe("반도체, 2차전지");
    expect(values.universe.avg_trading_value_min).toBe("");
    expect(values.rebalance.frequency).toBe("WEEKLY");
  });

  it("round-trips back into a write payload the schema itself accepts", () => {
    const values = strategyConfigToFormValues(responseConfig);
    expect(strategyConfigFormSchema.safeParse(values).success).toBe(true);

    const write = formValuesToStrategyConfigWrite(values);

    expect(write.buy_rules?.ma_alignment).toEqual([20, 60]);
    expect(write.universe?.sectors).toEqual(["반도체", "2차전지"]);
    expect(write.universe?.avg_trading_value_min).toBeUndefined();
    expect(write.position_sizing?.max_participation_pct).toBe(0.05);
    expect(write.rebalance?.frequency).toBe("WEEKLY");
  });
});
