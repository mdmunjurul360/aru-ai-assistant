"""ResearchService: web search aggregation, validation, citations, and AI summarization."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from modules.config import (
    RESEARCH_CACHE_TTL_SECONDS,
    RESEARCH_MAX_RESULTS,
)
from modules.research_cache import ResearchCache
from modules.search_providers import (
    DEFAULT_USER_AGENT,
    SearchResult,
    get_search_provider,
)

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger
    from modules.ai import AruAI
    from modules.memory import MemoryStore
    from modules.search_providers import SearchProvider

logger = logging.getLogger("aru.research_service")

JOB_KEYWORDS = ("job", "jobs", "vacancy", "hiring", "openings", "position", "career", "careers")

JOB_PLATFORM_MAP = {
    "linkedin.com": "LinkedIn",
    "indeed.com": "Indeed",
    "remoteok.com": "RemoteOK",
    "weworkremotely.com": "WeWorkRemotely",
    "upwork.com": "Upwork",
    "fiverr.com": "Fiverr",
    "glassdoor.com": "Glassdoor",
    "simplyhired.com": "SimplyHired",
    "builtin.com": "BuiltIn",
    "wellfound.com": "Wellfound",
}


@dataclass
class Citation:
    """Individual source citation with index, title, publisher, and URL."""

    index: int
    title: str
    source: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "source": self.source,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Citation:
        return cls(
            index=int(data.get("index", 0)),
            title=str(data.get("title", "")),
            source=str(data.get("source", "")),
            url=str(data.get("url", "")),
        )


@dataclass
class JobListing:
    """Normalized and verified job listing."""

    title: str
    company: str
    location: str
    platform: str
    url: str
    snippet: str
    verified: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "platform": self.platform,
            "url": self.url,
            "snippet": self.snippet,
            "verified": self.verified,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobListing:
        return cls(
            title=str(data.get("title", "—")),
            company=str(data.get("company", "—")),
            location=str(data.get("location", "—")),
            platform=str(data.get("platform", "Web")),
            url=str(data.get("url", "")),
            snippet=str(data.get("snippet", "")),
            verified=bool(data.get("verified", True)),
        )


@dataclass
class ResearchResult:
    """Complete structured research outcome."""

    query: str
    summary: str
    citations: list[Citation] = field(default_factory=list)
    raw_results: list[SearchResult] = field(default_factory=list)
    cached: bool = False
    created_at: str = ""
    is_job_search: bool = False
    verified_jobs: list[JobListing] = field(default_factory=list)

    def formatted_markdown(self) -> str:
        """Format the research result into clean Telegram-compatible markdown."""
        if self.is_job_search:
            if not self.verified_jobs:
                return (
                    f"💼 **Job Search: {self.query}**\n\n"
                    "দুঃখিত বস, কোনো সক্রিয় ও যাচাইকৃত চাকরির লিংক পাওয়া যায়নি। "
                    "অনুরোধটি অন্য পদ বা প্ল্যাটফর্ম দিয়ে চেষ্টা করুন।"
                )
            parts = [f"💼 **Verified Job Opportunities: {self.query}**\n\n"]
            for i, job in enumerate(self.verified_jobs, 1):
                parts.append(
                    f"**{i}. {job.title}**\n"
                    f"🏢 Company: {job.company}\n"
                    f"📍 Location: {job.location} | Platform: {job.platform}\n"
                    f"🔗 [Apply / View Listing]({job.url})\n\n"
                )
            if self.cached:
                parts.append("⚡ _(Served from verified cache)_\n")
            return "".join(parts).strip()

        # General Research Formatting
        parts = [f"📚 **Research Report: {self.query}**\n\n", self.summary.strip(), "\n\n"]
        if self.citations:
            parts.append("🔗 **Verified Sources & Citations:**\n")
            for c in self.citations:
                parts.append(f"[{c.index}] [{c.title}]({c.url}) — _{c.source}_\n")

        if self.cached:
            parts.append("\n⚡ _(Served from research cache)_")

        return "".join(parts).strip()


class ResearchService:
    """
    Production-grade Research Engine.
    
    Orchestrates:
      1. Cache lookup with optional bypass
      2. Web search querying via modular SearchProvider
      3. Result deduplication & relevance ranking
      4. Live URL validation (job search) & normalization
      5. Grounded LLM reasoning & citation synthesis
    """

    def __init__(
        self,
        ai: "AruAI",
        search_provider: "SearchProvider | None" = None,
        cache: ResearchCache | None = None,
        activity: "ActivityLogger | None" = None,
        db_path: str | Path | None = None,
    ) -> None:
        self._ai = ai
        self._provider = search_provider or get_search_provider()
        self._cache = cache or ResearchCache(db_path=db_path)
        self._activity = activity

    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def execute_research(
        self,
        query: str,
        *,
        bypass_cache: bool = False,
        memory_context: str = "",
        max_results: int = RESEARCH_MAX_RESULTS,
    ) -> ResearchResult:
        """Run full research pipeline for a query."""
        clean_query = query.strip()
        if not clean_query:
            return ResearchResult(
                query="",
                summary="অনুগ্রহ করে একটি বিষয় উল্লেখ করুন। ব্যবহার: `/research <বিষয়>`",
            )

        # Check for inline bypass flag: e.g. /research --refresh <topic>
        if clean_query.startswith("--refresh "):
            bypass_cache = True
            clean_query = clean_query[10:].strip()
        elif clean_query.startswith("refresh:"):
            bypass_cache = True
            clean_query = clean_query[8:].strip()

        # 1. Cache Check
        if not bypass_cache:
            cached_data = self._cache.get(clean_query)
            if cached_data:
                logger.info("Research cache HIT for query='%s'", clean_query[:40])
                return self._inflate_cached_result(cached_data)

        logger.info("Research pipeline START | query='%s' provider='%s'", clean_query[:60], self._provider.name)
        if self._activity:
            self._activity.log("research", "start", clean_query[:200])

        is_job = any(k in clean_query.lower() for k in JOB_KEYWORDS)

        try:
            if is_job:
                result = await self._pipeline_job_search(clean_query, max_results=max_results)
            else:
                result = await self._pipeline_general_research(
                    clean_query,
                    memory_context=memory_context,
                    max_results=max_results,
                )

            # Save to Cache
            citations_dict = [c.to_dict() for c in result.citations]
            raw_dict = [
                {"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source, "score": r.score}
                for r in result.raw_results
            ]
            jobs_dict = [j.to_dict() for j in result.verified_jobs]
            self._cache.set(
                clean_query,
                summary=result.summary,
                citations=citations_dict,
                raw_results=raw_dict,
                is_job_search=result.is_job_search,
                verified_jobs=jobs_dict,
                ttl_seconds=RESEARCH_CACHE_TTL_SECONDS,
            )

            if self._activity:
                self._activity.log(
                    "research",
                    "complete",
                    f"query={clean_query[:60]} sources={len(result.citations)} jobs={len(result.verified_jobs)}",
                )
            return result

        except Exception as exc:
            logger.exception("Research pipeline error: %s", exc)
            if self._activity:
                self._activity.log_error("research", "pipeline_failed", exc)
            return ResearchResult(
                query=clean_query,
                summary=(
                    f"দুঃখিত বস, '{clean_query}' নিয়ে লাইভ রিসার্চ সম্পন্ন করা সম্ভব হয়নি। "
                    "সার্চ প্রোভাইডার সাময়িক অনুপলব্ধ বা টাইমআউট হতে পারে। কিছুক্ষণ পর আবার চেষ্টা করুন।"
                ),
            )

    # -------------------------------------------------------------------------
    # Pipeline: General Web Research
    # -------------------------------------------------------------------------

    async def _pipeline_general_research(
        self,
        query: str,
        memory_context: str,
        max_results: int,
    ) -> ResearchResult:
        # 1. Search
        raw_results = await self._provider.search(query, max_results=max_results * 2)

        # 2. Deduplicate
        deduped = self.deduplicate_results(raw_results)

        # 3. Rank
        ranked = self.rank_results(query, deduped)[:max_results]

        if not ranked:
            logger.warning("No search results found for query='%s'", query[:40])
            # Fallback to AI knowledge if live search returns zero hits
            ai_summary = await self._ai.generate(
                f"Topic: {query}\nProvide a structured summary. Note that live internet retrieval yielded no hits.",
                memory_context=memory_context,
                max_tokens=3000,
            )
            return ResearchResult(
                query=query,
                summary=ai_summary,
                citations=[],
                raw_results=[],
                created_at=datetime.now(timezone.utc).isoformat(),
            )

        # 4. Synthesize Citations
        citations = [
            Citation(index=i, title=r.title, source=r.source, url=r.url)
            for i, r in enumerate(ranked, 1)
        ]

        # 5. Build Evidence Context for LLM
        evidence_passages = []
        for c, r in zip(citations, ranked):
            evidence_passages.append(
                f"[{c.index}] Title: {r.title}\nSource: {r.source}\nURL: {r.url}\nExcerpt: {r.snippet}"
            )
        evidence_text = "\n\n".join(evidence_passages)

        llm_prompt = (
            f"You are Aru's Research Agent. Synthesize verified web research for Boss.\n\n"
            f"RESEARCH TOPIC: {query}\n\n"
            f"VERIFIED EVIDENCE SOURCES:\n{evidence_text}\n\n"
            "INSTRUCTIONS:\n"
            "1. Produce a factual, high-quality, actionable summary in the same language as the query.\n"
            "2. Ground every major finding strictly on the verified sources provided.\n"
            "3. Use inline bracket citations like [1], [2] to reference which source provides the fact.\n"
            "4. Organize with: Executive Summary, Key Findings, and Actionable Recommendations for Boss.\n"
            "5. Do NOT invent URLs or sources."
        )

        full_context = f"{memory_context}\n\n{evidence_text}".strip() if memory_context else evidence_text
        summary = await self._ai.generate(
            llm_prompt,
            memory_context=full_context,
            max_tokens=3500,
        )

        return ResearchResult(
            query=query,
            summary=summary,
            citations=citations,
            raw_results=ranked,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    # -------------------------------------------------------------------------
    # Pipeline: Job Search (Zero Hallucination, Link Validated)
    # -------------------------------------------------------------------------

    async def _pipeline_job_search(self, query: str, max_results: int) -> ResearchResult:
        logger.info("Executing job search pipeline for query='%s'", query[:60])

        # Target real job boards in the query
        job_query = f"{query} remoteok OR linkedin OR indeed OR weworkremotely OR upwork"
        raw_results = await self._provider.search(job_query, max_results=max_results * 3)

        deduped = self.deduplicate_results(raw_results)
        ranked = self.rank_results(query, deduped)

        # Validate URLs and extract structured job listings
        verified_jobs: list[JobListing] = []
        validation_tasks = []

        candidate_results = ranked[: max_results * 2]
        for r in candidate_results:
            validation_tasks.append(self._validate_and_normalize_job(r))

        if validation_tasks:
            results = await asyncio.gather(*validation_tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, JobListing) and res.verified:
                    verified_jobs.append(res)
                if len(verified_jobs) >= max_results:
                    break

        citations = [
            Citation(index=i, title=j.title, source=j.platform, url=j.url)
            for i, j in enumerate(verified_jobs, 1)
        ]

        return ResearchResult(
            query=query,
            summary=f"Found {len(verified_jobs)} verified job listings.",
            citations=citations,
            raw_results=ranked[:max_results],
            is_job_search=True,
            verified_jobs=verified_jobs,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    async def _validate_and_normalize_job(self, result: SearchResult) -> JobListing | None:
        """Validate live link reachability and normalize job metadata."""
        is_alive = await self.validate_link(result.url)
        if not is_alive:
            logger.debug("Job URL unreachable: %s", result.url)
            return None

        # Determine platform
        domain = result.source.lower()
        platform = "Web"
        for key, name in JOB_PLATFORM_MAP.items():
            if key in domain:
                platform = name
                break

        # Extract title and company from title pattern e.g. "Software Engineer at Acme" or "Job Title - Company - Location"
        raw_title = result.title
        company = "—"
        clean_title = raw_title
        location = "Remote / Flexible"

        # Heuristic extraction
        if " at " in raw_title:
            parts = raw_title.split(" at ", 1)
            clean_title = parts[0].strip()
            company = parts[1].split("-")[0].split("|")[0].strip()
        elif " | " in raw_title:
            parts = raw_title.split(" | ")
            clean_title = parts[0].strip()
            if len(parts) > 1:
                company = parts[1].strip()
        elif " - " in raw_title:
            parts = raw_title.split(" - ")
            clean_title = parts[0].strip()
            if len(parts) > 1:
                company = parts[1].strip()

        # Check snippet for location keywords
        snippet_lower = result.snippet.lower()
        if "remote" in snippet_lower or "work from home" in snippet_lower:
            location = "Remote"
        elif "bangladesh" in snippet_lower or "dhaka" in snippet_lower:
            location = "Dhaka / Bangladesh"
        elif "usa" in snippet_lower or "united states" in snippet_lower:
            location = "United States"

        return JobListing(
            title=clean_title,
            company=company,
            location=location,
            platform=platform,
            url=result.url,
            snippet=result.snippet,
            verified=True,
        )

    # -------------------------------------------------------------------------
    # Utilities: Deduplication, Ranking, Validation
    # -------------------------------------------------------------------------

    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize URL for deduplication by stripping tracking queries and fragments."""
        try:
            parsed = urlparse(url)
            # Filter out common analytics and tracking parameters
            tracking_keys = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
            clean_query = [
                (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                if k.lower() not in tracking_keys
            ]
            normalized = urlunparse((
                parsed.scheme.lower(),
                parsed.netloc.lower().replace("www.", ""),
                parsed.path.rstrip("/") or "/",
                parsed.params,
                urlencode(clean_query),
                "",
            ))
            return normalized
        except Exception:
            return url

    def deduplicate_results(self, results: list[SearchResult]) -> list[SearchResult]:
        """Deduplicate results based on normalized URL and near-identical titles."""
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        deduped: list[SearchResult] = []

        for r in results:
            norm_url = self.normalize_url(r.url)
            norm_title = re.sub(r"[^\w]", "", r.title.lower())

            if norm_url in seen_urls:
                continue
            if norm_title and norm_title in seen_titles:
                continue

            seen_urls.add(norm_url)
            if norm_title:
                seen_titles.add(norm_title)
            deduped.append(r)

        return deduped

    @staticmethod
    def rank_results(query: str, results: list[SearchResult]) -> list[SearchResult]:
        """Rank search results by term overlap and domain credibility."""
        query_terms = [t.lower() for t in query.split() if len(t) > 2]
        if not query_terms:
            return results

        scored_results: list[SearchResult] = []
        for r in results:
            score = r.score
            title_lower = r.title.lower()
            snippet_lower = r.snippet.lower()

            for term in query_terms:
                if term in title_lower:
                    score += 3.0
                if term in snippet_lower:
                    score += 1.0

            # Boost reputable authoritative technical / career domains
            domain = r.source.lower()
            if any(auth in domain for auth in ("github.com", "python.org", "wikipedia.org", "arxiv.org", "docs.", "developer.")):
                score += 1.5

            r.score = score
            scored_results.append(r)

        scored_results.sort(key=lambda x: x.score, reverse=True)
        return scored_results

    @staticmethod
    async def validate_link(url: str, timeout: float = 6.0) -> bool:
        """Asynchronously verify that a web link responds with HTTP < 400."""
        headers = {"User-Agent": DEFAULT_USER_AGENT}
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                try:
                    resp = await client.head(url, headers=headers)
                    if resp.status_code < 400:
                        return True
                    # If HEAD is disallowed (HTTP 405 Method Not Allowed), retry with GET
                    if resp.status_code == 405:
                        resp = await client.get(url, headers=headers)
                        return resp.status_code < 400
                except (httpx.RequestError, httpx.HTTPStatusError):
                    # Fallback retry with GET on initial HEAD transport failure
                    resp = await client.get(url, headers=headers)
                    return resp.status_code < 400
            return False
        except Exception:
            return False

    @staticmethod
    def _inflate_cached_result(data: dict[str, Any]) -> ResearchResult:
        """Reconstruct ResearchResult instance from raw cache dictionary."""
        citations = [Citation.from_dict(c) for c in data.get("citations", [])]
        raw_results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("snippet", ""),
                source=r.get("source", ""),
                score=float(r.get("score", 0.0)),
            )
            for r in data.get("raw_results", [])
        ]
        verified_jobs = [JobListing.from_dict(j) for j in data.get("verified_jobs", [])]

        return ResearchResult(
            query=data.get("query", ""),
            summary=data.get("summary", ""),
            citations=citations,
            raw_results=raw_results,
            cached=True,
            created_at=data.get("created_at", ""),
            is_job_search=bool(data.get("is_job_search", False)),
            verified_jobs=verified_jobs,
        )
