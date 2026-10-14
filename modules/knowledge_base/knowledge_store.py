"""KnowledgeStore: Ingestion, indexing, FTS5 + Vector hybrid retrieval for knowledge documents."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.config import DATABASE_PATH
from modules.knowledge_base.chunker import SemanticChunker, TextChunk
from modules.knowledge_base.citation import Citation
from modules.knowledge_base.extractors import UniversalExtractor
from modules.semantic_memory.vector_store import (
    DenseEmbeddingProvider,
    cosine_similarity,
)

logger = logging.getLogger("aru.knowledge_base.store")


class KnowledgeStore:
    """
    Manages persistent ingestion, storage, and retrieval for the Knowledge Base.
    Features:
      - Document metadata registry (PDF, DOCX, MD, TXT)
      - Chunk storage with FTS5 search
      - Vector embeddings for each chunk
      - Citation generation with exact source location
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        chunk_size: int = 500,
        chunk_overlap: int = 80,
    ) -> None:
        self.db_path = str(db_path or DATABASE_PATH)
        self.chunker = SemanticChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.embedder = DenseEmbeddingProvider(dimension=128)
        self._ensure_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _ensure_tables(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_name TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    title TEXT,
                    total_chunks INTEGER DEFAULT 0,
                    metadata_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    heading TEXT DEFAULT 'General',
                    vector_blob BLOB,
                    start_char INTEGER DEFAULT 0,
                    end_char INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (doc_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
                );
                """
            )
            # FTS5 for knowledge chunks
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(
                        content,
                        heading,
                        content='knowledge_chunks',
                        content_rowid='id'
                    );
                    """
                )
            except Exception as exc:
                logger.warning("FTS5 table for knowledge chunks already exists or notice: %s", exc)

            conn.commit()

    def ingest_file(self, file_path: str | Path) -> dict[str, Any]:
        """Extract, chunk, embed, and store a document."""
        p = Path(file_path)
        if not p.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        extracted = UniversalExtractor.extract_file(p)
        chunks = self.chunker.chunk_document(extracted.content, headings=extracted.headings)
        now = datetime.now(timezone.utc).isoformat()
        meta_str = json.dumps(extracted.metadata, ensure_ascii=False)

        with self._get_connection() as conn:
            # Delete prior record if re-ingesting same file path
            existing = conn.execute(
                "SELECT id FROM knowledge_documents WHERE file_path = ?;", (str(p),)
            ).fetchone()
            if existing:
                doc_id = existing["id"]
                conn.execute("DELETE FROM knowledge_chunks WHERE doc_id = ?;", (doc_id,))
                conn.execute(
                    """
                    UPDATE knowledge_documents
                    SET doc_name = ?, doc_type = ?, title = ?, total_chunks = ?, metadata_json = ?, created_at = ?
                    WHERE id = ?;
                    """,
                    (p.name, extracted.doc_type, extracted.title, len(chunks), meta_str, now, doc_id),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO knowledge_documents (doc_name, doc_type, file_path, title, total_chunks, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (p.name, extracted.doc_type, str(p), extracted.title, len(chunks), meta_str, now),
                )
                doc_id = cursor.lastrowid or 0

            # Insert chunks with embeddings
            import struct
            for chunk in chunks:
                vec = self.embedder.embed_text(chunk.content)
                vec_blob = struct.pack(f"{len(vec)}f", *vec)
                c_cursor = conn.execute(
                    """
                    INSERT INTO knowledge_chunks (doc_id, chunk_index, content, heading, vector_blob, start_char, end_char, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (doc_id, chunk.chunk_index, chunk.content, chunk.heading, vec_blob, chunk.start_char, chunk.end_char, now),
                )
                c_id = c_cursor.lastrowid or 0
                conn.execute(
                    "INSERT INTO knowledge_chunks_fts (rowid, content, heading) VALUES (?, ?, ?);",
                    (c_id, chunk.content, chunk.heading),
                )

            conn.commit()

        logger.info("Ingested '%s' -> %d chunks (doc_id=%d)", p.name, len(chunks), doc_id)
        return {
            "success": True,
            "doc_id": doc_id,
            "doc_name": p.name,
            "doc_type": extracted.doc_type,
            "chunks_count": len(chunks),
            "title": extracted.title,
        }

    def search_knowledge(
        self,
        query: str,
        limit: int = 5,
    ) -> list[Citation]:
        """Hybrid search across ingested knowledge base returning verified Citations."""
        if not query or not query.strip():
            return []

        import struct
        query_vec = self.embedder.embed_text(query.strip())
        scored: list[tuple[float, Citation]] = []

        with self._get_connection() as conn:
            # Join chunks and documents
            rows = conn.execute(
                """
                SELECT c.id, c.doc_id, c.chunk_index, c.content, c.heading, c.vector_blob,
                       d.doc_name, d.doc_type
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON c.doc_id = d.id;
                """
            ).fetchall()

            for idx, r in enumerate(rows):
                vec_blob = r["vector_blob"]
                if not vec_blob:
                    continue
                dim = len(vec_blob) // 4
                vec = list(struct.unpack(f"{dim}f", vec_blob))
                score = cosine_similarity(query_vec, vec)

                # Keyword bonus
                content_lower = r["content"].lower()
                query_words = query.lower().split()
                matched_words = sum(1 for w in query_words if w in content_lower)
                if matched_words > 0:
                    score += 0.15 * (matched_words / max(1, len(query_words)))

                if score > 0.15:
                    citation = Citation(
                        citation_id=len(scored) + 1,
                        doc_id=r["doc_id"],
                        doc_name=r["doc_name"],
                        doc_type=r["doc_type"],
                        chunk_index=r["chunk_index"],
                        heading=r["heading"] or "General",
                        snippet=r["content"],
                        confidence=round(score, 4),
                    )
                    scored.append((score, citation))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [item[1] for item in scored[:limit]]
        # Renumber citation IDs 1..limit
        for idx, cit in enumerate(top, start=1):
            cit.citation_id = idx
        return top

    def list_documents(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, doc_name, doc_type, file_path, title, total_chunks, created_at FROM knowledge_documents;"
            ).fetchall()
            return [dict(r) for r in rows]

    def count_documents(self) -> int:
        with self._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM knowledge_documents;").fetchone()
            return int(row["cnt"]) if row else 0

    def delete_document(self, doc_id: int) -> bool:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM knowledge_chunks WHERE doc_id = ?;", (doc_id,))
            cursor = conn.execute("DELETE FROM knowledge_documents WHERE id = ?;", (doc_id,))
            conn.commit()
            return cursor.rowcount > 0
