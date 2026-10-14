"""Browser Tool for Sprint 4 Integration Layer: Playwright headless browser automation."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from modules.config import ROOT_DIR
from modules.tools.base import BaseTool, ToolPermission, ToolResult

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger

logger = logging.getLogger("aru.tools.browser")


class BrowserTool(BaseTool):
    """
    Playwright-powered headless browser automation tool.
    Supports dynamic JavaScript execution, content extraction, and full-page screenshots.
    """

    name = "browser"
    description = (
        "Headless browser automation powered by Playwright. Navigate live web pages, "
        "render dynamic JavaScript content, extract DOM text, and capture screenshots."
    )
    required_permission = ToolPermission.EXECUTE
    timeout = 60.0

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["navigate", "extract_text", "screenshot"],
                "description": "Action: 'navigate' (page load & preview), 'extract_text' (selector text), 'screenshot' (PNG capture).",
            },
            "url": {
                "type": "string",
                "description": "Target webpage URL (must start with http:// or https://).",
            },
            "selector": {
                "type": "string",
                "description": "Optional CSS selector to query and extract text from (default 'body').",
            },
            "full_page": {
                "type": "boolean",
                "description": "Capture full scrollable page for screenshots (default False).",
            },
            "output_path": {
                "type": "string",
                "description": "Relative path in workspace to save screenshot (e.g., 'downloads/page.png').",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters of text to return (default 8000).",
            },
            "wait_until": {
                "type": "string",
                "enum": ["domcontentloaded", "load", "networkidle"],
                "description": "Navigation wait condition (default 'domcontentloaded').",
            },
        },
        "required": ["action", "url"],
    }

    def __init__(
        self,
        headless: bool = True,
        activity: ActivityLogger | None = None,
    ) -> None:
        self.headless = headless
        self.activity = activity

    async def _run_with_playwright(self, callback: Any) -> Any:
        """Helper to run a routine within async_playwright context."""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                return await callback(page)
            finally:
                await browser.close()

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "navigate")
        url = kwargs.get("url", "").strip()
        selector = kwargs.get("selector", "body") or "body"
        full_page = bool(kwargs.get("full_page", False))
        output_path = kwargs.get("output_path")
        max_chars = min(int(kwargs.get("max_chars", 8000)), 32000)
        wait_until = kwargs.get("wait_until", "domcontentloaded")

        if not url.startswith(("http://", "https://", "data:")):
            return ToolResult(
                success=False,
                error="Invalid URL: Must start with http:// or https://",
                metadata={"url": url},
            )

        try:
            # Action: navigate
            if action == "navigate":
                async def nav_handler(page: Any) -> dict[str, Any]:
                    resp = await page.goto(url, wait_until=wait_until, timeout=30000)
                    title = await page.title()
                    status = resp.status if resp else None
                    # Get body text preview
                    text = await page.inner_text("body")
                    if len(text) > max_chars:
                        text = text[:max_chars] + "\n... [truncated]"
                    return {
                        "title": title,
                        "status": status,
                        "url": page.url,
                        "text": text,
                    }

                res_data = await self._run_with_playwright(nav_handler)
                formatted = (
                    f"🌐 **{res_data['title']}** (Status: {res_data['status']})\n"
                    f"URL: {res_data['url']}\n\n"
                    f"{res_data['text']}"
                )
                return ToolResult(
                    success=True,
                    output=formatted,
                    metadata=res_data,
                )

            # Action: extract_text
            if action == "extract_text":
                async def text_handler(page: Any) -> dict[str, Any]:
                    await page.goto(url, wait_until=wait_until, timeout=30000)
                    title = await page.title()
                    element = await page.query_selector(selector)
                    if not element:
                        return {"title": title, "text": None, "found": False}
                    text = await element.inner_text()
                    if len(text) > max_chars:
                        text = text[:max_chars] + "\n... [truncated]"
                    return {"title": title, "text": text, "found": True}

                res_data = await self._run_with_playwright(text_handler)
                if not res_data.get("found"):
                    return ToolResult(
                        success=False,
                        error=f"Selector '{selector}' not found on page {url}",
                        metadata={"url": url, "selector": selector},
                    )
                return ToolResult(
                    success=True,
                    output=res_data["text"],
                    metadata={"url": url, "selector": selector, "title": res_data["title"]},
                )

            # Action: screenshot
            if action == "screenshot":
                async def shot_handler(page: Any) -> bytes:
                    await page.goto(url, wait_until=wait_until, timeout=30000)
                    return await page.screenshot(full_page=full_page)

                image_bytes: bytes = await self._run_with_playwright(shot_handler)
                saved_to = None
                if output_path:
                    # Sanitize destination inside ROOT_DIR
                    clean_dest = (ROOT_DIR / output_path).resolve()
                    clean_dest.relative_to(ROOT_DIR.resolve())  # Traversal check
                    clean_dest.parent.mkdir(parents=True, exist_ok=True)
                    clean_dest.write_bytes(image_bytes)
                    saved_to = str(clean_dest.relative_to(ROOT_DIR.resolve()))

                b64_prefix = base64.b64encode(image_bytes[:512]).decode("ascii")
                return ToolResult(
                    success=True,
                    output=f"Screenshot captured ({len(image_bytes)} bytes)" + (f" -> saved to {saved_to}" if saved_to else ""),
                    metadata={
                        "url": url,
                        "bytes_len": len(image_bytes),
                        "saved_to": saved_to,
                        "preview_b64": b64_prefix,
                    },
                )

            return ToolResult(
                success=False,
                error=f"Unknown browser action: '{action}'",
            )

        except Exception as exc:
            logger.exception("BrowserTool execution failed on %s: %s", url, exc)
            return ToolResult(
                success=False,
                error=f"Browser automation error: {type(exc).__name__}: {exc}",
                metadata={"url": url, "action": action},
            )
