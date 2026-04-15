"""Tests for the token-bucket rate limiter."""

import pytest

from imap_mcp.errors import RateLimitedError
from imap_mcp.rate_limit import RateLimiter, TokenBucket


class TestTokenBucket:
    def test_allows_up_to_capacity(self):
        bucket = TokenBucket(max_ops_per_minute=3)
        for _ in range(3):
            bucket.consume("acc")  # should not raise

    def test_raises_when_exhausted(self):
        bucket = TokenBucket(max_ops_per_minute=2)
        bucket.consume("acc")
        bucket.consume("acc")
        with pytest.raises(RateLimitedError):
            bucket.consume("acc")


class TestRateLimiter:
    def test_unconfigured_account_is_unrestricted(self):
        limiter = RateLimiter()
        # No bucket registered → no error regardless of call count
        for _ in range(1000):
            limiter.consume("unknown")

    def test_configured_account_is_enforced(self):
        limiter = RateLimiter()
        limiter.configure("personal", max_ops_per_minute=2)
        limiter.consume("personal")
        limiter.consume("personal")
        with pytest.raises(RateLimitedError):
            limiter.consume("personal")

    def test_multiple_accounts_independent(self):
        limiter = RateLimiter()
        limiter.configure("a", max_ops_per_minute=1)
        limiter.configure("b", max_ops_per_minute=5)
        limiter.consume("a")
        with pytest.raises(RateLimitedError):
            limiter.consume("a")
        # "b" still has tokens
        limiter.consume("b")
        limiter.consume("b")
