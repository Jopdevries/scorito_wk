from datetime import UTC, datetime

import pytest

from scorito_wk_odds_optimizer.match_optimizer import (
    expected_scorito_points,
    optimize_matches,
)
from scorito_wk_odds_optimizer.rules import load_rules
from scorito_wk_odds_optimizer.schemas import AggregatedMarketProbability, Fixture


def _probability(market: str, outcome: str, probability: float):
    return AggregatedMarketProbability(
        entity_id="fixture",
        market=market,
        outcome=outcome,
        probability=probability,
        mean_probability=probability,
        median_probability=probability,
        min_probability=probability,
        max_probability=probability,
        bookmaker_count=5,
        source_used="test",
    )


def test_expected_scorito_points_formula() -> None:
    expected = expected_scorito_points(0.671, 0.162, 30, 45)
    assert expected == pytest.approx(30 * 0.671 + 15 * 0.162)


def test_ev_dominance_and_recommended_score_is_listed() -> None:
    fixture = Fixture(
        fixture_id="fixture",
        kickoff_datetime=datetime(2026, 6, 11, tzinfo=UTC),
        home_team="Home",
        away_team="Away",
        match_url=None,
        group="A",
        source="test",
    )
    x1x2 = [
        _probability("1x2", "HOME", 0.67),
        _probability("1x2", "DRAW", 0.22),
        _probability("1x2", "AWAY", 0.11),
    ]
    scores = [
        _probability("correct_score_full_time", "1-0", 0.14),
        _probability("correct_score_full_time", "0-0", 0.16),
    ]
    predictions, candidates, failures = optimize_matches(
        [fixture], x1x2, scores, load_rules()
    )
    assert not failures
    assert predictions[0].recommended_score == "1-0"
    assert candidates[0].score == "1-0"
    assert predictions[0].recommended_score in {row.outcome for row in scores}
