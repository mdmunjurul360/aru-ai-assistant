"""Semantic Memory package: Vector storage, Hybrid Search (BM25 + Vector RRF), and Context Compression."""

from __future__ import annotations

from modules.semantic_memory.compression import ContextCompressor
from modules.semantic_memory.hybrid_search import (
    HybridSearchEngine,
    HybridSearchResult,
)
from modules.semantic_memory.vector_store import (
    DenseEmbeddingProvider,
    VectorMemoryStore,
    VectorRecord,
    cosine_similarity,
)

__all__ = [
    "DenseEmbeddingProvider",
    "VectorMemoryStore",
    "VectorRecord",
    "cosine_similarity",
    "HybridSearchEngine",
    "HybridSearchResult",
    "ContextCompressor",
]
