from __future__ import annotations

import math

from .rules import ScoritoRules
from .schemas import (
    AggregatedMarketProbability,
    OutrightRecommendation,
    PlayerMetadata,
    TopscorerRecommendation,
)

MINUTES_RISK_MULTIPLIER = {"LOW": 1.00, "MEDIUM": 0.80, "HIGH": 0.60}


def optimize_topscorers(
    aggregated: list[AggregatedMarketProbability],
    metadata: list[PlayerMetadata],
    outrights: list[OutrightRecommendation],
    rules: ScoritoRules,
    player_countries: dict[str, str | None] | None = None,
) -> list[TopscorerRecommendation]:
    market = [row for row in aggregated if row.market == "top_goalscorer"]
    metadata_by_player = {row.player.casefold(): row for row in metadata}
    champions = {row.country.casefold(): row.p_champion for row in outrights}
    player_countries = {
        key.casefold(): value for key, value in (player_countries or {}).items()
    }
    recommendations: list[TopscorerRecommendation] = []

    for row in market:
        meta = metadata_by_player.get(row.outcome.casefold())
        notes: list[str] = []
        if meta is None:
            country = player_countries.get(row.outcome.casefold())
            meta = PlayerMetadata(
                player=row.outcome,
                country=country,
                position="UNKNOWN",
                position_confidence="LOW",
                starter_prob=0.90,
                penalty_taker=0,
                set_piece_taker=0,
                minutes_risk="MEDIUM",
                source="UNKNOWN",
                notes="Position missing; treated as FWD conservatively.",
            )
        country = meta.country or player_countries.get(row.outcome.casefold())
        p_champion = champions.get(country.casefold()) if country else None
        if p_champion is None:
            progression = 0.50
            notes.append("Country probability missing; progression proxy set to 0.50.")
        else:
            progression = math.sqrt(p_champion)
        position_for_points = meta.position if meta.position != "UNKNOWN" else "FWD"
        position_points = float(
            getattr(rules.topscorers.group_stage, position_for_points)
        )
        penalty_multiplier = 1.15 if meta.penalty_taker == 1 else 1.00
        set_piece_multiplier = 1.08 if meta.set_piece_taker == 1 else 1.00
        minutes_multiplier = MINUTES_RISK_MULTIPLIER[meta.minutes_risk]
        value = (
            row.probability
            * progression
            * position_points
            * meta.starter_prob
            * penalty_multiplier
            * set_piece_multiplier
            * minutes_multiplier
        )

        if meta.position == "UNKNOWN":
            notes.append("Position unknown; treated as FWD conservatively.")
        elif meta.position in {"MID", "DEF", "GK"}:
            notes.append(f"{meta.position} position multiplier improves Scorito value.")
        else:
            notes.append("FWD has lower Scorito goal value.")
        if meta.penalty_taker:
            notes.append("Penalty duties improve Scorito value.")
        if meta.set_piece_taker:
            notes.append("Set-piece duties improve Scorito value.")
        if meta.minutes_risk != "LOW":
            notes.append("Minutes risk reduces value.")
        if progression > 0.50:
            notes.append("Strong country progression proxy increases value.")
        if meta.notes:
            notes.append(meta.notes)

        recommendations.append(
            TopscorerRecommendation(
                rank=1,
                player=row.outcome,
                country=country,
                position=meta.position,
                position_confidence=meta.position_confidence,
                p_topscorer=row.probability,
                team_progression_proxy=progression,
                position_points=position_points,
                starter_prob=meta.starter_prob,
                penalty_taker=meta.penalty_taker,
                set_piece_taker=meta.set_piece_taker,
                minutes_risk=meta.minutes_risk,
                estimated_scorito_value=value,
                bookmaker_count=row.bookmaker_count,
                source_used=row.source_used,
                rationale=" ".join(dict.fromkeys(notes)),
            )
        )
    recommendations.sort(
        key=lambda item: (-item.estimated_scorito_value, item.player)
    )
    return [
        recommendation.model_copy(update={"rank": rank})
        for rank, recommendation in enumerate(recommendations, start=1)
    ]
