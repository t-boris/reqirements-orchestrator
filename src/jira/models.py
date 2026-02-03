"""Jira integration models."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel


class FieldOwnership(str, Enum):
    """Who owns a Jira field."""
    JIRA_OWNED = "jira_owned"      # Jira is source of truth (status, assignee)
    SLACK_OWNED = "slack_owned"    # Slack is source of truth (description, AC)
    SHARED = "shared"              # Both can modify (needs conflict detection)


# Field ownership mapping - per spec maro_2_0.md Part 10.1
FIELD_OWNERSHIP = {
    "summary": FieldOwnership.SLACK_OWNED,
    "description": FieldOwnership.SLACK_OWNED,
    "status": FieldOwnership.JIRA_OWNED,
    "assignee": FieldOwnership.JIRA_OWNED,
    "reporter": FieldOwnership.JIRA_OWNED,
    "priority": FieldOwnership.SHARED,
    "labels": FieldOwnership.SHARED,
    "components": FieldOwnership.SHARED,
}


class PreflightResult(str, Enum):
    """Result of preflight check."""
    OK = "ok"                       # Safe to proceed
    CONFLICT = "conflict"           # Needs human resolution
    DUPLICATE = "duplicate"         # Potential duplicate found


@dataclass(frozen=True)
class FieldConflict:
    """Conflict on a specific field."""
    field: str
    slack_value: Any
    jira_value: Any
    ownership: FieldOwnership


@dataclass(frozen=True)
class PreflightCheck:
    """Result of preflight check before Jira operation."""
    result: PreflightResult
    details: str
    conflicts: tuple[FieldConflict, ...] = ()
    duplicate_keys: tuple[str, ...] = ()  # Potential duplicate Jira keys


@dataclass(frozen=True)
class SyncDiscrepancy:
    """Discrepancy between Slack entity and Jira issue."""
    entity_id: str
    jira_key: str
    field: str
    slack_value: Any
    jira_value: Any
    ownership: FieldOwnership
