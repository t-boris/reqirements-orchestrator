"""Question prioritization and filtering for decision node.

Phase 28.4: Lifecycle-aware question selection.
R5: Draft must have lifecycle - Cannot ask AC while in PLAN stage
"""
import logging
from typing import TYPE_CHECKING, Optional

from src.schemas.draft import IssueType

if TYPE_CHECKING:
    from src.schemas.structured_draft import DraftLifecycle

logger = logging.getLogger(__name__)


# Plan-specific questions for PLAN lifecycle stage
PLAN_QUESTIONS = {
    "decomposition": "How should we break this down? Do you want epics only, or epics with stories?",
    "item_structure": "What items should this plan include?",
    "scope_clarification": "Should this remain a single epic, or split into multiple epics?",
}


def _filter_questions_by_lifecycle(
    missing_fields: list[str],
    lifecycle: Optional["DraftLifecycle"] = None,
    issue_type: Optional[IssueType] = None,
) -> list[str]:
    """Filter out questions inappropriate for current lifecycle/type.

    R5: Cannot ask for AC while Draft is in PLAN stage.

    Args:
        missing_fields: List of missing field names from validation.
        lifecycle: Current draft lifecycle state.
        issue_type: Primary item's issue type.

    Returns:
        Filtered list of missing fields.
    """
    from src.schemas.structured_draft import DraftLifecycle

    filtered = list(missing_fields)

    # R5: Filter out AC questions if in PLAN stage
    if lifecycle == DraftLifecycle.PLAN:
        filtered = [f for f in filtered if "acceptance_criteria" not in f.lower()]

    # Filter out AC questions for EPIC type items
    if issue_type == IssueType.EPIC:
        filtered = [f for f in filtered if "acceptance_criteria" not in f.lower()]

    return filtered


def prioritize_issues(
    missing_fields: list[str],
    conflicts: list[str],
    suggestions: list[str],
    lifecycle: Optional["DraftLifecycle"] = None,
    issue_type: Optional[IssueType] = None,
) -> list[str]:
    """Prioritize issues by impact, respecting lifecycle rules.

    Phase 28.4: Now filters questions based on lifecycle (R5) and issue type (R6).

    Order: conflicts (blockers) > missing required > suggestions (nice-to-have)
    Returns list of questions/issues, most impactful first.

    Args:
        missing_fields: List of missing field names.
        conflicts: List of conflict descriptions.
        suggestions: List of improvement suggestions.
        lifecycle: Current draft lifecycle state (for filtering).
        issue_type: Primary item's issue type (for filtering).

    Returns:
        List of prioritized questions.
    """
    questions = []

    # Conflicts are blockers - ask first
    for conflict in conflicts:
        questions.append(f"I found a conflict: {conflict}. How should we resolve this?")

    # Filter missing fields by lifecycle (R5) before generating questions
    filtered_fields = _filter_questions_by_lifecycle(
        missing_fields, lifecycle=lifecycle, issue_type=issue_type
    )

    # Missing required fields
    field_questions = {
        "title": "What should be the title/summary for this ticket?",
        "problem": "What problem are we trying to solve?",
        "acceptance_criteria": "What are the acceptance criteria? How will we know this is done?",
        "plan_items": "What items should this plan include? A plan needs at least 2 items.",
    }
    for field in filtered_fields:
        # Extract base field name
        base_field = field.split(" ")[0].strip("()")
        if base_field in field_questions:
            questions.append(field_questions[base_field])
        else:
            questions.append(f"Please provide: {field}")

    return questions


def batch_questions(questions: list[str], max_batch: int = 3) -> list[str]:
    """Batch related questions together.

    Returns at most max_batch questions to avoid overwhelming user.
    Most impactful questions first (already prioritized).
    """
    return questions[:max_batch]


def get_lifecycle_questions(
    draft,  # TicketDraft or StructuredDraft
    missing_fields: list[str],
) -> list[str]:
    """Get questions appropriate for current lifecycle stage.

    R5: Cannot ask for AC while Draft is in PLAN stage.

    Rules:
    - PLAN stage: Ask about decomposition, not AC
    - EPIC type: Ask about goal/scope, not AC
    - STORY type: Ask about AC

    Args:
        draft: The draft (TicketDraft or StructuredDraft).
        missing_fields: Raw missing fields from validation.

    Returns:
        Filtered list of missing fields appropriate for lifecycle.
    """
    from src.schemas.structured_draft import StructuredDraft, DraftLifecycle

    # If no draft or it's a legacy TicketDraft, return as-is
    if not draft or not isinstance(draft, StructuredDraft):
        return missing_fields

    # Get lifecycle and primary item type
    lifecycle = draft.lifecycle
    primary_item = draft.get_primary_item()
    issue_type = primary_item.issue_type if primary_item else None

    # Filter questions based on lifecycle and type
    filtered = _filter_questions_by_lifecycle(
        missing_fields, lifecycle=lifecycle, issue_type=issue_type
    )

    logger.debug(
        "Lifecycle-filtered questions",
        extra={
            "lifecycle": lifecycle.value if lifecycle else None,
            "issue_type": issue_type.value if issue_type else None,
            "original_count": len(missing_fields),
            "filtered_count": len(filtered),
        }
    )

    return filtered
