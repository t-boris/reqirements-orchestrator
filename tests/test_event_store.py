"""Integration tests for event store and projection flow.

These tests validate the complete event sourcing pipeline:
event -> store -> outbox -> projection -> query

Requirements:
- PostgreSQL database for testing
- Set TEST_DATABASE_URL environment variable or use default:
  postgresql://maro:maro@localhost/maro_test

Setup:
1. Create test database: createdb maro_test
2. Run migrations: alembic upgrade head
3. Run tests: pytest tests/test_event_store.py -v

Note: These are integration tests that require a real database.
For unit tests, see test_domain.py (future).
"""

import os
from uuid import uuid4

import pytest
import pytest_asyncio

try:
    import asyncpg
except ImportError:
    pytest.skip("asyncpg not available", allow_module_level=True)

from src.domain.content import IssueType, WorkItemContent
from src.domain.events import WorkItemDrafted
from src.domain.types import ChannelId, EntityId, ThreadTs, UserId
from src.infrastructure.event_store import ConcurrencyError, EventStore
from src.infrastructure.outbox import OutboxProcessor
from src.infrastructure.projections import EntityProjection


# =============================================================================
# Fixtures
# =============================================================================


@pytest_asyncio.fixture
async def pool():
    """Create test database pool.

    Uses TEST_DATABASE_URL environment variable or defaults to local test DB.
    """
    dsn = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://maro:maro@localhost/maro_test",
    )
    try:
        pool = await asyncpg.create_pool(dsn=dsn)
    except Exception as e:
        pytest.skip(f"Database not available: {e}")
        return

    yield pool

    await pool.close()


@pytest_asyncio.fixture
async def clean_tables(pool):
    """Clean test tables before each test.

    Removes all data from event-related tables to ensure test isolation.
    """
    async with pool.acquire() as conn:
        # Clean in order to respect foreign key constraints (if any)
        await conn.execute("TRUNCATE outbox_events RESTART IDENTITY CASCADE")
        await conn.execute("TRUNCATE channel_events RESTART IDENTITY CASCADE")
        await conn.execute("TRUNCATE entities_view CASCADE")
        await conn.execute("TRUNCATE projection_positions CASCADE")
    yield


# =============================================================================
# Event Store Tests
# =============================================================================


@pytest.mark.asyncio
async def test_event_store_append_and_read(pool, clean_tables):
    """Test basic append and read operations.

    Verifies that events can be written to the store and retrieved
    in version order.
    """
    store = EventStore(pool)
    channel_id = ChannelId(f"C{uuid4().hex[:8]}")

    event = WorkItemDrafted(
        aggregate_id=channel_id,
        actor_id=UserId("U123"),
        version=1,
        entity_id=EntityId.generate(),
        thread_ts=ThreadTs("1234567890.123456"),
        content=WorkItemContent(
            issue_type=IssueType.STORY,
            title="Test Story",
            acceptance_criteria=["AC1"],
        ),
    )

    await store.append(event)
    events = await store.get_events(channel_id)

    assert len(events) == 1
    assert events[0].entity_id == event.entity_id
    assert events[0].version == 1


@pytest.mark.asyncio
async def test_event_store_multiple_events(pool, clean_tables):
    """Test appending and reading multiple events."""
    store = EventStore(pool)
    channel_id = ChannelId(f"C{uuid4().hex[:8]}")

    # Append multiple events
    for i in range(3):
        event = WorkItemDrafted(
            aggregate_id=channel_id,
            actor_id=UserId("U123"),
            version=i + 1,
            entity_id=EntityId.generate(),
            thread_ts=ThreadTs(f"1234567890.12345{i}"),
            content=WorkItemContent(
                issue_type=IssueType.TASK,
                title=f"Task {i + 1}",
            ),
        )
        await store.append(event)

    events = await store.get_events(channel_id)
    assert len(events) == 3
    # Verify version order
    assert [e.version for e in events] == [1, 2, 3]


@pytest.mark.asyncio
async def test_concurrency_error_on_duplicate_version(pool, clean_tables):
    """Test optimistic concurrency control.

    Attempting to append an event with a version that already exists
    should raise ConcurrencyError.
    """
    store = EventStore(pool)
    channel_id = ChannelId(f"C{uuid4().hex[:8]}")

    event1 = WorkItemDrafted(
        aggregate_id=channel_id,
        actor_id=UserId("U123"),
        version=1,
        entity_id=EntityId.generate(),
        thread_ts=ThreadTs("1234567890.123456"),
        content=WorkItemContent(issue_type=IssueType.TASK, title="Task 1"),
    )
    await store.append(event1)

    # Same version should fail
    event2 = WorkItemDrafted(
        aggregate_id=channel_id,
        actor_id=UserId("U123"),
        version=1,  # Duplicate version!
        entity_id=EntityId.generate(),
        thread_ts=ThreadTs("1234567890.123457"),
        content=WorkItemContent(issue_type=IssueType.TASK, title="Task 2"),
    )

    with pytest.raises(ConcurrencyError):
        await store.append(event2)


@pytest.mark.asyncio
async def test_get_events_after_version(pool, clean_tables):
    """Test filtering events after a specific version."""
    store = EventStore(pool)
    channel_id = ChannelId(f"C{uuid4().hex[:8]}")

    # Append 5 events
    for i in range(5):
        event = WorkItemDrafted(
            aggregate_id=channel_id,
            actor_id=UserId("U123"),
            version=i + 1,
            entity_id=EntityId.generate(),
            thread_ts=ThreadTs(f"1234567890.12345{i}"),
            content=WorkItemContent(
                issue_type=IssueType.TASK,
                title=f"Task {i + 1}",
            ),
        )
        await store.append(event)

    # Get events after version 2
    events = await store.get_events(channel_id, after_version=2)
    assert len(events) == 3
    assert [e.version for e in events] == [3, 4, 5]


@pytest.mark.asyncio
async def test_get_latest_version(pool, clean_tables):
    """Test getting the latest version for an aggregate."""
    store = EventStore(pool)
    channel_id = ChannelId(f"C{uuid4().hex[:8]}")

    # No events yet
    version = await store.get_latest_version(channel_id)
    assert version == 0

    # Add some events
    for i in range(3):
        event = WorkItemDrafted(
            aggregate_id=channel_id,
            actor_id=UserId("U123"),
            version=i + 1,
            entity_id=EntityId.generate(),
            thread_ts=ThreadTs(f"1234567890.12345{i}"),
            content=WorkItemContent(
                issue_type=IssueType.TASK,
                title=f"Task {i + 1}",
            ),
        )
        await store.append(event)

    version = await store.get_latest_version(channel_id)
    assert version == 3


# =============================================================================
# Outbox and Projection Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_outbox_projection_flow(pool, clean_tables):
    """Test event -> outbox -> projection flow.

    This is the core integration test that validates the complete
    event sourcing pipeline:
    1. Event is appended to store
    2. Event is written to outbox (atomically)
    3. Outbox processor reads event
    4. Projection is updated
    5. Query returns projected data
    """
    store = EventStore(pool)
    projection = EntityProjection(pool)
    processor = OutboxProcessor(pool, [projection])

    channel_id = ChannelId(f"C{uuid4().hex[:8]}")
    entity_id = EntityId.generate()

    event = WorkItemDrafted(
        aggregate_id=channel_id,
        actor_id=UserId("U123"),
        version=1,
        entity_id=entity_id,
        thread_ts=ThreadTs("1234567890.123456"),
        content=WorkItemContent(
            issue_type=IssueType.STORY,
            title="Integration Test Story",
            acceptance_criteria=["Test AC"],
        ),
    )

    # Step 1 & 2: Append event (writes to both store and outbox atomically)
    await store.append(event)

    # Step 3 & 4: Process outbox (applies to projection)
    count = await processor.process_pending()
    assert count == 1

    # Step 5: Verify projection
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM entities_view WHERE id = $1",
            str(entity_id),
        )
        assert row is not None
        assert row["lifecycle"] == "draft"
        assert row["entity_type"] == "work_item"
        assert row["channel_id"] == channel_id
        assert row["content"]["title"] == "Integration Test Story"
        assert row["content"]["issue_type"] == "story"


@pytest.mark.asyncio
async def test_outbox_idempotency(pool, clean_tables):
    """Test that projection is idempotent.

    Replaying the same event should not corrupt the projection.
    """
    projection = EntityProjection(pool)
    channel_id = ChannelId(f"C{uuid4().hex[:8]}")
    entity_id = EntityId.generate()

    event = WorkItemDrafted(
        aggregate_id=channel_id,
        actor_id=UserId("U123"),
        version=1,
        entity_id=entity_id,
        thread_ts=ThreadTs("1234567890.123456"),
        content=WorkItemContent(
            issue_type=IssueType.TASK,
            title="Idempotency Test",
        ),
    )

    # Apply the same event twice
    await projection.apply(event)
    await projection.apply(event)

    # Should still have only one entity
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM entities_view WHERE id = $1",
            str(entity_id),
        )
        assert count == 1

        row = await conn.fetchrow(
            "SELECT * FROM entities_view WHERE id = $1",
            str(entity_id),
        )
        assert row["content"]["title"] == "Idempotency Test"


@pytest.mark.asyncio
async def test_outbox_batch_processing(pool, clean_tables):
    """Test batch processing of multiple events."""
    store = EventStore(pool)
    projection = EntityProjection(pool)
    processor = OutboxProcessor(pool, [projection])

    channel_id = ChannelId(f"C{uuid4().hex[:8]}")

    # Append multiple events
    entity_ids = []
    for i in range(5):
        entity_id = EntityId.generate()
        entity_ids.append(entity_id)
        event = WorkItemDrafted(
            aggregate_id=channel_id,
            actor_id=UserId("U123"),
            version=i + 1,
            entity_id=entity_id,
            thread_ts=ThreadTs(f"1234567890.12345{i}"),
            content=WorkItemContent(
                issue_type=IssueType.TASK,
                title=f"Batch Task {i + 1}",
            ),
        )
        await store.append(event)

    # Process all at once
    count = await processor.process_all()
    assert count == 5

    # Verify all entities projected
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM entities_view WHERE channel_id = $1",
            channel_id,
        )
        assert count == 5


@pytest.mark.asyncio
async def test_outbox_stats(pool, clean_tables):
    """Test outbox statistics."""
    store = EventStore(pool)
    projection = EntityProjection(pool)
    processor = OutboxProcessor(pool, [projection])

    channel_id = ChannelId(f"C{uuid4().hex[:8]}")

    # Add some events
    for i in range(3):
        event = WorkItemDrafted(
            aggregate_id=channel_id,
            actor_id=UserId("U123"),
            version=i + 1,
            entity_id=EntityId.generate(),
            thread_ts=ThreadTs(f"1234567890.12345{i}"),
            content=WorkItemContent(
                issue_type=IssueType.TASK,
                title=f"Stats Task {i + 1}",
            ),
        )
        await store.append(event)

    # Check stats before processing
    stats = await processor.get_stats()
    assert stats["pending"] == 3
    assert stats["processed"] == 0

    # Process and check again
    await processor.process_all()
    stats = await processor.get_stats()
    assert stats["pending"] == 0
    assert stats["processed"] == 3
