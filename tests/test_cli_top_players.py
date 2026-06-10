from datetime import UTC, datetime

from scorito_wk_odds_optimizer.cli import _top_player_country_pairs
from scorito_wk_odds_optimizer.schemas import RawTopGoalscorerOdd


def test_api_football_players_are_limited_to_market_top_100() -> None:
    now = datetime.now(UTC)
    rows = [
        RawTopGoalscorerOdd(
            player=f"Player {index:03d}",
            country=f"Country {index:03d}",
            bookmaker="Bookmaker",
            odds=float(index + 2),
            source="test",
            scraped_at=now,
        )
        for index in range(120)
    ]

    result = _top_player_country_pairs(rows)

    assert len(result) == 100
    assert result[0] == ("Player 000", "Country 000")
    assert result[-1] == ("Player 099", "Country 099")
    assert all(player != "Player 100" for player, _country in result)
