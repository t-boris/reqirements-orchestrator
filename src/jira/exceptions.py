"""Jira exceptions.

Contains JiraAPIError and other Jira-specific exceptions.
"""
from typing import Any, Optional


class JiraAPIError(Exception):
    """Exception for Jira API errors."""

    def __init__(
        self,
        status_code: int,
        message: str,
        response_body: Optional[dict[str, Any]] = None,
    ):
        self.status_code = status_code
        self.message = message
        self.response_body = response_body
        super().__init__(f"Jira API error {status_code}: {message}")
