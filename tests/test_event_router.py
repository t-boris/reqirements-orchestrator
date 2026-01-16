"""Tests for event-first routing logic."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.slack.event_router import (
    route_event,
    RouteResult,
    is_workflow_event,
    extract_event_info,
    _get_event_id,
)
from src.schemas.state import WorkflowEventType, WorkflowStep, PendingAction


class TestIsWorkflowEvent:
    """Tests for is_workflow_event detection."""

    def test_button_click_is_workflow_event(self):
        """Button clicks are workflow events."""
        body = {"type": "block_actions", "actions": [{"action_id": "approve"}]}
        assert is_workflow_event(body) is True

    def test_slash_command_is_workflow_event(self):
        """Slash commands are workflow events."""
        body = {"command": "/maro"}
        assert is_workflow_event(body) is True

    def test_modal_submit_is_workflow_event(self):
        """Modal submissions are workflow events."""
        body = {"type": "view_submission", "view": {"callback_id": "scope_gate"}}
        assert is_workflow_event(body) is True

    def test_message_is_not_workflow_event(self):
        """Regular messages are not workflow events."""
        body = {"type": "message", "text": "hello"}
        assert is_workflow_event(body) is False

    def test_empty_body_is_not_workflow_event(self):
        """Empty body is not a workflow event."""
        body = {}
        assert is_workflow_event(body) is False

    def test_event_callback_is_not_workflow_event(self):
        """Event callback (app_mention) is not a workflow event."""
        body = {"type": "event_callback", "event": {"type": "app_mention"}}
        assert is_workflow_event(body) is False


class TestExtractEventInfo:
    """Tests for event info extraction."""

    def test_button_click_extraction(self):
        """Extract action from button click."""
        body = {
            "type": "block_actions",
            "actions": [{"action_id": "approve", "value": "draft_123:5"}],
        }
        event_type, action, ui_version = extract_event_info(body)
        assert event_type == WorkflowEventType.BUTTON_CLICK
        assert action == "approve"
        assert ui_version == 5

    def test_button_without_version(self):
        """Handle button without ui_version."""
        body = {
            "type": "block_actions",
            "actions": [{"action_id": "cancel", "value": "just_cancel"}],
        }
        event_type, action, ui_version = extract_event_info(body)
        assert action == "cancel"
        assert ui_version is None

    def test_button_with_non_numeric_colon(self):
        """Handle button with colon but non-numeric suffix."""
        body = {
            "type": "block_actions",
            "actions": [{"action_id": "edit", "value": "some:value:here"}],
        }
        event_type, action, ui_version = extract_event_info(body)
        assert action == "edit"
        assert ui_version is None

    def test_slash_command_extraction(self):
        """Extract command from slash command."""
        body = {"command": "/maro", "text": "help"}
        event_type, action, ui_version = extract_event_info(body)
        assert event_type == WorkflowEventType.SLASH_COMMAND
        assert action == "/maro"
        assert ui_version is None

    def test_modal_submit_extraction(self):
        """Extract callback_id from modal submission."""
        body = {
            "type": "view_submission",
            "view": {"callback_id": "scope_gate_submit"},
        }
        event_type, action, ui_version = extract_event_info(body)
        assert event_type == WorkflowEventType.MODAL_SUBMIT
        assert action == "scope_gate_submit"
        assert ui_version is None

    def test_unknown_event_returns_none(self):
        """Unknown event types return None."""
        body = {"type": "message", "text": "hello"}
        event_type, action, ui_version = extract_event_info(body)
        assert event_type is None
        assert action is None
        assert ui_version is None


class TestGetEventId:
    """Tests for event ID extraction."""

    def test_uses_event_id_if_present(self):
        """Prefer event_id from envelope."""
        body = {"event_id": "Ev123", "type": "block_actions"}
        assert _get_event_id(body) == "Ev123"

    def test_constructs_fallback_for_buttons(self):
        """Construct fallback key for button clicks."""
        body = {
            "type": "block_actions",
            "actions": [{"action_id": "approve"}],
            "message": {"ts": "1234.5678"},
            "user": {"id": "U123"},
        }
        event_id = _get_event_id(body)
        assert event_id == "approve:1234.5678:U123"

    def test_returns_none_for_incomplete_button(self):
        """Return None if button click missing required fields."""
        body = {
            "type": "block_actions",
            "actions": [{"action_id": "approve"}],
            # missing message.ts and user.id
        }
        assert _get_event_id(body) is None

    def test_returns_none_for_non_button(self):
        """Return None for non-button events without event_id."""
        body = {"type": "message", "text": "hello"}
        assert _get_event_id(body) is None


class TestRouteEvent:
    """Tests for route_event main routing logic."""

    @pytest.fixture
    def mock_event_store(self):
        """Create mock EventStore."""
        store = AsyncMock()
        store.is_processed = AsyncMock(return_value=False)
        store.mark_processed = AsyncMock(return_value=True)
        return store

    @pytest.mark.asyncio
    async def test_duplicate_event_rejected(self, mock_event_store):
        """Duplicate events return DUPLICATE result."""
        mock_event_store.is_processed.return_value = True
        body = {"event_id": "Ev123", "type": "message"}
        state = {}

        result = await route_event(body, "T123", state, mock_event_store)

        assert result.result == RouteResult.DUPLICATE
        assert "already processed" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_workflow_event_routed_directly(self, mock_event_store):
        """Workflow events route to WORKFLOW_EVENT."""
        body = {
            "type": "block_actions",
            "actions": [{"action_id": "approve", "value": "draft:1"}],
            "message": {"ts": "1234.5678"},
            "user": {"id": "U123"},
        }
        state = {"workflow_step": WorkflowStep.DRAFT_PREVIEW, "ui_version": 1}

        result = await route_event(body, "T123", state, mock_event_store)

        assert result.result == RouteResult.WORKFLOW_EVENT
        assert result.event_action == "approve"

    @pytest.mark.asyncio
    async def test_stale_event_rejected(self, mock_event_store):
        """Stale events (wrong step) return STALE_UI."""
        body = {
            "type": "block_actions",
            "actions": [{"action_id": "approve", "value": "draft:1"}],
            "message": {"ts": "1234.5678"},
            "user": {"id": "U123"},
        }
        # Current step is REVIEW_ACTIVE, but "approve" is for DRAFT_PREVIEW
        state = {"workflow_step": WorkflowStep.REVIEW_ACTIVE, "ui_version": 1}

        result = await route_event(body, "T123", state, mock_event_store)

        assert result.result == RouteResult.STALE_UI

    @pytest.mark.asyncio
    async def test_stale_ui_version_rejected(self, mock_event_store):
        """Stale UI version (old preview) returns STALE_UI."""
        body = {
            "type": "block_actions",
            "actions": [{"action_id": "approve", "value": "draft:1"}],
            "message": {"ts": "1234.5678"},
            "user": {"id": "U123"},
        }
        # Button has version 1, but state has version 2
        state = {"workflow_step": WorkflowStep.DRAFT_PREVIEW, "ui_version": 2}

        result = await route_event(body, "T123", state, mock_event_store)

        assert result.result == RouteResult.STALE_UI
        assert "outdated" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_pending_action_routes_to_continuation(self, mock_event_store):
        """Messages with pending_action route to CONTINUATION."""
        body = {"type": "message", "text": "yes, approve it"}
        state = {"pending_action": PendingAction.WAITING_APPROVAL}

        result = await route_event(body, "T123", state, mock_event_store)

        assert result.result == RouteResult.CONTINUATION
        assert result.pending_action == PendingAction.WAITING_APPROVAL

    @pytest.mark.asyncio
    async def test_thread_default_intent_used(self, mock_event_store):
        """Thread default intent routes to INTENT_CLASSIFY with default."""
        from datetime import datetime, timezone, timedelta
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        body = {"type": "message", "text": "another question"}
        state = {
            "thread_default_intent": "review",
            "thread_default_expires_at": expires,
        }

        result = await route_event(body, "T123", state, mock_event_store)

        assert result.result == RouteResult.INTENT_CLASSIFY
        from src.schemas.state import UserIntent
        assert result.default_intent == UserIntent.REVIEW

    @pytest.mark.asyncio
    async def test_expired_thread_default_ignored(self, mock_event_store):
        """Expired thread default routes to INTENT_CLASSIFY without default."""
        from datetime import datetime, timezone, timedelta
        expires = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        body = {"type": "message", "text": "another question"}
        state = {
            "thread_default_intent": "review",
            "thread_default_expires_at": expires,
        }

        result = await route_event(body, "T123", state, mock_event_store)

        assert result.result == RouteResult.INTENT_CLASSIFY
        assert result.default_intent is None

    @pytest.mark.asyncio
    async def test_normal_message_routes_to_intent_classify(self, mock_event_store):
        """Normal messages without special state route to INTENT_CLASSIFY."""
        body = {"type": "message", "text": "create a ticket for login bug"}
        state = {}

        result = await route_event(body, "T123", state, mock_event_store)

        assert result.result == RouteResult.INTENT_CLASSIFY
        assert result.default_intent is None
        assert result.pending_action is None
