from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright

from .logging_utils import load_json, save_json, slugify
from .odds_math import fractional_to_decimal
from .schemas import RawOutrightOdd, RawTopGoalscorerOdd

LOGGER = logging.getLogger(__name__)
WINNER_URLS = [
    "https://www.oddschecker.com/football/world-cup",
    "https://www.oddschecker.com/football/world-cup/winner",
]
TOPSCORER_URL = "https://www.oddschecker.com/football/world-cup/top-goalscorer"


class OddscheckerBlockedError(RuntimeError):
    """Raised when Oddschecker explicitly blocks the browser session."""


class OddscheckerScraper:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.raw_dir = Path("data/raw/oddschecker")
        self.debug_dir = Path("debug")
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self.blocked_reason: str | None = None

    async def scrape_winner_odds(self) -> list[RawOutrightOdd]:
        failures: list[str] = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            page = await browser.new_page(locale="en-GB")
            rows: list[RawOutrightOdd] = []
            for url in WINNER_URLS:
                try:
                    await self._goto(page, url)
                    raw = await self._extract_table(page)
                    rows = self._parse_outrights(raw)
                    if rows:
                        break
                except Exception as exc:
                    LOGGER.warning("Oddschecker winner scrape failed: %s", exc)
                    failures.append(f"{url}: {exc}")
                    await self._save_debug(page, "oddschecker-winner")
                    if isinstance(exc, OddscheckerBlockedError):
                        self.blocked_reason = str(exc)
                        break
            await browser.close()
        if not rows and not failures:
            failures.append("Winner page loaded but no usable odds rows were found.")
        cache_used = False
        if not rows and failures:
            cached = load_json(self.raw_dir / "winner.json", []) or []
            rows = [
                RawOutrightOdd.model_validate(row)
                for row in cached
                if isinstance(row, dict)
            ]
            cache_used = bool(rows)
        if rows and not cache_used:
            save_json(self.raw_dir / "winner.json", rows)
        save_json(
            self.raw_dir / "winner_status.json",
            {
                "status": "CACHED" if cache_used else "OK" if rows else "FAILED",
                "row_count": len(rows),
                "failures": failures,
                "cache_used": cache_used,
                "checked_at": datetime.now(UTC),
            },
        )
        return rows

    async def scrape_top_goalscorer_odds(self) -> list[RawTopGoalscorerOdd]:
        if self.blocked_reason:
            failure = (
                "Skipped because Oddschecker already blocked this browser session: "
                f"{self.blocked_reason}"
            )
            cached = load_json(self.raw_dir / "top_goalscorer.json", []) or []
            rows = [
                RawTopGoalscorerOdd.model_validate(row)
                for row in cached
                if isinstance(row, dict)
            ]
            save_json(
                self.raw_dir / "top_goalscorer_status.json",
                {
                    "status": "CACHED" if rows else "FAILED",
                    "row_count": len(rows),
                    "failures": [failure],
                    "cache_used": bool(rows),
                    "checked_at": datetime.now(UTC),
                },
            )
            LOGGER.warning(failure)
            return rows

        failures: list[str] = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            page = await browser.new_page(locale="en-GB")
            rows: list[RawTopGoalscorerOdd] = []
            try:
                await self._goto(page, TOPSCORER_URL)
                raw = await self._extract_table(page)
                rows = self._parse_topscorers(raw)
            except Exception as exc:
                LOGGER.warning("Oddschecker topscorer scrape failed: %s", exc)
                failures.append(f"{TOPSCORER_URL}: {exc}")
                await self._save_debug(page, "oddschecker-topscorer")
                if isinstance(exc, OddscheckerBlockedError):
                    self.blocked_reason = str(exc)
            await browser.close()
        if not rows and not failures:
            failures.append(
                "Top goalscorer page loaded but no usable odds rows were found."
            )
        cache_used = False
        if not rows and failures:
            cached = load_json(self.raw_dir / "top_goalscorer.json", []) or []
            rows = [
                RawTopGoalscorerOdd.model_validate(row)
                for row in cached
                if isinstance(row, dict)
            ]
            cache_used = bool(rows)
        if rows and not cache_used:
            save_json(self.raw_dir / "top_goalscorer.json", rows)
        save_json(
            self.raw_dir / "top_goalscorer_status.json",
            {
                "status": "CACHED" if cache_used else "OK" if rows else "FAILED",
                "row_count": len(rows),
                "failures": failures,
                "cache_used": cache_used,
                "checked_at": datetime.now(UTC),
            },
        )
        return rows

    async def import_saved_winner_html(
        self,
        path: str | Path,
    ) -> list[RawOutrightOdd]:
        source = Path(path)
        raw_rows = await self._extract_saved_html(source)
        rows = self._parse_outrights(raw_rows)
        if rows:
            save_json(self.raw_dir / "winner.json", rows)
        save_json(
            self.raw_dir / "winner_status.json",
            {
                "status": "OK" if rows else "FAILED",
                "row_count": len(rows),
                "failures": (
                    []
                    if rows
                    else [f"No usable winner odds found in saved HTML: {source}"]
                ),
                "checked_at": datetime.now(UTC),
                "imported_from": str(source.resolve()),
            },
        )
        return rows

    async def import_saved_top_goalscorer_html(
        self,
        path: str | Path,
    ) -> list[RawTopGoalscorerOdd]:
        source = Path(path)
        raw_rows = await self._extract_saved_html(source)
        rows = self._parse_topscorers(raw_rows)
        if rows:
            save_json(self.raw_dir / "top_goalscorer.json", rows)
        save_json(
            self.raw_dir / "top_goalscorer_status.json",
            {
                "status": "OK" if rows else "FAILED",
                "row_count": len(rows),
                "failures": (
                    []
                    if rows
                    else [
                        "No usable top goalscorer odds found in saved HTML: "
                        f"{source}"
                    ]
                ),
                "checked_at": datetime.now(UTC),
                "imported_from": str(source.resolve()),
            },
        )
        return rows

    async def _extract_saved_html(
        self,
        path: Path,
    ) -> list[dict[str, list[str] | str]]:
        if not path.is_file():
            raise FileNotFoundError(f"Saved HTML file not found: {path}")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(locale="en-GB")
            await page.set_content(
                path.read_text(encoding="utf-8"),
                wait_until="domcontentloaded",
            )
            rows = await self._extract_table(page)
            await browser.close()
        return rows

    async def _extract_table(self, page: Page) -> list[dict[str, Any]]:
        legacy_rows = await page.evaluate(
            """() => {
                const bookmakerNames = {};
                document.querySelectorAll('td[data-bk]').forEach(cell => {
                    const code = cell.getAttribute('data-bk');
                    const name =
                        cell.querySelector('a[title]')?.getAttribute('title') ||
                        cell.querySelector('img[alt]')?.getAttribute('alt');
                    if (code && name) bookmakerNames[code] = name.trim();
                });
                return Array.from(document.querySelectorAll('tr'))
                    .map(row => {
                        const selection = row.querySelector(
                            'a.selTxt[data-name]'
                        );
                        if (!selection) return null;
                        const participant =
                            selection.getAttribute('data-name')?.trim() || '';
                        const prices = Array.from(
                            row.querySelectorAll('td[data-bk][data-odig]')
                        ).map(cell => {
                            const code = cell.getAttribute('data-bk') || '';
                            return {
                                bookmaker: bookmakerNames[code] || code,
                                odds: cell.getAttribute('data-odig') || ''
                            };
                        }).filter(price =>
                            price.bookmaker && price.odds
                        );
                        if (!participant || !prices.length) return null;
                        return {
                            text: row.textContent?.trim() || '',
                            cells: [
                                participant,
                                ...prices.map(price => price.odds)
                            ],
                            bookmakers: prices.map(price => price.bookmaker),
                            participant,
                            prices
                        };
                    })
                    .filter(Boolean);
            }"""
        )
        if legacy_rows:
            return legacy_rows

        rows = page.locator("tr, [role='row'], [data-testid*='event-row']")
        output = []
        for index in range(await rows.count()):
            row = rows.nth(index)
            text = " ".join((await row.inner_text()).split())
            if not text:
                continue
            cells = row.locator("td, [role='cell'], [data-testid*='price']")
            values = [
                " ".join((await cells.nth(i).inner_text()).split())
                for i in range(await cells.count())
            ]
            headers = [
                value
                for value in await row.locator(
                    "[data-bookmaker], img[alt], [title]"
                ).evaluate_all(
                    """els => els.map(e =>
                        e.getAttribute('data-bookmaker') ||
                        e.getAttribute('alt') ||
                        e.getAttribute('title') || '')"""
                )
                if value
            ]
            output.append({"text": text, "cells": values, "bookmakers": headers})
        return output

    def _parse_outrights(
        self,
        rows: list[dict[str, Any]],
    ) -> list[RawOutrightOdd]:
        parsed: list[RawOutrightOdd] = []
        now = datetime.now(UTC)
        for row in rows:
            prices = row.get("prices")
            participant = str(row.get("participant", "")).strip()
            if participant and isinstance(prices, list):
                for price in prices:
                    try:
                        parsed.append(
                            RawOutrightOdd(
                                country=participant,
                                bookmaker=str(price["bookmaker"]).strip(),
                                odds=fractional_to_decimal(str(price["odds"])),
                                source="oddschecker",
                                scraped_at=now,
                            )
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
                continue
            cells = list(row["cells"])
            if len(cells) < 2:
                continue
            country = cells[0].strip()
            if country.casefold() in {"each-way terms", "bookmakers", "odds"}:
                continue
            odds_values = [value for value in cells[1:] if self._looks_like_odds(value)]
            bookmakers = list(row["bookmakers"])
            for index, odds_text in enumerate(odds_values):
                if index >= len(bookmakers):
                    continue
                try:
                    parsed.append(
                        RawOutrightOdd(
                            country=country,
                            bookmaker=bookmakers[index],
                            odds=fractional_to_decimal(odds_text),
                            source="oddschecker",
                            scraped_at=now,
                        )
                    )
                except ValueError:
                    continue
        return self._deduplicate_outrights(parsed)

    def _parse_topscorers(
        self,
        rows: list[dict[str, Any]],
    ) -> list[RawTopGoalscorerOdd]:
        parsed: list[RawTopGoalscorerOdd] = []
        now = datetime.now(UTC)
        for row in rows:
            prices = row.get("prices")
            participant = str(row.get("participant", "")).strip()
            if participant and isinstance(prices, list):
                player, country = self._split_player_country(participant)
                for price in prices:
                    try:
                        parsed.append(
                            RawTopGoalscorerOdd(
                                player=player,
                                country=country,
                                bookmaker=str(price["bookmaker"]).strip(),
                                odds=fractional_to_decimal(str(price["odds"])),
                                source="oddschecker",
                                scraped_at=now,
                            )
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
                continue
            cells = list(row["cells"])
            if len(cells) < 2:
                continue
            player, country = self._split_player_country(cells[0])
            odds_values = [value for value in cells[1:] if self._looks_like_odds(value)]
            bookmakers = list(row["bookmakers"])
            for index, odds_text in enumerate(odds_values):
                if index >= len(bookmakers):
                    continue
                try:
                    parsed.append(
                        RawTopGoalscorerOdd(
                            player=player,
                            country=country,
                            bookmaker=bookmakers[index],
                            odds=fractional_to_decimal(odds_text),
                            source="oddschecker",
                            scraped_at=now,
                        )
                    )
                except ValueError:
                    continue
        output = {}
        for row in parsed:
            output.setdefault((row.player.casefold(), row.bookmaker.casefold()), row)
        return list(output.values())

    @staticmethod
    def _split_player_country(value: str) -> tuple[str, str | None]:
        match = re.match(r"^(.*?)\s+\(([^)]+)\)$", value.strip())
        return (match.group(1), match.group(2)) if match else (value.strip(), None)

    @staticmethod
    def _looks_like_odds(value: str) -> bool:
        value = value.strip()
        return bool(
            re.fullmatch(r"\d+\s*/\s*\d+", value)
            or re.fullmatch(r"\d+(?:\.\d+)?", value)
        )

    @staticmethod
    def _deduplicate_outrights(
        rows: list[RawOutrightOdd],
    ) -> list[RawOutrightOdd]:
        output = {}
        for row in rows:
            output.setdefault((row.country.casefold(), row.bookmaker.casefold()), row)
        return list(output.values())

    async def _goto(self, page: Page, url: str) -> None:
        last_error: Exception | None = None
        for attempt in range(3):
            await asyncio.sleep(random.uniform(2.0, 5.0))
            try:
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=45_000,
                )
                if response is None:
                    raise RuntimeError("navigation returned no HTTP response")
                await page.wait_for_timeout(1_500)
                title = await page.title()
                body = (await page.locator("body").inner_text())[:500]
                if "Cloudflare" in title or "you have been blocked" in body.lower():
                    raise OddscheckerBlockedError(
                        "Cloudflare blocked the browser session"
                    )
                if response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status}")
                return
            except OddscheckerBlockedError:
                raise
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(2**attempt)
        raise RuntimeError(f"Could not load {url}") from last_error

    async def _save_debug(self, page: Page, label: str) -> None:
        safe = slugify(label)
        try:
            await page.screenshot(
                path=str(self.debug_dir / f"{safe}.png"),
                full_page=True,
            )
            (self.debug_dir / f"{safe}.html").write_text(
                await page.content(),
                encoding="utf-8",
            )
        except Exception as exc:
            LOGGER.warning("Could not save Oddschecker debug data: %s", exc)
