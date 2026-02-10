"""Aggregate loading from event store with inline outbox processing.

After persisting events, processes the outbox to apply projections
(entity read model updates, Jira notifications, etc.) inline rather
than requiring a separate background worker.
"""

import logging

from src.domain.channel import ChannelAggregate
from src.domain.types import ChannelId
from src.infrastructure.database import get_pool
from src.infrastructure.event_store import ConcurrencyError, EventStore

logger = logging.getLogger(__name__)

# Maximum retries for optimistic concurrency conflicts
MAX_CONCURRENCY_RETRIES = 3


async def load_aggregate(channel_id: str) -> ChannelAggregate:
    """Load a ChannelAggregate by replaying events from the store.

    Args:
        channel_id: Slack channel ID

    Returns:
        ChannelAggregate with state rebuilt from events
    """
    pool = await get_pool()
    store = EventStore(pool)
    events = await store.get_events(channel_id)
    aggregate = ChannelAggregate.from_events(ChannelId(channel_id), events)
    logger.debug(
        f"Loaded aggregate for {channel_id}: "
        f"{len(aggregate.entities)} entities, version {aggregate.version}"
    )
    return aggregate


async def save_events(aggregate: ChannelAggregate) -> list:
    """Persist pending events and process outbox projections inline.

    After appending events to the store (and outbox), processes pending
    outbox entries through all registered projections. This ensures
    read models and side effects (e.g., Jira notifications) are applied
    without requiring a separate background outbox worker.

    Handles optimistic concurrency conflicts by rebasing events onto
    the latest version and retrying (up to MAX_CONCURRENCY_RETRIES times).

    Args:
        aggregate: Aggregate with pending events

    Returns:
        List of persisted events
    """
    events = aggregate.clear_pending_events()
    if not events:
        return []

    pool = await get_pool()
    store = EventStore(pool)

    for attempt in range(MAX_CONCURRENCY_RETRIES):
        try:
            await store.append_batch(events)
            logger.info(f"Persisted {len(events)} events for {aggregate.channel_id}")

            # Process outbox inline — applies projections for newly persisted events
            await _process_outbox(pool)
            return events

        except ConcurrencyError as e:
            if attempt >= MAX_CONCURRENCY_RETRIES - 1:
                logger.error(
                    f"Concurrency conflict for {aggregate.channel_id} after "
                    f"{MAX_CONCURRENCY_RETRIES} retries: {e}"
                )
                raise

            # Rebase events onto new version
            logger.warning(
                f"Concurrency conflict for {aggregate.channel_id}, "
                f"rebasing events (attempt {attempt + 1}/{MAX_CONCURRENCY_RETRIES})"
            )
            latest_version = await store.get_latest_version(str(aggregate.channel_id))
            events = _rebase_events(events, latest_version)

    return events


def _rebase_events(events: list, new_base_version: int) -> list:
    """Rebase event versions onto a new base version.

    Used when optimistic concurrency fails - adjusts event versions
    to continue from the current store version.

    Args:
        events: List of events with stale versions
        new_base_version: Current version in the store

    Returns:
        Events with updated version numbers
    """
    for i, event in enumerate(events):
        event.version = new_base_version + i + 1
    return events


async def _process_outbox(pool) -> None:
    """Process pending outbox events through all registered projections.

    Runs EntityProjection (read model) and JiraNotificationProjection
    (async Jira side effects) against any pending outbox entries.

    Errors in projection processing are logged but do not propagate —
    the outbox processor handles retries on subsequent calls.
    """
    try:
        from src.infrastructure.projections import EntityProjection, JiraNotificationProjection
        from src.infrastructure.outbox import OutboxProcessor

        projections = [
            EntityProjection(pool),
            JiraNotificationProjection(pool),
        ]
        processor = OutboxProcessor(pool, projections)
        processed = await processor.process_all()
        if processed > 0:
            logger.debug(f"Outbox: processed {processed} events")
    except Exception as e:
        # Outbox processing failure must not break the save flow.
        # Events are safely persisted; projections will catch up on next call.
        logger.warning(f"Outbox processing failed (events are persisted, will retry): {e}")
