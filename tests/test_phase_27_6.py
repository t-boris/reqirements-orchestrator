"""Unit tests for Phase 27.6 - Notifications & Slack UX.

Tests cover:
- Notification service (targeted @mentions)
- OpenQuestionStore (no-response policy)
- Status card blocks (channel visibility)
- Noise filter (low-noise principle)
"""
import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from psycopg import AsyncConnection


# Database fixture (duplicated from tests/db/conftest.py for isolation)
@pytest_asyncio.fixture
async def db_connection():
    """Create a database connection for testing.

    Skips if database is not available (common in CI).
    """
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://maro:maro_db_k7x9Qp2mNv@localhost:5432/maro",
    )

    try:
        async with await AsyncConnection.connect(database_url) as conn:
            await conn.execute("BEGIN")
            yield conn
            await conn.rollback()
    except Exception as e:
        pytest.skip(f"Database not available: {e}")


# === Noise Filter Tests ===

class TestNoiseFilter:
    """Tests for src/slack/noise_filter.py."""

    def test_direct_mention_always_responds(self):
        """Should always respond when directly @mentioned."""
        from src.slack.noise_filter import should_respond

        result, reason = should_respond(
            message_text="<@U123BOT> help me with this",
            bot_user_id="U123BOT",
            is_listening_mode=False,
        )
        assert result is True
        assert reason == "direct_mention"

    def test_direct_mention_in_listening_mode(self):
        """Should respond to direct @mention even in listening mode."""
        from src.slack.noise_filter import should_respond

        result, reason = should_respond(
            message_text="<@U123BOT> create a ticket for this",
            bot_user_id="U123BOT",
            is_listening_mode=True,
        )
        assert result is True
        assert reason == "direct_mention"

    def test_pending_action_always_responds(self):
        """Should respond when there's a pending action."""
        from src.slack.noise_filter import should_respond

        result, reason = should_respond(
            message_text="yes, go ahead",
            bot_user_id="U123BOT",
            is_listening_mode=True,
            has_pending_action=True,
        )
        assert result is True
        assert reason == "pending_action"

    def test_name_mention_responds(self):
        """Should respond when MARO is mentioned by name."""
        from src.slack.noise_filter import should_respond

        result, reason = should_respond(
            message_text="hey maro can you help",
            bot_user_id="U123BOT",
            is_listening_mode=False,
        )
        assert result is True
        assert reason == "name_mention"

    def test_listening_mode_filters_noise(self):
        """Should not respond to casual conversation in listening mode."""
        from src.slack.noise_filter import should_respond

        result, reason = should_respond(
            message_text="how was your weekend?",
            bot_user_id="U123BOT",
            is_listening_mode=True,
        )
        assert result is False
        assert reason == "listening_mode_noise"

    def test_listening_mode_high_confidence_actionable(self):
        """Should respond to high-confidence actionable content in listening mode."""
        from src.slack.noise_filter import should_respond

        # Task creation signals
        result, reason = should_respond(
            message_text="we need to track this issue",
            bot_user_id="U123BOT",
            is_listening_mode=True,
        )
        assert result is True
        assert reason == "high_confidence_actionable"

        # Decision signals
        result, reason = should_respond(
            message_text="we decided to use PostgreSQL",
            bot_user_id="U123BOT",
            is_listening_mode=True,
        )
        assert result is True
        assert reason == "high_confidence_actionable"

    def test_not_mentioned_no_response(self):
        """Should not respond when not mentioned and not in listening mode."""
        from src.slack.noise_filter import should_respond

        result, reason = should_respond(
            message_text="let's discuss the architecture",
            bot_user_id="U123BOT",
            is_listening_mode=False,
        )
        assert result is False
        assert reason == "not_mentioned"

    def test_is_actionable_utility(self):
        """Test the is_actionable utility function."""
        from src.slack.noise_filter import is_actionable

        assert is_actionable("we need to create a ticket") is True
        assert is_actionable("action item: review PR") is True
        assert is_actionable("let's go with option A") is True
        assert is_actionable("how was your weekend") is False
        assert is_actionable("nice work on the feature") is False

    def test_get_actionable_signals(self):
        """Test that actionable signals are detected and returned."""
        from src.slack.noise_filter import get_actionable_signals

        signals = get_actionable_signals("we need to track this issue")
        assert len(signals) > 0
        assert any("task" in s for s in signals)

        signals = get_actionable_signals("we decided to go with React")
        assert len(signals) > 0
        assert any("decision" in s for s in signals)

        signals = get_actionable_signals("how was your day")
        assert len(signals) == 0


# === Status Card Tests ===

class TestStatusCardBlocks:
    """Tests for src/slack/blocks/status_card.py."""

    def test_build_jira_status_card(self):
        """Should build a proper Jira status card."""
        from src.slack.blocks.status_card import build_jira_status_card

        blocks = build_jira_status_card(
            jira_key="SCRUM-123",
            jira_url="https://jira.example.com/browse/SCRUM-123",
            summary="Implement user authentication",
            status="In Progress",
            assignee="john.doe",
            issue_type="Story",
        )

        assert len(blocks) == 2
        assert blocks[0]["type"] == "section"
        assert "SCRUM-123" in blocks[0]["text"]["text"]
        assert blocks[0]["accessory"]["type"] == "button"
        assert blocks[1]["type"] == "context"
        assert "In Progress" in blocks[1]["elements"][0]["text"]

    def test_build_ticket_created_card(self):
        """Should build a ticket creation announcement card."""
        from src.slack.blocks.status_card import build_ticket_created_card

        blocks = build_ticket_created_card(
            jira_key="SCRUM-456",
            jira_url="https://jira.example.com/browse/SCRUM-456",
            summary="Fix login bug",
            created_by="U123USER",
            thread_link="https://slack.com/archives/C123/p1234567890",
            issue_type="Bug",
        )

        assert len(blocks) == 2
        assert blocks[0]["type"] == "section"
        assert "SCRUM-456" in blocks[0]["text"]["text"]
        assert ":white_check_mark:" in blocks[0]["text"]["text"]
        assert blocks[1]["type"] == "context"
        assert "U123USER" in blocks[1]["elements"][0]["text"]

    def test_build_status_update_card(self):
        """Should build a status update card with transition."""
        from src.slack.blocks.status_card import build_status_update_card

        blocks = build_status_update_card(
            jira_key="SCRUM-789",
            jira_url="https://jira.example.com/browse/SCRUM-789",
            summary="Implement caching",
            old_status="To Do",
            new_status="In Progress",
            updated_by="U456USER",
        )

        assert len(blocks) == 2
        assert "SCRUM-789" in blocks[0]["text"]["text"]
        assert "To Do" in blocks[1]["elements"][0]["text"]
        assert "In Progress" in blocks[1]["elements"][0]["text"]

    def test_build_workitem_status_card(self):
        """Should build a WorkItem status card."""
        from src.slack.blocks.status_card import build_workitem_status_card

        blocks = build_workitem_status_card(
            workitem_id="abc123",
            summary="Draft: Add search feature",
            status="draft",
            owners=["U111", "U222"],
        )

        assert len(blocks) == 2
        assert blocks[0]["type"] == "section"
        assert "Add search feature" in blocks[0]["text"]["text"]
        assert blocks[1]["type"] == "context"
        assert ":pencil:" in blocks[1]["elements"][0]["text"]


# === OpenQuestionStore Tests ===

class TestOpenQuestionStore:
    """Tests for src/db/open_question_store.py.

    Uses database fixture for integration testing.
    """

    @pytest_asyncio.fixture
    async def question_store(self, db_connection):
        """Create OpenQuestionStore with test connection."""
        from src.db.open_question_store import OpenQuestionStore

        store = OpenQuestionStore(db_connection)
        await store.ensure_table()
        return store

    @pytest.mark.asyncio
    async def test_record_question(self, question_store):
        """Should record a new open question."""
        question = await question_store.record_question(
            channel_id="C123",
            thread_ts="1234567890.000001",
            question_text="What is the deadline?",
            target_user_ids=["U111", "U222"],
        )

        assert question is not None
        assert question.channel_id == "C123"
        assert question.thread_ts == "1234567890.000001"
        assert question.question_text == "What is the deadline?"
        assert question.ping_count == 1
        assert question.status == "open"

    @pytest.mark.asyncio
    async def test_should_ping_again_new_thread(self, question_store):
        """Should allow pinging on new thread."""
        result = await question_store.should_ping_again(
            channel_id="C999",
            thread_ts="9999999999.000001",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_ping_count_increments(self, question_store):
        """Should increment ping count on subsequent records."""
        # First ping
        q1 = await question_store.record_question(
            channel_id="C123",
            thread_ts="1234567890.000002",
            question_text="First question",
            target_user_ids=["U111"],
        )
        assert q1.ping_count == 1

        # Second ping in same thread
        q2 = await question_store.record_question(
            channel_id="C123",
            thread_ts="1234567890.000002",
            question_text="Still waiting for answer",
            target_user_ids=["U111"],
        )
        assert q2.ping_count == 2

    @pytest.mark.asyncio
    async def test_max_pings_limit(self, question_store):
        """Should stop pinging after MAX_PINGS reached."""
        channel = "C123"
        thread = "1234567890.000003"

        # Record MAX_PINGS times
        for i in range(question_store.MAX_PINGS):
            await question_store.record_question(
                channel_id=channel,
                thread_ts=thread,
                question_text=f"Ping {i+1}",
                target_user_ids=["U111"],
            )

        # Should not ping again
        result = await question_store.should_ping_again(channel, thread)
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_answered(self, question_store):
        """Should mark question as answered."""
        # Record question
        await question_store.record_question(
            channel_id="C123",
            thread_ts="1234567890.000004",
            question_text="What color?",
            target_user_ids=["U111"],
        )

        # Mark answered
        await question_store.mark_answered(
            channel_id="C123",
            thread_ts="1234567890.000004",
            answered_by="U222",
        )

        # Verify
        question = await question_store.get_question(
            channel_id="C123",
            thread_ts="1234567890.000004",
        )
        assert question is None  # Should not return answered questions

    @pytest.mark.asyncio
    async def test_get_open_questions(self, question_store):
        """Should list open questions for channel."""
        # Record several questions
        for i in range(3):
            await question_store.record_question(
                channel_id="C456",
                thread_ts=f"1234567890.00000{i}",
                question_text=f"Question {i}",
                target_user_ids=["U111"],
            )

        questions = await question_store.get_open_questions("C456", limit=10)
        assert len(questions) == 3


# === Notification Service Tests ===

class TestNotificationService:
    """Tests for src/slack/notifications.py.

    Uses mocked Slack client and database.
    """

    @pytest.fixture
    def mock_client(self):
        """Create mock Slack WebClient."""
        client = MagicMock()
        client.chat_postMessage = MagicMock()
        return client

    @pytest.mark.asyncio
    async def test_notify_user(self, mock_client):
        """Should notify a specific user with @mention."""
        from src.slack.notifications import notify_user

        await notify_user(
            client=mock_client,
            channel_id="C123",
            thread_ts="1234567890.000001",
            user_id="U111",
            message="Please review this draft",
        )

        mock_client.chat_postMessage.assert_called_once()
        call_args = mock_client.chat_postMessage.call_args
        assert call_args.kwargs["channel"] == "C123"
        assert "<@U111>" in call_args.kwargs["text"]
        assert "review this draft" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_notify_owners_with_workitem(self, mock_client):
        """Should notify WorkItem owners."""
        from src.slack.notifications import notify_owners

        # Mock the database access via src.db module
        mock_conn_cm = MagicMock()
        mock_conn = MagicMock()
        mock_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn_cm.__aexit__ = AsyncMock()

        mock_store = MagicMock()
        mock_store.get = AsyncMock(return_value=MagicMock(
            owners=["U111", "U222"],
            watchers=[],
            created_by="U333",
        ))

        with patch("src.db.get_connection", return_value=mock_conn_cm):
            with patch("src.db.workitem_store.WorkItemStore", return_value=mock_store):
                await notify_owners(
                    client=mock_client,
                    channel_id="C123",
                    thread_ts="1234567890.000001",
                    workitem_id="test-workitem-id",
                    message="Draft needs approval",
                )

        mock_client.chat_postMessage.assert_called_once()
        call_args = mock_client.chat_postMessage.call_args
        assert "<@U111>" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_notify_respects_max_mentions(self, mock_client):
        """Should limit mentions to MAX_MENTIONS."""
        from src.slack.notifications import _send_notification, MAX_MENTIONS

        # Try to mention more than MAX_MENTIONS users
        many_users = [f"U{i}" for i in range(10)]

        _send_notification(
            client=mock_client,
            channel_id="C123",
            thread_ts="1234567890.000001",
            message="Important update",
            user_ids=many_users,
        )

        mock_client.chat_postMessage.assert_called_once()
        call_args = mock_client.chat_postMessage.call_args
        text = call_args.kwargs["text"]

        # Count mentions
        mention_count = text.count("<@U")
        assert mention_count <= MAX_MENTIONS


# === Integration-style Tests ===

class TestIntegration:
    """Lightweight integration tests without external services."""

    def test_noise_filter_with_status_card(self):
        """Verify noise filter and status card work together."""
        from src.slack.noise_filter import should_respond
        from src.slack.blocks.status_card import build_ticket_created_card

        # Simulate: user says "we need to track this"
        respond, reason = should_respond(
            message_text="we need to track this bug",
            bot_user_id="UBOT",
            is_listening_mode=True,
        )

        # If actionable, would create ticket and post card
        if respond and reason == "high_confidence_actionable":
            blocks = build_ticket_created_card(
                jira_key="SCRUM-100",
                jira_url="https://jira.example.com/browse/SCRUM-100",
                summary="Track bug from Slack",
                created_by="U123",
                issue_type="Bug",
            )
            assert len(blocks) > 0
            assert "SCRUM-100" in str(blocks)
