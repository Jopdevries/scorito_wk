from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Odds = Annotated[float, Field(gt=1.0)]
Probability = Annotated[float, Field(ge=0.0, le=1.0)]
SCORE_PATTERN = re.compile(r"^[0-9]+-[0-9]+$")
VALID_POSITIONS = {"GK", "DEF", "MID", "FWD", "UNKNOWN"}
VALID_CONFIDENCE = {"HIGH", "MEDIUM", "LOW", "FAILED"}
VALID_MINUTES_RISK = {"LOW", "MEDIUM", "HIGH"}


class StrictModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)


def _finite_odds(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 1.0:
        raise ValueError("odds must be finite and greater than 1.0")
    return value


class Fixture(StrictModel):
    fixture_id: str
    kickoff_datetime: datetime
    home_team: str
    away_team: str
    match_url: str | None = None
    group: str | None = None
    source: str

    @field_validator("fixture_id", "home_team", "away_team", "source")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("value must not be empty")
        return value

    @model_validator(mode="after")
    def different_teams(self) -> "Fixture":
        if self.home_team.casefold() == self.away_team.casefold():
            raise ValueError("home_team and away_team must differ")
        return self


class Raw1X2Odd(StrictModel):
    fixture_id: str
    bookmaker: str
    home_win_odds: Odds
    draw_odds: Odds
    away_win_odds: Odds
    source: str
    scraped_at: datetime

    _home_finite = field_validator("home_win_odds")(_finite_odds)
    _draw_finite = field_validator("draw_odds")(_finite_odds)
    _away_finite = field_validator("away_win_odds")(_finite_odds)


class RawCorrectScoreOdd(StrictModel):
    fixture_id: str
    bookmaker: str
    score: str
    odds: Odds
    source: str
    scraped_at: datetime

    _odds_finite = field_validator("odds")(_finite_odds)

    @field_validator("score")
    @classmethod
    def valid_score(cls, value: str) -> str:
        if not SCORE_PATTERN.fullmatch(value):
            raise ValueError("score must match ^[0-9]+-[0-9]+$")
        return value


class RawOUBTTSOdd(StrictModel):
    fixture_id: str
    bookmaker: str
    over_2_5_odds: float | None = None
    under_2_5_odds: float | None = None
    btts_yes_odds: float | None = None
    btts_no_odds: float | None = None
    source: str
    scraped_at: datetime

    @field_validator(
        "over_2_5_odds",
        "under_2_5_odds",
        "btts_yes_odds",
        "btts_no_odds",
    )
    @classmethod
    def optional_finite_odds(cls, value: float | None) -> float | None:
        return None if value is None else _finite_odds(value)


class RawOutrightOdd(StrictModel):
    country: str
    bookmaker: str
    odds: Odds
    source: str
    scraped_at: datetime

    _odds_finite = field_validator("odds")(_finite_odds)


class RawTopGoalscorerOdd(StrictModel):
    player: str
    country: str | None = None
    bookmaker: str
    odds: Odds
    source: str
    scraped_at: datetime

    _odds_finite = field_validator("odds")(_finite_odds)


class PlayerMetadata(StrictModel):
    player: str
    country: str | None = None
    position: str = "UNKNOWN"
    position_confidence: str = "LOW"
    starter_prob: Probability = 0.90
    penalty_taker: int = Field(default=0, ge=0, le=1)
    set_piece_taker: int = Field(default=0, ge=0, le=1)
    minutes_risk: str = "MEDIUM"
    source: str = "UNKNOWN"
    notes: str = ""

    @field_validator("position")
    @classmethod
    def valid_position(cls, value: str) -> str:
        value = value.upper()
        if value not in VALID_POSITIONS:
            raise ValueError(f"position must be one of {sorted(VALID_POSITIONS)}")
        return value

    @field_validator("position_confidence")
    @classmethod
    def valid_position_confidence(cls, value: str) -> str:
        value = value.upper()
        if value not in {"HIGH", "MEDIUM", "LOW"}:
            raise ValueError("position_confidence must be HIGH, MEDIUM, or LOW")
        return value

    @field_validator("minutes_risk")
    @classmethod
    def valid_minutes_risk(cls, value: str) -> str:
        value = value.upper()
        if value not in VALID_MINUTES_RISK:
            raise ValueError("minutes_risk must be LOW, MEDIUM, or HIGH")
        return value


class AggregatedMarketProbability(StrictModel):
    entity_id: str
    market: str
    outcome: str
    probability: Probability
    mean_probability: Probability
    median_probability: Probability
    min_probability: Probability
    max_probability: Probability
    bookmaker_count: int = Field(ge=1)
    source_used: str


class MatchPrediction(StrictModel):
    fixture_id: str
    kickoff_datetime: datetime
    home_team: str
    away_team: str
    recommended_score: str
    recommended_result: str
    expected_scorito_points: float
    p_home: Probability
    p_draw: Probability
    p_away: Probability
    p_exact_recommended: Probability
    most_likely_exact_score: str
    most_likely_exact_score_probability: Probability
    most_likely_1x2: str
    recommended_differs_from_most_likely_exact: bool
    x1x2_bookmaker_count: int = Field(ge=0)
    correct_score_bookmaker_count: int = Field(ge=0)
    confidence: str
    source_used: str
    notes: str

    _score_valid = field_validator("recommended_score")(
        lambda value: value
        if SCORE_PATTERN.fullmatch(value)
        else (_ for _ in ()).throw(ValueError("invalid recommended score"))
    )


class ScoreCandidate(StrictModel):
    fixture_id: str
    home_team: str
    away_team: str
    score: str
    result: str
    p_exact: Probability
    p_toto: Probability
    expected_scorito_points: float
    bookmaker_count: int = Field(ge=1)
    rank_for_match: int = Field(ge=1)

    @field_validator("score")
    @classmethod
    def valid_score(cls, value: str) -> str:
        if not SCORE_PATTERN.fullmatch(value):
            raise ValueError("invalid score")
        return value


class TopscorerRecommendation(StrictModel):
    rank: int = Field(ge=1)
    player: str
    country: str | None = None
    position: str
    position_confidence: str
    p_topscorer: Probability
    team_progression_proxy: Probability
    position_points: float
    starter_prob: Probability
    penalty_taker: int
    set_piece_taker: int
    minutes_risk: str
    estimated_scorito_value: float
    bookmaker_count: int = Field(ge=1)
    source_used: str
    rationale: str


class OutrightRecommendation(StrictModel):
    country: str
    p_champion: Probability
    winner_odds_median: float
    bookmaker_count: int = Field(ge=1)
    recommended: bool
    confidence: str
    notes: str
