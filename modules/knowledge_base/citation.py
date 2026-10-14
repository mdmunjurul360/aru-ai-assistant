"""Citation support and evidence formatting for ingested knowledge."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Citation:
    """Evidence citation linking an AI answer back to a source knowledge chunk."""
    citation_id: int
    doc_id: int
    doc_name: str
    doc_type: str
    chunk_index: int
    heading: str
    snippet: str
    confidence: float = 1.0

    def format_inline(self) -> str:
        """Inline citation reference."""
        return f"[^{self.citation_id}]"

    def format_footnote(self) -> str:
        """Detailed footnote with document name, section, and excerpt."""
        clean_snippet = self.snippet.replace("\n", " ").strip()
        if len(clean_snippet) > 160:
            clean_snippet = clean_snippet[:160] + "..."
        heading_part = f", § {self.heading}" if self.heading and self.heading != "General" else ""
        return (
            f"[^{self.citation_id}]: **{self.doc_name}** ({self.doc_type}{heading_part}, "
            f"chunk #{self.chunk_index})\n"
            f'   > "{clean_snippet}"'
        )


class CitationFormatter:
    """Helper formatting multi-citation footnote blocks."""

    @staticmethod
    def format_citations_block(citations: list[Citation]) -> str:
        if not citations:
            return ""
        lines = ["\n📚 **তথ্যসূত্র ও সূত্রাবলি (Citations):**"]
        for c in citations:
            lines.append(c.format_footnote())
        return "\n".join(lines)
