import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ApiError } from "../lib/api-client";
import {
  fetchWatchlistItems,
  removeWatchlistItem,
  type FetchWatchlistItemsParams,
  type WatchlistItem,
} from "../lib/watchlist-api";

export function watchlistItemsQueryKey(params: FetchWatchlistItemsParams) {
  return ["watchlist", params] as const;
}

export function useWatchlistItemsQuery(params: FetchWatchlistItemsParams = {}) {
  return useQuery<WatchlistItem[], ApiError>({
    queryKey: watchlistItemsQueryKey(params),
    queryFn: () => fetchWatchlistItems(params),
    retry: false,
  });
}

export function useRemoveWatchlistItemMutation() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (assetId: string) => removeWatchlistItem(assetId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["watchlist"] });
    },
  });
}
