from __future__ import annotations

import asyncio
import html
import json
import logging
import random
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.async_api import Locator, Page, async_playwright

from .logging_utils import load_json, save_json, slugify
from .schemas import (
    Fixture,
    Raw1X2Odd,
    RawCorrectScoreOdd,
    RawOUBTTSOdd,
    RawOutrightOdd,
)

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://www.oddsportal.com"
COMPETITION_URLS = [
    "https://www.oddsportal.com/football/world/world-championship-2026/",
]


class OddsPortalScraper:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.raw_dir = Path("data/raw/oddsportal")
        self.debug_dir = Path("debug")
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.debug_dir.mkdir(parents=True, exist_ok=True)

    async def scrape_fixtures(
        self,
        max_matches: int | None = None,
    ) -> list[Fixture]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            page = await browser.new_page(locale="en-GB")
            fixtures: list[Fixture] = []
            failures: list[str] = []
            for url in COMPETITION_URLS:
                try:
                    await self._goto_with_retry(page, url, "fixtures")
                    if "oddsportal.com" not in page.url:
                        message = f"{url} redirected to {page.url}"
                        failures.append(message)
                        LOGGER.warning(message)
                        await self.save_debug(page, "fixtures-redirected")
                        continue
                    fixtures = await self._extract_fixtures(page)
                    if fixtures:
                        break
                    failures.append(f"No fixtures found at {url}")
                    await self.save_debug(page, "fixtures-no-data")
                except Exception as exc:  # Site failures must not stop fallbacks.
                    LOGGER.warning("OddsPortal fixture page failed: %s", exc)
                    failures.append(f"{url}: {exc}")
                    await self.save_debug(page, "fixtures-failed")
            await browser.close()
        fixtures = sorted(fixtures, key=lambda fixture: fixture.kickoff_datetime)
        if max_matches is not None:
            fixtures = fixtures[:max_matches]
        save_json(self.raw_dir / "fixtures.json", fixtures)
        save_json(
            self.raw_dir / "fixtures_status.json",
            {
                "status": "OK" if fixtures else "FAILED",
                "fixture_count": len(fixtures),
                "failures": failures,
                "checked_at": datetime.now(UTC),
            },
        )
        return fixtures

    async def scrape_match(self, match_url: str, fixture_id: str) -> dict[str, Any]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            page = await browser.new_page(locale="en-GB")
            result = await self._scrape_match_page(page, match_url, fixture_id)
            await browser.close()
        return result

    async def scrape_all(self, max_matches: int | None = None) -> None:
        fixtures = await self.scrape_fixtures(max_matches)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            page = await browser.new_page(locale="en-GB")
            for fixture in fixtures:
                cache_path = self.raw_dir / f"{fixture.fixture_id}.json"
                if cache_path.exists():
                    cached = load_json(cache_path, {}) or {}
                    if not cached.get("failed"):
                        LOGGER.info(
                            "Using cached OddsPortal match %s",
                            fixture.fixture_id,
                        )
                        continue
                    LOGGER.info(
                        "Retrying previously failed OddsPortal match %s",
                        fixture.fixture_id,
                    )
                if not fixture.match_url:
                    LOGGER.warning("Fixture %s has no match URL", fixture.fixture_id)
                    continue
                try:
                    await self._scrape_match_page(
                        page,
                        fixture.match_url,
                        fixture.fixture_id,
                    )
                except Exception as exc:
                    LOGGER.warning(
                        "OddsPortal match %s failed: %s",
                        fixture.fixture_id,
                        exc,
                    )
                    await self.save_debug(page, f"{fixture.fixture_id}-failed")
                    save_json(
                        cache_path,
                        {"fixture_id": fixture.fixture_id, "failed": str(exc)},
                    )
            try:
                outrights = await self._scrape_outrights_page(page)
                save_json(self.raw_dir / "outrights.json", outrights)
            except Exception as exc:
                LOGGER.warning("OddsPortal outright scrape failed: %s", exc)
                await self.save_debug(page, "oddsportal-outrights-failed")
            await browser.close()

    async def _scrape_outrights_page(
        self,
        page: Page,
    ) -> list[RawOutrightOdd]:
        url = (
            "https://www.oddsportal.com/football/world/"
            "world-championship-2026/outrights/"
        )
        await self._goto_with_retry(page, url, "outrights")
        rows = page.locator('[data-testid="outrights-table-row"]')
        await rows.first.wait_for(state="visible", timeout=30_000)
        await rows.evaluate_all("elements => elements.forEach(element => element.click())")
        await page.wait_for_timeout(300)
        groups = await rows.evaluate_all(
            """elements => elements.map(element => {
                const country = element.querySelector(
                    '[data-testid="outrights-participant-name"] p'
                )?.textContent?.trim() || '';
                const prices = [];
                let sibling = element.nextElementSibling;
                while (
                    sibling &&
                    sibling.getAttribute('data-testid') !== 'outrights-table-row'
                ) {
                    if (
                        sibling.getAttribute('data-testid') ===
                        'outrights-expanded-table-row'
                    ) {
                        const bookmaker =
                            sibling.querySelector(
                                '[data-testid="outrights-expanded-bookmaker-name"]'
                            )?.textContent?.trim() ||
                            sibling.querySelector('img.bookmaker-logo')
                                ?.getAttribute('alt') ||
                            'UNKNOWN';
                        prices.push({
                            bookmaker,
                            odds: Array.from(
                                sibling.querySelectorAll(
                                    '[data-testid="outrights-expanded-table-odd-container"]'
                                )
                            ).map(item => item.textContent || '')
                        });
                    }
                    sibling = sibling.nextElementSibling;
                }
                return {country, prices};
            })"""
        )
        now = datetime.now(UTC)
        output: list[RawOutrightOdd] = []
        for group in groups:
            country = str(group["country"]).strip()
            for price in group["prices"]:
                odds: list[float] = []
                for odds_text in price["odds"]:
                    odds.extend(
                        self.extract_decimal_odds_from_text(str(odds_text))
                    )
                if not odds:
                    continue
                try:
                    output.append(
                        RawOutrightOdd(
                            country=country,
                            bookmaker=str(price["bookmaker"]).strip(),
                            odds=odds[0],
                            source="oddsportal",
                            scraped_at=now,
                        )
                    )
                except ValueError:
                    continue
        if not output:
            raise RuntimeError("No usable OddsPortal outright bookmaker rows")
        return self._deduplicate(
            output,
            lambda row: (row.country.casefold(), row.bookmaker.casefold()),
        )

    async def _extract_fixtures(self, page: Page) -> list[Fixture]:
        structured = await self._extract_structured_fixtures(page)
        if structured:
            return structured

        links = page.locator('a[href*="/football/"][href*="-"]')
        fixtures: list[Fixture] = []
        seen: set[str] = set()
        for index in range(await links.count()):
            link = links.nth(index)
            href = await link.get_attribute("href")
            text = " ".join((await link.inner_text()).split())
            if not href or not text or len(text) > 160:
                continue
            teams = await self._extract_teams_from_link(link, text)
            if not teams:
                continue
            home, away = teams
            kickoff = await self._extract_kickoff(link)
            if kickoff is None:
                continue
            fixture_id = (
                f"{kickoff:%Y%m%d%H%M}-"
                f"{slugify(home)}-{slugify(away)}"
            )
            if fixture_id in seen:
                continue
            seen.add(fixture_id)
            fixtures.append(
                Fixture(
                    fixture_id=fixture_id,
                    kickoff_datetime=kickoff,
                    home_team=home,
                    away_team=away,
                    match_url=urljoin(BASE_URL, href),
                    group=None,
                    source="oddsportal",
                )
            )
        return fixtures

    async def _extract_structured_fixtures(self, page: Page) -> list[Fixture]:
        scripts = page.locator('script[type="application/ld+json"]')
        fixtures: list[Fixture] = []
        seen: set[str] = set()
        for index in range(await scripts.count()):
            raw = await scripts.nth(index).text_content()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            entries = payload if isinstance(payload, list) else [payload]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                event_types = entry.get("@type", [])
                if isinstance(event_types, str):
                    event_types = [event_types]
                if "SportsEvent" not in event_types:
                    continue
                name = html.unescape(str(entry.get("name", ""))).strip()
                if " - " not in name or not entry.get("startDate"):
                    continue
                home, away = (part.strip() for part in name.split(" - ", 1))
                try:
                    kickoff = datetime.fromisoformat(
                        str(entry["startDate"]).replace("Z", "+00:00")
                    )
                except ValueError:
                    continue
                fixture_id = (
                    f"{kickoff:%Y%m%d%H%M}-"
                    f"{slugify(home)}-{slugify(away)}"
                )
                if fixture_id in seen:
                    continue
                seen.add(fixture_id)
                fixtures.append(
                    Fixture(
                        fixture_id=fixture_id,
                        kickoff_datetime=kickoff,
                        home_team=home,
                        away_team=away,
                        match_url=entry.get("url"),
                        group=None,
                        source="oddsportal",
                    )
                )
        return fixtures

    async def _extract_teams_from_link(
        self,
        link: Locator,
        text: str,
    ) -> tuple[str, str] | None:
        spans = [
            " ".join((await link.locator("span").nth(i).inner_text()).split())
            for i in range(min(await link.locator("span").count(), 8))
        ]
        candidates = [
            value
            for value in spans
            if value
            and not re.fullmatch(r"\d{1,2}:\d{2}", value)
            and not re.fullmatch(r"[\d.]+", value)
        ]
        if len(candidates) >= 2:
            return candidates[-2], candidates[-1]
        for separator in (" - ", " vs ", " v "):
            if separator in text:
                parts = text.split(separator)
                if len(parts) == 2:
                    return parts[0].strip(), parts[1].strip()
        return None

    async def _extract_kickoff(self, link: Locator) -> datetime | None:
        parent = link.locator("xpath=ancestor::*[self::div or self::tr][1]")
        text = " ".join((await parent.inner_text()).split())
        iso = await parent.get_attribute("data-dt")
        if iso:
            try:
                return datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except ValueError:
                pass
        match = re.search(
            r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}).*?(\d{1,2}:\d{2})",
            text,
        )
        if match:
            for fmt in ("%d/%m/%Y %H:%M", "%d.%m.%Y %H:%M", "%d-%m-%Y %H:%M"):
                try:
                    return datetime.strptime(
                        f"{match.group(1)} {match.group(2)}",
                        fmt,
                    ).replace(tzinfo=UTC)
                except ValueError:
                    continue
        return None

    async def _scrape_match_page(
        self,
        page: Page,
        match_url: str,
        fixture_id: str,
    ) -> dict[str, Any]:
        await self._goto_with_retry(page, match_url, fixture_id)
        await self._wait_for_initial_odds(page, match_url)
        x1x2 = await self._extract_1x2(page, fixture_id)
        correct_scores: list[RawCorrectScoreOdd] = []
        ou_btts: list[RawOUBTTSOdd] = []

        if await self.click_tab(page, "Correct Score"):
            await self.click_tab(page, "Full Time")
            correct_scores = await self._extract_correct_scores(page, fixture_id)
        if await self.click_tab(page, "Over/Under"):
            ou_btts = await self._extract_ou(page, fixture_id)
        if await self.click_tab(page, "Both Teams to Score"):
            btts = await self._extract_btts(page, fixture_id)
            ou_btts = self._merge_ou_btts(ou_btts, btts)

        if not x1x2:
            raise RuntimeError("OddsPortal returned no usable 1X2 bookmaker rows")
        if not correct_scores:
            raise RuntimeError(
                "OddsPortal returned no usable Full Time Correct Score rows"
            )
        result = {
            "fixture_id": fixture_id,
            "x1x2": x1x2,
            "correct_scores": correct_scores,
            "ou_btts": ou_btts,
            "scraped_at": datetime.now(UTC),
        }
        save_json(self.raw_dir / f"{fixture_id}.json", result)
        return result

    async def click_tab(self, page: Page, tab_name: str) -> bool:
        locator = page.get_by_text(tab_name, exact=True)
        for index in range(await locator.count()):
            item = locator.nth(index)
            if await item.is_visible():
                try:
                    await item.click(timeout=5_000)
                    await page.wait_for_timeout(400)
                    return True
                except Exception:
                    continue
        # OddsPortal keeps overflow market tabs in the DOM but hidden.
        for index in range(await locator.count()):
            item = locator.nth(index)
            try:
                await item.evaluate(
                    """element => {
                        const target = element.closest('li, button, a');
                        (target || element).click();
                    }"""
                )
                await page.wait_for_timeout(400)
                return True
            except Exception:
                continue
        return False

    @staticmethod
    def extract_decimal_odds_from_text(text: str) -> list[float]:
        values = []
        # OddsPortal renders duplicate desktop/mobile values without whitespace,
        # for example "5.805.80". Match each displayed two-decimal value.
        for match in re.findall(r"\d{1,4}\.\d{2}", text):
            value = float(match)
            if value > 1.0:
                values.append(value)
        return values

    async def _extract_1x2(self, page: Page, fixture_id: str) -> list[Raw1X2Odd]:
        now = datetime.now(UTC)
        output: list[Raw1X2Odd] = []
        rows = page.locator('[data-testid="over-under-expanded-row"]')
        for index in range(await rows.count()):
            row = rows.nth(index)
            bookmaker = await self._bookmaker_from_row(row)
            odds = await self._odds_from_row(row)
            if len(odds) < 3:
                continue
            try:
                output.append(
                    Raw1X2Odd(
                        fixture_id=fixture_id,
                        bookmaker=bookmaker,
                        home_win_odds=odds[0],
                        draw_odds=odds[1],
                        away_win_odds=odds[2],
                        source="oddsportal",
                        scraped_at=now,
                    )
                )
            except ValueError:
                continue
        return self._deduplicate(output, lambda row: row.bookmaker.casefold())

    async def _extract_correct_scores(
        self,
        page: Page,
        fixture_id: str,
    ) -> list[RawCorrectScoreOdd]:
        now = datetime.now(UTC)
        output: list[RawCorrectScoreOdd] = []
        collapsed_rows = page.locator('[data-testid="over-under-collapsed-row"]')
        await collapsed_rows.evaluate_all(
            "elements => elements.forEach(element => element.click())"
        )
        await page.wait_for_timeout(300)
        groups = await collapsed_rows.evaluate_all(
            """elements => elements.map(element => {
                const score = element.querySelector(
                    '[data-testid="over-under-collapsed-option-box"] p'
                )?.textContent?.trim() || '';
                const prices = Array.from(
                    element.parentElement?.querySelectorAll(
                        '[data-testid="over-under-expanded-row"]'
                    ) || []
                ).map(sibling => {
                        const bookmaker =
                            sibling.querySelector(
                                '[data-testid="outrights-expanded-bookmaker-name"]'
                            )?.textContent?.trim() ||
                            sibling.querySelector(
                                '[data-testid="bookie-name"]'
                            )?.textContent?.trim() ||
                            sibling.querySelector('img.bookmaker-logo')
                                ?.getAttribute('alt') ||
                            'UNKNOWN';
                        const odds = Array.from(
                            sibling.querySelectorAll(
                                '[data-testid="odd-container"]'
                            )
                        ).map(item => item.textContent || '');
                        return {bookmaker, odds};
                    });
                return {score, prices};
            })"""
        )
        for group in groups:
            text = str(group["score"])
            score_match = re.search(r"(?<!\d)(\d+)\s*[-:]\s*(\d+)(?!\d)", text)
            if not score_match:
                continue
            score = f"{score_match.group(1)}-{score_match.group(2)}"
            for price in group["prices"]:
                odds: list[float] = []
                for odds_text in price["odds"]:
                    parsed = self.extract_decimal_odds_from_text(str(odds_text))
                    if parsed:
                        odds.append(parsed[0])
                if not odds:
                    continue
                try:
                    output.append(
                        RawCorrectScoreOdd(
                            fixture_id=fixture_id,
                            bookmaker=str(price["bookmaker"]).strip(),
                            score=score,
                            odds=odds[0],
                            source="oddsportal",
                            scraped_at=now,
                        )
                    )
                except ValueError:
                    continue
        return self._deduplicate(
            output,
            lambda row: (row.bookmaker.casefold(), row.score),
        )

    async def _extract_ou(
        self,
        page: Page,
        fixture_id: str,
    ) -> list[RawOUBTTSOdd]:
        now = datetime.now(UTC)
        output: list[RawOUBTTSOdd] = []
        collapsed_rows = page.locator('[data-testid="over-under-collapsed-row"]')
        target: Locator | None = None
        for index in range(await collapsed_rows.count()):
            row = collapsed_rows.nth(index)
            text = " ".join((await row.inner_text()).split())
            if re.search(r"Over/Under\s+\+?2\.5(?:\s|$)", text, re.I):
                target = row
                break
        if target is None:
            return []
        container = target.locator("xpath=..")
        try:
            await target.evaluate("element => element.click()")
            await container.locator(
                '[data-testid="over-under-expanded-row"]'
            ).first.wait_for(state="attached", timeout=1_000)
        except Exception:
            return []
        rows = container.locator('[data-testid="over-under-expanded-row"]')
        for index in range(await rows.count()):
            row = rows.nth(index)
            odds = await self._odds_from_row(row)
            if len(odds) < 2:
                continue
            try:
                output.append(
                    RawOUBTTSOdd(
                        fixture_id=fixture_id,
                        bookmaker=await self._bookmaker_from_row(row),
                        over_2_5_odds=odds[0],
                        under_2_5_odds=odds[1],
                        source="oddsportal",
                        scraped_at=now,
                    )
                )
            except ValueError:
                continue
        return self._deduplicate(output, lambda row: row.bookmaker.casefold())

    async def _extract_btts(
        self,
        page: Page,
        fixture_id: str,
    ) -> list[RawOUBTTSOdd]:
        now = datetime.now(UTC)
        output: list[RawOUBTTSOdd] = []
        rows = page.locator('[data-testid="over-under-expanded-row"]')
        for index in range(await rows.count()):
            row = rows.nth(index)
            odds = await self._odds_from_row(row)
            if len(odds) < 2:
                continue
            try:
                output.append(
                    RawOUBTTSOdd(
                        fixture_id=fixture_id,
                        bookmaker=await self._bookmaker_from_row(row),
                        btts_yes_odds=odds[0],
                        btts_no_odds=odds[1],
                        source="oddsportal",
                        scraped_at=now,
                    )
                )
            except ValueError:
                continue
        return self._deduplicate(output, lambda row: row.bookmaker.casefold())

    async def _wait_for_initial_odds(self, page: Page, match_url: str) -> None:
        selector = '[data-testid="over-under-expanded-row"]'
        for attempt in range(2):
            try:
                await page.locator(selector).first.wait_for(
                    state="visible",
                    timeout=30_000,
                )
                return
            except Exception:
                if attempt == 0:
                    LOGGER.info("Odds widget not loaded; reloading %s", match_url)
                    await page.reload(
                        wait_until="domcontentloaded",
                        timeout=45_000,
                    )
        raise RuntimeError("OddsPortal odds widget did not load")

    async def _bookmaker_from_row(self, row: Locator) -> str:
        selectors = (
            '[data-testid="outrights-expanded-bookmaker-name"]',
            '[data-testid="bookie-name"]',
        )
        for selector in selectors:
            locator = row.locator(selector)
            if await locator.count():
                value = " ".join((await locator.first.inner_text()).split())
                if value:
                    return value
        image = row.locator("img.bookmaker-logo")
        if await image.count():
            value = await image.first.get_attribute("alt")
            if value:
                return value.strip()
        return "UNKNOWN"

    async def _odds_from_row(self, row: Locator) -> list[float]:
        values: list[float] = []
        containers = row.locator('[data-testid="odd-container"]')
        for index in range(await containers.count()):
            text = " ".join((await containers.nth(index).inner_text()).split())
            odds = self.extract_decimal_odds_from_text(text)
            if odds:
                values.append(odds[0])
        return values

    @staticmethod
    def _merge_ou_btts(
        totals: list[RawOUBTTSOdd],
        btts: list[RawOUBTTSOdd],
    ) -> list[RawOUBTTSOdd]:
        merged = {row.bookmaker.casefold(): row for row in totals}
        for row in btts:
            key = row.bookmaker.casefold()
            if key in merged:
                merged[key] = merged[key].model_copy(
                    update={
                        "btts_yes_odds": row.btts_yes_odds,
                        "btts_no_odds": row.btts_no_odds,
                    }
                )
            else:
                merged[key] = row
        return list(merged.values())

    @staticmethod
    def _deduplicate(rows: list[Any], key: Any) -> list[Any]:
        output = {}
        for row in rows:
            output.setdefault(key(row), row)
        return list(output.values())

    async def _goto_with_retry(
        self,
        page: Page,
        url: str,
        label: str,
    ) -> None:
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
                if response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status}")
                await page.wait_for_timeout(1_500)
                return
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(2**attempt)
        await self.save_debug(page, f"{label}-navigation")
        raise RuntimeError(f"Could not load {url}") from last_error

    async def save_debug(self, page: Page, label: str) -> None:
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
            LOGGER.warning("Could not save debug artifacts for %s: %s", label, exc)
