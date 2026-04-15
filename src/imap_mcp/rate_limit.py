"""Token-bucket rate limiter (per account, in-process)."""

from __future__ import annotations

import time
from threading import Lock

from .errors import RateLimitedError


class TokenBucket:
    """Thread-safe token bucket with a per-minute refill rate."""

    def __init__(self, max_ops_per_minute: int) -> None:
        self._capacity = float(max_ops_per_minute)
        self._tokens = float(max_ops_per_minute)
        self._refill_rate = max_ops_per_minute / 60.0  # tokens per second
        self._last_refill = time.monotonic()
        self._lock = Lock()

    def consume(self, account: str) -> None:
        """Consume one token, or raise RateLimitedError if the bucket is empty."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self._capacity,
                self._tokens + elapsed * self._refill_rate,
            )
            self._last_refill = now

            if self._tokens < 1.0:
                raise RateLimitedError(account)
            self._tokens -= 1.0


class RateLimiter:
    """Registry of per-account token buckets.

    Constructed once at server startup and shared across all requests.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = Lock()

    def configure(self, account: str, max_ops_per_minute: int) -> None:
        """Register (or replace) a bucket for the given account."""
        with self._lock:
            self._buckets[account] = TokenBucket(max_ops_per_minute)

    def consume(self, account: str) -> None:
        """Consume one token for the account.

        If no bucket is registered for the account, the call is a no-op
        (unconfigured accounts are unrestricted).
        """
        with self._lock:
            bucket = self._buckets.get(account)
        if bucket is not None:
            bucket.consume(account)
