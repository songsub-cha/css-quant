import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ApiError } from "../lib/api-client";
import {
  activateStrategy,
  archiveStrategy,
  cloneStrategy,
  createStrategy,
  deleteStrategy,
  fetchStrategies,
  fetchStrategy,
  fetchStrategyTemplates,
  pauseStrategy,
  updateStrategy,
  type CreateStrategyPayload,
  type FetchStrategiesParams,
  type Strategy,
  type StrategyTemplate,
  type UpdateStrategyPayload,
} from "../lib/strategy-api";

export function strategiesQueryKey(params: FetchStrategiesParams = {}) {
  return ["strategies", params] as const;
}

export function strategyQueryKey(id: string) {
  return ["strategies", id] as const;
}

export function useStrategiesQuery(params: FetchStrategiesParams = {}) {
  return useQuery<Strategy[], ApiError>({
    queryKey: strategiesQueryKey(params),
    queryFn: () => fetchStrategies(params),
    retry: false,
  });
}

export function useStrategyQuery(id: string) {
  return useQuery<Strategy, ApiError>({
    queryKey: strategyQueryKey(id),
    queryFn: () => fetchStrategy(id),
    retry: false,
    enabled: id.length > 0,
  });
}

export function useStrategyTemplatesQuery() {
  return useQuery<StrategyTemplate[], ApiError>({
    queryKey: ["strategy-templates"] as const,
    queryFn: () => fetchStrategyTemplates(),
    retry: false,
  });
}

function useInvalidateStrategies() {
  const queryClient = useQueryClient();
  return (id?: string) => {
    void queryClient.invalidateQueries({ queryKey: ["strategies"] });
    if (id) void queryClient.invalidateQueries({ queryKey: strategyQueryKey(id) });
  };
}

export function useCreateStrategyMutation() {
  const invalidate = useInvalidateStrategies();
  return useMutation<Strategy, ApiError, CreateStrategyPayload>({
    mutationFn: (payload) => createStrategy(payload),
    onSuccess: (strategy) => invalidate(strategy.id),
  });
}

export function useUpdateStrategyMutation() {
  const invalidate = useInvalidateStrategies();
  return useMutation<Strategy, ApiError, { id: string; payload: UpdateStrategyPayload }>({
    mutationFn: ({ id, payload }) => updateStrategy(id, payload),
    onSuccess: (strategy) => invalidate(strategy.id),
  });
}

export function useDeleteStrategyMutation() {
  const invalidate = useInvalidateStrategies();
  return useMutation<void, ApiError, string>({
    mutationFn: (id) => deleteStrategy(id),
    onSuccess: (_data, id) => invalidate(id),
  });
}

export function useActivateStrategyMutation() {
  const invalidate = useInvalidateStrategies();
  return useMutation<Strategy, ApiError, string>({
    mutationFn: (id) => activateStrategy(id),
    onSuccess: (strategy) => invalidate(strategy.id),
  });
}

export function usePauseStrategyMutation() {
  const invalidate = useInvalidateStrategies();
  return useMutation<Strategy, ApiError, string>({
    mutationFn: (id) => pauseStrategy(id),
    onSuccess: (strategy) => invalidate(strategy.id),
  });
}

export function useArchiveStrategyMutation() {
  const invalidate = useInvalidateStrategies();
  return useMutation<Strategy, ApiError, string>({
    mutationFn: (id) => archiveStrategy(id),
    onSuccess: (strategy) => invalidate(strategy.id),
  });
}

export function useCloneStrategyMutation() {
  const invalidate = useInvalidateStrategies();
  return useMutation<Strategy, ApiError, string>({
    mutationFn: (id) => cloneStrategy(id),
    onSuccess: (strategy) => invalidate(strategy.id),
  });
}
