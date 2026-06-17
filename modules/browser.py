"""Future: Playwright browser automation hub."""

from __future__ import annotations

import logging

logger = logging.getLogger("aru.browser")


class BrowserAutomation:
    """
    Placeholder for Playwright-based automation.
    Install browsers: playwright install chromium
    """

    def __init__(self) -> None:
        self._ready = False

    async def start(self) -> bool:
        """Launch browser when automation is enabled."""
        logger.info("Browser automation module reserved (not active)")
        return False

    async def stop(self) -> None:
        self._ready = False

    async def navigate(self, url: str) -> str:
        return "Browser automation is not enabled yet. Coming soon."

    async def screenshot(self, url: str) -> bytes | None:
        return None
