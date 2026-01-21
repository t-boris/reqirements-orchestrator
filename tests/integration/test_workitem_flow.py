"""Integration tests for WorkItem flow (Phase 23.5).

Tests the complete flow:
1. Epic binding -> WorkItem creation
2. WorkItem updates -> Jira sync
3. Readiness detection -> CTA display
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.db.models import WorkItem, WorkItemType, WorkItemStatus
from src.slack.session import SessionIdentity


class TestEpicBindingFlow:
    """Test Epic binding creates WorkItem."""

    @pytest.mark.asyncio
    async def test_bind_epic_creates_workitem(self, identity, mock_slack_client):
        """bind_epic creates a WorkItem linked to the Epic."""
        # Mock WorkItemStore
        mock_store = AsyncMock()
        mock_store.list_by_channel.return_value = []  # No existing items
        mock_store.create.return_value = WorkItem(
            id="wi-123",
            channel_id=identity.channel_id,
            item_type=WorkItemType.STORY,
            status=WorkItemStatus.DRAFT,
            summary="Work from thread (under PROJ-100)",
            description=None,
            facts={},
            jira_key=None,
            jira_sync_at=None,
            jira_fingerprint=None,
            parent_id=None,
            source_thread_ts=identity.thread_ts,
            created_by=identity.user_id,
            created_at=None,
            updated_at=None,
            readiness_score=0.0,
        )
        mock_store.update.return_value = WorkItem(
            id="wi-123",
            channel_id=identity.channel_id,
            item_type=WorkItemType.STORY,
            status=WorkItemStatus.ACTIVE,
            summary="Work from thread (under PROJ-100)",
            description=None,
            facts={},
            jira_key="PROJ-100",
            jira_sync_at=None,
            jira_fingerprint=None,
            parent_id=None,
            source_thread_ts=identity.thread_ts,
            created_by=identity.user_id,
            created_at=None,
            updated_at=None,
            readiness_score=0.0,
        )
        mock_store.get.return_value = mock_store.update.return_value

        # Mock Jira client
        with patch("src.slack.binding.JiraService") as mock_jira_cls:
            mock_jira = AsyncMock()
            mock_jira.get_issue.return_value = MagicMock(summary="Test Epic")
            mock_jira_cls.return_value = mock_jira

            with patch("src.slack.binding.JiraLinker") as mock_linker_cls:
                mock_linker = AsyncMock()
                mock_linker_cls.return_value = mock_linker

                from src.slack.binding import bind_epic

                await bind_epic(identity, "PROJ-100", mock_store, mock_slack_client)

        # Verify WorkItem created
        mock_store.create.assert_called_once()
        call_kwargs = mock_store.create.call_args.kwargs
        assert call_kwargs.get("channel_id") == identity.channel_id
        assert call_kwargs.get("source_thread_ts") == identity.thread_ts

        # Verify WorkItem updated with jira_key
        mock_store.update.assert_called()
        update_kwargs = mock_store.update.call_args.kwargs
        assert update_kwargs.get("jira_key") == "PROJ-100"
        assert update_kwargs.get("status") == WorkItemStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_existing_workitem_updated_on_bind(self, identity, mock_slack_client):
        """bind_epic updates existing WorkItem if thread already has one."""
        existing_item = WorkItem(
            id="wi-existing",
            channel_id=identity.channel_id,
            item_type=WorkItemType.STORY,
            status=WorkItemStatus.DRAFT,
            summary="Existing draft",
            description=None,
            facts={},
            jira_key=None,
            jira_sync_at=None,
            jira_fingerprint=None,
            parent_id=None,
            source_thread_ts=identity.thread_ts,
            created_by=identity.user_id,
            created_at=None,
            updated_at=None,
            readiness_score=0.5,
        )

        mock_store = AsyncMock()
        mock_store.list_by_channel.return_value = [existing_item]
        mock_store.update.return_value = existing_item
        mock_store.get.return_value = existing_item

        with patch("src.slack.binding.JiraService") as mock_jira_cls:
            mock_jira = AsyncMock()
            mock_jira.get_issue.return_value = MagicMock(summary="Test Epic")
            mock_jira_cls.return_value = mock_jira

            with patch("src.slack.binding.JiraLinker") as mock_linker_cls:
                mock_linker = AsyncMock()
                mock_linker_cls.return_value = mock_linker

                from src.slack.binding import bind_epic

                await bind_epic(identity, "PROJ-200", mock_store, mock_slack_client)

        # Verify no new WorkItem created
        mock_store.create.assert_not_called()

        # Verify existing item updated
        mock_store.update.assert_called()
        assert mock_store.update.call_args[0][0] == "wi-existing"


class TestStartBindingFlow:
    """Test start_binding_flow checks for existing WorkItems."""

    @pytest.mark.asyncio
    async def test_shows_selector_when_no_workitem(self, identity, mock_slack_client):
        """start_binding_flow shows Epic selector for new threads."""
        mock_store = AsyncMock()
        mock_store.list_by_channel.return_value = []

        with patch("src.slack.binding.suggest_epics", return_value=[]):
            from src.slack.binding import start_binding_flow

            await start_binding_flow(
                mock_slack_client, identity, "Test message", mock_store
            )

        # Verify selector posted
        mock_slack_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_slack_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["channel"] == identity.channel_id
        assert call_kwargs["thread_ts"] == identity.thread_ts

    @pytest.mark.asyncio
    async def test_shows_card_when_bound_workitem_exists(self, identity, mock_slack_client):
        """start_binding_flow shows session card if WorkItem already bound."""
        bound_item = WorkItem(
            id="wi-bound",
            channel_id=identity.channel_id,
            item_type=WorkItemType.STORY,
            status=WorkItemStatus.ACTIVE,
            summary="Bound item",
            description=None,
            facts={},
            jira_key="PROJ-300",  # Already bound
            jira_sync_at=None,
            jira_fingerprint=None,
            parent_id=None,
            source_thread_ts=identity.thread_ts,
            created_by=identity.user_id,
            created_at=None,
            updated_at=None,
            readiness_score=0.7,
        )

        mock_store = AsyncMock()
        mock_store.list_by_channel.return_value = [bound_item]

        from src.slack.binding import start_binding_flow

        await start_binding_flow(
            mock_slack_client, identity, "Test message", mock_store
        )

        # Verify session card posted (not selector)
        call_kwargs = mock_slack_client.chat_postMessage.call_args.kwargs
        assert "Session active" in call_kwargs["text"]


class TestGetWorkitemForThread:
    """Test helper function."""

    @pytest.mark.asyncio
    async def test_finds_workitem_by_thread(self):
        """get_workitem_for_thread finds matching item."""
        target_item = WorkItem(
            id="wi-target",
            channel_id="C123",
            item_type=WorkItemType.STORY,
            status=WorkItemStatus.DRAFT,
            summary="Target",
            description=None,
            facts={},
            jira_key=None,
            jira_sync_at=None,
            jira_fingerprint=None,
            parent_id=None,
            source_thread_ts="1234567890.111111",
            created_by="U123",
            created_at=None,
            updated_at=None,
            readiness_score=0.0,
        )

        other_item = WorkItem(
            id="wi-other",
            channel_id="C123",
            item_type=WorkItemType.BUG,
            status=WorkItemStatus.ACTIVE,
            summary="Other",
            description=None,
            facts={},
            jira_key="BUG-1",
            jira_sync_at=None,
            jira_fingerprint=None,
            parent_id=None,
            source_thread_ts="1234567890.222222",
            created_by="U123",
            created_at=None,
            updated_at=None,
            readiness_score=0.0,
        )

        mock_store = AsyncMock()
        mock_store.list_by_channel.return_value = [target_item, other_item]

        from src.slack.binding import get_workitem_for_thread

        result = await get_workitem_for_thread(
            mock_store, "C123", "1234567890.111111"
        )

        assert result is not None
        assert result.id == "wi-target"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        """get_workitem_for_thread returns None if no match."""
        mock_store = AsyncMock()
        mock_store.list_by_channel.return_value = []

        from src.slack.binding import get_workitem_for_thread

        result = await get_workitem_for_thread(
            mock_store, "C123", "nonexistent"
        )

        assert result is None
