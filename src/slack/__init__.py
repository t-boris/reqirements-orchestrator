"""Slack integration layer."""

from src.slack.app import create_bolt_app, get_bolt_app

__all__ = ["create_bolt_app", "get_bolt_app"]
