"""AI score ranking read service (SoT A5.2/A6.1 — services layer).

``list_ranked_scores`` is the first consumer of the read side of the AI-score
pipeline (universe filter #56/#57 -> factor calculation #58/#59 ->
normalization/weighted-sum/persistence #62/#63 -> LLM explanation #64/#65):
it turns an ``AssetScoreRepository.get_by_date`` snapshot into a
``total_score``-ranked list paired with each asset's ticker/name via
``AssetRepository.list_by_ids``. Purely in-process sort — the universe filter
already bounds the candidate set to ~700 rows (SoT A6.1 1), so no DB-side
ORDER BY/pagination is needed.
"""

from __future__ import annotations

from datetime import date

from src.domain.ai_score import AssetScore, AssetScoreRepository
from src.domain.asset import Asset, AssetRepository


async def list_ranked_scores(
    score_repo: AssetScoreRepository,
    asset_repo: AssetRepository,
    *,
    score_date: date | None,
) -> tuple[date | None, list[tuple[AssetScore, Asset]]]:
    """Return ``(resolved_date, ranked_pairs)`` for ``score_date`` (or the latest
    scored date if ``score_date`` is ``None``).

    Both a cold-start pipeline (no ``score_date`` argument, no scores ever
    computed) and a specific date with no rows resolve to an empty list, not
    an error — a caller distinguishes the two via the returned date being
    ``None`` or not.
    """
    resolved_date = score_date
    if resolved_date is None:
        resolved_date = await score_repo.get_latest_score_date()
        if resolved_date is None:
            return None, []

    scores = await score_repo.get_by_date(score_date=resolved_date)
    if not scores:
        return resolved_date, []

    assets = await asset_repo.list_by_ids([score.asset_id for score in scores])
    assets_by_id = {asset.id: asset for asset in assets}

    pairs = [
        (score, assets_by_id[score.asset_id])
        for score in scores
        if score.asset_id in assets_by_id
    ]
    pairs.sort(key=lambda pair: (-pair[0].total_score, pair[0].asset_id))
    return resolved_date, pairs
