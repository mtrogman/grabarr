"""
Tests for rate limiting functionality.

Tests:
- Basic rate limiting
- Window sliding
- Multiple users
- Edge cases
"""

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from src.utils.rate_limiter import RateLimiter, RateLimitExceeded


@pytest.fixture
def rate_limiter():
    """Create a rate limiter with test-friendly settings."""
    return RateLimiter(max_requests=3, window_seconds=10)


class TestRateLimiter:
    """Tests for RateLimiter class."""

    @pytest.mark.asyncio
    async def test_allows_requests_within_limit(self, rate_limiter):
        """Test that requests within limit are allowed."""
        user_id = 12345

        # Should allow 3 requests
        for _ in range(3):
            await rate_limiter.acquire(user_id)

        # All should succeed without raising

    @pytest.mark.asyncio
    async def test_blocks_requests_over_limit(self, rate_limiter):
        """Test that requests over limit are blocked."""
        user_id = 12345

        # Use up the limit
        for _ in range(3):
            await rate_limiter.acquire(user_id)

        # Next request should fail
        with pytest.raises(RateLimitExceeded) as exc_info:
            await rate_limiter.acquire(user_id)

        assert exc_info.value.user_id == user_id
        assert exc_info.value.retry_after >= 0

    @pytest.mark.asyncio
    async def test_separate_limits_per_user(self, rate_limiter):
        """Test that different users have separate limits."""
        user1 = 11111
        user2 = 22222

        # User 1 uses all requests
        for _ in range(3):
            await rate_limiter.acquire(user1)

        # User 2 should still be able to make requests
        await rate_limiter.acquire(user2)  # Should not raise

        # User 1 should be blocked
        with pytest.raises(RateLimitExceeded):
            await rate_limiter.acquire(user1)

    @pytest.mark.asyncio
    async def test_window_sliding(self, rate_limiter):
        """Test that old requests fall off the window."""
        user_id = 12345

        # Make requests
        for _ in range(3):
            await rate_limiter.acquire(user_id)

        # Simulate time passing beyond window
        # Access internal state to modify timestamps
        user_limit = rate_limiter._user_limits[user_id]
        old_time = datetime.now(timezone.utc) - timedelta(seconds=15)
        user_limit.requests = [old_time, old_time, old_time]

        # Should now allow new request
        await rate_limiter.acquire(user_id)  # Should not raise

    @pytest.mark.asyncio
    async def test_get_remaining(self, rate_limiter):
        """Test getting remaining requests."""
        user_id = 12345

        # Initially should have full quota
        remaining = await rate_limiter.get_remaining(user_id)
        assert remaining == 3

        # After one request
        await rate_limiter.acquire(user_id)
        remaining = await rate_limiter.get_remaining(user_id)
        assert remaining == 2

    @pytest.mark.asyncio
    async def test_get_reset_time(self, rate_limiter):
        """Test getting reset time."""
        user_id = 12345

        # No requests yet
        reset_time = await rate_limiter.get_reset_time(user_id)
        assert reset_time is None

        # After request
        await rate_limiter.acquire(user_id)
        reset_time = await rate_limiter.get_reset_time(user_id)
        assert reset_time is not None
        assert 0 <= reset_time <= 10

    @pytest.mark.asyncio
    async def test_clear_user(self, rate_limiter):
        """Test clearing rate limit for a user."""
        user_id = 12345

        # Use up limit
        for _ in range(3):
            await rate_limiter.acquire(user_id)

        # Clear user
        await rate_limiter.clear_user(user_id)

        # Should be able to make requests again
        await rate_limiter.acquire(user_id)  # Should not raise

    @pytest.mark.asyncio
    async def test_clear_all(self, rate_limiter):
        """Test clearing all rate limits."""
        user1 = 11111
        user2 = 22222

        # Both users use their limits
        for _ in range(3):
            await rate_limiter.acquire(user1)
            await rate_limiter.acquire(user2)

        # Clear all
        await rate_limiter.clear_all()

        # Both should be able to make requests
        await rate_limiter.acquire(user1)
        await rate_limiter.acquire(user2)

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, rate_limiter):
        """Test thread safety with concurrent requests."""
        user_id = 12345
        successful = 0
        failed = 0

        async def make_request():
            nonlocal successful, failed
            try:
                await rate_limiter.acquire(user_id)
                successful += 1
            except RateLimitExceeded:
                failed += 1

        # Make 10 concurrent requests (only 3 should succeed)
        await asyncio.gather(*[make_request() for _ in range(10)])

        assert successful == 3
        assert failed == 7


class TestRateLimitExceeded:
    """Tests for RateLimitExceeded exception."""

    def test_exception_message(self):
        exc = RateLimitExceeded(user_id=12345, retry_after=5.5)

        assert exc.user_id == 12345
        assert exc.retry_after == 5.5
        assert "12345" in str(exc)
        assert "5.5" in str(exc)
