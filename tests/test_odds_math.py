import pytest

from scorito_wk_odds_optimizer.odds_math import (
    fractional_to_decimal,
    normalize_implied_probabilities,
)


def test_normalize_implied_probabilities() -> None:
    probabilities = normalize_implied_probabilities(
        {"HOME": 1.48, "DRAW": 4.56, "AWAY": 8.90}
    )
    assert probabilities["HOME"] == pytest.approx(0.671, abs=0.001)
    assert probabilities["DRAW"] == pytest.approx(0.218, abs=0.001)
    assert probabilities["AWAY"] == pytest.approx(0.111, abs=0.001)
    assert sum(probabilities.values()) == pytest.approx(1.0)


def test_fractional_odds_to_decimal() -> None:
    assert fractional_to_decimal("5/1") == 6.0


@pytest.mark.parametrize("odds", [1.0, 0.0, -2.0, float("nan")])
def test_invalid_decimal_odds_rejected(odds: float) -> None:
    with pytest.raises(ValueError):
        normalize_implied_probabilities({"HOME": odds})
