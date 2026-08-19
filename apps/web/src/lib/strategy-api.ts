/**
 * Strategy endpoints (SoT A5.3/A6.5). Mirrors apps/api's `StrategyResponse` /
 * `StrategyTemplateResponse` (src/api/v1/strategies.py) field-for-field.
 *
 * Decimal fields in `StrategyConfig` serialize as **strings** in responses
 * (Pydantic's default JSON-mode encoding for `Decimal`, confirmed by
 * `apps/api/tests/test_strategy_api.py`'s `config["ai_filter"]["min_score"]
 * == "80"` assertion) but are accepted as plain JSON numbers on write —
 * hence `StrategyConfig`/`StrategyConfigWrite` are distinct shapes below.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from "./api-client";

export type StrategyStatus = "draft" | "active" | "paused" | "archived";

export type ExecutionMode = "backtest" | "paper" | "live_approval" | "live_auto";

export type RebalanceFrequency = "DAILY" | "WEEKLY" | "MONTHLY" | "QUARTERLY";

export type Market = "KR";

export type AssetType = "STOCK" | "ETF";

export interface UniverseConfig {
  markets: Market[];
  asset_types: AssetType[];
  sectors: string[] | null;
  market_cap_min: string | null;
  avg_trading_value_min: string | null;
}

export interface AiFilterConfig {
  min_score: string | null;
  top_n: number | null;
}

export interface BuyRules {
  momentum_3m_min: string | null;
  momentum_6m_min: string | null;
  price_above_ma: number | null;
  ma_alignment: number[] | null;
  near_high_pct: string | null;
  near_high_lookback: number | null;
  volatility_max_percentile: string | null;
}

export interface SellRules {
  stop_loss_pct: string | null;
  trailing_stop_pct: string | null;
  price_below_ma: number | null;
  ai_score_below: string | null;
  momentum_below: string | null;
  take_profit_pct: string | null;
  holding_days_max: number | null;
}

export interface PositionSizing {
  max_weight_per_asset: string | null;
  max_positions: number | null;
  min_cash_weight: string | null;
  max_participation_pct: string;
}

export interface RebalanceConfig {
  frequency: RebalanceFrequency | null;
}

export interface StrategyConfig {
  universe: UniverseConfig;
  ai_filter: AiFilterConfig;
  buy_rules: BuyRules;
  sell_rules: SellRules;
  position_sizing: PositionSizing;
  rebalance: RebalanceConfig;
}

export interface Strategy {
  id: string;
  name: string;
  description: string | null;
  status: StrategyStatus;
  execution_mode: ExecutionMode;
  config: StrategyConfig;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface StrategyTemplate {
  key: string;
  name: string;
  description: string;
  config: StrategyConfig;
}

// Write-side shapes: every nested object/field is optional (a strategy can
// start bare, SoT A5.3 "빈 전략에서 시작한다") and Decimal fields are plain
// numbers, matching what apps/api's StrategyConfig Pydantic model accepts.
export interface UniverseConfigWrite {
  markets?: Market[];
  asset_types?: AssetType[];
  sectors?: string[] | null;
  market_cap_min?: number | null;
  avg_trading_value_min?: number | null;
}

export interface AiFilterConfigWrite {
  min_score?: number | null;
  top_n?: number | null;
}

export interface BuyRulesWrite {
  momentum_3m_min?: number | null;
  momentum_6m_min?: number | null;
  price_above_ma?: number | null;
  ma_alignment?: number[] | null;
  near_high_pct?: number | null;
  near_high_lookback?: number | null;
  volatility_max_percentile?: number | null;
}

export interface SellRulesWrite {
  stop_loss_pct?: number | null;
  trailing_stop_pct?: number | null;
  price_below_ma?: number | null;
  ai_score_below?: number | null;
  momentum_below?: number | null;
  take_profit_pct?: number | null;
  holding_days_max?: number | null;
}

export interface PositionSizingWrite {
  max_weight_per_asset?: number | null;
  max_positions?: number | null;
  min_cash_weight?: number | null;
  max_participation_pct?: number;
}

export interface RebalanceConfigWrite {
  frequency?: RebalanceFrequency | null;
}

export interface StrategyConfigWrite {
  universe?: UniverseConfigWrite;
  ai_filter?: AiFilterConfigWrite;
  buy_rules?: BuyRulesWrite;
  sell_rules?: SellRulesWrite;
  position_sizing?: PositionSizingWrite;
  rebalance?: RebalanceConfigWrite;
}

export interface FetchStrategiesParams {
  status?: StrategyStatus;
}

// `config` accepts either shape — the backend's Decimal fields parse from a
// JSON string or number equally well, so a template's response-shaped
// config (decimals as strings) can be forwarded to create/update as-is,
// alongside a form-built write config (decimals as numbers).
export interface CreateStrategyPayload {
  name: string;
  description?: string | null;
  execution_mode: ExecutionMode;
  config?: StrategyConfig | StrategyConfigWrite;
}

export interface UpdateStrategyPayload {
  name?: string;
  description?: string | null;
  execution_mode?: ExecutionMode;
  config?: StrategyConfig | StrategyConfigWrite;
}

export function fetchStrategies(params: FetchStrategiesParams = {}): Promise<Strategy[]> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  const suffix = query.toString();
  return apiGet<Strategy[]>(`/api/v1/strategies${suffix ? `?${suffix}` : ""}`);
}

export function fetchStrategy(id: string): Promise<Strategy> {
  return apiGet<Strategy>(`/api/v1/strategies/${encodeURIComponent(id)}`);
}

export function fetchStrategyTemplates(): Promise<StrategyTemplate[]> {
  return apiGet<StrategyTemplate[]>("/api/v1/strategies/templates");
}

export function createStrategy(payload: CreateStrategyPayload): Promise<Strategy> {
  return apiPost<Strategy>("/api/v1/strategies", payload);
}

export function updateStrategy(id: string, payload: UpdateStrategyPayload): Promise<Strategy> {
  return apiPatch<Strategy>(`/api/v1/strategies/${encodeURIComponent(id)}`, payload);
}

export function deleteStrategy(id: string): Promise<void> {
  return apiDelete<void>(`/api/v1/strategies/${encodeURIComponent(id)}`);
}

export function activateStrategy(id: string): Promise<Strategy> {
  return apiPost<Strategy>(`/api/v1/strategies/${encodeURIComponent(id)}/activate`);
}

export function pauseStrategy(id: string): Promise<Strategy> {
  return apiPost<Strategy>(`/api/v1/strategies/${encodeURIComponent(id)}/pause`);
}

export function archiveStrategy(id: string): Promise<Strategy> {
  return apiPost<Strategy>(`/api/v1/strategies/${encodeURIComponent(id)}/archive`);
}

export function cloneStrategy(id: string): Promise<Strategy> {
  return apiPost<Strategy>(`/api/v1/strategies/${encodeURIComponent(id)}/clone`);
}
