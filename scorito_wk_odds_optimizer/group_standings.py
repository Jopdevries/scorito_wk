from __future__ import annotations

from collections import defaultdict
from typing import Any

from .schemas import Fixture, MatchPrediction


def compute_group_standings(
    fixtures: list[Fixture],
    predictions: list[MatchPrediction],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    fixtures_by_id = {fixture.fixture_id: fixture for fixture in fixtures}
    tables: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(
            lambda: {"points": 0, "goals_for": 0, "goals_against": 0}
        )
    )
    low_confidence_groups: set[str] = set()
    warnings: list[dict[str, str]] = []

    for prediction in predictions:
        fixture = fixtures_by_id.get(prediction.fixture_id)
        group = fixture.group if fixture and fixture.group else "UNKNOWN"
        if group == "UNKNOWN":
            warnings.append(
                _warning(
                    "group_labels_missing",
                    prediction,
                    group,
                    "Group label missing; ranking placed in UNKNOWN.",
                )
            )
        if prediction.confidence == "LOW":
            low_confidence_groups.add(group)
        if prediction.recommended_differs_from_most_likely_exact:
            warnings.append(
                _warning(
                    "recommended_differs_from_most_likely_exact",
                    prediction,
                    group,
                    "Recommended score differs from the most likely exact score.",
                )
            )
        home_goals, away_goals = (
            int(value) for value in prediction.recommended_score.split("-", 1)
        )
        home = tables[group][prediction.home_team]
        away = tables[group][prediction.away_team]
        home["goals_for"] += home_goals
        home["goals_against"] += away_goals
        away["goals_for"] += away_goals
        away["goals_against"] += home_goals
        if home_goals > away_goals:
            home["points"] += 3
        elif home_goals < away_goals:
            away["points"] += 3
        else:
            home["points"] += 1
            away["points"] += 1

    rankings: list[dict[str, Any]] = []
    for group, teams in sorted(tables.items()):
        ordered = sorted(
            teams.items(),
            key=lambda item: (
                -item[1]["points"],
                -(item[1]["goals_for"] - item[1]["goals_against"]),
                -item[1]["goals_for"],
                item[0].casefold(),
            ),
        )
        fallback_teams: set[str] = set()
        for index in range(1, len(ordered)):
            previous_name, previous = ordered[index - 1]
            current_name, current = ordered[index]
            previous_key = (
                previous["points"],
                previous["goals_for"] - previous["goals_against"],
                previous["goals_for"],
            )
            current_key = (
                current["points"],
                current["goals_for"] - current["goals_against"],
                current["goals_for"],
            )
            if previous_key == current_key:
                fallback_teams.update({previous_name, current_name})
        for rank, (team, values) in enumerate(ordered, start=1):
            note = (
                "Tie-break unresolved; alphabetical fallback used."
                if team in fallback_teams
                else ""
            )
            rankings.append(
                {
                    "group": group,
                    "rank": rank,
                    "team": team,
                    "points": values["points"],
                    "goal_difference": (
                        values["goals_for"] - values["goals_against"]
                    ),
                    "goals_for": values["goals_for"],
                    "goals_against": values["goals_against"],
                    "notes": note,
                }
            )
        if fallback_teams:
            warnings.append(
                {
                    "warning_type": "group_winner_unresolved_tiebreak",
                    "fixture_id": "",
                    "home_team": "",
                    "away_team": "",
                    "group": group,
                    "warning_text": (
                        "Group ranking includes an unresolved tie; alphabetical "
                        "fallback was used."
                    ),
                }
            )
        if group in low_confidence_groups:
            warnings.append(
                {
                    "warning_type": "group_depends_on_low_confidence",
                    "fixture_id": "",
                    "home_team": "",
                    "away_team": "",
                    "group": group,
                    "warning_text": "Group ranking depends on LOW confidence fixtures.",
                }
            )
    return rankings, warnings


def _warning(
    warning_type: str,
    prediction: MatchPrediction,
    group: str,
    text: str,
) -> dict[str, str]:
    return {
        "warning_type": warning_type,
        "fixture_id": prediction.fixture_id,
        "home_team": prediction.home_team,
        "away_team": prediction.away_team,
        "group": group,
        "warning_text": text,
    }
