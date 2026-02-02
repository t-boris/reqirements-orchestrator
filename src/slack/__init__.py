"""Slack integration layer.

Provides:
- AsyncApp: Bolt app for receiving Slack events
- SlackClient: Wrapper for sending messages with routing and rate limiting
- SlackMessage, SlackWriteTarget: Types for Slack communication
- Block builders: Build Block Kit messages
- DashboardManager: Manage channel status dashboards
- Handlers: Event, action, and command handlers
"""
from src.slack.app import create_bolt_app, get_bolt_app
from src.slack.client import SlackClient, RateLimiter
from src.slack.types import SlackMessage, SlackWriteTarget, WRITE_TARGETS
from src.slack.dashboard import DashboardManager, ChannelDashboard
from src.slack.blocks import (
    build_approval_blocks,
    build_decision_blocks,
    build_dashboard_blocks,
    build_error_blocks,
    build_help_blocks,
)
from src.slack.handlers import (
    register_event_handlers,
    register_action_handlers,
    register_command_handlers,
)

__all__ = [
    # App
    "create_bolt_app",
    "get_bolt_app",
    # Client
    "SlackClient",
    "RateLimiter",
    # Types
    "SlackMessage",
    "SlackWriteTarget",
    "WRITE_TARGETS",
    # Dashboard
    "DashboardManager",
    "ChannelDashboard",
    # Blocks
    "build_approval_blocks",
    "build_decision_blocks",
    "build_dashboard_blocks",
    "build_error_blocks",
    "build_help_blocks",
    # Handlers
    "register_event_handlers",
    "register_action_handlers",
    "register_command_handlers",
]
