from datetime import UTC, datetime

import pytest

from scorito_wk_odds_optimizer.market_aggregation import aggregate_1x2
from scorito_wk_odds_optimizer.schemas import Raw1X2Odd


def _odd(bookmaker: str, home: float, draw: float, away: float) -> Raw1X2Odd:
    return Raw1X2Odd(
        fixture_id="fixture",
        bookmaker=bookmaker,
        home_win_odds=home,
        draw_odds=draw,
        away_win_odds=away,
        source="test",
        scraped_at=datetime.now(UTC),
    )


def test_aggregate_uses_median_and_renormalizes() -> None:
    rows = [
        _odd("A", 1.50, 4.50, 8.50),
        _odd("B", 1.48, 4.56, 8.90),
        _odd("C", 1.46, 4.70, 9.20),
    ]
    result = aggregate_1x2(rows)
    assert len(result) == 3
    assert sum(row.probability for row in result) == pytest.approx(1.0)
    assert all(row.bookmaker_count == 3 for row in result)
    home = next(row for row in result if row.outcome == "HOME")
    assert home.median_probability > home.min_probability
    assert home.median_probability < home.max_probability


def test_duplicate_bookmaker_is_deduplicated_deterministically() -> None:
    first = _odd("A", 1.50, 4.50, 8.50)
    duplicate = _odd("A", 2.00, 3.00, 4.00)
    result = aggregate_1x2([first, duplicate])
    assert all(row.bookmaker_count == 1 for row in result)
    clean = aggregate_1x2([first])
    assert [row.probability for row in result] == pytest.approx(
        [row.probability for row in clean]
    )
