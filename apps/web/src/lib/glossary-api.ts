/**
 * Glossary endpoints (SoT A6.12). Mirrors apps/api's `GlossaryTerm`
 * (src/domain/glossary.py) field-for-field.
 */

import { apiGet } from "./api-client";

export type GlossaryCategory =
  | "factor"
  | "financial_metric"
  | "performance_metric"
  | "trading_order"
  | "risk"
  | "disclosure"
  | "market_regime";

export type GlossaryDirection = "higher_is_better" | "lower_is_better" | "neutral";

export interface GlossaryTerm {
  key: string;
  term_ko: string;
  term_en: string;
  category: GlossaryCategory;
  definition: string;
  interpretation: string;
  caution: string | null;
  in_system: string | null;
  direction: GlossaryDirection | null;
  related: string[];
}

export interface FetchGlossaryTermsParams {
  category?: GlossaryCategory;
  q?: string;
}

export function fetchGlossaryTerms(
  params: FetchGlossaryTermsParams = {},
): Promise<GlossaryTerm[]> {
  const query = new URLSearchParams();
  if (params.category) query.set("category", params.category);
  if (params.q) query.set("q", params.q);
  const suffix = query.toString();
  return apiGet<GlossaryTerm[]>(`/api/v1/glossary${suffix ? `?${suffix}` : ""}`);
}

export function fetchGlossaryTerm(key: string): Promise<GlossaryTerm> {
  return apiGet<GlossaryTerm>(`/api/v1/glossary/${encodeURIComponent(key)}`);
}
