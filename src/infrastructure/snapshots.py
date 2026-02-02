"""Snapshot store for fast aggregate loading.

Snapshots are periodic captures of aggregate state that allow us to avoid
replaying all events from the beginning. When loading an aggregate, we:
1. Load the latest snapshot (if any)
2. Replay only events after the snapshot version

Based on:
- 01-CONTEXT.md: Snapshot every 500-1000 events or by time for active channels
- 01-RESEARCH.md: Automatic snapshotting patterns
"""

from datetime import datetime
from typing import Any

import asyncpg


class SnapshotStore:
    """Store and retrieve aggregate snapshots.

    Snapshots capture aggregate state at a point in time, reducing the
    number of events that need to be replayed when loading an aggregate.

    Usage:
        pool = await asyncpg.create_pool(database_url)
        store = SnapshotStore(pool, snapshot_interval=500)

        # Save a snapshot
        await store.save_snapshot(channel_id, version=500, state={...})

        # Load a snapshot
        result = await store.get_snapshot(channel_id)
        if result:
            version, state = result
            # Now replay events after this version

        # Check if snapshot needed
        if store.should_snapshot(current_version=550, snapshot_version=0):
            await store.save_snapshot(channel_id, current_version, state)
    """

    def __init__(self, pool: asyncpg.Pool, snapshot_interval: int = 500):
        """Initialize the snapshot store.

        Args:
            pool: An asyncpg connection pool
            snapshot_interval: Number of events between snapshots (default: 500)
        """
        self.pool = pool
        self.snapshot_interval = snapshot_interval

    async def save_snapshot(
        self,
        aggregate_id: str,
        version: int,
        state: dict[str, Any],
    ) -> None:
        """Save or update snapshot for an aggregate.

        Uses upsert (INSERT ... ON CONFLICT UPDATE) to handle both
        initial snapshot and updates.

        Args:
            aggregate_id: The aggregate (channel) ID
            version: The event version this snapshot represents
            state: The serialized aggregate state
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO channel_snapshots (aggregate_id, version, state)
                VALUES ($1, $2, $3)
                ON CONFLICT (aggregate_id) DO UPDATE
                SET version = $2, state = $3, created_at = NOW()
                """,
                aggregate_id,
                version,
                state,
            )

    async def get_snapshot(
        self,
        aggregate_id: str,
    ) -> tuple[int, dict[str, Any]] | None:
        """Get the latest snapshot for an aggregate.

        Args:
            aggregate_id: The aggregate (channel) ID

        Returns:
            Tuple of (version, state) if snapshot exists, None otherwise
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT version, state FROM channel_snapshots
                WHERE aggregate_id = $1
                """,
                aggregate_id,
            )
            if row:
                return row["version"], dict(row["state"])
            return None

    async def delete_snapshot(self, aggregate_id: str) -> bool:
        """Delete a snapshot for an aggregate.

        Useful for testing or when aggregate is deleted.

        Args:
            aggregate_id: The aggregate (channel) ID

        Returns:
            True if a snapshot was deleted, False if none existed
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM channel_snapshots
                WHERE aggregate_id = $1
                """,
                aggregate_id,
            )
            return result == "DELETE 1"

    def should_snapshot(
        self,
        current_version: int,
        snapshot_version: int | None,
    ) -> bool:
        """Determine if we should take a snapshot based on event count.

        The decision is based on the number of events since the last snapshot.
        If no snapshot exists, we snapshot after snapshot_interval events.
        If a snapshot exists, we snapshot when events since snapshot >= interval.

        Args:
            current_version: The current aggregate version
            snapshot_version: The version of the last snapshot, or None if no snapshot

        Returns:
            True if a new snapshot should be taken
        """
        if snapshot_version is None:
            # No snapshot yet - snapshot after interval events
            return current_version >= self.snapshot_interval
        # Snapshot when events since last snapshot >= interval
        return (current_version - snapshot_version) >= self.snapshot_interval

    async def get_all_snapshots(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[str, int, datetime]]:
        """Get metadata about all snapshots.

        Useful for monitoring and debugging snapshot coverage.

        Args:
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of (aggregate_id, version, created_at) tuples
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT aggregate_id, version, created_at
                FROM channel_snapshots
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
            return [(row["aggregate_id"], row["version"], row["created_at"]) for row in rows]

    async def get_stale_aggregates(
        self,
        threshold: int | None = None,
    ) -> list[tuple[str, int, int]]:
        """Find aggregates that need new snapshots.

        Returns aggregates where events since last snapshot exceed threshold.

        Args:
            threshold: Event count threshold (default: snapshot_interval)

        Returns:
            List of (aggregate_id, current_version, snapshot_version) tuples
        """
        if threshold is None:
            threshold = self.snapshot_interval

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH current_versions AS (
                    SELECT aggregate_id, MAX(version) as current_version
                    FROM channel_events
                    GROUP BY aggregate_id
                )
                SELECT
                    cv.aggregate_id,
                    cv.current_version,
                    COALESCE(cs.version, 0) as snapshot_version
                FROM current_versions cv
                LEFT JOIN channel_snapshots cs ON cv.aggregate_id = cs.aggregate_id
                WHERE cv.current_version - COALESCE(cs.version, 0) >= $1
                ORDER BY cv.current_version - COALESCE(cs.version, 0) DESC
                """,
                threshold,
            )
            return [
                (row["aggregate_id"], row["current_version"], row["snapshot_version"])
                for row in rows
            ]
