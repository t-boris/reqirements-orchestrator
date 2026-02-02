"""Slack integration layer.

Provides:
- AsyncApp: Bolt app for receiving Slack events
- SlackClient: Wrapper for sending messages with routing and rate limiting
- SlackMessage, SlackWriteTarget: Types for Slack communication
"""
from src.slack.app import create_bolt_app, get_bolt_app
from src.slack.client import SlackClient, RateLimiter
from src.slack.types import SlackMessage, SlackWriteTarget, WRITE_TARGETS

__all__ = [
    "create_bolt_app",
    "get_bolt_app",
    "SlackClient",
    "RateLimiter",
    "SlackMessage",
    "SlackWriteTarget",
    "WRITE_TARGETS",
]
