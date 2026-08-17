import { useQuery } from "@tanstack/react-query";

import type { ApiError } from "../lib/api-client";
import {
  fetchGlossaryTerm,
  fetchGlossaryTerms,
  type FetchGlossaryTermsParams,
  type GlossaryTerm,
} from "../lib/glossary-api";

// Glossary content is static per deploy (git-versioned, code-reviewed —
// SoT A6.12), so a long staleTime avoids re-fetching on every <Term> mount
// while still letting TanStack Query dedupe concurrent requests by key.
const GLOSSARY_STALE_TIME_MS = 5 * 60 * 1000;

export function glossaryTermsQueryKey(params: FetchGlossaryTermsParams) {
  return ["glossary", "terms", params] as const;
}

export function glossaryTermQueryKey(key: string) {
  return ["glossary", "term", key] as const;
}

export function useGlossaryTermsQuery(params: FetchGlossaryTermsParams = {}) {
  return useQuery<GlossaryTerm[], ApiError>({
    queryKey: glossaryTermsQueryKey(params),
    queryFn: () => fetchGlossaryTerms(params),
    retry: false,
    staleTime: GLOSSARY_STALE_TIME_MS,
  });
}

export function useGlossaryTermQuery(key: string) {
  return useQuery<GlossaryTerm, ApiError>({
    queryKey: glossaryTermQueryKey(key),
    queryFn: () => fetchGlossaryTerm(key),
    retry: false,
    staleTime: GLOSSARY_STALE_TIME_MS,
  });
}
