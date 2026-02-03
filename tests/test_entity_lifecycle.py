"""Entity lifecycle tests.

Tests for ChannelAggregate entity lifecycle transitions:
- Draft -> Proposed -> Approved -> Committed
- Objection handling
- Decision lifecycle
- Invalid state transitions
"""

import pytest
from src.domain.channel import ChannelAggregate, EntityNotFoundError, InvalidStateError
from src.domain.entities import (
    ApprovedEntity,
    CommittedEntity,
    DraftEntity,
    ProposedEntity,
)
from src.domain.transitions import TransitionError
from src.domain.types import ChannelId, EntityId, JiraKey, ThreadTs, UserId


class TestWorkItemLifecycle:
    """Test work item lifecycle transitions."""

    def test_draft_work_item(self, channel_id, thread_ts, user_id, work_item_content):
        """Test creating a draft work item emits event and updates state."""
        channel = ChannelAggregate(channel_id=channel_id)

        draft = channel.draft_work_item(
            actor_id=user_id,
            thread_ts=thread_ts,
            content=work_item_content,
        )

        # Verify entity created
        assert isinstance(draft, DraftEntity)
        assert draft.content.title == "Test Story"
        assert draft.thread_ts == thread_ts
        assert draft.channel_id == channel_id

        # Verify event emitted
        events = channel.pending_events
        assert len(events) == 1
        assert events[0].__class__.__name__ == "WorkItemDrafted"
        assert events[0].entity_id == draft.id

        # Verify entity stored
        assert channel.get_entity(draft.id) == draft

    def test_propose_work_item(self, channel_id, thread_ts, user_id, work_item_content):
        """Test transitioning draft to proposed."""
        channel = ChannelAggregate(channel_id=channel_id)
        draft = channel.draft_work_item(
            actor_id=user_id,
            thread_ts=thread_ts,
            content=work_item_content,
        )
        channel.clear_pending_events()

        proposed = channel.propose_work_item(
            entity_id=draft.id,
            actor_id=user_id,
            canonical_message_ts="1234567890.999999",
        )

        # Verify state transition
        assert isinstance(proposed, ProposedEntity)
        assert proposed.canonical_message_ts == "1234567890.999999"
        assert proposed.approvals == []
        assert proposed.objections == []

        # Verify event emitted
        events = channel.pending_events
        assert len(events) == 1
        assert events[0].__class__.__name__ == "WorkItemProposed"

    def test_approve_work_item(self, channel_id, thread_ts, user_id, work_item_content):
        """Test adding approval transitions to approved when threshold met."""
        channel = ChannelAggregate(channel_id=channel_id)
        draft = channel.draft_work_item(
            actor_id=user_id,
            thread_ts=thread_ts,
            content=work_item_content,
        )
        channel.propose_work_item(
            entity_id=draft.id,
            actor_id=user_id,
            canonical_message_ts="1234567890.999999",
        )
        channel.clear_pending_events()

        approver = UserId("U_APPROVER")
        result = channel.approve_work_item(
            entity_id=draft.id,
            actor_id=approver,
            comment="LGTM",
        )

        # With 1 approval and no objections, should auto-transition to Approved
        assert isinstance(result, ApprovedEntity)
        assert result.attribution.approved_by == approver

        # Verify events: ApprovalAdded + WorkItemApproved
        events = channel.pending_events
        assert len(events) == 2
        assert events[0].__class__.__name__ == "ApprovalAdded"
        assert events[1].__class__.__name__ == "WorkItemApproved"

    def test_commit_work_item(self, channel_id, thread_ts, user_id, work_item_content):
        """Test committing approved work item to Jira."""
        channel = ChannelAggregate(channel_id=channel_id)
        draft = channel.draft_work_item(
            actor_id=user_id,
            thread_ts=thread_ts,
            content=work_item_content,
        )
        channel.propose_work_item(
            entity_id=draft.id,
            actor_id=user_id,
            canonical_message_ts="1234567890.999999",
        )
        approver = UserId("U_APPROVER")
        channel.approve_work_item(entity_id=draft.id, actor_id=approver)
        channel.clear_pending_events()

        jira_key = JiraKey("PROJ-123")
        committed = channel.commit_work_item(
            entity_id=draft.id,
            actor_id=user_id,
            jira_key=jira_key,
        )

        # Verify committed state
        assert isinstance(committed, CommittedEntity)
        assert committed.jira_link is not None
        assert committed.jira_link.jira_key == jira_key

        # Verify event
        events = channel.pending_events
        assert len(events) == 1
        assert events[0].__class__.__name__ == "WorkItemCommitted"
        assert events[0].jira_key == jira_key


class TestObjectionHandling:
    """Test objection workflow."""

    def test_objection_blocks_approval(self, channel_id, thread_ts, user_id, work_item_content):
        """Test that active objection prevents auto-approval."""
        channel = ChannelAggregate(channel_id=channel_id)
        draft = channel.draft_work_item(
            actor_id=user_id,
            thread_ts=thread_ts,
            content=work_item_content,
        )
        channel.propose_work_item(
            entity_id=draft.id,
            actor_id=user_id,
            canonical_message_ts="1234567890.999999",
        )

        # Raise objection
        objector = UserId("U_OBJECTOR")
        channel.raise_entity_objection(
            entity_id=draft.id,
            actor_id=objector,
            reason="Missing edge case handling",
        )
        channel.clear_pending_events()

        # Try to approve - should stay in ProposedEntity due to objection
        approver = UserId("U_APPROVER")
        result = channel.approve_work_item(
            entity_id=draft.id,
            actor_id=approver,
        )

        # Should still be proposed, not approved (objection blocks)
        assert isinstance(result, ProposedEntity)
        assert len(result.approvals) == 1
        assert len(result.objections) == 1

    def test_resolve_objection_allows_approval(self, channel_id, thread_ts, user_id, work_item_content):
        """Test that resolving objection allows approval to proceed."""
        channel = ChannelAggregate(channel_id=channel_id)
        draft = channel.draft_work_item(
            actor_id=user_id,
            thread_ts=thread_ts,
            content=work_item_content,
        )
        channel.propose_work_item(
            entity_id=draft.id,
            actor_id=user_id,
            canonical_message_ts="1234567890.999999",
        )

        # Raise and resolve objection
        objector = UserId("U_OBJECTOR")
        channel.raise_entity_objection(
            entity_id=draft.id,
            actor_id=objector,
            reason="Missing edge case handling",
        )
        channel.resolve_entity_objection(
            entity_id=draft.id,
            objection_index=0,
            actor_id=user_id,
            resolution="Added edge case handling in description",
        )
        channel.clear_pending_events()

        # Now approval should work
        approver = UserId("U_APPROVER")
        result = channel.approve_work_item(
            entity_id=draft.id,
            actor_id=approver,
        )

        # Should now be approved
        assert isinstance(result, ApprovedEntity)


class TestDecisionLifecycle:
    """Test decision-specific lifecycle."""

    def test_decision_lifecycle(self, channel_id, thread_ts, user_id, decision_content):
        """Test full decision lifecycle: record -> propose -> approve -> commit."""
        channel = ChannelAggregate(channel_id=channel_id)

        # Record decision (creates draft)
        draft = channel.record_decision(
            actor_id=user_id,
            thread_ts=thread_ts,
            content=decision_content,
        )
        assert isinstance(draft, DraftEntity)
        assert draft.content.title == "Test Decision"

        # Propose for approval
        proposed = channel.propose_decision(
            entity_id=draft.id,
            actor_id=user_id,
            canonical_message_ts="1234567890.999999",
        )
        assert isinstance(proposed, ProposedEntity)

        # Approve
        approver = UserId("U_APPROVER")
        approved = channel.approve_decision(
            entity_id=draft.id,
            actor_id=approver,
        )
        assert isinstance(approved, ApprovedEntity)

        # Commit to Jira
        jira_key = JiraKey("PROJ-456")
        committed = channel.commit_decision(
            entity_id=draft.id,
            actor_id=user_id,
            jira_key=jira_key,
            field_path="description",
        )
        assert isinstance(committed, CommittedEntity)
        assert committed.jira_link.jira_key == jira_key
        assert committed.jira_link.field_path == "description"


class TestInvalidStateTransitions:
    """Test invalid state transitions raise appropriate errors."""

    def test_cannot_modify_committed(self, channel_id, thread_ts, user_id, work_item_content):
        """Test that committed entity cannot be re-proposed or modified."""
        channel = ChannelAggregate(channel_id=channel_id)

        # Create and commit a work item
        draft = channel.draft_work_item(
            actor_id=user_id,
            thread_ts=thread_ts,
            content=work_item_content,
        )
        channel.propose_work_item(
            entity_id=draft.id,
            actor_id=user_id,
            canonical_message_ts="1234567890.999999",
        )
        approver = UserId("U_APPROVER")
        channel.approve_work_item(entity_id=draft.id, actor_id=approver)
        channel.commit_work_item(
            entity_id=draft.id,
            actor_id=user_id,
            jira_key=JiraKey("PROJ-123"),
        )

        # Try to propose again - should fail
        with pytest.raises(InvalidStateError) as exc_info:
            channel.propose_work_item(
                entity_id=draft.id,
                actor_id=user_id,
                canonical_message_ts="1234567890.111111",
            )
        assert "must be draft" in str(exc_info.value)

        # Try to approve again - should fail
        with pytest.raises(InvalidStateError) as exc_info:
            channel.approve_work_item(
                entity_id=draft.id,
                actor_id=UserId("U_ANOTHER"),
            )
        assert "must be proposed" in str(exc_info.value)

    def test_entity_not_found_error(self, channel_id, user_id):
        """Test that operations on non-existent entity raise EntityNotFoundError."""
        channel = ChannelAggregate(channel_id=channel_id)
        fake_id = EntityId("nonexistent-entity-id")

        with pytest.raises(EntityNotFoundError):
            channel.propose_work_item(
                entity_id=fake_id,
                actor_id=user_id,
                canonical_message_ts="1234567890.999999",
            )

    def test_duplicate_approval_raises_error(self, channel_id, thread_ts, user_id, work_item_content):
        """Test that same user cannot approve twice."""
        channel = ChannelAggregate(channel_id=channel_id)
        draft = channel.draft_work_item(
            actor_id=user_id,
            thread_ts=thread_ts,
            content=work_item_content,
        )
        channel.propose_work_item(
            entity_id=draft.id,
            actor_id=user_id,
            canonical_message_ts="1234567890.999999",
        )

        # Raise objection to prevent auto-approval on first approval
        objector = UserId("U_OBJECTOR")
        channel.raise_entity_objection(
            entity_id=draft.id,
            actor_id=objector,
            reason="Need review",
        )

        # First approval
        approver = UserId("U_APPROVER")
        channel.approve_work_item(entity_id=draft.id, actor_id=approver)

        # Second approval by same user should fail
        with pytest.raises(TransitionError) as exc_info:
            channel.approve_work_item(entity_id=draft.id, actor_id=approver)
        assert "already approved" in str(exc_info.value)
