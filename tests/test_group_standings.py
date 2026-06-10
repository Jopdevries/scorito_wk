from datetime import UTC, datetime

from scorito_wk_odds_optimizer.group_standings import compute_group_standings
from scorito_wk_odds_optimizer.schemas import Fixture, MatchPrediction


def _fixture(fixture_id: str, home: str, away: str) -> Fixture:
    return Fixture(
        fixture_id=fixture_id,
        kickoff_datetime=datetime(2026, 6, 11, tzinfo=UTC),
        home_team=home,
        away_team=away,
        match_url=None,
        group="A",
        source="test",
    )


def _prediction(
    fixture_id: str,
    home: str,
    away: str,
    score: str,
) -> MatchPrediction:
    return MatchPrediction(
        fixture_id=fixture_id,
        kickoff_datetime=datetime(2026, 6, 11, tzinfo=UTC),
        home_team=home,
        away_team=away,
        recommended_score=score,
        recommended_result="DRAW" if score == "0-0" else "HOME",
        expected_scorito_points=10,
        p_home=0.4,
        p_draw=0.3,
        p_away=0.3,
        p_exact_recommended=0.1,
        most_likely_exact_score=score,
        most_likely_exact_score_probability=0.1,
        most_likely_1x2="HOME",
        recommended_differs_from_most_likely_exact=False,
        x1x2_bookmaker_count=5,
        correct_score_bookmaker_count=5,
        confidence="HIGH",
        source_used="test",
        notes="",
    )


def test_group_table_points_goal_difference_and_goals_for() -> None:
    fixtures = [_fixture("1", "A", "B"), _fixture("2", "A", "C")]
    predictions = [
        _prediction("1", "A", "B", "2-0"),
        _prediction("2", "A", "C", "1-1"),
    ]
    rankings, _ = compute_group_standings(fixtures, predictions)
    team_a = next(row for row in rankings if row["team"] == "A")
    assert team_a["points"] == 4
    assert team_a["goal_difference"] == 2
    assert team_a["goals_for"] == 3


def test_tiebreak_fallback_adds_warning() -> None:
    fixtures = [_fixture("1", "A", "B")]
    predictions = [_prediction("1", "A", "B", "0-0")]
    rankings, warnings = compute_group_standings(fixtures, predictions)
    assert all("alphabetical fallback" in row["notes"] for row in rankings)
    assert any(
        row["warning_type"] == "group_winner_unresolved_tiebreak"
        for row in warnings
    )
