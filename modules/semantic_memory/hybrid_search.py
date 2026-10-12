"""Hybrid Search engine combining FTS5 BM25 keyword matching with Vector embeddings via RRF."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from modules.memory import MemoryItem, MemoryStore
from modules.semantic_memory.vector_store import VectorMemoryStore

logger = logging.getLogger("aru.semantic_memory.hybrid_search")


@dataclass
class HybridSearchResult:
    """Unified result item scored and ranked across keyword and semantic searches."""
    memory_id: int | None
    title: str
    content: str
    category: str
    bm25_rank: int | None
    vector_rank: int | None
    rrf_score: float
    vector_similarity: float
    source: str  # "both", "bm25", "vector"


class HybridSearchEngine:
    """
    Combines FTS5 BM25 keyword retrieval and dense vector cosine similarity.
    Uses Reciprocal Rank Fusion (RRF):
        RRF(d) = (w_bm25 / (k + rank_bm25)) + (w_vec / (k + rank_vec))
    with k=60 to prevent domination by high-scoring outliers.
    """

    def __init__(
        self,
        memory_store: MemoryStore,
        vector_store: VectorMemoryStore,
        k: int = 60,
        weight_bm25: float = 0.5,
        weight_vector: float = 0.5,
    ) -> None:
        self.memory_store = memory_store
        self.vector_store = vector_store
        self.k = k
        self.w_bm25 = weight_bm25
        self.w_vec = weight_vector

    def search(
        self,
        query: str,
        limit: int = 5,
        category: str | None = None,
    ) -> list[HybridSearchResult]:
        """Execute hybrid search blending BM25 and vector results."""
        if not query or not query.strip():
            return []

        # 1. Fetch BM25 matches from SQLite FTS5
        bm25_items: list[MemoryItem] = []
        try:
            bm25_items = self.memory_store.search(query.strip(), limit=limit * 2)
            if category:
                bm25_items = [m for m in bm25_items if m.category == category]
        except Exception as exc:
            logger.warning("FTS5 BM25 search failed: %s", exc)

        # 2. Fetch Vector matches
        vector_items: list[dict[str, Any]] = []
        try:
            vector_items = self.vector_store.search_similar(query.strip(), limit=limit * 2, threshold=0.15)
        except Exception as exc:
            logger.warning("Vector search failed: %s", exc)

        # 3. Build RRF rank maps
        bm25_ranks: dict[int, int] = {}
        for rank, item in enumerate(bm25_items, start=1):
            if item.id is not None:
                bm25_ranks[item.id] = rank

        vector_ranks: dict[int, int] = {}
        vector_scores: dict[int, float] = {}
        vector_data: dict[int, dict[str, Any]] = {}
        for rank, v_item in enumerate(vector_items, start=1):
            mem_id = v_item.get("memory_id")
            if mem_id is not None:
                vector_ranks[mem_id] = rank
                vector_scores[mem_id] = v_item.get("score", 0.0)
                vector_data[mem_id] = v_item

        # 4. Compute RRF scores for all unique memory IDs
        all_ids = set(bm25_ranks.keys()) | set(vector_ranks.keys())
        results: list[HybridSearchResult] = []

        for m_id in all_ids:
            r_bm25 = bm25_ranks.get(m_id)
            r_vec = vector_ranks.get(m_id)

            score = 0.0
            if r_bm25 is not None:
                score += self.w_bm25 / (self.k + r_bm25)
            if r_vec is not None:
                score += self.w_vec / (self.k + r_vec)

            # Resolve memory details
            mem_item = self.memory_store.get(m_id)
            if mem_item:
                title = mem_item.title
                content = mem_item.content
                cat = mem_item.category
            elif m_id in vector_data:
                v_entry = vector_data[m_id]
                title = v_entry.get("metadata", {}).get("title", f"Memory #{m_id}")
                content = v_entry.get("text", "")
                cat = v_entry.get("metadata", {}).get("category", "fact")
            else:
                continue

            if category and cat != category:
                continue

            source = "both" if (r_bm25 and r_vec) else ("bm25" if r_bm25 else "vector")
            results.append(
                HybridSearchResult(
                    memory_id=m_id,
                    title=title,
                    content=content,
                    category=cat,
                    bm25_rank=r_bm25,
                    vector_rank=r_vec,
                    rrf_score=round(score, 6),
                    vector_similarity=vector_scores.get(m_id, 0.0),
                    source=source,
                )
            )

        # Sort by RRF score descending
        results.sort(key=lambda r: r.rrf_score, reverse=True)
        return results[:limit]

    def index_memory_item(self, item: MemoryItem) -> int:
        """Helper to create/update vector index for a memory item."""
        if item.id is None:
            return 0
        # Delete old embedding if exists
        self.vector_store.delete_by_memory_id(item.id)
        # Add new embedding combining title and content
        full_text = f"{item.title}\n{item.content}".strip()
        return self.vector_store.add_vector(
            text=full_text,
            memory_id=item.id,
            metadata={"title": item.title, "category": item.category},
        )
