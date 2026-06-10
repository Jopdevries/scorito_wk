from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from statistics import mean, median
from typing import TypeVar

from .odds_math import normalize_implied_probabilities, renormalize_probabilities
from .schemas import (
    AggregatedMarketProbability,
    Raw1X2Odd,
    RawCorrectScoreOdd,
    RawOUBTTSOdd,
    RawOutrightOdd,
    RawTopGoalscorerOdd,
)

T = TypeVar("T")


def _aggregate_market(
    rows: Iterable[T],
    *,
    entity_key: Callable[[T], str],
    bookmaker_key: Callable[[T], str],
    source_key: Callable[[T], str],
    outcomes_and_odds: Callable[[T], dict[str, float]],
    market: str,
) -> list[AggregatedMarketProbability]:
    grouped: dict[tuple[str, str], dict[str, tuple[float, str]]] = defaultdict(dict)
    labels: dict[tuple[str, str], str] = {}
    for row in rows:
        entity = entity_key(row)
        bookmaker = bookmaker_key(row).casefold()
        for outcome, odds in outcomes_and_odds(row).items():
            key = outcome.casefold()
            labels.setdefault((entity, key), outcome)
            # Deterministic duplicate handling: retain the first validated row.
            grouped[(entity, bookmaker)].setdefault(
                key,
                (float(odds), source_key(row)),
            )

    probabilities: dict[str, dict[str, list[tuple[float, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for (entity, _bookmaker), outcome_values in grouped.items():
        if not outcome_values:
            continue
        normalized = normalize_implied_probabilities(
            {outcome: value[0] for outcome, value in outcome_values.items()}
        )
        for outcome, probability in normalized.items():
            probabilities[entity][outcome].append(
                (probability, outcome_values[outcome][1])
            )

    results: list[AggregatedMarketProbability] = []
    for entity, outcomes in probabilities.items():
        stats: dict[str, dict[str, float | int | str]] = {}
        for outcome, values_and_sources in outcomes.items():
            values = [item[0] for item in values_and_sources]
            sources = sorted({item[1] for item in values_and_sources})
            stats[outcome] = {
                "mean": mean(values),
                "median": median(values),
                "min": min(values),
                "max": max(values),
                "count": len(values),
                "sources": "+".join(sources),
            }
        final = renormalize_probabilities(
            {outcome: float(values["median"]) for outcome, values in stats.items()}
        )
        for outcome in sorted(stats):
            values = stats[outcome]
            results.append(
                AggregatedMarketProbability(
                    entity_id=entity,
                    market=market,
                    outcome=(
                        outcome.upper()
                        if market in {"1x2", "btts"}
                        else labels[(entity, outcome)]
                    ),
                    probability=final[outcome],
                    mean_probability=float(values["mean"]),
                    median_probability=float(values["median"]),
                    min_probability=float(values["min"]),
                    max_probability=float(values["max"]),
                    bookmaker_count=int(values["count"]),
                    source_used=str(values["sources"]),
                )
            )
    return results


def aggregate_1x2(rows: Iterable[Raw1X2Odd]) -> list[AggregatedMarketProbability]:
    return _aggregate_market(
        rows,
        entity_key=lambda row: row.fixture_id,
        bookmaker_key=lambda row: row.bookmaker,
        source_key=lambda row: row.source,
        outcomes_and_odds=lambda row: {
            "HOME": row.home_win_odds,
            "DRAW": row.draw_odds,
            "AWAY": row.away_win_odds,
        },
        market="1x2",
    )


def aggregate_correct_score(
    rows: Iterable[RawCorrectScoreOdd],
) -> list[AggregatedMarketProbability]:
    return _aggregate_market(
        rows,
        entity_key=lambda row: row.fixture_id,
        bookmaker_key=lambda row: row.bookmaker,
        source_key=lambda row: row.source,
        outcomes_and_odds=lambda row: {row.score: row.odds},
        market="correct_score_full_time",
    )


def aggregate_ou_btts(
    rows: Iterable[RawOUBTTSOdd],
) -> list[AggregatedMarketProbability]:
    rows = list(rows)
    totals = _aggregate_market(
        rows,
        entity_key=lambda row: row.fixture_id,
        bookmaker_key=lambda row: row.bookmaker,
        source_key=lambda row: row.source,
        outcomes_and_odds=lambda row: {
            key: value
            for key, value in {
                "OVER_2.5": row.over_2_5_odds,
                "UNDER_2.5": row.under_2_5_odds,
            }.items()
            if value is not None
        },
        market="over_under_2_5",
    )
    btts = _aggregate_market(
        rows,
        entity_key=lambda row: row.fixture_id,
        bookmaker_key=lambda row: row.bookmaker,
        source_key=lambda row: row.source,
        outcomes_and_odds=lambda row: {
            key: value
            for key, value in {
                "YES": row.btts_yes_odds,
                "NO": row.btts_no_odds,
            }.items()
            if value is not None
        },
        market="btts",
    )
    return totals + btts


def aggregate_outrights(
    rows: Iterable[RawOutrightOdd],
) -> list[AggregatedMarketProbability]:
    return _aggregate_market(
        rows,
        entity_key=lambda _row: "WORLD_CUP_2026",
        bookmaker_key=lambda row: row.bookmaker,
        source_key=lambda row: row.source,
        outcomes_and_odds=lambda row: {row.country: row.odds},
        market="outright_winner",
    )


def aggregate_topscorers(
    rows: Iterable[RawTopGoalscorerOdd],
) -> list[AggregatedMarketProbability]:
    return _aggregate_market(
        rows,
        entity_key=lambda _row: "WORLD_CUP_2026",
        bookmaker_key=lambda row: row.bookmaker,
        source_key=lambda row: row.source,
        outcomes_and_odds=lambda row: {row.player: row.odds},
        market="top_goalscorer",
    )
