from __future__ import annotations

from collections import defaultdict

from .rules import ScoritoRules
from .schemas import (
    AggregatedMarketProbability,
    Fixture,
    MatchPrediction,
    ScoreCandidate,
)


def score_result(score: str) -> str:
    home, away = (int(value) for value in score.split("-", maxsplit=1))
    if home > away:
        return "HOME"
    if home < away:
        return "AWAY"
    return "DRAW"


def expected_scorito_points(
    p_toto: float,
    p_exact: float,
    correct_toto_points: float,
    exact_score_points: float,
) -> float:
    return (
        correct_toto_points * p_toto
        + (exact_score_points - correct_toto_points) * p_exact
    )


def optimize_matches(
    fixtures: list[Fixture],
    x1x2: list[AggregatedMarketProbability],
    correct_scores: list[AggregatedMarketProbability],
    rules: ScoritoRules,
) -> tuple[list[MatchPrediction], list[ScoreCandidate], list[str]]:
    x1x2_by_fixture: dict[str, dict[str, AggregatedMarketProbability]] = defaultdict(dict)
    correct_by_fixture: dict[str, list[AggregatedMarketProbability]] = defaultdict(list)
    for row in x1x2:
        if row.market == "1x2":
            x1x2_by_fixture[row.entity_id][row.outcome.upper()] = row
    for row in correct_scores:
        if row.market == "correct_score_full_time":
            correct_by_fixture[row.entity_id].append(row)

    predictions: list[MatchPrediction] = []
    all_candidates: list[ScoreCandidate] = []
    failures: list[str] = []
    stage_rules = rules.match_predictions.group_stage

    for fixture in sorted(fixtures, key=lambda item: item.kickoff_datetime):
        result_market = x1x2_by_fixture.get(fixture.fixture_id, {})
        score_market = correct_by_fixture.get(fixture.fixture_id, [])
        if not {"HOME", "DRAW", "AWAY"}.issubset(result_market) or not score_market:
            failures.append(
                f"{fixture.fixture_id}: missing usable 1X2 or correct-score market"
            )
            continue

        p_result = {
            outcome: result_market[outcome].probability
            for outcome in ("HOME", "DRAW", "AWAY")
        }
        ranked: list[tuple[AggregatedMarketProbability, str, float]] = []
        for score_probability in score_market:
            result = score_result(score_probability.outcome)
            ev = expected_scorito_points(
                p_result[result],
                score_probability.probability,
                stage_rules.correct_toto_points,
                stage_rules.exact_score_points,
            )
            ranked.append((score_probability, result, ev))
        ranked.sort(
            key=lambda item: (
                -item[2],
                -item[0].probability,
                item[0].outcome,
            )
        )

        for rank, (score_probability, result, ev) in enumerate(ranked, start=1):
            all_candidates.append(
                ScoreCandidate(
                    fixture_id=fixture.fixture_id,
                    home_team=fixture.home_team,
                    away_team=fixture.away_team,
                    score=score_probability.outcome,
                    result=result,
                    p_exact=score_probability.probability,
                    p_toto=p_result[result],
                    expected_scorito_points=ev,
                    bookmaker_count=score_probability.bookmaker_count,
                    rank_for_match=rank,
                )
            )

        recommended, recommended_result, recommended_ev = ranked[0]
        most_likely_exact = max(
            score_market,
            key=lambda item: (item.probability, item.outcome),
        )
        most_likely_1x2 = max(
            ("HOME", "DRAW", "AWAY"),
            key=lambda outcome: p_result[outcome],
        )
        x1x2_count = min(
            result_market[outcome].bookmaker_count
            for outcome in ("HOME", "DRAW", "AWAY")
        )
        correct_score_count = min(row.bookmaker_count for row in score_market)
        outcome_count = len(score_market)
        if x1x2_count >= 5 and correct_score_count >= 5 and outcome_count >= 10:
            confidence = "HIGH"
        elif x1x2_count >= 3 and correct_score_count >= 3 and outcome_count >= 5:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        sources = sorted(
            {
                *(row.source_used for row in result_market.values()),
                *(row.source_used for row in score_market),
            }
        )
        predictions.append(
            MatchPrediction(
                fixture_id=fixture.fixture_id,
                kickoff_datetime=fixture.kickoff_datetime,
                home_team=fixture.home_team,
                away_team=fixture.away_team,
                recommended_score=recommended.outcome,
                recommended_result=recommended_result,
                expected_scorito_points=recommended_ev,
                p_home=p_result["HOME"],
                p_draw=p_result["DRAW"],
                p_away=p_result["AWAY"],
                p_exact_recommended=recommended.probability,
                most_likely_exact_score=most_likely_exact.outcome,
                most_likely_exact_score_probability=most_likely_exact.probability,
                most_likely_1x2=most_likely_1x2,
                recommended_differs_from_most_likely_exact=(
                    recommended.outcome != most_likely_exact.outcome
                ),
                x1x2_bookmaker_count=x1x2_count,
                correct_score_bookmaker_count=correct_score_count,
                confidence=confidence,
                source_used="+".join(sources),
                notes="Correct-score market normalized over listed scores; "
                "missing_tail_warning=true.",
            )
        )
    return predictions, all_candidates, failures
