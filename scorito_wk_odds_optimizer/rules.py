from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field
from rich.console import Console
from rich.table import Table


class MatchStageRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correct_toto_points: float = Field(gt=0)
    exact_score_points: float = Field(gt=0)


class MatchPredictionRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_stage: MatchStageRules


class GroupRankingRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correct_group_position_points: float = Field(gt=0)


class TopscorerStageRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    GK: float = Field(gt=0)
    DEF: float = Field(gt=0)
    MID: float = Field(gt=0)
    FWD: float = Field(gt=0)


class TopscorerRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_stage: TopscorerStageRules
    round_of_32_multiplier: float = Field(gt=0)
    round_of_16_multiplier: float = Field(gt=0)
    quarter_final_multiplier: float = Field(gt=0)
    semi_final_multiplier: float = Field(gt=0)
    final_multiplier: float = Field(gt=0)


class WinnerPredictionRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    world_champion_points: float = Field(gt=0)


class ScoritoRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_predictions: MatchPredictionRules
    group_rankings: GroupRankingRules
    topscorers: TopscorerRules
    winner_prediction: WinnerPredictionRules


def load_rules(path: str | Path = "config/scorito_rules.yaml") -> ScoritoRules:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle)
    return ScoritoRules.model_validate(raw)


def print_rules_table(rules: ScoritoRules, console: Console | None = None) -> None:
    console = console or Console()
    table = Table(title="Scorito WK 2026 rules")
    table.add_column("Rule")
    table.add_column("Points / multiplier", justify="right")
    match = rules.match_predictions.group_stage
    table.add_row("Match prediction (toto)", f"{match.correct_toto_points:g}")
    table.add_row("Exact score", f"{match.exact_score_points:g}")
    table.add_row(
        "Correct group position",
        f"{rules.group_rankings.correct_group_position_points:g}",
    )
    for position in ("GK", "DEF", "MID", "FWD"):
        table.add_row(
            f"Top scorer group-stage goal ({position})",
            f"{getattr(rules.topscorers.group_stage, position):g}",
        )
    table.add_row("Round of 32 multiplier", f"{rules.topscorers.round_of_32_multiplier:g}")
    table.add_row("Round of 16 multiplier", f"{rules.topscorers.round_of_16_multiplier:g}")
    table.add_row("Quarter-final multiplier", f"{rules.topscorers.quarter_final_multiplier:g}")
    table.add_row("Semi-final multiplier", f"{rules.topscorers.semi_final_multiplier:g}")
    table.add_row("Final multiplier", f"{rules.topscorers.final_multiplier:g}")
    table.add_row(
        "World champion",
        f"{rules.winner_prediction.world_champion_points:g}",
    )
    console.print(table)
    console.print(
        "[bold yellow]WARNING: Verify these values against the official Scorito "
        "WK 2026 rules before submitting predictions.[/bold yellow]"
    )
