import asyncio

from scorito_wk_odds_optimizer import cloak_browser


def test_launch_browser_uses_cloakbrowser_defaults(monkeypatch) -> None:
    expected_browser = object()
    received: dict[str, object] = {}

    async def fake_launch_async(**kwargs):
        received.update(kwargs)
        return expected_browser

    monkeypatch.setattr(cloak_browser, "launch_async", fake_launch_async)

    browser = asyncio.run(cloak_browser.launch_browser(headless=False))

    assert browser is expected_browser
    assert received == {
        "headless": False,
        "locale": "en-GB",
        "humanize": True,
    }


def test_browser_session_closes_browser(monkeypatch) -> None:
    closed = False

    class FakeBrowser:
        async def close(self) -> None:
            nonlocal closed
            closed = True

    async def fake_launch_browser(**kwargs):
        return FakeBrowser()

    monkeypatch.setattr(cloak_browser, "launch_browser", fake_launch_browser)

    async def use_session() -> None:
        async with cloak_browser.browser_session():
            pass

    asyncio.run(use_session())

    assert closed is True
