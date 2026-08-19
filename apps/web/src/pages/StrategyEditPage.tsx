import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, type UseFormRegisterReturn } from "react-hook-form";
import { Link, useParams } from "react-router";
import { z } from "zod";

import Term from "../components/Term";
import { useStrategyQuery, useUpdateStrategyMutation } from "../hooks/useStrategyQuery";
import type { ExecutionMode, Strategy } from "../lib/strategy-api";
import {
  formValuesToStrategyConfigWrite,
  strategyConfigFormSchema,
  strategyConfigToFormValues,
} from "../lib/strategy-config-schema";

const EXECUTION_MODE_OPTIONS: ExecutionMode[] = [
  "backtest",
  "paper",
  "live_approval",
  "live_auto",
];

const EXECUTION_MODE_LABELS: Record<ExecutionMode, string> = {
  backtest: "백테스트",
  paper: "모의투자",
  live_approval: "실거래(승인)",
  live_auto: "실거래(자동)",
};

const strategyEditFormSchema = z.object({
  name: z.string().min(1, "이름을 입력하세요."),
  description: z.string(),
  execution_mode: z.enum(["backtest", "paper", "live_approval", "live_auto"]),
  config: strategyConfigFormSchema,
});

type StrategyEditFormValues = z.infer<typeof strategyEditFormSchema>;

function ConfigField({
  label,
  error,
  registration,
  termKey,
}: {
  label: string;
  error?: string;
  registration: UseFormRegisterReturn;
  termKey?: string;
}) {
  return (
    <div className="space-y-1">
      {termKey && (
        <div className="text-xs text-slate-400">
          <Term termKey={termKey}>{label}</Term>
        </div>
      )}
      <label className="block space-y-1 text-sm text-slate-300">
        <span>{label}</span>
        <input
          type="text"
          inputMode="decimal"
          className="block w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          {...registration}
        />
      </label>
      {error && <p className="text-sm text-red-400">{error}</p>}
    </div>
  );
}

function StrategyEditForm({ strategy }: { strategy: Strategy }) {
  const updateMutation = useUpdateStrategyMutation();

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<StrategyEditFormValues>({
    resolver: zodResolver(strategyEditFormSchema),
    defaultValues: {
      name: strategy.name,
      description: strategy.description ?? "",
      execution_mode: strategy.execution_mode,
      config: strategyConfigToFormValues(strategy.config),
    },
  });

  const onSubmit = (values: StrategyEditFormValues) => {
    updateMutation.reset();
    updateMutation.mutate({
      id: strategy.id,
      payload: {
        name: values.name,
        description: values.description.trim() === "" ? null : values.description,
        execution_mode: values.execution_mode,
        config: formValuesToStrategyConfigWrite(values.config),
      },
    });
  };

  const configErrors = errors.config;

  return (
    <form onSubmit={(event) => void handleSubmit(onSubmit)(event)} noValidate className="space-y-6">
      <fieldset className="space-y-3 rounded border border-slate-800 p-4">
        <legend className="px-1 text-sm font-medium text-slate-300">기본 정보</legend>
        <label className="block space-y-1 text-sm text-slate-300">
          <span>이름</span>
          <input
            type="text"
            className="block w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            {...register("name")}
          />
        </label>
        {errors.name && <p className="text-sm text-red-400">{errors.name.message}</p>}

        <label className="block space-y-1 text-sm text-slate-300">
          <span>설명</span>
          <textarea
            rows={2}
            className="block w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            {...register("description")}
          />
        </label>

        <div className="text-xs text-slate-400">
          <Term termKey="execution_mode">실행 모드</Term>
        </div>
        <label className="block space-y-1 text-sm text-slate-300">
          <span>실행 모드</span>
          <select
            className="block w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            {...register("execution_mode")}
          >
            {EXECUTION_MODE_OPTIONS.map((mode) => (
              <option key={mode} value={mode}>
                {EXECUTION_MODE_LABELS[mode]}
              </option>
            ))}
          </select>
        </label>
      </fieldset>

      <fieldset className="space-y-3 rounded border border-slate-800 p-4">
        <legend className="px-1 text-sm font-medium text-slate-300">유니버스</legend>
        <div className="space-y-1">
          <span className="block text-sm text-slate-300">시장</span>
          <label className="mr-4 inline-flex items-center gap-1 text-sm text-slate-300">
            <input type="checkbox" value="KR" {...register("config.universe.markets")} />
            KR
          </label>
        </div>
        <div className="space-y-1">
          <span className="block text-sm text-slate-300">자산 유형</span>
          <label className="mr-4 inline-flex items-center gap-1 text-sm text-slate-300">
            <input type="checkbox" value="STOCK" {...register("config.universe.asset_types")} />
            주식
          </label>
          <label className="inline-flex items-center gap-1 text-sm text-slate-300">
            <input type="checkbox" value="ETF" {...register("config.universe.asset_types")} />
            ETF
          </label>
        </div>
        <ConfigField
          label="섹터(콤마로 구분)"
          registration={register("config.universe.sectors")}
        />
        <ConfigField
          label="최소 시가총액"
          registration={register("config.universe.market_cap_min")}
          error={configErrors?.universe?.market_cap_min?.message}
        />
        <ConfigField
          label="최소 평균 거래대금"
          registration={register("config.universe.avg_trading_value_min")}
          error={configErrors?.universe?.avg_trading_value_min?.message}
        />
      </fieldset>

      <fieldset className="space-y-3 rounded border border-slate-800 p-4">
        <legend className="px-1 text-sm font-medium text-slate-300">
          <Term termKey="ai_filter">AI 필터</Term>
        </legend>
        <ConfigField
          label="최소 점수(0~100)"
          registration={register("config.ai_filter.min_score")}
          error={configErrors?.ai_filter?.min_score?.message}
        />
        <ConfigField
          label="상위 N종목"
          registration={register("config.ai_filter.top_n")}
          error={configErrors?.ai_filter?.top_n?.message}
        />
      </fieldset>

      <fieldset className="space-y-3 rounded border border-slate-800 p-4">
        <legend className="px-1 text-sm font-medium text-slate-300">매수 규칙</legend>
        <ConfigField
          label="3개월 모멘텀 최소"
          termKey="momentum_3m"
          registration={register("config.buy_rules.momentum_3m_min")}
          error={configErrors?.buy_rules?.momentum_3m_min?.message}
        />
        <ConfigField
          label="6개월 모멘텀 최소"
          termKey="momentum_6m"
          registration={register("config.buy_rules.momentum_6m_min")}
          error={configErrors?.buy_rules?.momentum_6m_min?.message}
        />
        <ConfigField
          label="이동평균 상회(일)"
          termKey="price_above_ma"
          registration={register("config.buy_rules.price_above_ma")}
          error={configErrors?.buy_rules?.price_above_ma?.message}
        />
        <div>
          <div className="text-xs text-slate-400">
            <Term termKey="ma_alignment">이동평균 정렬 (짧은 기간 &lt; 긴 기간)</Term>
          </div>
          <div className="mt-1 grid grid-cols-2 gap-3">
            <ConfigField
              label="단기 이동평균(일)"
              registration={register("config.buy_rules.ma_alignment_short")}
              error={configErrors?.buy_rules?.ma_alignment_short?.message}
            />
            <ConfigField
              label="장기 이동평균(일)"
              registration={register("config.buy_rules.ma_alignment_long")}
              error={configErrors?.buy_rules?.ma_alignment_long?.message}
            />
          </div>
        </div>
        <div>
          <div className="text-xs text-slate-400">
            <Term termKey="near_high_pct">신고가 근접(비율·기간 함께 입력)</Term>
          </div>
          <div className="mt-1 grid grid-cols-2 gap-3">
            <ConfigField
              label="신고가 근접 비율(%)"
              registration={register("config.buy_rules.near_high_pct")}
              error={configErrors?.buy_rules?.near_high_pct?.message}
            />
            <ConfigField
              label="신고가 조회 기간(일)"
              registration={register("config.buy_rules.near_high_lookback")}
              error={configErrors?.buy_rules?.near_high_lookback?.message}
            />
          </div>
        </div>
        <ConfigField
          label="변동성 상한 백분위(0~100)"
          termKey="volatility_max_percentile"
          registration={register("config.buy_rules.volatility_max_percentile")}
          error={configErrors?.buy_rules?.volatility_max_percentile?.message}
        />
      </fieldset>

      <fieldset className="space-y-3 rounded border border-slate-800 p-4">
        <legend className="px-1 text-sm font-medium text-slate-300">매도 규칙</legend>
        <ConfigField
          label="손절(%)"
          termKey="stop_loss_pct"
          registration={register("config.sell_rules.stop_loss_pct")}
          error={configErrors?.sell_rules?.stop_loss_pct?.message}
        />
        <ConfigField
          label="트레일링 스탑(%)"
          termKey="trailing_stop_pct"
          registration={register("config.sell_rules.trailing_stop_pct")}
          error={configErrors?.sell_rules?.trailing_stop_pct?.message}
        />
        <ConfigField
          label="이동평균 하회(일)"
          termKey="price_below_ma"
          registration={register("config.sell_rules.price_below_ma")}
          error={configErrors?.sell_rules?.price_below_ma?.message}
        />
        <ConfigField
          label="AI 점수 하한(0~100)"
          termKey="score_momentum_below"
          registration={register("config.sell_rules.ai_score_below")}
          error={configErrors?.sell_rules?.ai_score_below?.message}
        />
        <ConfigField
          label="모멘텀 하한"
          termKey="score_momentum_below"
          registration={register("config.sell_rules.momentum_below")}
          error={configErrors?.sell_rules?.momentum_below?.message}
        />
        <ConfigField
          label="익절(%)"
          termKey="take_profit_pct"
          registration={register("config.sell_rules.take_profit_pct")}
          error={configErrors?.sell_rules?.take_profit_pct?.message}
        />
        <ConfigField
          label="최대 보유일"
          termKey="holding_days_max"
          registration={register("config.sell_rules.holding_days_max")}
          error={configErrors?.sell_rules?.holding_days_max?.message}
        />
      </fieldset>

      <fieldset className="space-y-3 rounded border border-slate-800 p-4">
        <legend className="px-1 text-sm font-medium text-slate-300">포지션 사이징</legend>
        <ConfigField
          label="종목당 최대 비중(0~1)"
          termKey="max_weight_per_asset"
          registration={register("config.position_sizing.max_weight_per_asset")}
          error={configErrors?.position_sizing?.max_weight_per_asset?.message}
        />
        <ConfigField
          label="최대 보유 종목 수"
          termKey="max_positions"
          registration={register("config.position_sizing.max_positions")}
          error={configErrors?.position_sizing?.max_positions?.message}
        />
        <ConfigField
          label="최소 현금 비중(0~1)"
          termKey="min_cash_weight"
          registration={register("config.position_sizing.min_cash_weight")}
          error={configErrors?.position_sizing?.min_cash_weight?.message}
        />
        <ConfigField
          label="주문 참여율 한도(0~1)"
          termKey="max_participation_pct"
          registration={register("config.position_sizing.max_participation_pct")}
          error={configErrors?.position_sizing?.max_participation_pct?.message}
        />
      </fieldset>

      <fieldset className="space-y-3 rounded border border-slate-800 p-4">
        <legend className="px-1 text-sm font-medium text-slate-300">
          <Term termKey="rebalance_frequency">리밸런싱 주기</Term>
        </legend>
        <select
          className="block w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          {...register("config.rebalance.frequency")}
        >
          <option value="">미설정</option>
          <option value="DAILY">매일</option>
          <option value="WEEKLY">매주</option>
          <option value="MONTHLY">매월</option>
          <option value="QUARTERLY">매분기</option>
        </select>
      </fieldset>

      {updateMutation.isError && (
        <p className="text-sm text-red-400">{updateMutation.error.message}</p>
      )}
      {updateMutation.isSuccess && <p className="text-sm text-emerald-400">저장했어요.</p>}

      <button
        type="submit"
        disabled={updateMutation.isPending}
        className="rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
      >
        {updateMutation.isPending ? "저장 중…" : "저장"}
      </button>
    </form>
  );
}

function StrategyEditPage() {
  const { id = "" } = useParams<{ id: string }>();
  const {
    data: strategy,
    isLoading,
    isError,
    error,
  } = useStrategyQuery(id);

  return (
    <main className="min-h-screen bg-slate-950 p-6 text-slate-100">
      <div className="mx-auto max-w-3xl space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">전략 편집</h1>
          <Link to="/strategies" className="text-sm text-sky-400 hover:underline">
            목록으로
          </Link>
        </div>

        {isLoading && <p className="text-sm text-slate-400">불러오는 중…</p>}
        {isError && <p className="text-sm text-red-400">{error.message}</p>}
        {strategy && <StrategyEditForm strategy={strategy} />}
      </div>
    </main>
  );
}

export default StrategyEditPage;
