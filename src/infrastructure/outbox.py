"""Outbox processor for reliable projection updates.

This module implements the outbox pattern for processing events and applying
them to projections. Events are written to the outbox atomically with the
main event store, then processed asynchronously by this processor.

Based on:
- maro_2_0.md spec Part 4.5
- 01-RESEARCH.md outbox pattern

Key features:
- Batch processing for efficiency
- FOR UPDATE SKIP LOCKED for safe concurrent processing
- Error handling with retry capability
- Continuous processing mode for background operation
"""

import asyncio
import logging
from datetime import datetime

import asyncpg

from src.infrastructure.projections import Projection
from src.infrastructure.serialization import deserialize_event


logger = logging.getLogger(__name__)


class OutboxProcessor:
    """Process outbox events and apply to projections.

    The outbox processor reads pending events from the outbox_events table
    and applies them to registered projections. It uses FOR UPDATE SKIP LOCKED
    to allow concurrent processors without conflicts.

    Usage:
        pool = await asyncpg.create_pool(database_url)
        projection = EntityProjection(pool)
        processor = OutboxProcessor(pool, [projection])

        # Process a batch
        count = await processor.process_pending()

        # Or run continuously
        await processor.run_continuously()
    """

    def __init__(self, pool: asyncpg.Pool, projections: list[Projection]):
        """Initialize the outbox processor.

        Args:
            pool: An asyncpg connection pool
            projections: List of projections to update
        """
        self.pool = pool
        self.projections = projections
        self._projection_handlers: dict[str, list[Projection]] = {}
        self._build_handler_map()
        self._running = False

    def _build_handler_map(self) -> None:
        """Build event_type -> projections map.

        Creates a lookup table from event types to the projections
        that handle them, for efficient dispatch during processing.
        """
        for projection in self.projections:
            for event_type in projection.handles():
                if event_type not in self._projection_handlers:
                    self._projection_handlers[event_type] = []
                self._projection_handlers[event_type].append(projection)

    async def process_pending(self, batch_size: int = 100) -> int:
        """Process pending outbox events.

        Fetches a batch of unprocessed events from the outbox and applies
        them to all relevant projections. Uses FOR UPDATE SKIP LOCKED to
        allow concurrent processors to work on different events.

        Args:
            batch_size: Maximum number of events to process in this batch

        Returns:
            Number of events processed
        """
        async with self.pool.acquire() as conn:
            # Get pending events (oldest first) with row-level lock
            # FOR UPDATE SKIP LOCKED allows concurrent processors
            rows = await conn.fetch(
                """
                SELECT id, event_id, event_type, payload
                FROM outbox_events
                WHERE processed_at IS NULL
                ORDER BY id ASC
                LIMIT $1
                FOR UPDATE SKIP LOCKED
                """,
                batch_size,
            )

            if not rows:
                return 0

            processed = 0
            for row in rows:
                event_type = row["event_type"]
                handlers = self._projection_handlers.get(event_type, [])

                if handlers:
                    try:
                        event = deserialize_event(dict(row["payload"]))
                        for projection in handlers:
                            await projection.apply(event)
                    except Exception as e:
                        # Log error but continue with other events
                        logger.error(
                            f"Error processing event {row['event_id']}: {e}",
                            exc_info=True,
                        )
                        # Update retry count
                        await conn.execute(
                            """
                            UPDATE outbox_events
                            SET retries = retries + 1
                            WHERE id = $1
                            """,
                            row["id"],
                        )
                        continue

                # Mark as processed
                await conn.execute(
                    """
                    UPDATE outbox_events
                    SET processed_at = $1, status = 'processed'
                    WHERE id = $2
                    """,
                    datetime.utcnow(),
                    row["id"],
                )
                processed += 1

            return processed

    async def process_all(self, batch_size: int = 100) -> int:
        """Process all pending events.

        Repeatedly calls process_pending until no more events remain.

        Args:
            batch_size: Batch size for each iteration

        Returns:
            Total number of events processed
        """
        total = 0
        while True:
            count = await self.process_pending(batch_size)
            if count == 0:
                break
            total += count
        return total

    async def run_continuously(self, interval_ms: int = 100) -> None:
        """Run processor continuously (for background task).

        Polls for new events at the specified interval. Backs off on errors
        to avoid tight loops during outages.

        Args:
            interval_ms: Polling interval in milliseconds when no events
        """
        self._running = True
        while self._running:
            try:
                count = await self.process_pending()
                if count == 0:
                    # No events, wait before polling again
                    await asyncio.sleep(interval_ms / 1000)
            except asyncio.CancelledError:
                # Graceful shutdown
                self._running = False
                break
            except Exception as e:
                # Log error and back off
                logger.error(f"Error in outbox processor: {e}", exc_info=True)
                await asyncio.sleep(1)  # Back off on error

    def stop(self) -> None:
        """Signal the processor to stop.

        Called to gracefully stop the continuous processor.
        """
        self._running = False

    async def get_stats(self) -> dict:
        """Get outbox processing statistics.

        Returns:
            Dict with pending, processed, and failed counts
        """
        async with self.pool.acquire() as conn:
            pending = await conn.fetchval(
                """
                SELECT COUNT(*) FROM outbox_events
                WHERE processed_at IS NULL
                """
            )
            processed = await conn.fetchval(
                """
                SELECT COUNT(*) FROM outbox_events
                WHERE processed_at IS NOT NULL AND status = 'processed'
                """
            )
            failed = await conn.fetchval(
                """
                SELECT COUNT(*) FROM outbox_events
                WHERE retries > 0 AND processed_at IS NULL
                """
            )
            return {
                "pending": pending,
                "processed": processed,
                "failed": failed,
            }
