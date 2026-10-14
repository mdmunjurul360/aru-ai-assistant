"""Vector store and dense embedding generation for Aru AI Semantic Memory."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from modules.config import DATABASE_PATH

logger = logging.getLogger("aru.semantic_memory.vector_store")


@dataclass
class VectorRecord:
    """Vector embedding record stored in SQLite."""
    record_id: int
    memory_id: int | None
    text: str
    vector: list[float]
    metadata: dict[str, Any]
    created_at: str


class DenseEmbeddingProvider:
    """
    High-performance, deterministic dense text embedding generator.
    Uses sub-word character n-gram hashing projection with L2 normalization.
    Provides fast, reproducible semantic representation without heavy PyTorch dependencies.
    """

    def __init__(self, dimension: int = 128) -> None:
        self.dimension = dimension

    def embed_text(self, text: str) -> list[float]:
        """Convert text into normalized dense float vector."""
        if not text or not text.strip():
            return [0.0] * self.dimension

        cleaned = text.lower().strip()
        vec = [0.0] * self.dimension

        # Generate character 3-grams, 4-grams, and word tokens
        tokens = cleaned.split()
        for token in tokens:
            # Word token projection
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dimension
            sign = 1.0 if ((h >> 8) & 1) else -1.0
            vec[idx] += sign * 1.5

            # Sub-word n-grams for morphological semantic capture
            for n in (3, 4):
                if len(token) >= n:
                    for i in range(len(token) - n + 1):
                        ngram = token[i : i + n]
                        h_ng = int(hashlib.sha256(ngram.encode("utf-8")).hexdigest(), 16)
                        idx_ng = h_ng % self.dimension
                        sign_ng = 1.0 if ((h_ng >> 8) & 1) else -1.0
                        vec[idx_ng] += sign_ng * 0.8

        # L2 Normalization
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 1e-9:
            vec = [x / norm for x in vec]
        return vec

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


def cosine_similarity(v1: Sequence[float], v2: Sequence[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if len(v1) != len(v2) or not v1:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 < 1e-9 or norm2 < 1e-9:
        return 0.0
    sim = dot / (norm1 * norm2)
    return max(-1.0, min(1.0, sim))


class VectorMemoryStore:
    """
    SQLite-backed transactional vector storage engine for semantic memory.
    Stores vectors as packed binary blobs with metadata indexing.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        dimension: int = 128,
        embedding_provider: DenseEmbeddingProvider | None = None,
    ) -> None:
        self.db_path = str(db_path or DATABASE_PATH)
        self.dimension = dimension
        self.embedder = embedding_provider or DenseEmbeddingProvider(dimension=dimension)
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
                CREATE TABLE IF NOT EXISTS semantic_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id INTEGER,
                    text TEXT NOT NULL,
                    vector_blob BLOB NOT NULL,
                    dim INTEGER NOT NULL,
                    metadata_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_semantic_memory_id ON semantic_embeddings(memory_id);"
            )
            conn.commit()

    def _pack_vector(self, vector: list[float]) -> bytes:
        return struct.pack(f"{len(vector)}f", *vector)

    def _unpack_vector(self, blob: bytes, dim: int) -> list[float]:
        return list(struct.unpack(f"{dim}f", blob))

    def add_vector(
        self,
        text: str,
        memory_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Embed text and insert vector record into database."""
        vector = self.embedder.embed_text(text)
        blob = self._pack_vector(vector)
        meta_str = json.dumps(metadata or {}, ensure_ascii=False)
        now = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO semantic_embeddings (memory_id, text, vector_blob, dim, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (memory_id, text, blob, self.dimension, meta_str, now),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def search_similar(
        self,
        query: str,
        limit: int = 5,
        threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Search top-K semantically similar records using cosine similarity."""
        query_vec = self.embedder.embed_text(query)
        records: list[tuple[float, dict[str, Any]]] = []

        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, memory_id, text, vector_blob, dim, metadata_json, created_at FROM semantic_embeddings;"
            ).fetchall()

            for row in rows:
                dim = row["dim"]
                blob = row["vector_blob"]
                vec = self._unpack_vector(blob, dim)
                score = cosine_similarity(query_vec, vec)
                if score >= threshold:
                    meta = json.loads(row["metadata_json"] or "{}")
                    records.append((
                        score,
                        {
                            "id": row["id"],
                            "memory_id": row["memory_id"],
                            "text": row["text"],
                            "score": round(score, 4),
                            "metadata": meta,
                            "created_at": row["created_at"],
                        },
                    ))

        # Sort descending by cosine similarity score
        records.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in records[:limit]]

    def delete_by_memory_id(self, memory_id: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM semantic_embeddings WHERE memory_id = ?;", (memory_id,)
            )
            conn.commit()
            return cursor.rowcount

    def count(self) -> int:
        with self._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM semantic_embeddings;").fetchone()
            return row["cnt"] if row else 0
