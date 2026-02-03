"""Event store with PostgreSQL backend and optimistic concurrency.

This module implements the append-only event store that is the foundation
of the event sourcing system. Events are persisted to PostgreSQL with
optimistic concurrency control via the unique (aggregate_id, version) constraint.

Based on:
- maro_2_0.md spec Part 4.4
- 01-RESEARCH.md patterns (outbox pattern, asyncpg)
"""

import json
from typing import Any
from uuid import UUID

import asyncpg

from src.domain.events import DomainEvent
from src.infrastructure.serialization import deserialize_event, serialize_event


class ConcurrencyError(Exception):
    """Raised when optimistic concurrency check fails.

    This occurs when two concurrent writers try to append an event
    with the same version for the same aggregate. The second write
    will fail with this error, and should be retried after reloading
    the aggregate state.
    """

    pass


class EventStore:
    """Append-only event store with optimistic concurrency.

    The event store is the core persistence mechanism for event sourcing.
    All state changes are recorded as immutable events, which can be replayed
    to reconstruct aggregate state.

    Key features:
    - Append-only: Events are never updated or deleted
    - Optimistic concurrency: Version conflicts raise ConcurrencyError
    - Outbox pattern: Events are written to outbox atomically with main store

    Usage:
        pool = await asyncpg.create_pool(database_url)
        store = EventStore(pool)

        # Append an event
        event = WorkItemDrafted(...)
        await store.append(event)

        # Load events for an aggregate
        events = await store.get_events(channel_id)
    """

    def __init__(self, pool: asyncpg.Pool):
        """Initialize the event store.

        Args:
            pool: An asyncpg connection pool
        """
        self.pool = pool

    async def append(self, event: DomainEvent) -> None:
        """Append event to the store.

        This method:
        1. Serializes the event to JSON
        2. Inserts into channel_events table
        3. Inserts into outbox_events for projection processing
        4. Both inserts happen in the same transaction (atomic)

        Raises:
            ConcurrencyError: If version conflict (another writer already used this version)
        """
        payload = json.dumps(serialize_event(event))

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                try:
                    # Insert into main event store
                    await conn.execute(
                        """
                        INSERT INTO channel_events
                        (event_id, event_type, schema_version, aggregate_id, version,
                         actor_id, correlation_id, causation_id, payload)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                        """,
                        UUID(event.event_id),
                        event.event_type,
                        event.schema_version,
                        event.aggregate_id,
                        event.version,
                        event.actor_id,
                        UUID(event.correlation_id) if event.correlation_id else None,
                        UUID(event.causation_id) if event.causation_id else None,
                        payload,
                    )

                    # Also write to outbox for projection processing
                    # This is atomic with the event insert - both succeed or both fail
                    await conn.execute(
                        """
                        INSERT INTO outbox_events
                        (event_id, aggregate_id, event_type, payload, status)
                        VALUES ($1, $2, $3, $4::jsonb, 'pending')
                        """,
                        UUID(event.event_id),
                        event.aggregate_id,
                        event.event_type,
                        payload,
                    )

                except asyncpg.UniqueViolationError:
                    raise ConcurrencyError(
                        f"Version {event.version} already exists for {event.aggregate_id}"
                    )

    async def append_batch(self, events: list[DomainEvent]) -> None:
        """Append multiple events atomically.

        All events are inserted in a single transaction. If any event
        fails (e.g., version conflict), the entire batch is rolled back.

        Args:
            events: List of events to append

        Raises:
            ConcurrencyError: If any version conflict occurs
        """
        if not events:
            return

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for event in events:
                    payload = json.dumps(serialize_event(event))
                    try:
                        await conn.execute(
                            """
                            INSERT INTO channel_events
                            (event_id, event_type, schema_version, aggregate_id, version,
                             actor_id, correlation_id, causation_id, payload)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                            """,
                            UUID(event.event_id),
                            event.event_type,
                            event.schema_version,
                            event.aggregate_id,
                            event.version,
                            event.actor_id,
                            UUID(event.correlation_id) if event.correlation_id else None,
                            UUID(event.causation_id) if event.causation_id else None,
                            payload,
                        )

                        await conn.execute(
                            """
                            INSERT INTO outbox_events
                            (event_id, aggregate_id, event_type, payload, status)
                            VALUES ($1, $2, $3, $4::jsonb, 'pending')
                            """,
                            UUID(event.event_id),
                            event.aggregate_id,
                            event.event_type,
                            payload,
                        )

                    except asyncpg.UniqueViolationError:
                        raise ConcurrencyError(
                            f"Version {event.version} already exists for {event.aggregate_id}"
                        )

    async def get_events(
        self,
        aggregate_id: str,
        after_version: int = 0,
    ) -> list[DomainEvent]:
        """Get all events for an aggregate after a given version.

        Events are returned in version order, suitable for replaying
        to reconstruct aggregate state.

        Args:
            aggregate_id: The aggregate (channel) ID
            after_version: Only return events after this version (default: 0 = all events)

        Returns:
            List of domain events in version order
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload FROM channel_events
                WHERE aggregate_id = $1 AND version > $2
                ORDER BY version ASC
                """,
                aggregate_id,
                after_version,
            )
            return [deserialize_event(dict(row["payload"])) for row in rows]

    async def get_latest_version(self, aggregate_id: str) -> int:
        """Get the current version for an aggregate.

        Returns 0 if no events exist for this aggregate.

        Args:
            aggregate_id: The aggregate (channel) ID

        Returns:
            The latest event version, or 0 if no events
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT COALESCE(MAX(version), 0)
                FROM channel_events
                WHERE aggregate_id = $1
                """,
                aggregate_id,
            )
            return result

    async def get_events_by_type(
        self,
        event_type: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DomainEvent]:
        """Get events of a specific type across all aggregates.

        Useful for projections that need to process all events of a type.

        Args:
            event_type: The event type name (e.g., "WorkItemDrafted")
            limit: Maximum number of events to return
            offset: Number of events to skip

        Returns:
            List of domain events
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload FROM channel_events
                WHERE event_type = $1
                ORDER BY id ASC
                LIMIT $2 OFFSET $3
                """,
                event_type,
                limit,
                offset,
            )
            return [deserialize_event(dict(row["payload"])) for row in rows]
