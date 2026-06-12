from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from cloakbrowser import launch_async
from playwright.async_api import Browser

DEFAULT_LOCALE = "en-GB"


async def launch_browser(
    *,
    headless: bool = True,
    locale: str = DEFAULT_LOCALE,
) -> Browser:
    """Launch the CloakBrowser Chromium build with shared scraper defaults."""
    return cast(
        Browser,
        await launch_async(
            headless=headless,
            locale=locale,
            humanize=True,
        ),
    )


@asynccontextmanager
async def browser_session(
    *,
    headless: bool = True,
    locale: str = DEFAULT_LOCALE,
) -> AsyncIterator[Browser]:
    browser = await launch_browser(headless=headless, locale=locale)
    try:
        yield browser
    finally:
        await browser.close()
