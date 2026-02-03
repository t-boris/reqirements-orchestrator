"""Process orchestration for task-based workflow management.

This module provides flow templates and orchestration primitives for
guiding conversations through flexible, non-linear task execution.
"""

from src.orchestration.flows import (
    ARCHITECTURE_REVIEW,
    BATCH_CREATE,
    CONVERSE,
    CREATE_DECISION,
    CREATE_WORK_ITEM,
    FLOW_TEMPLATES,
    REVIEW,
    FlowTemplate,
    can_complete,
    get_flow_template,
    missing_context,
    suggested_next,
)
from src.orchestration.models import (
    Question,
    QuestionType,
    Task,
    TaskStatus,
    Workspace,
)

__all__ = [
    # Core classes
    "FlowTemplate",
    "Question",
    "QuestionType",
    "Task",
    "TaskStatus",
    "Workspace",
    # Predefined flows
    "CREATE_WORK_ITEM",
    "CREATE_DECISION",
    "ARCHITECTURE_REVIEW",
    "BATCH_CREATE",
    "REVIEW",
    "CONVERSE",
    # Registry
    "FLOW_TEMPLATES",
    # Helper functions
    "get_flow_template",
    "can_complete",
    "missing_context",
    "suggested_next",
]
