from scorito_wk_odds_optimizer.source_oddsportal import OddsPortalScraper


def test_extract_decimal_odds_handles_duplicate_responsive_text() -> None:
    assert OddsPortalScraper.extract_decimal_odds_from_text("5.805.80") == [
        5.8,
        5.8,
    ]
    assert OddsPortalScraper.extract_decimal_odds_from_text(
        "1001.001001.00"
    ) == [1001.0, 1001.0]
