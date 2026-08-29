/**
 * Watchlist endpoints (SoT A5.2). Mirrors apps/api's `WatchlistListItemResponse`
 * (src/api/v1/watchlist.py) field-for-field — GET joins in ticker/name so the
 * UI never has to render a raw asset_id.
 */

import { apiDelete, apiGet } from "./api-client";

export type WatchlistKind = "watch" | "exclude";

export interface WatchlistItem {
  id: string;
  asset_id: string;
  ticker: string;
  name: string;
  kind: WatchlistKind;
  note: string | null;
  created_at: string;
}

export interface FetchWatchlistItemsParams {
  kind?: WatchlistKind;
}

export function fetchWatchlistItems(
  params: FetchWatchlistItemsParams = {},
): Promise<WatchlistItem[]> {
  const query = new URLSearchParams();
  if (params.kind) query.set("kind", params.kind);
  const suffix = query.toString();
  return apiGet<WatchlistItem[]>(`/api/v1/watchlist${suffix ? `?${suffix}` : ""}`);
}

export function removeWatchlistItem(assetId: string): Promise<void> {
  return apiDelete<void>(`/api/v1/watchlist/${encodeURIComponent(assetId)}`);
}
