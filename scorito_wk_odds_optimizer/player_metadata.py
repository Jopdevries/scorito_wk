from __future__ import annotations

from pathlib import Path

import yaml

from .schemas import PlayerMetadata, RawTopGoalscorerOdd


def resolve_player_metadata(
    topscorer_odds: list[RawTopGoalscorerOdd],
    api_metadata: list[PlayerMetadata] | None = None,
    manual_metadata: list[PlayerMetadata] | None = None,
    overrides_path: str | Path = "config/player_position_overrides.yaml",
) -> list[PlayerMetadata]:
    resolved: dict[str, PlayerMetadata] = {}
    for rows in (manual_metadata or [], api_metadata or []):
        for row in rows:
            resolved[row.player.casefold()] = row

    path = Path(overrides_path)
    overrides = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            overrides = yaml.safe_load(handle) or {}
    for player, value in overrides.items():
        details = value if isinstance(value, dict) else {"position": value}
        existing = resolved.get(player.casefold())
        resolved[player.casefold()] = PlayerMetadata(
            player=player,
            country=details.get("country") or (existing.country if existing else None),
            position=str(details.get("position", "UNKNOWN")).upper(),
            position_confidence="HIGH",
            starter_prob=float(
                details.get(
                    "starter_prob",
                    existing.starter_prob if existing else 0.90,
                )
            ),
            penalty_taker=int(
                details.get(
                    "penalty_taker",
                    existing.penalty_taker if existing else 0,
                )
            ),
            set_piece_taker=int(
                details.get(
                    "set_piece_taker",
                    existing.set_piece_taker if existing else 0,
                )
            ),
            minutes_risk=str(
                details.get(
                    "minutes_risk",
                    existing.minutes_risk if existing else "MEDIUM",
                )
            ).upper(),
            source="player_position_overrides",
            notes=str(details.get("notes", "")),
        )

    countries: dict[str, str | None] = {}
    names: dict[str, str] = {}
    for odd in topscorer_odds:
        key = odd.player.casefold()
        names.setdefault(key, odd.player)
        if odd.country:
            countries.setdefault(key, odd.country)
    for key, player in names.items():
        if key not in resolved:
            resolved[key] = PlayerMetadata(
                player=player,
                country=countries.get(key),
                position="UNKNOWN",
                position_confidence="LOW",
                starter_prob=0.90,
                penalty_taker=0,
                set_piece_taker=0,
                minutes_risk="MEDIUM",
                source="UNKNOWN",
                notes="Position missing; treated as FWD conservatively.",
            )
        elif resolved[key].country is None and countries.get(key):
            resolved[key] = resolved[key].model_copy(
                update={"country": countries[key]}
            )
    return sorted(resolved.values(), key=lambda item: item.player.casefold())
