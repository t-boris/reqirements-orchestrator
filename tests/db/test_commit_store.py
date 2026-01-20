"""Tests for CommitStore operations."""
import pytest

from src.db.models import CommitType, CommitEntry
from src.db.commit_store import CommitStore


class TestCommitStore:
    """Test suite for CommitStore."""

    @pytest.fixture
    async def store(self, db_connection):
        """Create store with test connection."""
        store = CommitStore(db_connection)
        await store.create_tables()
        return store

    @pytest.mark.asyncio
    async def test_create_commit(self, store):
        """create() creates a new commit entry."""
        entry = await store.create(
            channel_id="C123",
            commit_type=CommitType.DECISION,
            summary="Use background worker",
            user_id="U456",
        )

        assert entry.channel_id == "C123"
        assert entry.commit_type == CommitType.DECISION
        assert entry.summary == "Use background worker"
        assert entry.committed_by == "U456"
        assert entry.id is not None
        assert entry.committed_at is not None

    @pytest.mark.asyncio
    async def test_create_commit_with_workitem(self, store):
        """create() stores workitem_id when provided."""
        entry = await store.create(
            channel_id="C123",
            commit_type=CommitType.WORKITEM_CREATED,
            summary="Created STORY: Retry mechanism",
            user_id="U456",
            workitem_id="work-item-uuid",
        )

        assert entry.workitem_id == "work-item-uuid"
        assert entry.commit_type == CommitType.WORKITEM_CREATED

    @pytest.mark.asyncio
    async def test_create_commit_with_thread(self, store):
        """create() stores thread_ts when provided."""
        entry = await store.create(
            channel_id="C123",
            commit_type=CommitType.DECISION,
            summary="Architecture decision",
            user_id="U456",
            thread_ts="1234567890.123456",
        )

        assert entry.thread_ts == "1234567890.123456"

    @pytest.mark.asyncio
    async def test_get_commit(self, store):
        """get() retrieves commit by ID."""
        created = await store.create(
            channel_id="C123",
            commit_type=CommitType.CONSTRAINT_ADDED,
            summary="Must use OAuth",
            user_id="U456",
        )

        retrieved = await store.get(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.summary == "Must use OAuth"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, store):
        """get() returns None for nonexistent ID."""
        result = await store.get("nonexistent-uuid")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_recent(self, store):
        """list_recent() returns commits newest first."""
        # Create multiple commits
        await store.create("C123", CommitType.DECISION, "First", "U456")
        await store.create("C123", CommitType.DECISION, "Second", "U456")
        await store.create("C123", CommitType.DECISION, "Third", "U456")

        results = await store.list_recent("C123", limit=10)

        assert len(results) == 3
        # Newest first
        assert results[0].summary == "Third"
        assert results[1].summary == "Second"
        assert results[2].summary == "First"

    @pytest.mark.asyncio
    async def test_list_recent_respects_limit(self, store):
        """list_recent() respects limit parameter."""
        for i in range(5):
            await store.create("C123", CommitType.DECISION, f"Commit {i}", "U456")

        results = await store.list_recent("C123", limit=2)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_list_recent_filters_by_channel(self, store):
        """list_recent() only returns commits for specified channel."""
        await store.create("C123", CommitType.DECISION, "Channel 1", "U456")
        await store.create("C456", CommitType.DECISION, "Channel 2", "U456")

        results = await store.list_recent("C123")

        assert len(results) == 1
        assert results[0].summary == "Channel 1"

    @pytest.mark.asyncio
    async def test_list_recent_empty_channel(self, store):
        """list_recent() returns empty list for channel with no commits."""
        results = await store.list_recent("C_EMPTY")
        assert results == []

    @pytest.mark.asyncio
    async def test_count_by_channel(self, store):
        """count_by_channel() returns correct count."""
        await store.create("C123", CommitType.DECISION, "One", "U456")
        await store.create("C123", CommitType.DECISION, "Two", "U456")
        await store.create("C456", CommitType.DECISION, "Other", "U456")

        count = await store.count_by_channel("C123")

        assert count == 2

    @pytest.mark.asyncio
    async def test_count_by_channel_empty(self, store):
        """count_by_channel() returns 0 for empty channel."""
        count = await store.count_by_channel("C_EMPTY")
        assert count == 0

    @pytest.mark.asyncio
    async def test_all_commit_types(self, store):
        """All CommitType values can be stored and retrieved."""
        for commit_type in CommitType:
            entry = await store.create(
                channel_id="C123",
                commit_type=commit_type,
                summary=f"Test {commit_type.value}",
                user_id="U456",
            )
            assert entry.commit_type == commit_type

        # Verify all were stored
        count = await store.count_by_channel("C123")
        assert count == len(CommitType)
