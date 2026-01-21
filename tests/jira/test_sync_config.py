"""Tests for Jira sync configuration (Phase 23.4)."""
import pytest

from src.jira.sync_config import (
    FieldOwnership,
    SyncField,
    SyncDirection,
    SyncResult,
    FIELD_CLASSIFICATIONS,
    can_push_field,
    requires_conflict_check,
)


class TestFieldOwnership:
    """Test FieldOwnership enum."""

    def test_enum_values(self):
        """FieldOwnership has expected values."""
        assert FieldOwnership.JIRA_OWNED == "jira_owned"
        assert FieldOwnership.SLACK_OWNED == "slack_owned"
        assert FieldOwnership.SHARED == "shared"


class TestFieldClassifications:
    """Test FIELD_CLASSIFICATIONS dict."""

    def test_jira_owned_fields(self):
        """Jira-owned fields are classified correctly."""
        assert FIELD_CLASSIFICATIONS["status"].ownership == FieldOwnership.JIRA_OWNED
        assert FIELD_CLASSIFICATIONS["assignee"].ownership == FieldOwnership.JIRA_OWNED
        assert FIELD_CLASSIFICATIONS["story_points"].ownership == FieldOwnership.JIRA_OWNED

    def test_slack_owned_fields(self):
        """Slack-owned fields are classified correctly."""
        assert FIELD_CLASSIFICATIONS["summary"].ownership == FieldOwnership.SLACK_OWNED
        assert FIELD_CLASSIFICATIONS["description"].ownership == FieldOwnership.SLACK_OWNED
        assert FIELD_CLASSIFICATIONS["labels"].ownership == FieldOwnership.SLACK_OWNED

    def test_shared_fields(self):
        """Shared fields are classified correctly."""
        assert FIELD_CLASSIFICATIONS["priority"].ownership == FieldOwnership.SHARED
        assert FIELD_CLASSIFICATIONS["due_date"].ownership == FieldOwnership.SHARED


class TestCanPushField:
    """Test can_push_field() function."""

    def test_slack_owned_can_push_to_jira(self):
        """Slack-owned fields can be pushed to Jira."""
        assert can_push_field("summary", SyncDirection.SLACK_TO_JIRA) is True
        assert can_push_field("description", SyncDirection.SLACK_TO_JIRA) is True

    def test_jira_owned_cannot_push_to_jira(self):
        """Jira-owned fields cannot be pushed from Slack."""
        assert can_push_field("status", SyncDirection.SLACK_TO_JIRA) is False
        assert can_push_field("assignee", SyncDirection.SLACK_TO_JIRA) is False

    def test_jira_owned_can_pull_from_jira(self):
        """Jira-owned fields can be pulled from Jira."""
        assert can_push_field("status", SyncDirection.JIRA_TO_SLACK) is True
        assert can_push_field("assignee", SyncDirection.JIRA_TO_SLACK) is True

    def test_slack_owned_cannot_pull_from_jira(self):
        """Slack-owned fields cannot be pulled from Jira."""
        assert can_push_field("summary", SyncDirection.JIRA_TO_SLACK) is False
        assert can_push_field("description", SyncDirection.JIRA_TO_SLACK) is False

    def test_shared_fields_both_directions(self):
        """Shared fields can sync in both directions."""
        assert can_push_field("priority", SyncDirection.SLACK_TO_JIRA) is True
        assert can_push_field("priority", SyncDirection.JIRA_TO_SLACK) is True

    def test_unknown_field_returns_false(self):
        """Unknown fields cannot be pushed."""
        assert can_push_field("nonexistent", SyncDirection.SLACK_TO_JIRA) is False


class TestRequiresConflictCheck:
    """Test requires_conflict_check() function."""

    def test_shared_fields_require_conflict_check(self):
        """Shared fields require conflict detection."""
        assert requires_conflict_check("priority") is True
        assert requires_conflict_check("due_date") is True

    def test_owned_fields_no_conflict_check(self):
        """Single-owner fields don't need conflict check."""
        assert requires_conflict_check("status") is False
        assert requires_conflict_check("summary") is False

    def test_unknown_field_no_conflict_check(self):
        """Unknown fields don't require conflict check."""
        assert requires_conflict_check("nonexistent") is False


class TestSyncResult:
    """Test SyncResult model."""

    def test_successful_result(self):
        """SyncResult can represent success."""
        result = SyncResult(
            success=True,
            direction=SyncDirection.SLACK_TO_JIRA,
            fields_updated=["summary", "description"],
        )
        assert result.success is True
        assert result.error is None

    def test_failed_result_with_conflicts(self):
        """SyncResult can represent failure with conflicts."""
        result = SyncResult(
            success=False,
            direction=SyncDirection.SLACK_TO_JIRA,
            conflicts=[{"field": "priority", "slack_value": "High", "jira_value": "Low"}],
            error="Conflicts detected",
        )
        assert result.success is False
        assert len(result.conflicts) == 1
