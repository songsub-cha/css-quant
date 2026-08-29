/**
 * AI score ranking endpoint (SoT A5.2/A6.1). Mirrors apps/api's
 * `ScoreRankingItem`/`ScoreRankingResponse` (src/api/v1/scores.py)
 * field-for-field — Decimal fields serialize as **strings** in responses
 * (Pydantic's default JSON-mode encoding, same convention as
 * `strategy-api.ts`'s `StrategyConfig`).
 */

import { apiGet } from "./api-client";

export type RegimeStatus = "NORMAL" | "DEFENSIVE";

export interface ScoreRankingItem {
  asset_id: string;
  ticker: string;
  name: string;
  regime: RegimeStatus;

  total_score: string;
  momentum_score: string;
  quality_score: string;
  value_score: string;
  liquidity_score: string;
  risk_score: string;

  summary: string | null;
  positive_reasons: string[] | null;
  risk_reasons: string[] | null;
}

export interface ScoreRankingResponse {
  score_date: string | null;
  scores: ScoreRankingItem[];
}

export interface FetchScoresParams {
  scoreDate?: string;
}

export function fetchScores(params: FetchScoresParams = {}): Promise<ScoreRankingResponse> {
  const query = new URLSearchParams();
  if (params.scoreDate) query.set("score_date", params.scoreDate);
  const suffix = query.toString();
  return apiGet<ScoreRankingResponse>(`/api/v1/scores${suffix ? `?${suffix}` : ""}`);
}
