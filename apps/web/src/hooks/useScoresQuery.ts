import { useQuery } from "@tanstack/react-query";

import type { ApiError } from "../lib/api-client";
import { fetchScores, type FetchScoresParams, type ScoreRankingResponse } from "../lib/scores-api";

export function scoresQueryKey(params: FetchScoresParams) {
  return ["scores", params] as const;
}

export function useScoresQuery(params: FetchScoresParams = {}) {
  return useQuery<ScoreRankingResponse, ApiError>({
    queryKey: scoresQueryKey(params),
    queryFn: () => fetchScores(params),
    retry: false,
  });
}
