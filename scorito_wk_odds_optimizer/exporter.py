from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .schemas import (
    Fixture,
    MatchPrediction,
    OutrightRecommendation,
    ScoreCandidate,
    TopscorerRecommendation,
)


MATCH_COLUMNS = [
    "kickoff_datetime",
    "fixture_id",
    "home_team",
    "away_team",
    "recommended_score",
    "recommended_result",
    "expected_scorito_points",
    "p_home",
    "p_draw",
    "p_away",
    "p_exact_recommended",
    "most_likely_exact_score",
    "most_likely_exact_score_probability",
    "most_likely_1x2",
    "recommended_differs_from_most_likely_exact",
    "x1x2_bookmaker_count",
    "correct_score_bookmaker_count",
    "confidence",
    "source_used",
    "notes",
]


def write_csv(
    path: str | Path,
    rows: list[BaseModel | dict[str, Any]],
    columns: list[str],
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            raw = row.model_dump(mode="json") if isinstance(row, BaseModel) else row
            writer.writerow({column: raw.get(column, "") for column in columns})


def export_all(
    output_dir: str | Path,
    fixtures: list[Fixture],
    predictions: list[MatchPrediction],
    candidates: list[ScoreCandidate],
    outrights: list[OutrightRecommendation],
    rankings: list[dict[str, Any]],
    consistency_warnings: list[dict[str, str]],
    topscorers: list[TopscorerRecommendation],
    quality_warnings: list[dict[str, str]],
    validation_errors: list[dict[str, str]],
    source_failures: list[str],
    failed_fixture_count: int,
    timestamp: datetime,
) -> None:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    prediction_ids = {row.fixture_id for row in predictions}
    match_rows: list[BaseModel | dict[str, Any]] = list(predictions)
    match_rows.extend(
        {
            "kickoff_datetime": fixture.kickoff_datetime.isoformat(),
            "fixture_id": fixture.fixture_id,
            "home_team": fixture.home_team,
            "away_team": fixture.away_team,
            "recommended_score": "",
            "recommended_result": "",
            "expected_scorito_points": "",
            "p_home": "",
            "p_draw": "",
            "p_away": "",
            "p_exact_recommended": "",
            "most_likely_exact_score": "",
            "most_likely_exact_score_probability": "",
            "most_likely_1x2": "",
            "recommended_differs_from_most_likely_exact": "",
            "x1x2_bookmaker_count": 0,
            "correct_score_bookmaker_count": 0,
            "confidence": "FAILED",
            "source_used": fixture.source,
            "notes": "FAILED: missing usable 1X2 and/or correct-score market.",
        }
        for fixture in fixtures
        if fixture.fixture_id not in prediction_ids
    )
    match_rows.sort(key=lambda row: _match_row_kickoff(row))
    write_csv(root / "match_predictions.csv", match_rows, MATCH_COLUMNS)
    write_csv(
        root / "all_score_candidates.csv",
        candidates,
        list(ScoreCandidate.model_fields),
    )
    write_csv(
        root / "outright_recommendations.csv",
        outrights,
        list(OutrightRecommendation.model_fields),
    )
    write_csv(
        root / "group_rankings_from_predictions.csv",
        rankings,
        [
            "group",
            "rank",
            "team",
            "points",
            "goal_difference",
            "goals_for",
            "goals_against",
            "notes",
        ],
    )
    write_csv(
        root / "consistency_warnings.csv",
        consistency_warnings,
        [
            "warning_type",
            "fixture_id",
            "home_team",
            "away_team",
            "group",
            "warning_text",
        ],
    )
    write_csv(
        root / "topscorer_recommendations.csv",
        topscorers,
        list(TopscorerRecommendation.model_fields),
    )
    if quality_warnings:
        write_csv(
            root / "quality_gate_warnings.csv",
            quality_warnings,
            ["check", "entity", "warning"],
        )
    elif (root / "quality_gate_warnings.csv").exists():
        (root / "quality_gate_warnings.csv").unlink()
    if validation_errors:
        columns = sorted({key for row in validation_errors for key in row})
        write_csv(root / "validation_errors.csv", validation_errors, columns)
    elif (root / "validation_errors.csv").exists():
        (root / "validation_errors.csv").unlink()
    _export_entry_sheet(root, predictions, outrights, rankings, topscorers)
    _export_summary(
        root,
        predictions,
        outrights,
        rankings,
        topscorers,
        source_failures,
        failed_fixture_count,
        timestamp,
    )


def _match_row_kickoff(row: BaseModel | dict[str, Any]) -> str:
    if isinstance(row, BaseModel):
        return str(row.model_dump(mode="json").get("kickoff_datetime", ""))
    return str(row.get("kickoff_datetime", ""))


def _export_entry_sheet(
    root: Path,
    predictions: list[MatchPrediction],
    outrights: list[OutrightRecommendation],
    rankings: list[dict[str, Any]],
    topscorers: list[TopscorerRecommendation],
) -> None:
    rows: list[dict[str, str]] = []
    for prediction in sorted(predictions, key=lambda item: item.kickoff_datetime):
        rows.append(
            {
                "section": "MATCH",
                "item": f"{prediction.home_team} - {prediction.away_team}",
                "recommendation": prediction.recommended_score,
                "confidence": prediction.confidence,
                "reason": (
                    f"Maximum Scorito EV: "
                    f"{prediction.expected_scorito_points:.3f} points"
                ),
            }
        )
    champion = next((row for row in outrights if row.recommended), None)
    if champion:
        rows.append(
            {
                "section": "WORLD_CHAMPION",
                "item": "World champion",
                "recommendation": champion.country,
                "confidence": champion.confidence,
                "reason": f"Highest market probability: {champion.p_champion:.3%}",
            }
        )
    groups: dict[str, list[dict[str, Any]]] = {}
    for ranking in rankings:
        groups.setdefault(str(ranking["group"]), []).append(ranking)
    for group, group_rows in sorted(groups.items()):
        recommendation = " > ".join(
            row["team"] for row in sorted(group_rows, key=lambda item: item["rank"])
        )
        rows.append(
            {
                "section": "GROUP_RANKING",
                "item": f"Group {group}",
                "recommendation": recommendation,
                "confidence": "LOW"
                if any(row["notes"] for row in group_rows)
                else "MEDIUM",
                "reason": "Ranking implied by recommended match scores.",
            }
        )
    for recommendation in topscorers[:20]:
        rows.append(
            {
                "section": "TOPSCORER",
                "item": f"Rank {recommendation.rank}: {recommendation.player}",
                "recommendation": recommendation.player,
                "confidence": recommendation.position_confidence,
                "reason": recommendation.rationale,
            }
        )
    write_csv(
        root / "final_scorito_entry_sheet.csv",
        rows,
        ["section", "item", "recommendation", "confidence", "reason"],
    )


def _export_summary(
    root: Path,
    predictions: list[MatchPrediction],
    outrights: list[OutrightRecommendation],
    rankings: list[dict[str, Any]],
    topscorers: list[TopscorerRecommendation],
    source_failures: list[str],
    failed_fixture_count: int,
    timestamp: datetime,
) -> None:
    confidence_counts = {
        level: sum(row.confidence == level for row in predictions)
        for level in ("HIGH", "MEDIUM", "LOW")
    }
    lines = [
        "# Scorito WK 2026 odds optimizer summary",
        "",
        f"- Timestamp: {timestamp.isoformat()}",
        f"- Fixtures processed: {len(predictions)}",
        f"- Failed fixtures: {failed_fixture_count}",
        f"- Confidence: HIGH {confidence_counts['HIGH']}, MEDIUM {confidence_counts['MEDIUM']}, LOW {confidence_counts['LOW']}",
        "",
        "## Chronological recommended Scorito scores",
        "",
    ]
    lines.extend(
        f"- {row.kickoff_datetime.isoformat()} | {row.home_team} - "
        f"{row.away_team}: **{row.recommended_score}** ({row.confidence})"
        for row in sorted(predictions, key=lambda item: item.kickoff_datetime)
    )
    lines.extend(["", "## Recommendations differing from most likely exact score", ""])
    differing = [
        row for row in predictions if row.recommended_differs_from_most_likely_exact
    ]
    lines.extend(
        (
            f"- {row.home_team} - {row.away_team}: recommended "
            f"{row.recommended_score}, most likely {row.most_likely_exact_score}"
        )
        for row in differing
    )
    if not differing:
        lines.append("- None")
    champion = next((row for row in outrights if row.recommended), None)
    lines.extend(
        [
            "",
            "## World champion recommendation",
            "",
            (
                f"- {champion.country} ({champion.p_champion:.3%}, "
                f"{champion.confidence})"
                if champion
                else "- FAILED: no usable outright data"
            ),
            "",
            "## Group rankings from predictions",
            "",
        ]
    )
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rankings:
        groups.setdefault(str(row["group"]), []).append(row)
    for group, rows in sorted(groups.items()):
        order = " > ".join(
            row["team"] for row in sorted(rows, key=lambda item: item["rank"])
        )
        lines.append(f"- Group {group}: {order}")
    if not rankings:
        lines.append("- Not available")
    lines.extend(["", "## Top 20 Scorito-weighted topscorer picks", ""])
    lines.extend(
        f"- {row.rank}. {row.player} ({row.country or 'UNKNOWN'}, "
        f"{row.position}) - {row.estimated_scorito_value:.5f}"
        for row in topscorers[:20]
    )
    if not topscorers:
        lines.append("- FAILED: no usable topscorer data")
    lines.extend(["", "## Missing metadata warnings", ""])
    missing = [row for row in topscorers if row.position == "UNKNOWN"]
    lines.extend(f"- {row.player}: {row.rationale}" for row in missing)
    if not missing:
        lines.append("- None")
    lines.extend(["", "## Source failures", ""])
    lines.extend(f"- {failure}" for failure in source_failures)
    if not source_failures:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Required warnings",
            "",
            "- WARNING: Verify these values against the official Scorito WK 2026 rules before submitting predictions.",
            "- OddsPortal and Oddschecker scraping is fragile and may break when page structures change.",
            "- Bookmaker-implied probabilities are estimates, not guaranteed true probabilities.",
            "- This is not a betting tool.",
        ]
    )
    (root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
