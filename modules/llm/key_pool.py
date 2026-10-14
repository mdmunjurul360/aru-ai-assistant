"""API Key Pool and Slot Management for Multi-Key Provider Failover.

Provides:
- KeyHealthStatus: Enum for key lifecycle states (HEALTHY, COOLDOWN, PROBING, DISABLED).
- APIKeySlot: Tracks independent state, metrics, and circuit breaker for a single API key.
- KeyPool: Manages a collection of APIKeySlots with thread/coroutine safety (asyncio.Lock),
  Half-Open probe recovery, per-key circuit breaking, and intra-provider failover.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
import logging
import time
from typing import Any, Awaitable, Callable, TypeVar

from modules.llm.exceptions import (
    LLMProviderError,
    ProviderAuthenticationError,
    ProviderPoolExhaustedError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

logger = logging.getLogger("aru.llm.pool")

T = TypeVar("T")


class KeyHealthStatus(str, Enum):
    """Health states for an individual API key slot."""

    HEALTHY = "HEALTHY"
    COOLDOWN = "COOLDOWN"
    PROBING = "PROBING"
    DISABLED = "DISABLED"


def mask_key(key: str | None) -> str:
    """Safely mask an API key for logs and diagnostics (e.g. AIza....8kQ)."""
    if not key:
        return "<none>"
    clean = str(key).strip()
    if not clean:
        return "<none>"
    if len(clean) <= 8:
        return "***"
    return f"{clean[:4]}....{clean[-4:]}"


class APIKeySlot:
    """Manages state, usage metrics, and circuit breaker for an individual API key."""

    def __init__(
        self,
        index_or_key: int | str = 1,
        api_key: str = "",
        provider_name: str = "",
        *,
        index: int | None = None,
        account_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if isinstance(index_or_key, str) and not api_key:
            self.index = index if index is not None else 1
            self.api_key = index_or_key.strip()
        else:
            self.index = index if index is not None else int(index_or_key)
            self.api_key = api_key.strip()

        self.provider_name = provider_name.strip().lower()
        self.account_id = (account_id or "").strip()
        self.metadata = metadata or {}
        self.masked_key = mask_key(self.api_key)
        self.masked_account = mask_key(self.account_id) if self.account_id else ""

        # Health & Circuit Breaker
        self.status = KeyHealthStatus.HEALTHY if self.api_key else KeyHealthStatus.DISABLED
        self.cooldown_until: float = 0.0
        self.consecutive_failures: int = 0
        self.is_probing: bool = False

        # Metrics
        self.total_requests: int = 0
        self.successful_requests: int = 0
        self.failed_requests: int = 0
        self.total_latency_sec: float = 0.0
        self.avg_latency_ms: float = 0.0
        self.last_error: str | None = None
        self.last_used_timestamp: str | None = None

    @property
    def label(self) -> str:
        """Formatted display label without exposing secrets (e.g. 'Cloudflare Key #1 (Account: b687..4478)')."""
        prov = self.provider_name.capitalize() if self.provider_name else "Provider"
        if self.account_id:
            masked_acc = f"{self.account_id[:4]}..{self.account_id[-4:]}" if len(self.account_id) > 8 else "***"
            return f"{prov} Key #{self.index} (Account: {masked_acc})"
        return f"{prov} Key #{self.index}"

    @property
    def display_name(self) -> str:
        """Convenience alias for label."""
        return self.label

    @property
    def request_count(self) -> int:
        return self.total_requests

    @property
    def success_count(self) -> int:
        return self.successful_requests

    @property
    def failure_count(self) -> int:
        return self.failed_requests

    @property
    def average_latency(self) -> float:
        if self.successful_requests > 0:
            return self.total_latency_sec / self.successful_requests
        return 0.0

    @property
    def cooldown_timer(self) -> float:
        return self.cooldown_until

    @property
    def cooldown_remaining(self) -> float:
        return self.cooldown_seconds_remaining()

    @property
    def is_available(self) -> bool:
        return self.check_availability()

    def is_in_cooldown(self) -> bool:
        """Return True if the key is currently cooling down."""
        if self.status == KeyHealthStatus.DISABLED:
            return True
        if self.status == KeyHealthStatus.COOLDOWN:
            return time.time() < self.cooldown_until
        return False

    def cooldown_seconds_remaining(self) -> float:
        """Seconds remaining in cooldown, or 0.0 if healthy."""
        if self.status == KeyHealthStatus.DISABLED:
            return float("inf")
        return max(0.0, self.cooldown_until - time.time())

    def check_availability(self) -> bool:
        """
        Evaluate availability considering Half-Open Probing.
        Returns True if the key can accept a request.
        """
        if self.status == KeyHealthStatus.DISABLED:
            return False

        if self.status == KeyHealthStatus.HEALTHY:
            return True

        if self.status == KeyHealthStatus.COOLDOWN:
            now = time.time()
            if now >= self.cooldown_until:
                # Cooldown expired! Check if we can lease this slot as a probe
                if not self.is_probing:
                    self.is_probing = True
                    self.status = KeyHealthStatus.PROBING
                    return True
                # Another concurrent request is already probing this key
                return False
            return False

        if self.status == KeyHealthStatus.PROBING:
            # Already leased to a probe request
            return False

        return False

    def record_success(self, latency_sec: float) -> None:
        """Record successful request, reset failure counters, and clear cooldown."""
        self.status = KeyHealthStatus.HEALTHY
        self.is_probing = False
        self.cooldown_until = 0.0
        self.consecutive_failures = 0

        self.successful_requests += 1
        self.total_requests += 1
        self.total_latency_sec += latency_sec
        self.avg_latency_ms = (self.total_latency_sec / self.successful_requests) * 1000.0
        self.last_used_timestamp = datetime.now(timezone.utc).isoformat()

    def record_failure(
        self,
        error: Exception,
        cooldown_seconds: float = 60.0,
        is_permanent: bool = False,
    ) -> None:
        """Record error, increment failure counts, and trigger circuit breaker."""
        self.failed_requests += 1
        self.total_requests += 1
        self.consecutive_failures += 1
        err_str = str(error)
        self.last_error = err_str
        self.is_probing = False
        self.last_used_timestamp = datetime.now(timezone.utc).isoformat()

        err_lower = err_str.lower()
        is_auth = is_permanent or isinstance(error, ProviderAuthenticationError) or any(
            code in err_lower for code in ("401", "403", "unauthorized", "forbidden", "invalid api key", "invalid_api_key")
        )
        is_quota = any(
            kw in err_lower for kw in ("quota", "resource_exhausted", "credit", "balance", "insufficient_quota")
        )

        if is_auth:
            self.status = KeyHealthStatus.DISABLED
            self.cooldown_until = float("inf")
        elif is_quota:
            self.status = KeyHealthStatus.COOLDOWN
            # Quota exhausted -> long cooldown (1800s default)
            actual_cooldown = max(1800.0, cooldown_seconds)
            self.cooldown_until = time.time() + actual_cooldown
        else:
            self.status = KeyHealthStatus.COOLDOWN
            # 429 or other temporary -> short cooldown (60s default)
            mult = min(8, 2 ** max(0, self.consecutive_failures - 1))
            actual_cooldown = max(30.0, cooldown_seconds) * mult
            self.cooldown_until = time.time() + actual_cooldown

    def reset_cooldown(self) -> None:
        """Manually reset the slot back to HEALTHY."""
        self.is_probing = False
        self.cooldown_until = 0.0
        self.consecutive_failures = 0
        if self.api_key:
            self.status = KeyHealthStatus.HEALTHY
        else:
            self.status = KeyHealthStatus.DISABLED

    def to_dict(self) -> dict[str, Any]:
        """Diagnostic state representation."""
        return {
            "index": self.index,
            "label": self.label,
            "masked_key": self.masked_key,
            "status": self.status.value,
            "is_probing": self.is_probing,
            "cooldown_remaining_sec": round(self.cooldown_seconds_remaining(), 1),
            "consecutive_failures": self.consecutive_failures,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate_pct": (
                round((self.successful_requests / self.total_requests) * 100.0, 1)
                if self.total_requests > 0
                else 100.0
            ),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "last_error": self.last_error,
            "last_used": self.last_used_timestamp,
        }

    def __repr__(self) -> str:
        return f"<APIKeySlot {self.label} status={self.status.value} masked={self.masked_key}>"


class KeyPool:
    """
    Thread-safe / coroutine-safe API Key Pool for an LLM provider.
    Coordinates hierarchical intra-provider key failover, per-key circuit breakers,
    and single-flight Half-Open probes.
    """

    SHORT_COOLDOWN = 60.0    # 429 transient rate limit
    LONG_COOLDOWN = 1800.0   # Daily/monthly quota exhausted
    DEFAULT_COOLDOWN = 300.0 # Generic network/server errors

    def __init__(
        self,
        provider_name: str,
        keys: list[str] | list[dict[str, str]] | None = None,
        default_cooldown: float = 300.0,
    ) -> None:
        self.provider_name = provider_name.strip().lower()
        self.default_cooldown = float(default_cooldown)
        self._lock = asyncio.Lock()

        # Build key slots (deduplicated, order-preserved, 1-indexed)
        # Supports both string keys (standard) and dicts with account_id + api_key (e.g. Cloudflare)
        cleaned_items: list[Any] = []
        seen: set[str] = set()
        for k in (keys or []):
            if isinstance(k, dict):
                api_k = str(k.get("api_key") or "").strip()
                acc_id = str(k.get("account_id") or "").strip()
                dedup_key = f"{acc_id}:{api_k}"
                if (api_k or acc_id) and dedup_key not in seen:
                    seen.add(dedup_key)
                    cleaned_items.append({"api_key": api_k, "account_id": acc_id})
            else:
                stripped = (k or "").strip()
                if stripped and stripped not in seen:
                    seen.add(stripped)
                    cleaned_items.append(stripped)

        self.slots: list[APIKeySlot] = []
        for i, item in enumerate(cleaned_items):
            if isinstance(item, dict):
                self.slots.append(
                    APIKeySlot(
                        index=i + 1,
                        api_key=item["api_key"],
                        account_id=item["account_id"],
                        provider_name=self.provider_name,
                    )
                )
            else:
                self.slots.append(
                    APIKeySlot(
                        index=i + 1,
                        api_key=item,
                        provider_name=self.provider_name,
                    )
                )

    @property
    def total_keys(self) -> int:
        """Total configured keys in pool."""
        return len(self.slots)

    @property
    def has_keys(self) -> bool:
        """Return True if at least one key is configured."""
        return bool(self.slots)

    def active_keys_count(self) -> int:
        """Number of currently non-disabled keys."""
        return sum(1 for s in self.slots if s.status != KeyHealthStatus.DISABLED)

    def has_available_slot(self) -> bool:
        """Return True if at least one slot can accept requests or is ready to probe."""
        now = time.time()
        for s in self.slots:
            if s.status == KeyHealthStatus.HEALTHY:
                return True
            if s.status == KeyHealthStatus.COOLDOWN and s.cooldown_until <= now:
                return True
        return False

    def min_cooldown_remaining(self) -> float:
        """Minimum cooldown remaining across all cooling slots."""
        remaining = [
            s.cooldown_seconds_remaining()
            for s in self.slots
            if s.status == KeyHealthStatus.COOLDOWN
        ]
        return min(remaining) if remaining else 0.0

    def reset_all_cooldowns(self) -> None:
        """Reset all slots back to HEALTHY."""
        for s in self.slots:
            s.reset_cooldown()

    def first_slot(self) -> APIKeySlot | None:
        """Retrieve the primary slot (Key #1), if configured."""
        return self.slots[0] if self.slots else None

    async def select_slot(self) -> APIKeySlot | None:
        """Select the next available slot in priority order, leasing probe permission if applicable."""
        async with self._lock:
            for slot in self.slots:
                if slot.check_availability():
                    return slot
            return None

    async def release_slot(
        self,
        slot: APIKeySlot,
        success: bool,
        latency_sec: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        """Record outcome and release slot in a thread-safe manner."""
        async with self._lock:
            if success:
                slot.record_success(latency_sec)
            elif error:
                slot.record_failure(error)
            else:
                slot.is_probing = False

    async def get_ordered_candidate_slots(self) -> list[APIKeySlot]:
        """
        Thread-safe acquisition of candidate slots in priority order.
        Leases half-open probe permissions where cooldown has expired.
        """
        async with self._lock:
            candidates: list[APIKeySlot] = []
            for slot in self.slots:
                if slot.check_availability():
                    candidates.append(slot)
            return candidates

    async def execute_with_key_failover(
        self,
        op_or_name: str | Callable[[APIKeySlot], Awaitable[T]],
        operation: Callable[[APIKeySlot], Awaitable[T]] | None = None,
    ) -> T:
        """
        Execute an operation with intra-provider key failover:
        Key #1 -> Key #2 -> Key #3 ...
        
        Supports both signatures:
          execute_with_key_failover(callable)
          execute_with_key_failover("op_name", callable)
        """
        if callable(op_or_name):
            runner_fn = op_or_name
            op_name = getattr(runner_fn, "__name__", "operation")
        else:
            op_name = str(op_or_name)
            if not operation or not callable(operation):
                raise ValueError("An asynchronous operation callable must be provided.")
            runner_fn = operation

        if not self.slots:
            raise ProviderUnavailableError(
                f"Provider '{self.provider_name}' has no API keys configured.",
                provider=self.provider_name,
            )

        candidates = await self.get_ordered_candidate_slots()
        if not candidates:
            min_cd = round(self.min_cooldown_remaining(), 1)
            raise ProviderPoolExhaustedError(
                f"All {len(self.slots)} API keys for '{self.provider_name}' are in cooldown ({min_cd}s remaining).",
                provider=self.provider_name,
            )

        attempts_record: list[dict[str, Any]] = []

        for candidate_idx, slot in enumerate(candidates):
            start_time = time.perf_counter()
            try:
                logger.info(
                    "[%s] Dispatching %s to %s (%s) [candidate %d/%d]",
                    self.provider_name.capitalize(),
                    op_name,
                    slot.label,
                    slot.masked_key,
                    candidate_idx + 1,
                    len(candidates),
                )
                result = await runner_fn(slot)
                latency = time.perf_counter() - start_time

                async with self._lock:
                    slot.record_success(latency)

                logger.info(
                    "[%s] %s succeeded on %s (latency=%.3fs)",
                    self.provider_name.capitalize(),
                    op_name,
                    slot.label,
                    latency,
                )
                return result

            except Exception as exc:
                latency = time.perf_counter() - start_time
                err_str = str(exc)
                logger.warning(
                    "[%s] %s failed on %s (latency=%.3fs, error=%s)",
                    self.provider_name.capitalize(),
                    op_name,
                    slot.label,
                    latency,
                    err_str,
                )
                attempts_record.append({
                    "slot_index": slot.index,
                    "slot_label": slot.label,
                    "latency_sec": round(latency, 3),
                    "error": err_str,
                })

                # Error Classification & Per-Key Circuit Breaker Logic
                err_lower = err_str.lower()
                is_auth_error = isinstance(exc, ProviderAuthenticationError) or any(
                    kw in err_lower for kw in ("401", "403", "api key", "credentials", "invalid_api_key", "unauthorized", "forbidden")
                )
                is_quota_exhausted = any(
                    kw in err_lower for kw in ("quota exceeded", "quota_exhausted", "resource_exhausted", "insufficient_quota", "balance", "credit")
                )
                is_rate_limit = isinstance(exc, ProviderRateLimitError) or any(
                    kw in err_lower for kw in ("429", "rate limit", "tpm", "rpm", "too many requests")
                )
                is_invalid_request = any(
                    kw in err_lower for kw in ("context limit", "max tokens exceeded", "context length", "400", "invalid_request_error", "content policy", "safety", "invalid argument")
                )

                # Do NOT failover across keys on request-level payload errors
                if is_invalid_request:
                    logger.debug("[%s] Request-level error on %s; not failing over across keys.", self.provider_name.capitalize(), slot.label)
                    raise

                # Record failure on this slot with appropriate cooldown
                async with self._lock:
                    if is_auth_error:
                        slot.record_failure(exc, is_permanent=True)
                        logger.warning("[%s] %s permanently DISABLED due to auth rejection.", self.provider_name.capitalize(), slot.label)
                    elif is_quota_exhausted:
                        slot.record_failure(exc, cooldown_seconds=self.LONG_COOLDOWN)
                        logger.warning("[%s] %s placed in LONG COOLDOWN (%.0fs) due to quota exhaustion.", self.provider_name.capitalize(), slot.label, self.LONG_COOLDOWN)
                    elif is_rate_limit:
                        slot.record_failure(exc, cooldown_seconds=self.SHORT_COOLDOWN)
                        logger.warning("[%s] %s placed in SHORT COOLDOWN (%.0fs) due to rate limit.", self.provider_name.capitalize(), slot.label, self.SHORT_COOLDOWN)
                    else:
                        slot.record_failure(exc, cooldown_seconds=self.DEFAULT_COOLDOWN)

                # Check if next key in pool is available
                has_next = candidate_idx + 1 < len(candidates)
                if has_next:
                    next_slot = candidates[candidate_idx + 1]
                    logger.info(
                        "[%s] Intra-provider failover: Switching from %s to %s...",
                        self.provider_name.capitalize(),
                        slot.label,
                        next_slot.label,
                    )
                else:
                    logger.warning(
                        "[%s] All %d available keys in pool exhausted for %s. Triggering inter-provider failover.",
                        self.provider_name.capitalize(),
                        len(candidates),
                        op_name,
                    )

        raise ProviderPoolExhaustedError(
            f"All {len(self.slots)} API keys for provider '{self.provider_name}' are currently exhausted or unavailable.",
            provider=self.provider_name,
            key_attempts=attempts_record,
        )

    def get_pool_status(self) -> dict[str, Any]:
        """Aggregate health status of the pool."""
        return {
            "provider": self.provider_name,
            "total_keys": self.total_keys,
            "active_keys": self.active_keys_count(),
            "slots": [s.to_dict() for s in self.slots],
        }
