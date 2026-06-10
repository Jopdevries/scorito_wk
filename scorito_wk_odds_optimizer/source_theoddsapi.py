from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from .logging_utils import save_json, slugify
from .schemas import Fixture, Raw1X2Odd, RawCorrectScoreOdd, RawOUBTTSOdd, RawOutrightOdd

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://api.the-odds-api.com/v4"
SPORT_KEY = "soccer_fifa_world_cup"


def fetch_the_odds_api(timeout: int = 30) -> dict[str, list[Any]]:
    load_dotenv()
    api_key = os.getenv("THE_ODDS_API_KEY")
    empty = {
        "fixtures": [],
        "x1x2": [],
        "correct_scores": [],
        "ou_btts": [],
        "outrights": [],
        "topscorers": [],
    }
    if not api_key:
        LOGGER.info("THE_ODDS_API_KEY missing; skipping")
        return empty
    now = datetime.now(UTC)
    response = requests.get(
        f"{BASE_URL}/sports/{SPORT_KEY}/odds",
        params={
            "apiKey": api_key,
            "regions": "eu,uk",
            "markets": "h2h,totals,btts,correct_score",
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        },
        timeout=timeout,
    )
    if response.status_code == 422:
        response = requests.get(
            f"{BASE_URL}/sports/{SPORT_KEY}/odds",
            params={
                "apiKey": api_key,
                "regions": "eu,uk",
                "markets": "h2h,totals",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
            timeout=timeout,
        )
    response.raise_for_status()
    payload = response.json()
    save_json("data/raw/theoddsapi/response.json", payload)
    for event in payload:
        fixture_id = event.get("id") or (
            f"{slugify(event['commence_time'])}-"
            f"{slugify(event['home_team'])}-{slugify(event['away_team'])}"
        )
        empty["fixtures"].append(
            Fixture(
                fixture_id=fixture_id,
                kickoff_datetime=event["commence_time"],
                home_team=event["home_team"],
                away_team=event["away_team"],
                match_url=None,
                group=None,
                source="theoddsapi",
            )
        )
        for bookmaker in event.get("bookmakers", []):
            bookmaker_name = bookmaker.get("title") or bookmaker.get("key", "UNKNOWN")
            for market in bookmaker.get("markets", []):
                key = market.get("key")
                outcomes = market.get("outcomes", [])
                try:
                    if key == "h2h":
                        prices = {outcome["name"]: outcome["price"] for outcome in outcomes}
                        empty["x1x2"].append(
                            Raw1X2Odd(
                                fixture_id=fixture_id,
                                bookmaker=bookmaker_name,
                                home_win_odds=prices[event["home_team"]],
                                draw_odds=prices["Draw"],
                                away_win_odds=prices[event["away_team"]],
                                source="theoddsapi",
                                scraped_at=now,
                            )
                        )
                    elif key == "totals":
                        prices = {
                            outcome["name"].lower(): outcome["price"]
                            for outcome in outcomes
                            if float(outcome.get("point", 0)) == 2.5
                        }
                        if "over" in prices and "under" in prices:
                            empty["ou_btts"].append(
                                RawOUBTTSOdd(
                                    fixture_id=fixture_id,
                                    bookmaker=bookmaker_name,
                                    over_2_5_odds=prices["over"],
                                    under_2_5_odds=prices["under"],
                                    source="theoddsapi",
                                    scraped_at=now,
                                )
                            )
                    elif key == "btts":
                        prices = {
                            outcome["name"].lower(): outcome["price"]
                            for outcome in outcomes
                        }
                        if "yes" in prices and "no" in prices:
                            empty["ou_btts"].append(
                                RawOUBTTSOdd(
                                    fixture_id=fixture_id,
                                    bookmaker=bookmaker_name,
                                    btts_yes_odds=prices["yes"],
                                    btts_no_odds=prices["no"],
                                    source="theoddsapi",
                                    scraped_at=now,
                                )
                            )
                    elif key == "correct_score":
                        for outcome in outcomes:
                            score = _score_from_name(outcome.get("name", ""))
                            if score:
                                empty["correct_scores"].append(
                                    RawCorrectScoreOdd(
                                        fixture_id=fixture_id,
                                        bookmaker=bookmaker_name,
                                        score=score,
                                        odds=outcome["price"],
                                        source="theoddsapi",
                                        scraped_at=now,
                                    )
                                )
                except (KeyError, TypeError, ValueError) as exc:
                    LOGGER.warning(
                        "Skipping invalid The Odds API market %s/%s: %s",
                        fixture_id,
                        key,
                        exc,
                    )
    save_json("data/raw/theoddsapi/parsed.json", empty)
    return empty


def _score_from_name(name: str) -> str | None:
    import re

    match = re.search(r"(\d+)\s*[-:]\s*(\d+)", name)
    return f"{match.group(1)}-{match.group(2)}" if match else None
