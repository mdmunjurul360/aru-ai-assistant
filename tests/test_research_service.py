"""Tests for ResearchService, search providers, caching, citations, and job validation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from modules.research import ResearchAgent
from modules.research_cache import ResearchCache
from modules.research_service import (
    Citation,
    JobListing,
    ResearchResult,
    ResearchService,
)
from modules.search_providers import (
    DuckDuckGoSearchProvider,
    FallbackSearchProvider,
    SearchResult,
    SerperSearchProvider,
    TavilySearchProvider,
    get_search_provider,
)


class MockAI:
    """Mock AruAI for fast deterministic test execution."""

    def __init__(self, reply: str = "Synthesized research summary with [1] and [2].") -> None:
        self.reply = reply
        self.generate = AsyncMock(return_value=self.reply)


# =============================================================================
# 1. Search Providers Tests
# =============================================================================

@pytest.mark.asyncio
async def test_duckduckgo_search_provider_html_parsing() -> None:
    provider = DuckDuckGoSearchProvider()
    mock_html = """
    <div class="result results_links">
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org%2Fdoc">Python Documentation</a>
        <a class="result__snippet">Official documentation and language tutorials for Python.</a>
    </div>
    <div class="result results_links">
        <a class="result__a" href="https://realpython.com/async-io">Async IO in Python</a>
        <a class="result__snippet">Complete guide to asyncio in Python 3.</a>
    </div>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_html

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_resp):
        results = await provider.search("python asyncio", max_results=5)

    assert len(results) == 2
    assert results[0].title == "Python Documentation"
    assert results[0].url == "https://python.org/doc"
    assert results[0].source == "python.org"
    assert "Official documentation" in results[0].snippet

    assert results[1].title == "Async IO in Python"
    assert results[1].url == "https://realpython.com/async-io"
    assert results[1].source == "realpython.com"


@pytest.mark.asyncio
async def test_tavily_search_provider_success() -> None:
    provider = TavilySearchProvider(api_key="tvly-mock-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {"title": "GCP Cloud Run Guide", "url": "https://cloud.google.com/run", "content": "Deploy containers instantly.", "score": 0.95}
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_resp):
        results = await provider.search("Cloud Run")

    assert len(results) == 1
    assert results[0].title == "GCP Cloud Run Guide"
    assert results[0].url == "https://cloud.google.com/run"
    assert results[0].source == "cloud.google.com"
    assert results[0].score == 0.95


@pytest.mark.asyncio
async def test_tavily_missing_key_raises_error() -> None:
    provider = TavilySearchProvider(api_key="")
    with pytest.raises(ValueError, match="Tavily API key is not configured"):
        await provider.search("test")


@pytest.mark.asyncio
async def test_serper_search_provider_success() -> None:
    provider = SerperSearchProvider(api_key="serper-mock-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "organic": [
            {"title": "FastAPI Framework", "link": "https://fastapi.tiangolo.com", "snippet": "High performance web framework"}
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_resp):
        results = await provider.search("FastAPI")

    assert len(results) == 1
    assert results[0].title == "FastAPI Framework"
    assert results[0].url == "https://fastapi.tiangolo.com"
    assert results[0].source == "fastapi.tiangolo.com"


@pytest.mark.asyncio
async def test_fallback_search_provider_triggers_on_error() -> None:
    primary = TavilySearchProvider(api_key="mock-key")
    fallback = DuckDuckGoSearchProvider()
    composite = FallbackSearchProvider(primary, fallback)

    # Primary raises exception
    with patch.object(primary, "search", side_effect=RuntimeError("API Down")):
        with patch.object(fallback, "search", new_callable=AsyncMock, return_value=[
            SearchResult(title="Fallback Result", url="https://example.com", snippet="Retrieved via fallback")
        ]):
            results = await composite.search("test query")

    assert len(results) == 1
    assert results[0].title == "Fallback Result"


def test_get_search_provider_factory() -> None:
    ddg = get_search_provider("duckduckgo")
    assert isinstance(ddg, DuckDuckGoSearchProvider)

    # When no key is set for tavily, defaults safely to DuckDuckGo
    with patch("modules.search_providers.TAVILY_API_KEY", ""):
        provider = get_search_provider("tavily")
        assert isinstance(provider, DuckDuckGoSearchProvider)


# =============================================================================
# 2. Caching Tests
# =============================================================================

def test_research_cache_lifecycle(tmp_db_path: str) -> None:
    cache = ResearchCache(db_path=tmp_db_path)

    assert cache.get("Python async") is None

    citations = [{"index": 1, "title": "Doc", "source": "python.org", "url": "https://python.org"}]
    raw_results = [{"title": "Doc", "url": "https://python.org", "snippet": "Text", "source": "python.org", "score": 1.0}]

    cache.set("Python async", "Summary text", citations, raw_results, ttl_seconds=3600)

    entry = cache.get("Python async")
    assert entry is not None
    assert entry["summary"] == "Summary text"
    assert len(entry["citations"]) == 1
    assert entry["citations"][0]["url"] == "https://python.org"
    assert entry["cached"] is True


def test_research_cache_expiration(tmp_db_path: str) -> None:
    cache = ResearchCache(db_path=tmp_db_path)

    # Set cache with ttl of -1 second (already expired)
    cache.set("Expired topic", "Old summary", [], [], ttl_seconds=-1)

    assert cache.get("Expired topic") is None
    # Prune expired check
    pruned = cache.prune_expired()
    assert isinstance(pruned, int)


def test_research_cache_invalidation_and_clear(tmp_db_path: str) -> None:
    cache = ResearchCache(db_path=tmp_db_path)

    cache.set("Topic A", "Summary A", [], [])
    cache.set("Topic B", "Summary B", [], [])

    assert cache.get("Topic A") is not None
    assert cache.invalidate("Topic A") is True
    assert cache.get("Topic A") is None
    assert cache.get("Topic B") is not None

    cleared = cache.clear()
    assert cleared >= 1
    assert cache.get("Topic B") is None


# =============================================================================
# 3. Deduplication and Ranking Tests
# =============================================================================

def test_result_deduplication() -> None:
    ai = MockAI()
    service = ResearchService(ai=ai)

    raw = [
        SearchResult(title="Article 1", url="https://example.com/post?utm_source=twitter", snippet="Snippet 1"),
        SearchResult(title="Article 1 Duplicate", url="https://example.com/post?utm_source=facebook", snippet="Snippet 2"),
        SearchResult(title="Article 2", url="https://example.com/other", snippet="Snippet 3"),
    ]

    deduped = service.deduplicate_results(raw)
    assert len(deduped) == 2
    assert deduped[0].url.startswith("https://example.com/post")
    assert deduped[1].url.startswith("https://example.com/other")


def test_result_ranking_relevance() -> None:
    raw = [
        SearchResult(title="Random Page", url="https://general.com", snippet="Mentions machine learning once in footer", source="general.com"),
        SearchResult(title="Machine Learning Guide", url="https://docs.python.org/ml", snippet="Comprehensive guide to machine learning models", source="docs.python.org"),
    ]

    ranked = ResearchService.rank_results("machine learning", raw)
    assert len(ranked) == 2
    # The second result has query in title, snippet, and authoritative domain -> should rank first
    assert ranked[0].title == "Machine Learning Guide"
    assert ranked[0].score > ranked[1].score


# =============================================================================
# 4. Job Search Pipeline & Link Validation Tests
# =============================================================================

@pytest.mark.asyncio
async def test_job_link_validation_success() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch.object(httpx.AsyncClient, "head", new_callable=AsyncMock, return_value=mock_resp):
        is_valid = await ResearchService.validate_link("https://remoteok.com/job/12345")
        assert is_valid is True


@pytest.mark.asyncio
async def test_job_link_validation_failure() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.object(httpx.AsyncClient, "head", new_callable=AsyncMock, return_value=mock_resp):
        is_valid = await ResearchService.validate_link("https://broken-link.com/job/invalid")
        assert is_valid is False


@pytest.mark.asyncio
async def test_job_search_pipeline_integration(tmp_db_path: str) -> None:
    ai = MockAI()
    cache = ResearchCache(db_path=tmp_db_path)
    mock_provider = MagicMock()
    mock_provider.name = "mock"
    mock_provider.search = AsyncMock(return_value=[
        SearchResult(
            title="Senior Python Engineer at Acme Corp",
            url="https://remoteok.com/jobs/99123",
            snippet="Remote Python developer position with FastAPI experience.",
            source="remoteok.com",
        ),
        SearchResult(
            title="Dead Job Listing",
            url="https://linkedin.com/jobs/dead404",
            snippet="Expired position.",
            source="linkedin.com",
        )
    ])

    service = ResearchService(ai=ai, search_provider=mock_provider, cache=cache)

    # Mock link validation: first is alive (200), second is dead (404)
    async def mock_validate(url: str, timeout: float = 6.0) -> bool:
        return "remoteok.com" in url

    with patch.object(ResearchService, "validate_link", side_effect=mock_validate):
        result = await service.execute_research("Python developer jobs")

    assert result.is_job_search is True
    assert len(result.verified_jobs) == 1
    job = result.verified_jobs[0]
    assert "Senior Python Engineer" in job.title
    assert job.company == "Acme Corp"
    assert job.platform == "RemoteOK"
    assert job.verified is True

    # Output markdown check
    markdown = result.formatted_markdown()
    assert "Verified Job Opportunities" in markdown
    assert "Acme Corp" in markdown
    assert "https://remoteok.com/jobs/99123" in markdown


# =============================================================================
# 5. General Research Pipeline & Citations
# =============================================================================

@pytest.mark.asyncio
async def test_general_research_pipeline_flow(tmp_db_path: str) -> None:
    ai = MockAI(reply="Executive Summary: Python asyncio is performant [1]. Key Findings: Non-blocking event loop [2].")
    cache = ResearchCache(db_path=tmp_db_path)
    mock_provider = MagicMock()
    mock_provider.name = "mock"
    mock_provider.search = AsyncMock(return_value=[
        SearchResult(
            title="Asyncio Documentation",
            url="https://docs.python.org/3/library/asyncio.html",
            snippet="Asyncio is a library to write concurrent code using the async/await syntax.",
            source="docs.python.org",
        ),
        SearchResult(
            title="Understanding Async in Python",
            url="https://realpython.com/async-io-python/",
            snippet="Complete overview of event loops and tasks.",
            source="realpython.com",
        ),
    ])

    service = ResearchService(ai=ai, search_provider=mock_provider, cache=cache)

    result = await service.execute_research("Python asyncio best practices")

    assert result.is_job_search is False
    assert len(result.citations) == 2
    assert result.citations[0].index == 1
    assert result.citations[0].url == "https://docs.python.org/3/library/asyncio.html"
    assert result.citations[0].source == "docs.python.org"

    markdown = result.formatted_markdown()
    assert "Research Report:" in markdown
    assert "Verified Sources & Citations:" in markdown
    assert "[1] [Asyncio Documentation]" in markdown

    # Verify result was stored in cache
    cached_entry = cache.get("Python asyncio best practices")
    assert cached_entry is not None
    assert cached_entry["summary"] == result.summary


@pytest.mark.asyncio
async def test_research_cache_bypass_flag(tmp_db_path: str) -> None:
    ai = MockAI(reply="Fresh generated report")
    cache = ResearchCache(db_path=tmp_db_path)
    mock_provider = MagicMock()
    mock_provider.name = "mock"
    mock_provider.search = AsyncMock(return_value=[
        SearchResult(title="Article", url="https://example.com/1", snippet="Snippet", source="example.com")
    ])

    service = ResearchService(ai=ai, search_provider=mock_provider, cache=cache)

    # First run sets cache
    res1 = await service.execute_research("AI Agents")
    assert res1.cached is False

    # Second run hits cache
    res2 = await service.execute_research("AI Agents")
    assert res2.cached is True

    # Third run with bypass_cache flag ignores cache and queries provider
    res3 = await service.execute_research("AI Agents", bypass_cache=True)
    assert res3.cached is False
    assert mock_provider.search.call_count == 2


# =============================================================================
# 6. Failure & Error Handling Tests
# =============================================================================

@pytest.mark.asyncio
async def test_search_provider_timeout_handled_gracefully(tmp_db_path: str) -> None:
    ai = MockAI()
    cache = ResearchCache(db_path=tmp_db_path)
    mock_provider = MagicMock()
    mock_provider.name = "mock_timeout"
    mock_provider.search = AsyncMock(side_effect=httpx.TimeoutException("Search API timed out"))

    service = ResearchService(ai=ai, search_provider=mock_provider, cache=cache)

    result = await service.execute_research("Quantum Computing")
    assert "সময়" in result.summary or "অনুপলব্ধ" in result.summary or "টাইমআউট" in result.summary


@pytest.mark.asyncio
async def test_empty_search_results_fallback(tmp_db_path: str) -> None:
    ai = MockAI(reply="AI knowledge fallback summary.")
    cache = ResearchCache(db_path=tmp_db_path)
    mock_provider = MagicMock()
    mock_provider.name = "mock_empty"
    mock_provider.search = AsyncMock(return_value=[])

    service = ResearchService(ai=ai, search_provider=mock_provider, cache=cache)

    result = await service.execute_research("Extremely Obscure Query 123456789")
    assert len(result.citations) == 0
    assert result.summary == "AI knowledge fallback summary."


# =============================================================================
# 7. ResearchAgent Backward Compatibility Tests
# =============================================================================

@pytest.mark.asyncio
async def test_research_agent_backward_compatibility(tmp_db_path: str) -> None:
    ai = MockAI(reply="Agent summary")
    cache = ResearchCache(db_path=tmp_db_path)
    mock_provider = MagicMock()
    mock_provider.name = "mock"
    mock_provider.search = AsyncMock(return_value=[
        SearchResult(title="Topic", url="https://example.com/topic", snippet="Snippet", source="example.com")
    ])
    service = ResearchService(ai=ai, search_provider=mock_provider, cache=cache)
    agent = ResearchAgent(ai=ai, service=service)

    # Test legacy command parsing
    assert agent.handle_command("/research") is not None
    assert "ব্যবহার" in agent.handle_command("/research")
    assert agent.handle_command("/research Python") == "__RESEARCH__:Python"

    # Test legacy async handler
    response = await agent.handle_command_async("/research Python")
    assert isinstance(response, str)
    assert "Research Report" in response
    assert "https://example.com/topic" in response

    # Test structured return method
    structured = await agent.research_structured("Python")
    assert isinstance(structured, ResearchResult)
    assert len(structured.citations) == 1
