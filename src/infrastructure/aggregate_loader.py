"""Aggregate loading from event store."""

import logging

from src.domain.channel import ChannelAggregate
from src.domain.types import ChannelId
from src.infrastructure.database import get_pool
from src.infrastructure.event_store import EventStore

logger = logging.getLogger(__name__)


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
    """Persist pending events from an aggregate.

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
    await store.append_batch(events)
    logger.info(f"Persisted {len(events)} events for {aggregate.channel_id}")
    return events
