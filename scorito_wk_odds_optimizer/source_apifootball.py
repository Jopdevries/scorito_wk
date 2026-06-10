from __future__ import annotations

import logging
import os
import time
import unicodedata
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from .logging_utils import load_json, save_json
from .schemas import PlayerMetadata

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://v3.football.api-sports.io"
RAW_PATH = Path("data/raw/apifootball/player_metadata.json")
PARSED_PATH = Path("data/raw/apifootball/parsed_metadata.json")
STATUS_PATH = Path("data/raw/apifootball/status.json")
POSITION_MAP = {
    "Goalkeeper": "GK",
    "Defender": "DEF",
    "Midfielder": "MID",
    "Attacker": "FWD",
}
EXACT_MATCH_NOTE = "Exact accent-insensitive API name match."


def fetch_api_football_metadata(
    players: list[tuple[str, str | None]],
    timeout: int = 30,
    force_retry: bool = False,
) -> list[PlayerMetadata]:
    load_dotenv()
    api_key = os.getenv("API_FOOTBALL_KEY")
    if not api_key:
        LOGGER.debug("API_FOOTBALL_KEY missing; skipping")
        return []
    unique_players: dict[str, tuple[str, str | None]] = {}
    for player_name, expected_country in players[:100]:
        unique_players.setdefault(
            _normalize_name(player_name),
            (player_name, expected_country),
        )
    cached = _load_cached_metadata()
    output: dict[str, PlayerMetadata] = {}
    for row in cached:
        key = _normalize_name(row.player)
        if key not in unique_players or EXACT_MATCH_NOTE not in row.notes:
            continue
        requested_name, expected_country = unique_players[key]
        output[key] = row.model_copy(
            update={
                "player": requested_name,
                "country": expected_country or row.country,
            }
        )
    raw = load_json(RAW_PATH, []) or []
    previous_status = load_json(STATUS_PATH, {}) or {}
    no_match_keys = {
        _normalize_name(str(name))
        for name in previous_status.get("no_match_players", [])
    }
    pending = [
        pair
        for key, pair in unique_players.items()
        if key not in output and key not in no_match_keys
    ]
    _save_cache(raw, list(output.values()))
    now = datetime.now(UTC)
    retry_after_at = _retry_after_at(previous_status)
    if (
        previous_status.get("status") == "RATE_LIMITED"
        and retry_after_at is not None
        and now < retry_after_at
        and not force_retry
    ):
        save_json(
            STATUS_PATH,
            {
                **previous_status,
                "cached_player_count": len(output),
                "requested_player_count": len(unique_players),
                "remaining_player_count": max(
                    0,
                    len(unique_players) - len(output) - len(no_match_keys),
                ),
                "no_match_player_count": len(no_match_keys),
            },
        )
        LOGGER.info(
            "API-Football cooldown active until %s; using %s cached player "
            "metadata rows. Use fetch-apifootball --force-retry to retry now.",
            retry_after_at.isoformat(),
            len(output),
        )
        return list(output.values())

    max_requests = _request_budget()
    pending = pending[:max_requests]
    headers = {"x-apisports-key": api_key}
    requests_made = 0
    rate_limited = False
    retry_after_seconds: int | None = None
    failures = 0
    request_interval = _request_interval()
    for player_name, expected_country in pending:
        try:
            if requests_made:
                time.sleep(request_interval)
            response = requests.get(
                f"{BASE_URL}/players/profiles",
                headers=headers,
                params={"search": player_name},
                timeout=timeout,
            )
            requests_made += 1
            if response.status_code == 404:
                time.sleep(request_interval)
                response = requests.get(
                    f"{BASE_URL}/players",
                    headers=headers,
                    params={"search": player_name, "season": 2026},
                    timeout=timeout,
                )
                requests_made += 1
        except requests.RequestException as exc:
            failures += 1
            LOGGER.warning(
                "API-Football request failed for %s: %s",
                player_name,
                exc,
            )
            continue
        if response.status_code == 429:
            rate_limited = True
            retry_after_seconds = _retry_after_seconds(response)
            remaining = max(
                0,
                len(unique_players) - len(output) - len(no_match_keys),
            )
            LOGGER.warning(
                "API-Football rate limit reached after %s request(s); "
                "stopping this run for %s seconds and retaining cached metadata. "
                "%s player(s) remain unresolved.",
                requests_made,
                retry_after_seconds,
                remaining,
            )
            break
        if not response.ok:
            failures += 1
            LOGGER.warning(
                "API-Football lookup failed for %s: HTTP %s",
                player_name,
                response.status_code,
            )
            continue
        payload = response.json()
        api_errors = payload.get("errors")
        if api_errors:
            error_text = json.dumps(api_errors, ensure_ascii=False)
            if _is_rate_limit_error(error_text):
                rate_limited = True
                retry_after_seconds = _seconds_until_next_utc_day()
                LOGGER.warning(
                    "API-Football daily request limit reached after %s "
                    "request(s); retaining cached metadata until the next "
                    "UTC quota day.",
                    requests_made,
                )
                break
            failures += 1
            LOGGER.warning(
                "API-Football returned an API error for %s: %s",
                player_name,
                error_text,
            )
            continue
        raw.append(payload)
        candidates = payload.get("response", [])
        if not candidates:
            no_match_keys.add(_normalize_name(player_name))
            continue
        candidate = _best_candidate(
            candidates,
            player_name,
            expected_country,
        )
        if candidate is None:
            no_match_keys.add(_normalize_name(player_name))
            continue
        player = candidate.get("player", candidate)
        position = POSITION_MAP.get(player.get("position"), "UNKNOWN")
        metadata = PlayerMetadata(
            player=player_name,
            country=expected_country or player.get("nationality"),
            position=position,
            position_confidence="HIGH" if position != "UNKNOWN" else "LOW",
            starter_prob=0.90,
            penalty_taker=0,
            set_piece_taker=0,
            minutes_risk="MEDIUM",
            source="api-football",
            notes=(
                EXACT_MATCH_NOTE
                if position != "UNKNOWN"
                else (
                    f"{EXACT_MATCH_NOTE} Position missing; treated as FWD "
                    "conservatively."
                )
            ),
        )
        output[_normalize_name(player_name)] = metadata
        _save_cache(raw, list(output.values()))
    _save_cache(raw, list(output.values()))
    save_json(
        STATUS_PATH,
        {
            "status": (
                "RATE_LIMITED"
                if rate_limited
                else "PARTIAL"
                if len(output) < len(unique_players)
                else "OK"
            ),
            "checked_at": datetime.now(UTC),
            "retry_after_at": (
                datetime.now(UTC) + timedelta(seconds=retry_after_seconds)
                if retry_after_seconds is not None
                else None
            ),
            "requests_made": requests_made,
            "cached_player_count": len(output),
            "requested_player_count": len(unique_players),
            "remaining_player_count": max(
                0,
                len(unique_players) - len(output) - len(no_match_keys),
            ),
            "no_match_player_count": len(no_match_keys),
            "no_match_players": [
                player_name
                for key, (player_name, _country) in unique_players.items()
                if key in no_match_keys
            ],
            "failures": failures,
            "request_budget": max_requests,
        },
    )
    return list(output.values())


def _retry_after_at(status: dict[str, Any]) -> datetime | None:
    raw = status.get("retry_after_at")
    if raw:
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            pass
    if status.get("status") != "RATE_LIMITED" or not status.get("checked_at"):
        return None
    try:
        checked_at = datetime.fromisoformat(
            str(status["checked_at"]).replace("Z", "+00:00")
        )
    except ValueError:
        return None
    return checked_at + timedelta(minutes=15)


def _retry_after_seconds(response: requests.Response) -> int:
    value = response.headers.get("Retry-After")
    if value:
        try:
            return max(60, int(float(value)))
        except ValueError:
            pass
    return 15 * 60


def _is_rate_limit_error(value: str) -> bool:
    text = value.casefold()
    return any(
        marker in text
        for marker in (
            "request limit",
            "rate limit",
            "too many requests",
            "quota",
        )
    )


def _seconds_until_next_utc_day() -> int:
    now = datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).date()
    reset = datetime.combine(tomorrow, datetime.min.time(), tzinfo=UTC)
    return max(60, int((reset - now).total_seconds()))


def _load_cached_metadata() -> list[PlayerMetadata]:
    rows = load_json(PARSED_PATH, []) or []
    output = []
    for row in rows:
        try:
            output.append(PlayerMetadata.model_validate(row))
        except (TypeError, ValueError):
            continue
    return output


def _request_budget() -> int:
    raw = os.getenv("API_FOOTBALL_MAX_REQUESTS", "25")
    try:
        return max(0, int(raw))
    except ValueError:
        LOGGER.warning(
            "Invalid API_FOOTBALL_MAX_REQUESTS=%r; using 25",
            raw,
        )
        return 25


def _request_interval() -> float:
    raw = os.getenv("API_FOOTBALL_REQUEST_INTERVAL", "6.5")
    try:
        return max(0.0, float(raw))
    except ValueError:
        LOGGER.warning(
            "Invalid API_FOOTBALL_REQUEST_INTERVAL=%r; using 6.5",
            raw,
        )
        return 6.5


def _save_cache(
    raw: list[dict[str, Any]],
    parsed: list[PlayerMetadata],
) -> None:
    save_json(RAW_PATH, raw)
    save_json(PARSED_PATH, parsed)


def _best_candidate(
    candidates: list[dict[str, Any]],
    requested_name: str,
    expected_country: str | None,
) -> dict[str, Any] | None:
    requested_key = _normalize_name(requested_name)
    exact = [
        candidate
        for candidate in candidates
        if _normalize_name(
            str(candidate.get("player", candidate).get("name", ""))
        )
        == requested_key
    ]
    if not exact:
        return None
    if expected_country:
        country_matches = []
        for candidate in exact:
            player = candidate.get("player", candidate)
            if (
                str(player.get("nationality", "")).casefold()
                == expected_country.casefold()
            ):
                country_matches.append(candidate)
        if not country_matches:
            return None
        exact = country_matches
    position_priority = {
        "Attacker": 0,
        "Midfielder": 1,
        "Defender": 2,
        "Goalkeeper": 3,
    }
    return min(
        exact,
        key=lambda candidate: position_priority.get(
            candidate.get("player", candidate).get("position"),
            4,
        ),
    )


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(
        character.casefold()
        for character in normalized
        if character.isalnum()
        and not unicodedata.combining(character)
    )
