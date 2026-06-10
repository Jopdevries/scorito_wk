from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from .odds_math import probabilities_sum_to_one
from .rules import ScoritoRules
from .schemas import (
    AggregatedMarketProbability,
    Fixture,
    MatchPrediction,
    PlayerMetadata,
    TopscorerRecommendation,
)


def run_quality_gate(
    rules: ScoritoRules | None,
    aggregated: list[AggregatedMarketProbability],
    fixtures: list[Fixture],
    predictions: list[MatchPrediction],
    correct_score_outcomes: dict[str, set[str]],
    metadata: list[PlayerMetadata],
    topscorers: list[TopscorerRecommendation],
    timestamp: datetime | None,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []

    def warn(check: str, entity: str, message: str) -> None:
        warnings.append({"check": check, "entity": entity, "warning": message})

    if rules is None:
        warn("rules_loaded", "", "Scorito rules did not load successfully.")
    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in aggregated:
        groups[(row.entity_id, row.market)].append(row.probability)
    for (entity, market), probabilities in groups.items():
        if not probabilities_sum_to_one(probabilities):
            warn(
                "probability_normalization",
                f"{entity}:{market}",
                f"Probabilities sum to {sum(probabilities):.12f}, not 1.",
            )
    for prediction in predictions:
        if prediction.recommended_score not in correct_score_outcomes.get(
            prediction.fixture_id, set()
        ):
            warn(
                "recommended_score_market",
                prediction.fixture_id,
                "Recommended score does not exist in the correct-score market.",
            )
        if not prediction.source_used:
            warn(
                "source_used",
                prediction.fixture_id,
                "Recommendation has no source_used.",
            )
    predicted_ids = {prediction.fixture_id for prediction in predictions}
    for fixture in fixtures:
        if fixture.fixture_id not in predicted_ids:
            warn(
                "fixture_recommendation",
                fixture.fixture_id,
                "Fixture has no recommendation and is FAILED.",
            )
    duplicates = [
        fixture_id
        for fixture_id, count in Counter(
            fixture.fixture_id for fixture in fixtures
        ).items()
        if count > 1
    ]
    for fixture_id in duplicates:
        warn("duplicate_fixture_id", fixture_id, "Duplicate fixture_id.")
    unknown_players: list[str] = []
    for row in metadata:
        if row.position not in {"GK", "DEF", "MID", "FWD", "UNKNOWN"}:
            warn("player_position", row.player, "Invalid player position.")
        elif row.position == "UNKNOWN":
            unknown_players.append(row.player)
    if unknown_players:
        preview = ", ".join(unknown_players[:10])
        suffix = (
            f" and {len(unknown_players) - 10} more"
            if len(unknown_players) > 10
            else ""
        )
        warn(
            "player_position",
            f"{len(unknown_players)} players",
            "Position is UNKNOWN; FWD points are used conservatively for: "
            f"{preview}{suffix}.",
        )
    duplicate_players = [
        player
        for player, count in Counter(
            row.player.casefold() for row in topscorers
        ).items()
        if count > 1
    ]
    for player in duplicate_players:
        warn("duplicate_player", player, "Duplicate player after aggregation.")
    for row in topscorers:
        if not row.source_used:
            warn("source_used", row.player, "Topscorer row has no source_used.")
    if timestamp is None:
        warn("output_timestamp", "", "Output timestamp is missing.")
    return warnings
