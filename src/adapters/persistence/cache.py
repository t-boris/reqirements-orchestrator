"""
Redis cache layer.

Provides caching for graph snapshots and session data.
"""

import json
from typing import Any

import structlog
from redis.asyncio import Redis

from src.config.settings import Settings

logger = structlog.get_logger()


class RedisCache:
    """
    Redis cache for graph data and sessions.

    Provides:
    - Graph snapshot caching
    - Session state caching
    - Rate limiting state
    - Task queue integration
    """

    def __init__(self, settings: Settings) -> None:
        """
        Initialize Redis connection.

        Args:
            settings: Application settings with REDIS_URL.
        """
        self._redis = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        self._default_ttl = 3600  # 1 hour
        logger.info("redis_cache_initialized")

    async def close(self) -> None:
        """Close Redis connection."""
        await self._redis.close()
        logger.info("redis_cache_closed")

    # -------------------------------------------------------------------------
    # Graph Cache
    # -------------------------------------------------------------------------

    async def cache_graph(
        self,
        channel_id: str,
        graph_data: dict,
        ttl: int | None = None,
    ) -> None:
        """
        Cache a graph snapshot.

        Args:
            channel_id: Slack channel ID.
            graph_data: Serialized graph data.
            ttl: Time to live in seconds.
        """
        key = f"graph:{channel_id}"
        await self._redis.set(
            key,
            json.dumps(graph_data, default=str),
            ex=ttl or self._default_ttl,
        )

    async def get_cached_graph(self, channel_id: str) -> dict | None:
        """
        Get cached graph snapshot.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Graph data or None if not cached.
        """
        key = f"graph:{channel_id}"
        data = await self._redis.get(key)

        if data:
            return json.loads(data)
        return None

    async def invalidate_graph(self, channel_id: str) -> None:
        """Invalidate cached graph."""
        key = f"graph:{channel_id}"
        await self._redis.delete(key)

    # -------------------------------------------------------------------------
    # Session Cache
    # -------------------------------------------------------------------------

    async def cache_session(
        self,
        channel_id: str,
        session_data: dict,
        ttl: int | None = None,
    ) -> None:
        """
        Cache agent session state.

        Args:
            channel_id: Slack channel ID.
            session_data: Session state to cache.
            ttl: Time to live in seconds.
        """
        key = f"session:{channel_id}"
        await self._redis.set(
            key,
            json.dumps(session_data, default=str),
            ex=ttl or self._default_ttl * 2,  # Sessions live longer
        )

    async def get_cached_session(self, channel_id: str) -> dict | None:
        """Get cached session state."""
        key = f"session:{channel_id}"
        data = await self._redis.get(key)

        if data:
            return json.loads(data)
        return None

    async def invalidate_session(self, channel_id: str) -> None:
        """Invalidate cached session."""
        key = f"session:{channel_id}"
        await self._redis.delete(key)

    # -------------------------------------------------------------------------
    # Metrics & Counters
    # -------------------------------------------------------------------------

    async def increment_counter(
        self,
        key: str,
        amount: int = 1,
        ttl: int | None = None,
    ) -> int:
        """
        Increment a counter.

        Args:
            key: Counter key.
            amount: Amount to increment.
            ttl: Optional expiration.

        Returns:
            New counter value.
        """
        value = await self._redis.incr(key, amount)
        if ttl:
            await self._redis.expire(key, ttl)
        return value

    async def get_counter(self, key: str) -> int:
        """Get counter value."""
        value = await self._redis.get(key)
        return int(value) if value else 0

    # -------------------------------------------------------------------------
    # Generic Cache Operations
    # -------------------------------------------------------------------------

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """Set a cache value."""
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        await self._redis.set(key, value, ex=ttl or self._default_ttl)

    async def get(self, key: str) -> str | None:
        """Get a cache value."""
        return await self._redis.get(key)

    async def delete(self, key: str) -> None:
        """Delete a cache key."""
        await self._redis.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        return await self._redis.exists(key) > 0

    # -------------------------------------------------------------------------
    # Queue Operations (for RQ integration)
    # -------------------------------------------------------------------------

    async def enqueue(self, queue_name: str, data: dict) -> None:
        """
        Add item to a queue.

        Args:
            queue_name: Name of the queue.
            data: Data to enqueue.
        """
        await self._redis.lpush(queue_name, json.dumps(data, default=str))

    async def dequeue(self, queue_name: str, timeout: int = 0) -> dict | None:
        """
        Get item from queue.

        Args:
            queue_name: Name of the queue.
            timeout: Blocking timeout (0 = no block).

        Returns:
            Dequeued data or None.
        """
        if timeout:
            result = await self._redis.brpop(queue_name, timeout)
            if result:
                return json.loads(result[1])
        else:
            result = await self._redis.rpop(queue_name)
            if result:
                return json.loads(result)
        return None

    async def queue_length(self, queue_name: str) -> int:
        """Get queue length."""
        return await self._redis.llen(queue_name)
