"""Slack integration module."""

from src.slack.app import get_slack_app, start_socket_mode, stop_socket_mode
from src.slack.history import (
    ConversationContext,
    fetch_channel_history,
    fetch_thread_history,
    format_messages_for_context,
)
from src.slack.router import register_handlers

__all__ = [
    "get_slack_app",
    "start_socket_mode",
    "stop_socket_mode",
    "register_handlers",
    "fetch_channel_history",
    "fetch_thread_history",
    "format_messages_for_context",
    "ConversationContext",
]
