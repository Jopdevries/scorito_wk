from __future__ import annotations

from collections import defaultdict
from statistics import median

from .rules import ScoritoRules
from .schemas import (
    AggregatedMarketProbability,
    OutrightRecommendation,
    RawOutrightOdd,
)


def optimize_outrights(
    aggregated: list[AggregatedMarketProbability],
    raw_odds: list[RawOutrightOdd],
    rules: ScoritoRules,
) -> list[OutrightRecommendation]:
    del rules  # Winner points are constant across countries and do not alter ranking.
    market = [row for row in aggregated if row.market == "outright_winner"]
    if not market:
        return []
    raw_by_country: dict[str, list[float]] = defaultdict(list)
    for row in raw_odds:
        raw_by_country[row.country.casefold()].append(row.odds)
    winner = max(market, key=lambda row: (row.probability, row.outcome))
    recommendations: list[OutrightRecommendation] = []
    for row in sorted(market, key=lambda item: (-item.probability, item.outcome)):
        count = row.bookmaker_count
        confidence = "HIGH" if count >= 5 else "MEDIUM" if count >= 3 else "LOW"
        country_odds = raw_by_country.get(row.outcome.casefold(), [])
        recommendations.append(
            OutrightRecommendation(
                country=row.outcome,
                p_champion=row.probability,
                winner_odds_median=median(country_odds) if country_odds else 1 / row.probability,
                bookmaker_count=count,
                recommended=row.outcome == winner.outcome,
                confidence=confidence,
                notes="Median bookmaker-normalized market probability.",
            )
        )
    return recommendations
