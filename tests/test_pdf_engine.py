"""Comprehensive tests for PDF Engine: extraction, OCR fallback, semantic chunking, hierarchical summarization, and document QA."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.llm.base_provider import BaseLLMProvider
from modules.llm.provider_manager import ProviderManager
from modules.pdf_engine import (
    DocumentQA,
    DocumentStructure,
    HierarchicalSummarizer,
    PageContent,
    PDFAnalysisResult,
    PDFEngine,
    PDFExtractionEngine,
    SemanticChunk,
    SemanticChunker,
    detect_headings,
    has_code_blocks,
)
from modules.pdf_processor import PDFProcessor, PDFProcessingResult


class MockAIProvider(BaseLLMProvider):
    """Mock provider for testing document QA and summarization."""

    def __init__(self, name: str = "mock_ai", reply_prefix: str = "AI"):
        super().__init__(name=name, api_key="mock-key")
        self.reply_prefix = reply_prefix
        self.generated_prompts: list[str] = []

    async def generate(self, prompt: str, **kwargs) -> str:
        self.generated_prompts.append(prompt)
        if "Question:" in prompt:
            return f"[{self.reply_prefix} Answer] The revenue grew by 15% as stated on Page 1."
        if "synthesize" in prompt.lower() or "executive summary" in prompt.lower():
            return f"[{self.reply_prefix} Final Summary] Executive summary: All objectives were met."
        if "chapter" in prompt.lower() or "consolidate" in prompt.lower():
            return f"[{self.reply_prefix} Chapter Summary] Consolidated chapter key points."
        return f"[{self.reply_prefix} Section Summary] Summary bullet points."

    async def chat(self, *args, **kwargs):
        raise NotImplementedError

    async def vision(self, prompt: str, image_bytes_or_b64: bytes | str, **kwargs) -> str:
        return f"[{self.reply_prefix} Vision] Chart indicates steady growth in Q4."

    async def health_check(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Test 1: Heading Detection and Code Blocks
# ---------------------------------------------------------------------------

def test_heading_and_code_detection():
    """Verify heading patterns and code blocks are properly identified."""
    sample_text = (
        "# Introduction\n\n"
        "This is paragraph text.\n\n"
        "2. Architecture Overview\n"
        "System architecture consists of multiple services.\n\n"
        "```python\ndef run_pipeline():\n    return True\n```\n"
    )

    headings = detect_headings(sample_text)
    assert len(headings) >= 2
    assert any("Introduction" in h[1] for h in headings)
    assert any("Architecture Overview" in h[1] for h in headings)
    assert has_code_blocks(sample_text) is True

    plain_text = "Just a regular text document with no special formatting or headings."
    assert has_code_blocks(plain_text) is False


# ---------------------------------------------------------------------------
# Test 2: Semantic Chunking
# ---------------------------------------------------------------------------

def test_semantic_chunker():
    """SemanticChunker splits along section/paragraph boundaries."""
    chunker = SemanticChunker(target_size=400, overlap=50)

    # Build a simulated multi-page document
    pages = [
        PageContent(
            page_number=1,
            text="# Section 1: Introduction\n\n" + ("Introductory content details. " * 15),
            headings=["Section 1: Introduction"],
        ),
        PageContent(
            page_number=2,
            text="2. Technical Details\n\n" + ("Technical content specifications. " * 15),
            headings=["2. Technical Details"],
            tables=[[["Metric", "Value"], ["Latency", "5ms"]]],
        ),
    ]

    doc = DocumentStructure(title="Test Doc", total_pages=2, pages=pages)
    chunks = chunker.chunk_document(doc)

    assert len(chunks) >= 2
    assert chunks[0].page_start == 1
    # Check table was converted and preserved
    has_table_chunk = any(c.has_tables for c in chunks)
    assert has_table_chunk is True


def test_table_rendering():
    """Verify tables render as clean markdown/text tables."""
    table = [
        ["Product", "Q1", "Q2"],
        ["Widgets", "100", "150"],
        ["Gadgets", "200", "220"],
    ]
    rendered = SemanticChunker._render_table(table)
    assert "Product | Q1 | Q2" in rendered
    assert "Widgets | 100 | 150" in rendered
    assert "---" in rendered


# ---------------------------------------------------------------------------
# Test 3: OCR Fallback for Scanned Pages
# ---------------------------------------------------------------------------

def test_ocr_fallback_for_scanned_pages():
    """When a page has little/no text, OCR fallback is triggered."""
    extractor = PDFExtractionEngine(enable_ocr=True)

    # Mock pytesseract and PIL
    mock_pytesseract = MagicMock()
    mock_pytesseract.image_to_string.return_value = "OCR Extracted Text from scanned document."

    with patch.dict("sys.modules", {"pytesseract": mock_pytesseract, "PIL": MagicMock(), "PIL.Image": MagicMock()}):
        extractor._has_pytesseract = True
        extractor._has_pillow = True

        # Create pages where page 1 is scanned (empty text)
        pages = [
            PageContent(page_number=1, text="", is_scanned=True),
            PageContent(page_number=2, text="Regular page text here.", is_scanned=False),
        ]

        # Mock pdfplumber to simulate image extraction
        mock_page = MagicMock()
        mock_img = MagicMock()
        mock_img.original = "dummy_pil_img"
        mock_page.to_image.return_value = mock_img

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page, mock_page]
        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        with patch.dict("sys.modules", {"pdfplumber": mock_pdfplumber}):
            extractor._apply_ocr_to_scanned_pages(b"dummy_bytes", pages)

            assert pages[0].ocr_applied is True
            assert "OCR Extracted Text" in pages[0].text
            assert pages[1].ocr_applied is False


# ---------------------------------------------------------------------------
# Test 4: Hierarchical Summarization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hierarchical_summarization():
    """Verify Document -> Section -> Chapter -> Final hierarchical pipeline."""
    mock_provider = MockAIProvider()
    pm = ProviderManager(priority=["mock_ai"], providers={"mock_ai": mock_provider}, auto_load=False)

    summarizer = HierarchicalSummarizer(provider_manager=pm)

    # 8 chunks to trigger chapter grouping
    chunks = [
        SemanticChunk(
            chunk_index=i,
            page_start=i + 1,
            page_end=i + 1,
            text=f"Content for chunk {i+1} discussing topic {i+1}.",
            section_title=f"Section {i+1}",
        )
        for i in range(8)
    ]

    doc = DocumentStructure(title="Large Tech Report", total_pages=8)
    result = await summarizer.summarize_document(doc, chunks)

    assert result.total_chunks == 8
    assert len(result.section_summaries) == 8
    assert "Executive summary" in result.summary
    assert len(mock_provider.generated_prompts) >= 8  # Chunks + Chapters + Final


# ---------------------------------------------------------------------------
# Test 5: Document Question Answering (QA Mode)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_document_question_answering():
    """DocumentQA answers specific questions with context and page citations."""
    mock_provider = MockAIProvider()
    pm = ProviderManager(priority=["mock_ai"], providers={"mock_ai": mock_provider}, auto_load=False)

    qa = DocumentQA(provider_manager=pm)
    context = "[Page 1] Revenue was $10M in 2023.\n[Page 2] Net profit margin was 15%."

    answer = await qa.answer_question(
        question="What was the profit margin?",
        qa_context=context,
        title="Annual Report",
    )

    assert "The revenue grew by 15%" in answer
    assert any("Question: What was the profit margin?" in p for p in mock_provider.generated_prompts)


# ---------------------------------------------------------------------------
# Test 6: Unified PDFEngine Facade
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pdf_engine_facade():
    """Verify PDFEngine combines extraction, chunking, summarization, and QA."""
    mock_provider = MockAIProvider()
    pm = ProviderManager(priority=["mock_ai"], providers={"mock_ai": mock_provider}, auto_load=False)

    engine = PDFEngine(provider_manager=pm)

    # Mock extraction of a multi-page document
    simulated_doc = DocumentStructure(
        title="Quarterly Review",
        total_pages=2,
        pages=[
            PageContent(page_number=1, text="Q1 financial performance was exceptional."),
            PageContent(page_number=2, text="Q2 roadmap includes expansion to European markets."),
        ],
    )

    with patch.object(engine.extractor, "extract", return_value=simulated_doc):
        # 1. Summarize
        summary_result = await engine.process_and_summarize(b"pdf_bytes", filename="review.pdf")
        assert summary_result.title == "Quarterly Review"
        assert summary_result.total_pages == 2
        assert "Summary" in summary_result.summary

        # 2. Ask Question
        answer = await engine.ask_question(
            b"pdf_bytes",
            question="What is planned for Q2?",
            filename="review.pdf",
        )
        assert "Answer" in answer


# ---------------------------------------------------------------------------
# Test 7: Backward Compatibility of PDFProcessor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pdf_processor_backward_compatibility():
    """PDFProcessor maintains full backward compatibility for existing callers."""
    mock_provider = MockAIProvider()
    pm = ProviderManager(priority=["mock_ai"], providers={"mock_ai": mock_provider}, auto_load=False)

    processor = PDFProcessor(provider_manager=pm, chunk_size=300)

    # 1. chunk_text
    long_text = "This is a sentence. " * 30
    chunks = processor.chunk_text(long_text)
    assert len(chunks) > 1

    # 2. create_chunks
    pdf_chunks = processor.create_chunks(["Page 1 content", "Page 2 content"])
    assert len(pdf_chunks) == 2
    assert pdf_chunks[0].page_number == 1

    # 3. summarize_chunks
    summary = await processor.summarize_chunks(chunks)
    assert len(summary) > 0

    # 4. Automatic Question routing in summarize_pdf
    with patch.object(processor.engine, "ask_question", new_callable=AsyncMock) as mock_ask:
        mock_ask.return_value = "Direct QA Answer"
        res = await processor.summarize_pdf(b"pdf", prompt="What was the total profit?")
        assert res == "Direct QA Answer"
        mock_ask.assert_called_once()
