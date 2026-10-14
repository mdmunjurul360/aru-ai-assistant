"""Modular search providers for web information retrieval."""

from __future__ import annotations

import html
import logging
import re
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from modules.config import (
    RESEARCH_MAX_RESULTS,
    SEARCH_PROVIDER,
    SERPER_API_KEY,
    TAVILY_API_KEY,
)

logger = logging.getLogger("aru.search")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class SearchResult:
    """Structured search hit from any provider."""

    title: str
    url: str
    snippet: str
    source: str = ""
    score: float = 0.0

    def __post_init__(self) -> None:
        if not self.source and self.url:
            try:
                parsed = urlparse(self.url)
                self.source = parsed.netloc.replace("www.", "")
            except Exception:
                self.source = ""


class SearchProvider(ABC):
    """Abstract base class for swappable search providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        raise NotImplementedError

    @abstractmethod
    async def search(self, query: str, max_results: int = RESEARCH_MAX_RESULTS) -> list[SearchResult]:
        """Perform search and return normalized results."""
        raise NotImplementedError


class DuckDuckGoSearchProvider(SearchProvider):
    """
    DuckDuckGo search provider.
    
    Zero-config and free (no API key required). Parses DuckDuckGo HTML results
    with fallback to the DuckDuckGo Instant Answer API.
    """

    HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
    API_ENDPOINT = "https://api.duckduckgo.com/"

    def __init__(self, timeout: float = 12.0) -> None:
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "duckduckgo"

    async def search(self, query: str, max_results: int = RESEARCH_MAX_RESULTS) -> list[SearchResult]:
        stripped = query.strip()
        if not stripped:
            return []

        # 1. Primary: HTML search
        try:
            results = await self._search_html(stripped, max_results)
            if results:
                return results
        except Exception as exc:
            logger.warning("DuckDuckGo HTML search error: %s (attempting instant answer fallback)", exc)

        # 2. Fallback: Instant Answer API
        try:
            return await self._search_api(stripped, max_results)
        except Exception as exc:
            logger.error("DuckDuckGo instant answer fallback failed: %s", exc)
            return []

    async def _search_html(self, query: str, max_results: int) -> list[SearchResult]:
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        data = {"q": query, "b": ""}

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.post(self.HTML_ENDPOINT, data=data, headers=headers)
            if resp.status_code != 200:
                logger.warning("DuckDuckGo HTML returned HTTP %d", resp.status_code)
                return []
            text = resp.text

        results: list[SearchResult] = []
        # Split into result blocks or regex match
        # DuckDuckGo HTML puts each snippet into <div class="result ...">
        blocks = re.split(r'<div[^>]+class="[^"]*result[^"]*results_links[^"]*"', text)
        if len(blocks) <= 1:
            # Alternate match pattern
            blocks = re.findall(r'<div[^>]+class="[^"]*result\b[^"]*"[\s\S]*?</div>\s*</div>', text)

        for block in blocks:
            if len(results) >= max_results:
                break

            # Extract title and link
            # <a class="result__a" href="...">title</a>
            title_match = re.search(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', block)
            if not title_match:
                continue

            raw_url = title_match.group(1).strip()
            raw_title = title_match.group(2).strip()

            # Clean URL: DuckDuckGo uses redirect like /l/?uddg=https%3A%2F%2F...
            clean_url = self._extract_destination_url(raw_url)
            if not clean_url or not clean_url.startswith("http"):
                continue

            clean_title = html.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()

            # Extract snippet: <a class="result__snippet" ...>snippet</a>
            snippet_match = re.search(r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>([\s\S]*?)</a>', block)
            clean_snippet = ""
            if snippet_match:
                clean_snippet = html.unescape(re.sub(r"<[^>]+>", "", snippet_match.group(1))).strip()

            if clean_title and clean_url:
                results.append(
                    SearchResult(
                        title=clean_title,
                        url=clean_url,
                        snippet=clean_snippet or clean_title,
                    )
                )

        return results

    async def _search_api(self, query: str, max_results: int) -> list[SearchResult]:
        params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "0"}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(self.API_ENDPOINT, params=params, headers={"User-Agent": DEFAULT_USER_AGENT})
            if resp.status_code != 200:
                return []
            data = resp.json()

        results: list[SearchResult] = []
        # Abstract
        abstract = (data.get("AbstractText") or "").strip()
        abstract_url = (data.get("AbstractURL") or "").strip()
        heading = (data.get("Heading") or query).strip()
        if abstract and abstract_url:
            results.append(SearchResult(title=heading, url=abstract_url, snippet=abstract))

        # Related Topics
        for topic in data.get("RelatedTopics", []):
            if len(results) >= max_results:
                break
            if isinstance(topic, dict):
                text = (topic.get("Text") or "").strip()
                url = (topic.get("FirstURL") or "").strip()
                if text and url:
                    results.append(SearchResult(title=text.split(" - ")[0], url=url, snippet=text))

        return results

    @staticmethod
    def _extract_destination_url(raw_url: str) -> str:
        """Resolve DuckDuckGo redirect uddg parameter to clean target URL."""
        if "uddg=" in raw_url:
            parsed = urlparse(raw_url)
            params = parse_qs(parsed.query)
            if "uddg" in params:
                return urllib.parse.unquote(params["uddg"][0])
        if raw_url.startswith("//"):
            return "https:" + raw_url
        return raw_url


class TavilySearchProvider(SearchProvider):
    """Tavily search API provider."""

    ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None, timeout: float = 15.0) -> None:
        self.api_key = api_key or TAVILY_API_KEY
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "tavily"

    async def search(self, query: str, max_results: int = RESEARCH_MAX_RESULTS) -> list[SearchResult]:
        if not self.api_key:
            raise ValueError("Tavily API key is not configured")

        payload = {
            "api_key": self.api_key,
            "query": query.strip(),
            "search_depth": "basic",
            "max_results": max_results,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.ENDPOINT, json=payload)
            if resp.status_code == 429:
                logger.warning("Tavily rate limit exceeded (HTTP 429)")
                raise RuntimeError("Tavily rate limit exceeded")
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        for item in data.get("results", []):
            title = item.get("title", "").strip()
            url = item.get("url", "").strip()
            snippet = (item.get("content") or item.get("snippet") or "").strip()
            score = float(item.get("score") or 0.0)
            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=snippet, score=score))
        return results


class SerperSearchProvider(SearchProvider):
    """Google Serper.dev search API provider."""

    ENDPOINT = "https://google.serper.dev/search"

    def __init__(self, api_key: str | None = None, timeout: float = 15.0) -> None:
        self.api_key = api_key or SERPER_API_KEY
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "serper"

    async def search(self, query: str, max_results: int = RESEARCH_MAX_RESULTS) -> list[SearchResult]:
        if not self.api_key:
            raise ValueError("Serper API key is not configured")

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {"q": query.strip(), "num": max_results}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.ENDPOINT, headers=headers, json=payload)
            if resp.status_code == 429:
                logger.warning("Serper rate limit exceeded (HTTP 429)")
                raise RuntimeError("Serper rate limit exceeded")
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        for item in data.get("organic", []):
            title = item.get("title", "").strip()
            url = item.get("link", "").strip()
            snippet = item.get("snippet", "").strip()
            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=snippet))
        return results


class FallbackSearchProvider(SearchProvider):
    """Composes a primary provider with automatic fallback on failure."""

    def __init__(self, primary: SearchProvider, fallback: SearchProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    @property
    def name(self) -> str:
        return f"{self.primary.name}->{self.fallback.name}"

    async def search(self, query: str, max_results: int = RESEARCH_MAX_RESULTS) -> list[SearchResult]:
        try:
            results = await self.primary.search(query, max_results=max_results)
            if results:
                return results
            logger.info("Primary search provider '%s' returned empty results, using fallback '%s'", self.primary.name, self.fallback.name)
        except Exception as exc:
            logger.warning("Primary search provider '%s' failed: %s; falling back to '%s'", self.primary.name, exc, self.fallback.name)

        return await self.fallback.search(query, max_results=max_results)


def get_search_provider(name: str | None = None) -> SearchProvider:
    """Factory to create the configured search provider with DuckDuckGo fallback."""
    provider_name = (name or SEARCH_PROVIDER or "duckduckgo").strip().lower()
    ddg = DuckDuckGoSearchProvider()

    if provider_name == "tavily" and TAVILY_API_KEY:
        return FallbackSearchProvider(TavilySearchProvider(), ddg)
    if provider_name == "serper" and SERPER_API_KEY:
        return FallbackSearchProvider(SerperSearchProvider(), ddg)

    return ddg
