"""
Rate limiting implementation for Discord users.

Provides sliding window rate limiting to prevent abuse.
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..logging_config import get_logger

logger = get_logger(__name__)


class RateLimitExceeded(Exception):
    """Raised when user exceeds rate limit."""

    def __init__(self, user_id: int, retry_after: float):
        self.user_id = user_id
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded for user {user_id}. "
            f"Retry after {retry_after:.1f} seconds."
        )


@dataclass
class UserRateLimit:
    """Track rate limit state for a user."""
    requests: list[datetime] = field(default_factory=list)


class RateLimiter:
    """
    Sliding window rate limiter.

    Limits requests per user within a configurable time window.
    Thread-safe for async operations.
    """

    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: int = 60
    ):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed per window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._user_limits: dict[int, UserRateLimit] = defaultdict(UserRateLimit)
        self._lock = asyncio.Lock()

    def _cleanup_old_requests(self, user_limit: UserRateLimit) -> None:
        """Remove requests outside the current window."""
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - self.window_seconds
        user_limit.requests = [
            req for req in user_limit.requests
            if req.timestamp() > cutoff
        ]

    async def check_rate_limit(self, user_id: int) -> None:
        """
        Check if user is within rate limit.

        Args:
            user_id: Discord user ID

        Raises:
            RateLimitExceeded: If user has exceeded rate limit
        """
        async with self._lock:
            user_limit = self._user_limits[user_id]
            self._cleanup_old_requests(user_limit)

            if len(user_limit.requests) >= self.max_requests:
                # Calculate retry time
                oldest_request = min(user_limit.requests)
                retry_after = (
                    oldest_request.timestamp() +
                    self.window_seconds -
                    datetime.now(timezone.utc).timestamp()
                )
                retry_after = max(0.0, retry_after)

                logger.warning_structured(
                    "Rate limit exceeded",
                    user_id=user_id,
                    requests=len(user_limit.requests),
                    max_requests=self.max_requests,
                    retry_after=retry_after
                )
                raise RateLimitExceeded(user_id, retry_after)

    async def record_request(self, user_id: int) -> None:
        """
        Record a request for rate limiting.

        Args:
            user_id: Discord user ID
        """
        async with self._lock:
            user_limit = self._user_limits[user_id]
            user_limit.requests.append(datetime.now(timezone.utc))

    async def acquire(self, user_id: int) -> None:
        """
        Check rate limit and record request atomically.

        Args:
            user_id: Discord user ID

        Raises:
            RateLimitExceeded: If user has exceeded rate limit
        """
        await self.check_rate_limit(user_id)
        await self.record_request(user_id)

    async def get_remaining(self, user_id: int) -> int:
        """
        Get remaining requests for user.

        Args:
            user_id: Discord user ID

        Returns:
            Number of remaining requests in current window
        """
        async with self._lock:
            user_limit = self._user_limits[user_id]
            self._cleanup_old_requests(user_limit)
            return max(0, self.max_requests - len(user_limit.requests))

    async def get_reset_time(self, user_id: int) -> Optional[float]:
        """
        Get seconds until rate limit resets.

        Args:
            user_id: Discord user ID

        Returns:
            Seconds until reset, or None if no requests recorded
        """
        async with self._lock:
            user_limit = self._user_limits[user_id]
            self._cleanup_old_requests(user_limit)

            if not user_limit.requests:
                return None

            oldest_request = min(user_limit.requests)
            reset_time = (
                oldest_request.timestamp() +
                self.window_seconds -
                datetime.now(timezone.utc).timestamp()
            )
            return max(0.0, reset_time)

    async def clear_user(self, user_id: int) -> None:
        """Clear rate limit data for a user (admin function)."""
        async with self._lock:
            if user_id in self._user_limits:
                del self._user_limits[user_id]
                logger.info_structured(
                    "Rate limit cleared for user",
                    user_id=user_id
                )

    async def clear_all(self) -> None:
        """Clear all rate limit data (admin function)."""
        async with self._lock:
            self._user_limits.clear()
            logger.info_structured("All rate limits cleared")
