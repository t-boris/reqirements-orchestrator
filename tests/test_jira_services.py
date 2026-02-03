"""Jira service unit tests.

Tests for PreflightService and JiraSyncService with mocked JiraClient.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.domain.content import (
    Attribution,
    DecisionContent,
    DecisionType,
    IssueType,
    WorkItemContent,
)
from src.domain.entities import ApprovedEntity, CommittedEntity
from src.domain.types import ChannelId, EntityId, JiraKey, SyncStatus, ThreadTs, UserId, Version
from src.domain.content import JiraLink
from src.jira.models import (
    FieldOwnership,
    PreflightResult,
)
from src.jira.preflight import PreflightService
from src.jira.sync_service import (
    DuplicateDetectedError,
    JiraSyncService,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_jira_client():
    """Create a mock JiraClient."""
    client = MagicMock()
    # Default async methods
    client.search_duplicates = AsyncMock(return_value=[])
    client.get_issue = AsyncMock(return_value={"fields": {}})
    client.create_issue = AsyncMock(return_value="PROJ-999")
    client.add_comment = AsyncMock()
    return client


@pytest.fixture
def preflight_service(mock_jira_client):
    """Create PreflightService with mock client."""
    return PreflightService(jira=mock_jira_client)


@pytest.fixture
def sync_service(mock_jira_client, preflight_service):
    """Create JiraSyncService with mock client and preflight."""
    return JiraSyncService(jira=mock_jira_client, preflight=preflight_service)


@pytest.fixture
def approved_work_item():
    """Create an approved work item entity."""
    return ApprovedEntity(
        id=EntityId.generate(),
        entity_type="work_item",
        channel_id=ChannelId("C12345678"),
        thread_ts=ThreadTs("1234567890.123456"),
        content=WorkItemContent(
            issue_type=IssueType.STORY,
            title="Test Story",
            description="Test description",
            acceptance_criteria=["AC1", "AC2"],
        ),
        attribution=Attribution(
            proposed_by=UserId("U12345678"),
            proposed_at=datetime.utcnow(),
            approved_by=UserId("U_APPROVER"),
            approved_at=datetime.utcnow(),
        ),
        version=Version(3),
        canonical_message_ts="1234567890.999999",
    )


@pytest.fixture
def approved_decision():
    """Create an approved decision entity."""
    return ApprovedEntity(
        id=EntityId.generate(),
        entity_type="decision",
        channel_id=ChannelId("C12345678"),
        thread_ts=ThreadTs("1234567890.123456"),
        content=DecisionContent(
            decision_type=DecisionType.ARCHITECTURE,
            title="Use PostgreSQL",
            description="We will use PostgreSQL for event storage",
            rationale="Better support for JSONB and LISTEN/NOTIFY",
        ),
        attribution=Attribution(
            proposed_by=UserId("U12345678"),
            proposed_at=datetime.utcnow(),
            approved_by=UserId("U_APPROVER"),
            approved_at=datetime.utcnow(),
        ),
        version=Version(3),
        canonical_message_ts="1234567890.999999",
    )


@pytest.fixture
def committed_work_item(approved_work_item):
    """Create a committed work item entity."""
    return CommittedEntity(
        id=approved_work_item.id,
        entity_type=approved_work_item.entity_type,
        channel_id=approved_work_item.channel_id,
        thread_ts=approved_work_item.thread_ts,
        content=approved_work_item.content,
        attribution=approved_work_item.attribution,
        version=Version(4),
        canonical_message_ts=approved_work_item.canonical_message_ts,
        jira_link=JiraLink(
            jira_key=JiraKey("PROJ-100"),
            synced_version=Version(4),
            synced_at=datetime.utcnow(),
            sync_status=SyncStatus.SYNCED,
        ),
    )


# =============================================================================
# PreflightService Tests
# =============================================================================


class TestPreflightServiceCreate:
    """Tests for PreflightService.check_create."""

    @pytest.mark.asyncio
    async def test_check_create_no_duplicates(self, preflight_service, mock_jira_client):
        """Test check_create returns OK when no duplicates found."""
        mock_jira_client.search_duplicates.return_value = []

        result = await preflight_service.check_create(
            project_key="PROJ",
            summary="Brand new feature",
        )

        assert result.result == PreflightResult.OK
        assert "No duplicates found" in result.details
        mock_jira_client.search_duplicates.assert_called_once_with("PROJ", "Brand new feature")

    @pytest.mark.asyncio
    async def test_check_create_with_duplicates(self, preflight_service, mock_jira_client):
        """Test check_create returns DUPLICATE when duplicates found."""
        mock_jira_client.search_duplicates.return_value = ["PROJ-100", "PROJ-101"]

        result = await preflight_service.check_create(
            project_key="PROJ",
            summary="Existing feature",
        )

        assert result.result == PreflightResult.DUPLICATE
        assert "2 potential duplicate" in result.details
        assert result.duplicate_keys == ("PROJ-100", "PROJ-101")


class TestPreflightServiceUpdate:
    """Tests for PreflightService.check_update."""

    @pytest.mark.asyncio
    async def test_check_update_no_conflicts(self, preflight_service, mock_jira_client):
        """Test check_update returns OK when values match."""
        mock_jira_client.get_issue.return_value = {
            "fields": {
                "summary": "My Story",
                "description": "My description",
            }
        }

        result = await preflight_service.check_update(
            jira_key="PROJ-123",
            local_values={
                "summary": "My Story",
                "description": "My description",
            },
        )

        assert result.result == PreflightResult.OK
        assert "No conflicts" in result.details

    @pytest.mark.asyncio
    async def test_check_update_jira_owned_conflict(self, preflight_service, mock_jira_client):
        """Test check_update detects JIRA_OWNED field conflicts."""
        mock_jira_client.get_issue.return_value = {
            "fields": {
                "status": {"name": "In Progress"},
            }
        }

        result = await preflight_service.check_update(
            jira_key="PROJ-123",
            local_values={
                "status": {"name": "Done"},  # Trying to change Jira-owned field
            },
        )

        assert result.result == PreflightResult.CONFLICT
        assert "1 field conflict" in result.details
        assert len(result.conflicts) == 1
        assert result.conflicts[0].field == "status"
        assert result.conflicts[0].ownership == FieldOwnership.JIRA_OWNED


# =============================================================================
# JiraSyncService Tests
# =============================================================================


class TestJiraSyncServiceCommit:
    """Tests for JiraSyncService.commit_work_item."""

    @pytest.mark.asyncio
    async def test_commit_work_item_success(
        self, sync_service, mock_jira_client, approved_work_item
    ):
        """Test successful work item commit creates issue and returns key."""
        mock_jira_client.search_duplicates.return_value = []
        mock_jira_client.create_issue.return_value = "PROJ-999"

        jira_key = await sync_service.commit_work_item(
            entity=approved_work_item,
            project_key="PROJ",
        )

        assert jira_key == "PROJ-999"
        mock_jira_client.create_issue.assert_called_once()
        call_kwargs = mock_jira_client.create_issue.call_args.kwargs
        assert call_kwargs["project_key"] == "PROJ"
        assert call_kwargs["summary"] == "Test Story"
        assert call_kwargs["issue_type"] == "Story"
        assert "Acceptance Criteria" in call_kwargs["description"]

    @pytest.mark.asyncio
    async def test_commit_work_item_duplicate(
        self, sync_service, mock_jira_client, approved_work_item
    ):
        """Test commit_work_item raises DuplicateDetectedError when duplicates found."""
        mock_jira_client.search_duplicates.return_value = ["PROJ-100"]

        with pytest.raises(DuplicateDetectedError) as exc_info:
            await sync_service.commit_work_item(
                entity=approved_work_item,
                project_key="PROJ",
            )

        assert exc_info.value.duplicate_keys == ("PROJ-100",)
        # Should not create issue when duplicate detected
        mock_jira_client.create_issue.assert_not_called()


class TestJiraSyncServiceProjectDecision:
    """Tests for JiraSyncService.project_decision."""

    @pytest.mark.asyncio
    async def test_project_decision_success(
        self, sync_service, mock_jira_client, approved_decision
    ):
        """Test project_decision adds comment to existing issue."""
        await sync_service.project_decision(
            entity=approved_decision,
            target_jira_key="PROJ-100",
        )

        mock_jira_client.add_comment.assert_called_once()
        call_args = mock_jira_client.add_comment.call_args
        assert call_args[0][0] == "PROJ-100"  # jira_key
        comment = call_args[0][1]
        assert "Use PostgreSQL" in comment
        assert "PostgreSQL for event storage" in comment
        assert "JSONB and LISTEN/NOTIFY" in comment


class TestJiraSyncServiceReconcile:
    """Tests for JiraSyncService.reconcile."""

    @pytest.mark.asyncio
    async def test_reconcile_finds_discrepancies(
        self, sync_service, mock_jira_client, committed_work_item
    ):
        """Test reconcile detects field differences between Slack and Jira."""
        # Jira has different summary than our entity
        mock_jira_client.get_issue.return_value = {
            "fields": {
                "summary": "Different Title",  # Changed in Jira
                "description": "Test description",
            }
        }

        discrepancies = await sync_service.reconcile([committed_work_item])

        assert len(discrepancies) == 1
        assert discrepancies[0].field == "summary"
        assert discrepancies[0].slack_value == "Test Story"
        assert discrepancies[0].jira_value == "Different Title"

    @pytest.mark.asyncio
    async def test_reconcile_no_discrepancies(
        self, sync_service, mock_jira_client, committed_work_item
    ):
        """Test reconcile returns empty list when in sync."""
        mock_jira_client.get_issue.return_value = {
            "fields": {
                "summary": "Test Story",
                "description": "Test description with Acceptance Criteria and more",
            }
        }

        discrepancies = await sync_service.reconcile([committed_work_item])

        assert len(discrepancies) == 0

    @pytest.mark.asyncio
    async def test_reconcile_handles_jira_error(
        self, sync_service, mock_jira_client, committed_work_item
    ):
        """Test reconcile reports discrepancy when Jira issue not accessible."""
        mock_jira_client.get_issue.side_effect = Exception("Issue not found")

        discrepancies = await sync_service.reconcile([committed_work_item])

        assert len(discrepancies) == 1
        assert discrepancies[0].field == "__access__"
        assert "Issue not found" in discrepancies[0].jira_value
