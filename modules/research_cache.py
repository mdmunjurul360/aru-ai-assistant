"""SQLite-backed cache for research results with configurable TTL."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from modules.config import DATABASE_PATH, RESEARCH_CACHE_TTL_SECONDS
from modules.db import get_db_connection

logger = logging.getLogger("aru.research_cache")


class ResearchCache:
    """Persistent SQLite cache for research engine queries and citations."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or DATABASE_PATH)
        self._init_db()

    def _init_db(self) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS research_cache (
                    query_hash TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    citations_json TEXT NOT NULL DEFAULT '[]',
                    raw_results_json TEXT NOT NULL DEFAULT '[]',
                    is_job_search INTEGER NOT NULL DEFAULT 0,
                    verified_jobs_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_cache_expires ON research_cache(expires_at)"
            )

    @staticmethod
    def _hash_query(query: str) -> str:
        normalized = query.strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def get(self, query: str) -> dict[str, Any] | None:
        """Retrieve cached research item if still valid (not expired)."""
        q_hash = self._hash_query(query)
        now = datetime.now(timezone.utc).isoformat()

        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM research_cache WHERE query_hash = ?",
                (q_hash,),
            ).fetchone()

            if not row:
                return None

            if row["expires_at"] <= now:
                # Expired — delete and treat as cache miss
                conn.execute("DELETE FROM research_cache WHERE query_hash = ?", (q_hash,))
                logger.debug("Research cache expired for query='%s'", query[:40])
                return None

            try:
                citations = json.loads(row["citations_json"])
                raw_results = json.loads(row["raw_results_json"])
                verified_jobs = json.loads(row["verified_jobs_json"])
            except Exception as exc:
                logger.warning("Error parsing cached research JSON: %s", exc)
                return None

            return {
                "query": row["query"],
                "summary": row["summary"],
                "citations": citations,
                "raw_results": raw_results,
                "is_job_search": bool(row["is_job_search"]),
                "verified_jobs": verified_jobs,
                "created_at": row["created_at"],
                "cached": True,
            }

    def set(
        self,
        query: str,
        summary: str,
        citations: list[dict[str, Any]],
        raw_results: list[dict[str, Any]],
        *,
        is_job_search: bool = False,
        verified_jobs: list[dict[str, Any]] | None = None,
        ttl_seconds: int = RESEARCH_CACHE_TTL_SECONDS,
    ) -> None:
        """Store research result into SQLite cache."""
        q_hash = self._hash_query(query)
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        expires = (now_dt + timedelta(seconds=ttl_seconds)).isoformat()

        citations_json = json.dumps(citations, ensure_ascii=False)
        raw_results_json = json.dumps(raw_results, ensure_ascii=False)
        verified_jobs_json = json.dumps(verified_jobs or [], ensure_ascii=False)

        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO research_cache (
                    query_hash, query, summary, citations_json, raw_results_json,
                    is_job_search, verified_jobs_json, created_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(query_hash) DO UPDATE SET
                    query = excluded.query,
                    summary = excluded.summary,
                    citations_json = excluded.citations_json,
                    raw_results_json = excluded.raw_results_json,
                    is_job_search = excluded.is_job_search,
                    verified_jobs_json = excluded.verified_jobs_json,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (
                    q_hash,
                    query.strip(),
                    summary,
                    citations_json,
                    raw_results_json,
                    1 if is_job_search else 0,
                    verified_jobs_json,
                    now,
                    expires,
                ),
            )
        logger.debug("Stored research cache for query='%s' (ttl=%ds)", query[:40], ttl_seconds)

    def invalidate(self, query: str) -> bool:
        """Invalidate cache for a specific query."""
        q_hash = self._hash_query(query)
        with get_db_connection(self.db_path) as conn:
            cur = conn.execute("DELETE FROM research_cache WHERE query_hash = ?", (q_hash,))
            deleted = cur.rowcount > 0
        if deleted:
            logger.info("Invalidated research cache for query='%s'", query[:40])
        return deleted

    def clear(self) -> int:
        """Clear all entries in the research cache."""
        with get_db_connection(self.db_path) as conn:
            cur = conn.execute("DELETE FROM research_cache")
            deleted = cur.rowcount
        logger.info("Cleared %d entries from research cache", deleted)
        return deleted

    def prune_expired(self) -> int:
        """Prune all expired cache records."""
        now = datetime.now(timezone.utc).isoformat()
        with get_db_connection(self.db_path) as conn:
            cur = conn.execute("DELETE FROM research_cache WHERE expires_at <= ?", (now,))
            deleted = cur.rowcount
        if deleted > 0:
            logger.info("Pruned %d expired research cache records", deleted)
        return deleted
