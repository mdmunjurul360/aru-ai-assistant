"""Semantic and sliding-window document chunker."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


@dataclass
class TextChunk:
    """A discrete searchable segment of an ingested document."""
    chunk_index: int
    content: str
    heading: str
    start_char: int
    end_char: int
    token_estimate: int


class SemanticChunker:
    """
    Splits long text documents into overlapping, boundary-aware chunks.
    Preserves section headings, respects sentence/paragraph boundaries,
    and produces chunks optimized for vector and keyword search.
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 80,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_document(
        self,
        content: str,
        headings: Sequence[str] | None = None,
    ) -> list[TextChunk]:
        """Split text into structured TextChunk instances."""
        if not content or not content.strip():
            return []

        clean_text = content.strip()
        chunks: list[TextChunk] = []
        start = 0
        total_len = len(clean_text)
        chunk_idx = 0
        known_headings = list(headings or [])

        while start < total_len:
            end = min(start + self.chunk_size, total_len)

            # Snap to sentence or paragraph break if not at end of document
            if end < total_len:
                # Look for paragraph break first, then period/question/exclamation
                match = None
                for boundary in ("\n\n", "\n", ". ", "? ", "! "):
                    pos = clean_text.rfind(boundary, start + self.chunk_overlap, end)
                    if pos != -1:
                        end = pos + len(boundary)
                        match = True
                        break

            segment = clean_text[start:end].strip()
            if segment:
                # Detect the closest preceding heading
                closest_heading = ""
                for h in known_headings:
                    h_pos = clean_text.find(h, 0, end)
                    if h_pos != -1:
                        closest_heading = h

                tokens = max(1, len(segment) // 4)
                chunks.append(
                    TextChunk(
                        chunk_index=chunk_idx,
                        content=segment,
                        heading=closest_heading or "General",
                        start_char=start,
                        end_char=end,
                        token_estimate=tokens,
                    )
                )
                chunk_idx += 1

            if end >= total_len:
                break
            start = max(start + 1, end - self.chunk_overlap)

        return chunks
