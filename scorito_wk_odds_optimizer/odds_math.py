from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from fractions import Fraction


def validate_decimal_odds(odds: float) -> float:
    try:
        value = float(odds)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid decimal odds: {odds!r}") from exc
    if not math.isfinite(value) or value <= 1.0:
        raise ValueError(f"decimal odds must be finite and > 1.0, got {odds!r}")
    return value


def decimal_to_implied_probability(odds: float) -> float:
    return 1.0 / validate_decimal_odds(odds)


def normalize_implied_probabilities(
    odds_by_outcome: Mapping[str, float],
) -> dict[str, float]:
    if not odds_by_outcome:
        raise ValueError("at least one outcome is required")
    raw = {
        outcome: decimal_to_implied_probability(odds)
        for outcome, odds in odds_by_outcome.items()
    }
    total = sum(raw.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("implied probability total must be positive and finite")
    return {outcome: probability / total for outcome, probability in raw.items()}


def renormalize_probabilities(
    probabilities: Mapping[str, float],
) -> dict[str, float]:
    if not probabilities:
        raise ValueError("at least one probability is required")
    cleaned: dict[str, float] = {}
    for outcome, probability in probabilities.items():
        value = float(probability)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid probability for {outcome}: {probability!r}")
        cleaned[outcome] = value
    total = sum(cleaned.values())
    if total <= 0:
        raise ValueError("probability total must be positive")
    return {outcome: value / total for outcome, value in cleaned.items()}


def fractional_to_decimal(value: str) -> float:
    text = value.strip()
    if "/" not in text:
        return validate_decimal_odds(float(text))
    try:
        fraction = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"invalid fractional odds: {value!r}") from exc
    return validate_decimal_odds(float(fraction) + 1.0)


def probabilities_sum_to_one(
    values: Iterable[float],
    tolerance: float = 1e-6,
) -> bool:
    values = list(values)
    return bool(values) and abs(sum(values) - 1.0) <= tolerance
