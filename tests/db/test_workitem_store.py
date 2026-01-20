"""Tests for WorkItemStore CRUD operations."""
import pytest
from datetime import datetime, timezone

from src.db.models import WorkItem, WorkItemType, WorkItemStatus
from src.db.workitem_store import WorkItemStore


class TestWorkItemStore:
    """Test suite for WorkItemStore."""

    @pytest.fixture
    async def store(self, db_connection):
        """Create store with test connection."""
        store = WorkItemStore(db_connection)
        await store.create_tables()
        return store

    @pytest.mark.asyncio
    async def test_create_draft_workitem(self, store):
        """Create a draft work item."""
        item = await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Add retry logic",
            created_by="U456",
        )

        assert item.id is not None
        assert item.channel_id == "C123"
        assert item.item_type == WorkItemType.STORY
        assert item.status == WorkItemStatus.DRAFT
        assert item.summary == "Add retry logic"
        assert item.jira_key is None
        assert item.readiness_score == 0.0

    @pytest.mark.asyncio
    async def test_get_workitem_by_id(self, store):
        """Retrieve work item by ID."""
        created = await store.create(
            channel_id="C123",
            item_type=WorkItemType.BUG,
            summary="Fix null pointer",
            created_by="U456",
        )

        retrieved = await store.get(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.summary == "Fix null pointer"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, store):
        """Getting nonexistent ID returns None."""
        result = await store.get("nonexistent-uuid")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_jira_key(self, store):
        """Retrieve work item by Jira key."""
        item = await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Test story",
            created_by="U456",
        )
        await store.update(item.id, jira_key="PROJ-123")

        retrieved = await store.get_by_jira_key("PROJ-123")

        assert retrieved is not None
        assert retrieved.id == item.id
        assert retrieved.jira_key == "PROJ-123"

    @pytest.mark.asyncio
    async def test_list_by_channel(self, store):
        """List all work items for a channel."""
        await store.create(
            channel_id="C123",
            item_type=WorkItemType.EPIC,
            summary="Epic 1",
            created_by="U456",
        )
        await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Story 1",
            created_by="U456",
        )
        await store.create(
            channel_id="C999",  # Different channel
            item_type=WorkItemType.TASK,
            summary="Task in other channel",
            created_by="U456",
        )

        items = await store.list_by_channel("C123")

        assert len(items) == 2
        summaries = {i.summary for i in items}
        assert "Epic 1" in summaries
        assert "Story 1" in summaries

    @pytest.mark.asyncio
    async def test_list_by_channel_with_status_filter(self, store):
        """Filter by status when listing."""
        item1 = await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Draft story",
            created_by="U456",
        )
        item2 = await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Active story",
            created_by="U456",
        )
        await store.update(item2.id, status=WorkItemStatus.ACTIVE)

        drafts = await store.list_by_channel("C123", status=WorkItemStatus.DRAFT)
        active = await store.list_by_channel("C123", status=WorkItemStatus.ACTIVE)

        assert len(drafts) == 1
        assert drafts[0].summary == "Draft story"
        assert len(active) == 1
        assert active[0].summary == "Active story"

    @pytest.mark.asyncio
    async def test_list_by_channel_with_type_filter(self, store):
        """Filter by item type when listing."""
        await store.create(
            channel_id="C123",
            item_type=WorkItemType.EPIC,
            summary="An epic",
            created_by="U456",
        )
        await store.create(
            channel_id="C123",
            item_type=WorkItemType.BUG,
            summary="A bug",
            created_by="U456",
        )

        epics = await store.list_by_channel("C123", item_type=WorkItemType.EPIC)

        assert len(epics) == 1
        assert epics[0].item_type == WorkItemType.EPIC

    @pytest.mark.asyncio
    async def test_update_workitem(self, store):
        """Update work item fields."""
        item = await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Original",
            created_by="U456",
        )

        updated = await store.update(
            item.id,
            summary="Updated summary",
            description="New description",
            status=WorkItemStatus.ACTIVE,
            readiness_score=0.8,
        )

        assert updated.summary == "Updated summary"
        assert updated.description == "New description"
        assert updated.status == WorkItemStatus.ACTIVE
        assert updated.readiness_score == 0.8
        assert updated.updated_at > item.updated_at

    @pytest.mark.asyncio
    async def test_update_jira_fields(self, store):
        """Update Jira sync fields."""
        item = await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Test",
            created_by="U456",
        )

        fingerprint = {"problem": "abc123", "ac": "def456"}
        updated = await store.update(
            item.id,
            jira_key="PROJ-100",
            jira_fingerprint=fingerprint,
        )

        assert updated.jira_key == "PROJ-100"
        assert updated.jira_fingerprint == fingerprint
        assert updated.jira_sync_at is not None

    @pytest.mark.asyncio
    async def test_delete_workitem(self, store):
        """Delete a work item."""
        item = await store.create(
            channel_id="C123",
            item_type=WorkItemType.TASK,
            summary="To be deleted",
            created_by="U456",
        )

        result = await store.delete(item.id)
        assert result is True

        retrieved = await store.get(item.id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, store):
        """Deleting nonexistent item returns False."""
        result = await store.delete("nonexistent-uuid")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_children(self, store):
        """Get child work items (stories under epic)."""
        epic = await store.create(
            channel_id="C123",
            item_type=WorkItemType.EPIC,
            summary="Parent Epic",
            created_by="U456",
        )
        await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Child Story 1",
            created_by="U456",
            parent_id=epic.id,
        )
        await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Child Story 2",
            created_by="U456",
            parent_id=epic.id,
        )
        await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Orphan Story",
            created_by="U456",
        )

        children = await store.get_children(epic.id)

        assert len(children) == 2
        summaries = {c.summary for c in children}
        assert "Child Story 1" in summaries
        assert "Child Story 2" in summaries

    @pytest.mark.asyncio
    async def test_create_with_all_fields(self, store):
        """Create work item with all optional fields."""
        item = await store.create(
            channel_id="C123",
            item_type=WorkItemType.SPIKE,
            summary="Research caching",
            created_by="U456",
            description="Investigate Redis vs Memcached",
            parent_id=None,
            source_thread_ts="1234567890.123456",
        )

        assert item.description == "Investigate Redis vs Memcached"
        assert item.source_thread_ts == "1234567890.123456"

    @pytest.mark.asyncio
    async def test_update_facts(self, store):
        """Update facts dictionary."""
        item = await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Test",
            created_by="U456",
        )

        facts = {
            "constraint": "Must use existing auth",
            "decision": "Approved JWT approach",
        }
        updated = await store.update(item.id, facts=facts)

        assert updated.facts == facts

    @pytest.mark.asyncio
    async def test_calculate_readiness_minimal(self, store):
        """Minimal item has low readiness."""
        item = await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Just a title",
            created_by="U456",
        )

        score = store.calculate_readiness(item)

        assert score == 0.2  # Only summary

    @pytest.mark.asyncio
    async def test_calculate_readiness_complete(self, store):
        """Fully populated item has high readiness."""
        epic = await store.create(
            channel_id="C123",
            item_type=WorkItemType.EPIC,
            summary="Parent",
            created_by="U456",
        )
        item = await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Complete story",
            created_by="U456",
            description="Full description here",
            parent_id=epic.id,
            source_thread_ts="1234567890.123456",
        )
        await store.update(item.id, facts={"constraint": "must use auth"})
        item = await store.get(item.id)

        score = store.calculate_readiness(item)

        assert score == 1.0  # All components present

    @pytest.mark.asyncio
    async def test_refresh_readiness(self, store):
        """Refresh readiness persists new score."""
        item = await store.create(
            channel_id="C123",
            item_type=WorkItemType.STORY,
            summary="Test",
            created_by="U456",
        )
        assert item.readiness_score == 0.0

        updated = await store.refresh_readiness(item.id)

        assert updated.readiness_score == 0.2  # Just summary

    @pytest.mark.asyncio
    async def test_readiness_epic_gets_hierarchy_points(self, store):
        """Epics get hierarchy points without parent."""
        item = await store.create(
            channel_id="C123",
            item_type=WorkItemType.EPIC,
            summary="Top-level Epic",
            created_by="U456",
        )

        score = store.calculate_readiness(item)

        assert score >= 0.4  # summary + hierarchy
