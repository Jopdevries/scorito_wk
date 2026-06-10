from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .schemas import (
    Fixture,
    PlayerMetadata,
    Raw1X2Odd,
    RawCorrectScoreOdd,
    RawOUBTTSOdd,
    RawOutrightOdd,
    RawTopGoalscorerOdd,
)


@dataclass
class ManualData:
    fixtures: list[Fixture] = field(default_factory=list)
    x1x2: list[Raw1X2Odd] = field(default_factory=list)
    correct_scores: list[RawCorrectScoreOdd] = field(default_factory=list)
    ou_btts: list[RawOUBTTSOdd] = field(default_factory=list)
    outrights: list[RawOutrightOdd] = field(default_factory=list)
    topscorers: list[RawTopGoalscorerOdd] = field(default_factory=list)
    player_metadata: list[PlayerMetadata] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


def load_manual_data(input_dir: str | Path = "input") -> ManualData:
    root = Path(input_dir)
    data = ManualData()
    now = datetime.now(UTC)
    specs: list[tuple[str, type, str, dict[str, Any]]] = [
        (
            "manual_fixtures.csv",
            Fixture,
            "fixtures",
            {"source": "manual"},
        ),
        (
            "manual_1x2_odds.csv",
            Raw1X2Odd,
            "x1x2",
            {"source": "manual", "scraped_at": now},
        ),
        (
            "manual_correct_score_odds.csv",
            RawCorrectScoreOdd,
            "correct_scores",
            {"source": "manual", "scraped_at": now},
        ),
        (
            "manual_ou_btts_odds.csv",
            RawOUBTTSOdd,
            "ou_btts",
            {"source": "manual", "scraped_at": now},
        ),
        (
            "manual_outright_odds.csv",
            RawOutrightOdd,
            "outrights",
            {"source": "manual", "scraped_at": now},
        ),
        (
            "manual_top_goalscorer_odds.csv",
            RawTopGoalscorerOdd,
            "topscorers",
            {"source": "manual", "scraped_at": now},
        ),
        (
            "manual_player_metadata.csv",
            PlayerMetadata,
            "player_metadata",
            {
                "source": "manual",
                "position_confidence": "MEDIUM",
                "notes": "",
            },
        ),
    ]
    for filename, model, target, defaults in specs:
        path = root / filename
        if not path.exists() or path.stat().st_size == 0:
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for line_number, row in enumerate(csv.DictReader(handle), start=2):
                values = {
                    key: _empty_to_none(value)
                    for key, value in row.items()
                    if key is not None
                }
                values.update(defaults)
                try:
                    getattr(data, target).append(model.model_validate(values))
                except (ValidationError, ValueError) as exc:
                    data.errors.append(
                        {
                            "file": filename,
                            "line": str(line_number),
                            "error": str(exc),
                        }
                    )
    return data


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value if value else None
