"""Document extractors for PDF, DOCX, Markdown, and Text files."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("aru.knowledge_base.extractors")


@dataclass
class DocumentExtractResult:
    """Standardized representation of extracted document text and structure."""
    file_path: str
    doc_type: str
    content: str
    title: str = ""
    headings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseExtractor:
    """Base interface for file extractors."""
    def extract(self, file_path: str | Path) -> DocumentExtractResult:
        raise NotImplementedError


class TextExtractor(BaseExtractor):
    """Extract plain text from .txt and generic text files."""
    def extract(self, file_path: str | Path) -> DocumentExtractResult:
        p = Path(file_path)
        text = p.read_text(encoding="utf-8", errors="replace")
        return DocumentExtractResult(
            file_path=str(p),
            doc_type="text",
            content=text,
            title=p.stem,
            headings=[],
            metadata={"size_bytes": p.stat().st_size if p.exists() else len(text)},
        )


class MarkdownExtractor(BaseExtractor):
    """Extract text from markdown files and detect heading structure."""
    def extract(self, file_path: str | Path) -> DocumentExtractResult:
        p = Path(file_path)
        text = p.read_text(encoding="utf-8", errors="replace")
        headings = [m.group(1).strip() for m in re.finditer(r"^#+\s+(.+)$", text, re.MULTILINE)]
        title = headings[0] if headings else p.stem
        return DocumentExtractResult(
            file_path=str(p),
            doc_type="markdown",
            content=text,
            title=title,
            headings=headings,
            metadata={"heading_count": len(headings)},
        )


class DocxExtractor(BaseExtractor):
    """
    Extract text and tables from Word (.docx) documents.
    Uses standard library zipfile and XML parsing without requiring python-docx.
    """
    def extract(self, file_path: str | Path) -> DocumentExtractResult:
        p = Path(file_path)
        paragraphs: list[str] = []
        headings: list[str] = []

        try:
            with zipfile.ZipFile(p, "r") as z:
                xml_content = z.read("word/document.xml")
                root = ET.fromstring(xml_content)
                # Word XML namespace map
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

                for p_elem in root.iter(f"{{{ns['w']}}}p"):
                    texts = [node.text for node in p_elem.iter(f"{{{ns['w']}}}t") if node.text]
                    para_text = "".join(texts).strip()
                    if para_text:
                        # Check if style is heading
                        style_elem = p_elem.find(f".//{{{ns['w']}}}pStyle")
                        if style_elem is not None:
                            val = style_elem.attrib.get(f"{{{ns['w']}}}val", "")
                            if "Heading" in val or "title" in val.lower():
                                headings.append(para_text)
                        paragraphs.append(para_text)
        except Exception as exc:
            logger.warning("Failed parsing docx via XML: %s", exc)
            paragraphs.append(f"[Failed parsing docx: {exc}]")

        full_content = "\n\n".join(paragraphs)
        return DocumentExtractResult(
            file_path=str(p),
            doc_type="docx",
            content=full_content,
            title=headings[0] if headings else p.stem,
            headings=headings,
            metadata={"paragraphs_count": len(paragraphs)},
        )


class PdfExtractor(BaseExtractor):
    """
    Extract text from PDF documents using standard Python pypdf
    with clean stream fallback for encrypted or non-standard PDFs.
    """
    def extract(self, file_path: str | Path) -> DocumentExtractResult:
        p = Path(file_path)
        from modules.pdf_processor import PDFProcessor
        processor = PDFProcessor()
        pages, title = processor.extract_text_by_pages(p, p.name)
        content = "\n\n".join(pages).strip()
        if not content:
            content = f"Extracted document metadata for PDF: {p.name}"

        return DocumentExtractResult(
            file_path=str(p),
            doc_type="pdf",
            content=content,
            title=title or p.stem,
            headings=[],
            metadata={"pages_count": len(pages)},
        )


class UniversalExtractor:
    """Routing dispatcher selecting appropriate extractor based on file extension."""
    EXTRACTORS = {
        ".txt": TextExtractor(),
        ".log": TextExtractor(),
        ".csv": TextExtractor(),
        ".json": TextExtractor(),
        ".md": MarkdownExtractor(),
        ".markdown": MarkdownExtractor(),
        ".docx": DocxExtractor(),
        ".pdf": PdfExtractor(),
    }

    @classmethod
    def extract_file(cls, file_path: str | Path) -> DocumentExtractResult:
        p = Path(file_path)
        ext = p.suffix.lower()
        extractor = cls.EXTRACTORS.get(ext, TextExtractor())
        return extractor.extract(p)
