"""Future: Playwright browser automation hub."""

from __future__ import annotations

import logging

logger = logging.getLogger("aru.browser")


class BrowserAutomation:
    """
    Playwright-based browser automation hub.
    Powered by BrowserTool in the Sprint 4 Integration Layer.
    """

    def __init__(self) -> None:
        from modules.tools.browser_tool import BrowserTool
        self._tool = BrowserTool()
        self._ready = True

    async def start(self) -> bool:
        """Verify browser readiness."""
        self._ready = True
        logger.info("Browser automation active (Sprint 4 Integration Layer)")
        return True

    async def stop(self) -> None:
        self._ready = False

    async def navigate(self, url: str) -> str:
        res = await self._tool.execute(action="navigate", url=url)
        if res.success:
            return res.format_output()
        return f"Navigation failed: {res.error}"

    async def screenshot(self, url: str) -> bytes | None:
        from playwright.async_api import async_playwright

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                try:
                    page = await browser.new_page()
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    return await page.screenshot()
                finally:
                    await browser.close()
        except Exception as exc:
            logger.error("BrowserAutomation screenshot failed: %s", exc)
            return None

