import pytest
from unittest.mock import Mock, MagicMock, patch
from src.slack.handlers import handle_member_joined_channel


class TestChannelJoinHandler:
    """Test member_joined_channel event handler."""

    def test_ignores_non_bot_user_join(self):
        """Handler ignores when non-bot user joins channel."""
        event = {
            "user": "U123456",  # Some user
            "channel": "C123456",
        }
        context = MagicMock()
        context.get.return_value = "B999999"  # Bot user ID different
        client = Mock()

        handle_member_joined_channel(event, client, context)

        # Should NOT call chat_postMessage
        client.chat_postMessage.assert_not_called()

    def test_posts_message_when_bot_joins(self):
        """Handler posts welcome message when bot joins channel."""
        bot_user_id = "B123456"
        event = {
            "user": bot_user_id,  # Bot joining
            "channel": "C123456",
        }
        context = MagicMock()
        context.get.return_value = bot_user_id
        client = Mock()

        # Mock successful post
        client.chat_postMessage.return_value = {"ts": "1234567890.123456"}

        # Patch _run_async in the module where it's used (onboarding imports from core)
        with patch('src.slack.handlers.onboarding._run_async') as mock_run_async:
            handle_member_joined_channel(event, client, context)

            # Should call _run_async with the async handler
            mock_run_async.assert_called_once()

    def test_message_posts_to_channel_root_not_thread(self):
        """Welcome message posts to channel root without thread_ts."""
        # This is a code inspection test - verify chat_postMessage call
        # doesn't include thread_ts parameter

        # Read handler code
        import inspect
        from src.slack.handlers.onboarding import _handle_channel_join_async

        source = inspect.getsource(_handle_channel_join_async)

        # Verify chat_postMessage call has explicit comment about no thread_ts
        # The comment "# EXPLICITLY no thread_ts" proves it's intentionally omitted
        assert "# explicitly no thread_ts" in source.lower(), \
            "chat_postMessage should have comment confirming no thread_ts to post to channel root"

        # Also verify thread_ts is not used as a parameter (would appear as "thread_ts=")
        assert "thread_ts=" not in source, \
            "chat_postMessage should not include thread_ts parameter"
