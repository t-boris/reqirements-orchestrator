"""
Rate Limiter - Leaky bucket implementation for API rate limiting.

Prevents overwhelming external APIs with too many requests.
"""

import asyncio
import time
from dataclasses import dataclass


@dataclass
class LeakyBucketState:
    """State of the leaky bucket."""

    tokens: float
    last_update: float


class LeakyBucketRateLimiter:
    """
    Leaky bucket rate limiter for API calls.

    Allows bursts up to bucket size, then limits to tokens_per_second rate.
    Implements async acquire() that waits when rate limited.
    """

    def __init__(
        self,
        tokens_per_second: float = 10.0,
        bucket_size: float = 20.0,
    ) -> None:
        """
        Initialize rate limiter.

        Args:
            tokens_per_second: Rate at which tokens are added (leak rate).
            bucket_size: Maximum tokens in the bucket.
        """
        self._tokens_per_second = tokens_per_second
        self._bucket_size = bucket_size
        self._state = LeakyBucketState(
            tokens=bucket_size,
            last_update=time.monotonic(),
        )
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> float:
        """
        Acquire tokens from the bucket.

        Waits if insufficient tokens are available.

        Args:
            tokens: Number of tokens to acquire.

        Returns:
            Time waited in seconds.
        """
        async with self._lock:
            wait_time = 0.0

            # Refill bucket based on time elapsed
            now = time.monotonic()
            elapsed = now - self._state.last_update
            self._state.tokens = min(
                self._bucket_size,
                self._state.tokens + elapsed * self._tokens_per_second,
            )
            self._state.last_update = now

            # Wait if not enough tokens
            if self._state.tokens < tokens:
                wait_time = (tokens - self._state.tokens) / self._tokens_per_second
                await asyncio.sleep(wait_time)

                # Refill after waiting
                self._state.tokens = min(
                    self._bucket_size,
                    self._state.tokens + wait_time * self._tokens_per_second,
                )
                self._state.last_update = time.monotonic()

            # Consume tokens
            self._state.tokens -= tokens
            return wait_time

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """
        Try to acquire tokens without waiting.

        Args:
            tokens: Number of tokens to acquire.

        Returns:
            True if tokens acquired, False if rate limited.
        """
        now = time.monotonic()
        elapsed = now - self._state.last_update
        available = min(
            self._bucket_size,
            self._state.tokens + elapsed * self._tokens_per_second,
        )

        if available >= tokens:
            self._state.tokens = available - tokens
            self._state.last_update = now
            return True

        return False

    @property
    def available_tokens(self) -> float:
        """Get current available tokens (estimated)."""
        now = time.monotonic()
        elapsed = now - self._state.last_update
        return min(
            self._bucket_size,
            self._state.tokens + elapsed * self._tokens_per_second,
        )

    def reset(self) -> None:
        """Reset the bucket to full."""
        self._state.tokens = self._bucket_size
        self._state.last_update = time.monotonic()
