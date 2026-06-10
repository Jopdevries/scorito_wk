from scorito_wk_odds_optimizer.rules import load_rules
from scorito_wk_odds_optimizer.schemas import (
    AggregatedMarketProbability,
    OutrightRecommendation,
    PlayerMetadata,
)
from scorito_wk_odds_optimizer.topscorer_optimizer import optimize_topscorers


def _market(player: str, probability: float):
    return AggregatedMarketProbability(
        entity_id="WORLD_CUP_2026",
        market="top_goalscorer",
        outcome=player,
        probability=probability,
        mean_probability=probability,
        median_probability=probability,
        min_probability=probability,
        max_probability=probability,
        bookmaker_count=5,
        source_used="test",
    )


def _meta(player: str, country: str, position: str, penalty: int = 0):
    return PlayerMetadata(
        player=player,
        country=country,
        position=position,
        position_confidence="HIGH",
        starter_prob=0.90,
        penalty_taker=penalty,
        set_piece_taker=0,
        minutes_risk="LOW",
        source="test",
        notes="",
    )


def _outright(country: str, probability: float):
    return OutrightRecommendation(
        country=country,
        p_champion=probability,
        winner_odds_median=1 / probability,
        bookmaker_count=5,
        recommended=False,
        confidence="HIGH",
        notes="",
    )


def test_midfielder_with_penalties_ranks_above_similar_forward() -> None:
    result = optimize_topscorers(
        [_market("Mid", 0.10), _market("Forward", 0.11)],
        [_meta("Mid", "A", "MID", 1), _meta("Forward", "A", "FWD")],
        [_outright("A", 0.20)],
        load_rules(),
    )
    assert result[0].player == "Mid"


def test_unknown_position_uses_forward_points_and_low_confidence() -> None:
    result = optimize_topscorers(
        [_market("Unknown", 1.0)],
        [],
        [_outright("A", 0.20)],
        load_rules(),
        {"Unknown": "A"},
    )[0]
    assert result.position == "UNKNOWN"
    assert result.position_points == load_rules().topscorers.group_stage.FWD
    assert result.position_confidence == "LOW"


def test_strong_team_progression_increases_value() -> None:
    result = optimize_topscorers(
        [_market("Strong", 0.5), _market("Weak", 0.5)],
        [_meta("Strong", "A", "FWD"), _meta("Weak", "B", "FWD")],
        [_outright("A", 0.36), _outright("B", 0.04)],
        load_rules(),
    )
    assert result[0].player == "Strong"
    assert result[0].estimated_scorito_value > result[1].estimated_scorito_value
