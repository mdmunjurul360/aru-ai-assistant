"""Robust, progressive PDF extraction, semantic chunking, and hierarchical summarization for Aru AI."""

from __future__ import annotations

import io
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from modules.token_optimizer import TaskType, get_optimal_max_tokens
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
)

logger = logging.getLogger("aru.pdf_processor")


@dataclass
class PDFChunk:
    chunk_index: int
    page_number: int
    text: str
    char_count: int


@dataclass
class PDFProcessingResult:
    title: str
    total_pages: int
    total_chunks: int
    summary: str
    intermediate_summaries: list[str] = field(default_factory=list)
    processing_time_sec: float = 0.0
    error: str | None = None
    tables_found: int = 0
    scanned_pages: int = 0
    ocr_applied: bool = False
    qa_context: str = ""


# Question indicator patterns
_QUESTION_PATTERNS = re.compile(
    r"(\?|"
    r"\b(who|what|where|when|why|how|which|whose|whom|is|are|can|could|would|should|does|do|did|explain|tell me)\b|"
    r"(\u0995\u09bf|\u0995\u09c0|\u0995\u09c7\u09a8|\u0995\u09cb\u09a5\u09be\u09af\u09bc|\u0995\u0996\u09a8|\u0995\u09c7|\u0995\u09c0\u09ad\u09be\u09ac\u09c7|\u0995\u09a4))",
    re.IGNORECASE,
)


def is_question_prompt(text: str) -> bool:
    """Check if a prompt is seeking an answer to a question rather than a summary."""
    stripped = text.strip()
    if not stripped:
        return False
    if "?" in stripped or "？" in stripped:
        return True
    return bool(_QUESTION_PATTERNS.search(stripped))


class PDFProcessor:
    """
    Production-grade PDF Processor with:
    - Multi-backend extraction (pdfplumber primary with layout/tables, pypdf fallback)
    - Automatic OCR fallback via pytesseract for scanned pages
    - Semantic chunking (section/heading aware)
    - Hierarchical summarization (Document -> Sections -> Chapters -> Final)
    - Direct Document QA answering mode
    - Vision model support for charts/diagrams
    - Progressive Map-Reduce failover across LLM providers
    """

    CHUNK_SIZE_CHARS = 2000
    CHUNK_OVERLAP_CHARS = 150

    def __init__(
        self,
        provider_manager: Any = None,
        chunk_size: int = CHUNK_SIZE_CHARS,
        chunk_overlap: int = CHUNK_OVERLAP_CHARS,
        enable_ocr: bool = True,
    ) -> None:
        self.provider_manager = provider_manager
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.enable_ocr = enable_ocr
        self.engine = PDFEngine(
            provider_manager=provider_manager,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            enable_ocr=enable_ocr,
        )

    def chunk_text(
        self,
        text: str,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> list[str]:
        """Split arbitrary string into overlapping chunks."""
        size = chunk_size or self.chunk_size
        overlap = chunk_overlap if chunk_overlap is not None else self.chunk_overlap
        if not text:
            return []
        if len(text) <= size:
            return [text]

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start += max(1, size - overlap)
        return chunks

    async def summarize_chunks(
        self,
        chunks: list[str],
        prompt: str = "",
        title: str = "Document",
    ) -> str:
        """Progressively summarize a list of text chunks with failover."""
        pdf_chunks = [
            PDFChunk(chunk_index=i, page_number=1, text=c, char_count=len(c))
            for i, c in enumerate(chunks)
        ]
        summaries: list[str] = []
        for c in pdf_chunks:
            s = await self.summarize_chunk_with_failover(c, len(pdf_chunks), title, prompt)
            summaries.append(s)

        if len(summaries) == 1:
            return summaries[0]

        combined = "\n\n".join(f"Section {i+1}:\n{s}" for i, s in enumerate(summaries))
        synthesis_prompt = (
            f"You are Aru, personal AI assistant of your Boss. "
            f"Synthesize these section summaries into a final coherent summary.\n\n"
            f"{combined}\n\n"
            f"Reply with key findings and conclusion."
        )
        if self.provider_manager:
            return await self.provider_manager.generate_safe(synthesis_prompt, max_tokens=1536)
        return combined

    async def summarize_pdf(
        self,
        source: str | Path | bytes,
        prompt: str = "",
        filename: str = "document.pdf",
    ) -> str:
        """
        Convenience method to summarize an entire PDF or answer a question about it.
        If prompt is a question, routes directly to document QA for precise answers.
        """
        if prompt and is_question_prompt(prompt):
            logger.info("Detected question in PDF prompt; executing Document QA: %s", prompt[:80])
            return await self.ask_question(source, question=prompt, filename=filename)

        res = await self.process_and_summarize(source, filename=filename, user_instruction=prompt)
        return res.summary

    async def ask_question(
        self,
        source: str | Path | bytes,
        question: str,
        filename: str = "document.pdf",
    ) -> str:
        """Answer a specific question using extracted document context and page references."""
        return await self.engine.ask_question(source, question=question, filename=filename)

    async def analyze_with_vision(
        self,
        source: str | Path | bytes,
        question: str = "Describe the contents of this document",
        filename: str = "document.pdf",
    ) -> str:
        """Analyze embedded charts/diagrams in the PDF using vision models."""
        return await self.engine.analyze_with_vision(source, question=question, filename=filename)

    def extract_text_by_pages(
        self,
        source: str | Path | bytes,
        filename: str = "document.pdf",
    ) -> tuple[list[str], str]:
        """
        Extract text per page using PDFEngine (pdfplumber + tables + OCR fallback),
        with fallback to legacy pypdf and regex stream extraction.
        Returns: (pages_text_list, document_title)
        """
        title = Path(filename).stem
        try:
            doc = self.engine.extractor.extract(source, filename)
            if doc and doc.pages:
                pages_text: list[str] = []
                for p in doc.pages:
                    page_str = p.text
                    # Append formatted tables if present
                    if p.tables:
                        for tbl_idx, tbl in enumerate(p.tables):
                            tbl_str = SemanticChunker._render_table(tbl)
                            if tbl_str:
                                page_str = (
                                    f"{page_str}\n\n[Table {tbl_idx + 1}]\n{tbl_str}"
                                    if page_str
                                    else f"[Table {tbl_idx + 1}]\n{tbl_str}"
                                )
                    if page_str.strip():
                        pages_text.append(page_str.strip())

                if pages_text:
                    logger.info("PDFEngine extracted %d pages from '%s'", len(pages_text), doc.title)
                    return pages_text, doc.title
        except Exception as exc:
            logger.debug("PDFEngine extraction failed (%s); falling back to direct reader", exc)

        # Legacy fallback
        data: bytes
        if isinstance(source, (str, Path)):
            p = Path(source)
            title = p.stem
            if not p.exists():
                logger.warning("PDF file not found: %s", p)
                return [], title
            data = p.read_bytes()
        else:
            data = source

        # 1. pypdf
        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(data))
            pages_text = []
            for page_idx, page in enumerate(reader.pages):
                try:
                    txt = page.extract_text() or ""
                    cleaned = re.sub(r"[ \t]+", " ", txt).strip()
                    if cleaned:
                        pages_text.append(cleaned)
                except Exception:
                    pass
            if pages_text:
                return pages_text, title
        except Exception:
            pass

        # 2. Resilient fallback text stream parser
        try:
            text_blocks: list[str] = []
            for m in re.findall(rb"\((.*?)\)\s*Tj", data):
                try:
                    decoded = m.decode("latin1", errors="ignore").strip()
                    if len(decoded) > 1:
                        text_blocks.append(decoded)
                except Exception:
                    pass

            if not text_blocks:
                for block in re.findall(rb"\[(.*?)\]\s*TJ", data):
                    items = re.findall(rb"\((.*?)\)", block)
                    combined = " ".join(i.decode("latin1", errors="ignore") for i in items if i)
                    if combined.strip():
                        text_blocks.append(combined.strip())

            raw_combined = " ".join(text_blocks).strip()
            if raw_combined:
                synthetic_pages = [raw_combined[i : i + 2000] for i in range(0, len(raw_combined), 2000)]
                return synthetic_pages or [raw_combined], title
        except Exception as exc:
            logger.warning("PDF stream fallback error: %s", exc)

        return [], title

    def create_chunks(self, pages_text: list[str]) -> list[PDFChunk]:
        """Split page texts into manageable chunks that will not trigger context limit errors."""
        chunks: list[PDFChunk] = []
        chunk_idx = 0

        for page_num, page_content in enumerate(pages_text, start=1):
            text_len = len(page_content)
            if text_len <= self.CHUNK_SIZE_CHARS:
                chunks.append(
                    PDFChunk(
                        chunk_index=chunk_idx,
                        page_number=page_num,
                        text=page_content,
                        char_count=text_len,
                    )
                )
                chunk_idx += 1
            else:
                # Segment long page into sub-chunks with overlap
                start = 0
                while start < text_len:
                    end = min(start + self.CHUNK_SIZE_CHARS, text_len)
                    sub_text = page_content[start:end].strip()
                    if sub_text:
                        chunks.append(
                            PDFChunk(
                                chunk_index=chunk_idx,
                                page_number=page_num,
                                text=sub_text,
                                char_count=len(sub_text),
                            )
                        )
                        chunk_idx += 1
                    start += self.CHUNK_SIZE_CHARS - self.CHUNK_OVERLAP_CHARS

        return chunks

    async def summarize_chunk_with_failover(
        self,
        chunk: PDFChunk,
        total_chunks: int,
        title: str,
        user_instruction: str = "",
    ) -> str:
        """Summarize a single PDF chunk with automatic multi-provider failover."""
        instr = f"\nUser Focus: {user_instruction}" if user_instruction else ""
        prompt = (
            f"Extract and summarize the key facts, decisions, data, and findings from "
            f"Section {chunk.chunk_index + 1}/{total_chunks} (Page {chunk.page_number}) of '{title}'.{instr}\n\n"
            f"Content:\n{chunk.text}\n\n"
            f"Provide a concise summary in 2-4 bullet points."
        )

        max_tokens = get_optimal_max_tokens(prompt, task_type=TaskType.PDF_CHUNK, requested_tokens=512)

        if self.provider_manager:
            return await self.provider_manager.generate_safe(
                prompt,
                max_tokens=max_tokens,
                fallback_message=f"[Section {chunk.chunk_index + 1}: Content extracted successfully ({chunk.char_count} chars).]",
            )

        return f"[Section {chunk.chunk_index + 1}: Extracted {chunk.char_count} chars]"

    async def process_and_summarize(
        self,
        source: str | Path | bytes,
        filename: str = "document.pdf",
        user_instruction: str = "",
    ) -> PDFProcessingResult:
        """
        Execute full progressive summarization with hierarchical structure:
        1. Extract page-by-page (pdfplumber + tables + OCR fallback)
        2. Create semantic chunks
        3. Summarize chunk-by-chunk with failover
        4. Synthesize final comprehensive summary
        """
        start_time = time.perf_counter()

        try:
            analysis: PDFAnalysisResult = await self.engine.process_and_summarize(
                source, filename=filename, user_instruction=user_instruction
            )
            intermediate = [s.get("summary", "") for s in analysis.section_summaries]

            return PDFProcessingResult(
                title=analysis.title,
                total_pages=analysis.total_pages,
                total_chunks=analysis.total_chunks,
                summary=analysis.summary,
                intermediate_summaries=intermediate,
                processing_time_sec=analysis.processing_time_sec,
                error=analysis.error,
                tables_found=analysis.tables_found,
                scanned_pages=analysis.scanned_pages,
                ocr_applied=analysis.ocr_applied,
                qa_context=analysis.qa_context,
            )
        except Exception as exc:
            logger.warning("PDFEngine process_and_summarize encountered an error (%s); falling back", exc)

        # Legacy fallback if engine fails
        pages, title = self.extract_text_by_pages(source, filename)

        if not pages:
            return PDFProcessingResult(
                title=title,
                total_pages=0,
                total_chunks=0,
                summary="দুঃখিত বস, PDF ফাইলটি থেকে কোনো টেক্সট বের করা সম্ভব হয়নি (ফাইলটি এনক্রিপ্টেড বা শুধুমাত্র ছবি হতে পারে)।",
                processing_time_sec=time.perf_counter() - start_time,
                error="No text extracted",
            )

        chunks = self.create_chunks(pages)
        total_chunks = len(chunks)

        intermediate_summaries: list[str] = []
        for i, chunk in enumerate(chunks):
            chunk_summary = await self.summarize_chunk_with_failover(chunk, total_chunks, title, user_instruction)
            intermediate_summaries.append(chunk_summary)

        combined_summaries = "\n\n".join(
            f"**Section {idx + 1} (Page {chunks[idx].page_number}):**\n{s}"
            for idx, s in enumerate(intermediate_summaries)
        )

        instr = f"\nFocus on answering: {user_instruction}" if user_instruction else ""
        synthesis_prompt = (
            f"You are Aru, personal AI assistant of your Boss. "
            f"Below are section-by-section summaries of the PDF document '{title}' "
            f"({len(pages)} pages, {total_chunks} sections).{instr}\n\n"
            f"{combined_summaries}\n\n"
            f"Synthesize these into a cohesive, executive summary for the Boss. "
            f"Include:\n"
            f"1. Executive Overview\n"
            f"2. Core Key Findings & Takeaways\n"
            f"3. Important Details & Data\n"
            f"4. Conclusion\n"
            f"Reply in the same language requested by Boss (Bangla or English)."
        )

        max_tokens = get_optimal_max_tokens(synthesis_prompt, task_type=TaskType.PDF_FINAL, requested_tokens=2048)
        final_summary = (
            await self.provider_manager.generate_safe(synthesis_prompt, max_tokens=max_tokens)
            if self.provider_manager
            else combined_summaries
        )

        total_dur = time.perf_counter() - start_time
        return PDFProcessingResult(
            title=title,
            total_pages=len(pages),
            total_chunks=total_chunks,
            summary=final_summary,
            intermediate_summaries=intermediate_summaries,
            processing_time_sec=total_dur,
        )


__all__ = [
    "PDFProcessor",
    "PDFChunk",
    "PDFProcessingResult",
    "PDFEngine",
    "PDFExtractionEngine",
    "SemanticChunker",
    "HierarchicalSummarizer",
    "DocumentQA",
    "DocumentStructure",
    "PageContent",
    "SemanticChunk",
    "PDFAnalysisResult",
]
