"""Task safety classification for multi-intent orchestration.

Phase 35: Multi-Intent Task Orchestration

Safety levels determine whether tasks auto-execute or require user confirmation.
Based on SuperMode (user-facing) and side effects.
"""

from typing import TYPE_CHECKING

from src.schemas.intent import Intent, SuperMode
from src.schemas.task_plan import SafetyLevel, SideEffect

if TYPE_CHECKING:
    from src.schemas.task_plan import Task

# SuperMode to default safety level
MODE_SAFETY_MAP: dict[SuperMode, SafetyLevel] = {
    SuperMode.THINK: SafetyLevel.AUTO_EXECUTE,   # Analysis, search, review
    SuperMode.CHAT: SafetyLevel.AUTO_EXECUTE,    # Discussion, meta
    SuperMode.BUILD: SafetyLevel.REQUIRES_CONFIRMATION,   # Creates Jira
    SuperMode.OPERATE: SafetyLevel.REQUIRES_CONFIRMATION,  # Modifies Jira
    SuperMode.DECIDE: SafetyLevel.REQUIRES_CONFIRMATION,   # Records decisions
}

# Intent-specific overrides (some BUILD intents are safe)
INTENT_SAFETY_OVERRIDES: dict[Intent, SafetyLevel] = {
    # These BUILD intents only create drafts, no Jira yet
    Intent.DRAFT_REFINE: SafetyLevel.AUTO_EXECUTE,
    Intent.DRAFT_TRANSFORM: SafetyLevel.AUTO_EXECUTE,
    # Search is always safe
    Intent.JIRA_SEARCH: SafetyLevel.AUTO_EXECUTE,
}

# Side effects that always require confirmation
DANGEROUS_SIDE_EFFECTS = {SideEffect.JIRA}


def classify_task_safety(task: "Task") -> SafetyLevel:
    """Determine safety level for a task.

    Priority:
    1. If task has JIRA side effect -> REQUIRES_CONFIRMATION
    2. If intent has override -> use override
    3. Fall back to mode-based classification

    Args:
        task: The Task to classify.

    Returns:
        The determined SafetyLevel.
    """
    # Rule 1: JIRA side effects always dangerous
    if SideEffect.JIRA in task.side_effects:
        return SafetyLevel.REQUIRES_CONFIRMATION

    # Rule 2: Intent-specific override
    if task.intent in INTENT_SAFETY_OVERRIDES:
        return INTENT_SAFETY_OVERRIDES[task.intent]

    # Rule 3: Mode-based default
    return MODE_SAFETY_MAP.get(task.mode, SafetyLevel.REQUIRES_CONFIRMATION)


def is_task_auto_executable(task: "Task") -> bool:
    """Check if task can execute without user confirmation.

    Args:
        task: The Task to check.

    Returns:
        True if task can auto-execute, False otherwise.
    """
    return task.safety_level == SafetyLevel.AUTO_EXECUTE


def get_tasks_needing_confirmation(tasks: list["Task"]) -> list["Task"]:
    """Filter tasks that need user approval before execution.

    Args:
        tasks: List of tasks to filter.

    Returns:
        List of tasks requiring confirmation.
    """
    return [t for t in tasks if t.safety_level == SafetyLevel.REQUIRES_CONFIRMATION]


def get_auto_executable_tasks(tasks: list["Task"]) -> list["Task"]:
    """Filter tasks that can run immediately.

    Args:
        tasks: List of tasks to filter.

    Returns:
        List of tasks that can auto-execute.
    """
    return [t for t in tasks if t.safety_level == SafetyLevel.AUTO_EXECUTE]
