"""Slack integration module."""

from src.slack.app import get_slack_app, start_socket_mode, stop_socket_mode

__all__ = ["get_slack_app", "start_socket_mode", "stop_socket_mode"]
