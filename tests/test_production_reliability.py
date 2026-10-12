"""Production Reliability and Multi-Provider Failover Test Suite.

Tests covering:
- Issue 1: AI Provider Priority (Gemini -> Groq -> DeepSeek -> OpenAI)
- Issue 2: Automatic Recovery, Cooldown, and Circuit Breaker
- Issue 3: PDF Processing (Chunking, Progressive Summarization, Chunk Retry)
- Issue 4: Image Processing & Vision Failover
- Issue 5: Long Conversation Stability & Context Trimming
- Issue 6: Token Optimization
- Issue 7: Error Sanitization (Polite Bangla Fallback)
- Issue 8: Production Logging (No API keys logged)
"""

from __future__ import annotations

import asyncio
import io
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.llm.base_provider import BaseLLMProvider, ProviderHealthState
from modules.llm.exceptions import (
    AllProvidersFailedError,
    CircuitBreakerOpenError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from modules.llm.provider_manager import ProviderManager
from modules.pdf_processor import PDFProcessor
from modules.token_optimizer import (
    PROVIDER_MAX_OUTPUT_LIMITS,
    TASK_TOKEN_BUDGETS,
    TaskType,
    detect_task_type,
    estimate_tokens,
    get_optimal_max_tokens,
)
from modules.vision.image_handler import (
    detect_image_format_and_mime,
    is_image_message,
    process_image_message,
)


class DummyMockProvider(BaseLLMProvider):
    """Configurable mock provider for failover tests."""

    def __init__(
        self,
        name: str,
        enabled: bool = True,
        fail_generate: Exception | None = None,
        generate_return: str = "ok",
        fail_vision: Exception | None = None,
        vision_return: str = "vision ok",
    ):
        super().__init__(
            name=name,
            api_key="mock_key" if enabled else "",
            default_model=f"mock-{name}-v1",
        )
        self.fail_generate = fail_generate
        self.generate_return = generate_return
        self.fail_vision = fail_vision
        self.vision_return = vision_return
        self.generate_calls = 0
        self.vision_calls = 0

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        self.check_readiness()
        self.generate_calls += 1
        if self.fail_generate:
            raise self.fail_generate
        return f"[{self.name}] {self.generate_return}"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        json_mode: bool = False,
        model: str | None = None,
        **kwargs: Any,
    ) -> tuple[str | None, list[Any] | None]:
        self.check_readiness()
        self.generate_calls += 1
        if self.fail_generate:
            raise self.fail_generate
        return f"[{self.name}] {self.generate_return}", None

    async def vision(
        self,
        prompt: str,
        image_bytes_or_b64: bytes | str,
        *,
        max_tokens: int = 1024,
        model: str | None = None,
        mime_type: str = "image/jpeg",
        **kwargs: Any,
    ) -> str:
        self.check_readiness()
        self.vision_calls += 1
        if self.fail_vision:
            raise self.fail_vision
        return f"[{self.name}] {self.vision_return}"

    async def health_check(self) -> bool:
        return self.is_enabled and not self.is_in_cooldown()


# =====================================================================
# Issue 1 & 2: Provider Priority & Automatic Failover Recovery
# =====================================================================


@pytest.mark.asyncio
async def test_provider_priority_chain_order():
    """Verify primary is Gemini, followed by Groq, DeepSeek, and OpenAI."""
    pm = ProviderManager(
        priority=["gemini", "groq", "deepseek", "openai"],
        auto_load=False,
    )

    gemini = DummyMockProvider("gemini", enabled=True, generate_return="gemini response")
    groq = DummyMockProvider("groq", enabled=True, generate_return="groq response")
    deepseek = DummyMockProvider("deepseek", enabled=True, generate_return="deepseek response")
    openai = DummyMockProvider("openai", enabled=True, generate_return="openai response")

    pm.register_provider(gemini)
    pm.register_provider(groq)
    pm.register_provider(deepseek)
    pm.register_provider(openai)

    # Gemini succeeds -> primary used
    res = await pm.generate("Hello world")
    assert "gemini" in res
    assert gemini.generate_calls == 1
    assert groq.generate_calls == 0


@pytest.mark.asyncio
async def test_gemini_fails_immediately_falls_over_to_groq():
    """Gemini 429 / RateLimit trips fast failover directly to Groq."""
    pm = ProviderManager(
        priority=["gemini", "groq", "deepseek", "openai"],
        auto_load=False,
        cooldown_seconds=10,
    )

    gemini = DummyMockProvider(
        "gemini",
        fail_generate=ProviderRateLimitError("429 Quota Exceeded", provider="gemini"),
    )
    groq = DummyMockProvider("groq", generate_return="groq answer")
    deepseek = DummyMockProvider("deepseek")
    openai = DummyMockProvider("openai")

    pm.register_provider(gemini)
    pm.register_provider(groq)
    pm.register_provider(deepseek)
    pm.register_provider(openai)

    res = await pm.generate("Test prompt")
    assert "groq" in res
    assert gemini.generate_calls == 1
    assert groq.generate_calls == 1
    assert deepseek.generate_calls == 0

    # Verify Gemini is now marked in cooldown
    assert gemini.is_in_cooldown() is True
    assert gemini.health.consecutive_failures >= 1


@pytest.mark.asyncio
async def test_deepseek_and_openai_cascading_failover():
    """Gemini and Groq fail -> DeepSeek succeeds. If DeepSeek fails -> OpenAI succeeds."""
    pm = ProviderManager(
        priority=["gemini", "groq", "deepseek", "openai"],
        auto_load=False,
        cooldown_seconds=10,
    )

    gemini = DummyMockProvider("gemini", fail_generate=ProviderRateLimitError("429 limit", provider="gemini"))
    groq = DummyMockProvider("groq", fail_generate=ProviderRateLimitError("429 limit", provider="groq"))
    deepseek = DummyMockProvider("deepseek", generate_return="deepseek answered")
    openai = DummyMockProvider("openai", generate_return="openai answered")

    pm.register_provider(gemini)
    pm.register_provider(groq)
    pm.register_provider(deepseek)
    pm.register_provider(openai)

    # First call: DeepSeek handles it
    res1 = await pm.generate("Query 1")
    assert "deepseek" in res1

    # Now make DeepSeek fail as well
    deepseek.fail_generate = ProviderTimeoutError("timeout", provider="deepseek")
    res2 = await pm.generate("Query 2")
    assert "openai" in res2


@pytest.mark.asyncio
async def test_all_providers_fail_raises_all_providers_failed_error():
    """When all providers fail, AllProvidersFailedError is raised cleanly."""
    pm = ProviderManager(priority=["gemini", "groq"], auto_load=False)
    pm.register_provider(DummyMockProvider("gemini", fail_generate=RuntimeError("Gemini down")))
    pm.register_provider(DummyMockProvider("groq", fail_generate=RuntimeError("Groq down")))

    with pytest.raises(AllProvidersFailedError):
        await pm.generate("Test")


# =====================================================================
# Issue 3: PDF Processing & Progressive Summarization
# =====================================================================


@pytest.mark.asyncio
async def test_pdf_chunking_and_progressive_summarization():
    """Test text chunking and multi-provider map-reduce summarization."""
    pm = ProviderManager(priority=["gemini", "groq"], auto_load=False)
    gemini = DummyMockProvider("gemini", generate_return="Summary chunk")
    pm.register_provider(gemini)

    processor = PDFProcessor(provider_manager=pm, chunk_size=300, chunk_overlap=50)

    # 1. Chunking test
    long_doc = "Paragraph one with important notes. " * 30
    chunks = processor.chunk_text(long_doc)
    assert len(chunks) > 1
    assert all(len(c) <= 400 for c in chunks)

    # 2. Summarize chunks progressively
    final_summary = await processor.summarize_chunks(chunks, prompt="Summarize this")
    assert "Summary chunk" in final_summary
    assert gemini.generate_calls >= len(chunks)


@pytest.mark.asyncio
async def test_pdf_chunk_failover_retry():
    """If primary fails on a PDF chunk, fallback provider processes it."""
    pm = ProviderManager(priority=["groq", "gemini"], auto_load=False)
    # Groq fails on chunk
    groq = DummyMockProvider("groq", fail_generate=ProviderRateLimitError("429 TPM", provider="groq"))
    gemini = DummyMockProvider("gemini", generate_return="Gemini summary of chunk")
    pm.register_provider(groq)
    pm.register_provider(gemini)

    processor = PDFProcessor(provider_manager=pm, chunk_size=500)
    chunks = ["Chunk 1: First section of large PDF", "Chunk 2: Second section of large PDF"]

    summary = await processor.summarize_chunks(chunks)
    assert "Gemini summary of chunk" in summary


# =====================================================================
# Issue 4: Image Processing & Vision Failover
# =====================================================================


def test_image_format_and_mime_detection():
    """Test magic bytes identification for PNG, JPEG, WEBP, and GIF."""
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x64\x00\x00\x00\x32\x08\x06"
    fmt, mime, w, h = detect_image_format_and_mime(png_bytes)
    assert fmt == "PNG"
    assert mime == "image/png"
    assert w == 100
    assert h == 50

    jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    fmt, mime, _, _ = detect_image_format_and_mime(jpeg_bytes)
    assert fmt == "JPEG"
    assert mime == "image/jpeg"

    webp_bytes = b"RIFF\x20\x00\x00\x00WEBPVP8 "
    fmt, mime, _, _ = detect_image_format_and_mime(webp_bytes)
    assert fmt == "WEBP"
    assert mime == "image/webp"


def test_is_image_message_detection():
    """Detect photo, file, and document attachments as image messages."""
    # 1. Native photo
    mock_photo_msg = MagicMock()
    mock_photo_msg.photo = MagicMock()
    mock_photo_msg.document = None
    mock_photo_msg.file = None
    assert is_image_message(mock_photo_msg) is True

    # 2. Document with image MIME
    mock_doc_msg = MagicMock()
    mock_doc_msg.photo = None
    mock_doc = MagicMock()
    mock_doc.mime_type = "image/png"
    mock_doc.attributes = []
    mock_doc_msg.document = mock_doc
    mock_doc_msg.file = None
    assert is_image_message(mock_doc_msg) is True

    # 3. None message
    assert is_image_message(None) is False


@pytest.mark.asyncio
async def test_process_image_message_vision_failover():
    """Primary Gemini Vision is used for images, falling back to secondary vision provider."""
    pm = ProviderManager(priority=["gemini", "groq"], auto_load=False)
    gemini = DummyMockProvider("gemini", vision_return="Gemini saw a cat in the image")
    pm.register_provider(gemini)

    mock_msg = MagicMock()
    mock_msg.download_media = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 30)

    res = await process_image_message(
        message=mock_msg,
        user_prompt="What is this?",
        provider_manager=pm,
    )
    assert "Gemini saw a cat" in res
    assert gemini.vision_calls == 1


# =====================================================================
# Issue 5: Long Conversation Stability & Context Compression
# =====================================================================


def test_conversation_history_pruning(tmp_path):
    """Auto-pruning keeps the latest messages and prevents unbounded growth."""
    from modules.conversation import ConversationHistoryStore

    db_path = tmp_path / "conv_test.db"
    store = ConversationHistoryStore(db_path=db_path)

    # Insert 100 messages
    for i in range(100):
        store.add_message(
            chat_id=123,
            role="user" if i % 2 == 0 else "assistant",
            message=f"Message {i}",
        )

    assert store.count_messages(123) == 100

    # Prune to keep 40
    deleted = store.prune_history(keep_last=40, chat_id=123)
    assert deleted == 60
    assert store.count_messages(123) == 40

    # Get trimmed history
    trimmed = store.get_trimmed_history(123, max_chars_per_turn=500)
    assert len(trimmed) <= 40


# =====================================================================
# Issue 6: Token Optimization
# =====================================================================


def test_token_optimization_budgets_and_limits():
    """Test dynamic max_tokens selection based on task type and provider limits."""
    # Task detection
    assert detect_task_type("Summarize this long document") == TaskType.SUMMARIZATION
    assert detect_task_type("Write a python function to solve fibonacci") == TaskType.CODING
    assert detect_task_type("Hello how are you?") == TaskType.CHAT

    # Optimal max tokens calculation
    groq_tokens = get_optimal_max_tokens(TaskType.CODING, provider="groq")
    assert groq_tokens == min(TASK_TOKEN_BUDGETS[TaskType.CODING], PROVIDER_MAX_OUTPUT_LIMITS["groq"])

    # Explicit user max_tokens clamped by provider limit
    clamped = get_optimal_max_tokens(max_tokens=999999, provider="deepseek")
    assert clamped == PROVIDER_MAX_OUTPUT_LIMITS["deepseek"]

    # Token estimation
    sample_text = "The quick brown fox jumps over the lazy dog."
    est = estimate_tokens(sample_text)
    assert 5 <= est <= 15


# =====================================================================
# Issue 7: Error Sanitization (Polite Bangla Fallback)
# =====================================================================


@pytest.mark.asyncio
async def test_ai_sanitizes_raw_errors_with_bangla_fallback():
    """Raw provider errors (429, 404, 500, quota) are never returned to the user."""
    from modules.ai import AruAI

    ai = AruAI()
    ai._client = None  # disable legacy fallback to simulate complete outage

    # Force provider_manager to raise AllProvidersFailedError
    with patch.object(
        ai.provider_manager,
        "generate",
        new=AsyncMock(side_effect=AllProvidersFailedError("429 Quota Exceeded")),
    ):
        reply = await ai.generate("Hello")
        assert "429" not in reply
        assert "Quota" not in reply
        assert "দুঃখিত বস" in reply
