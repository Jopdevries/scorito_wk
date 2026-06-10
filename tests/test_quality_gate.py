from datetime import UTC, datetime

from scorito_wk_odds_optimizer.quality_gate import run_quality_gate
from scorito_wk_odds_optimizer.rules import load_rules
from scorito_wk_odds_optimizer.schemas import (
    AggregatedMarketProbability,
    PlayerMetadata,
)


def test_missing_probability_normalization_creates_warning() -> None:
    row = AggregatedMarketProbability(
        entity_id="fixture",
        market="1x2",
        outcome="HOME",
        probability=0.5,
        mean_probability=0.5,
        median_probability=0.5,
        min_probability=0.5,
        max_probability=0.5,
        bookmaker_count=1,
        source_used="test",
    )
    warnings = run_quality_gate(
        load_rules(), [row], [], [], {}, [], [], datetime.now(UTC)
    )
    assert any(item["check"] == "probability_normalization" for item in warnings)


def test_unknown_position_warns_without_crashing() -> None:
    metadata = [
        PlayerMetadata(
            player="Unknown",
            country=None,
            position="UNKNOWN",
            position_confidence="LOW",
            starter_prob=0.9,
            penalty_taker=0,
            set_piece_taker=0,
            minutes_risk="MEDIUM",
            source="UNKNOWN",
            notes="",
        )
    ]
    warnings = run_quality_gate(
        load_rules(), [], [], [], {}, metadata, [], datetime.now(UTC)
    )
    assert any(item["check"] == "player_position" for item in warnings)
