"""Draft validation helpers for StructuredDraft.

Provides validation functions for draft operations.
Split from structured_draft.py for modularization.
"""
from typing import TYPE_CHECKING

from src.schemas.draft import IssueType

if TYPE_CHECKING:
    from src.schemas.structured_draft import (
        DraftItem,
        DraftLifecycle,
        StructuredDraft,
    )


def validate_lifecycle_transition(
    current: "DraftLifecycle",
    target: "DraftLifecycle",
) -> tuple[bool, str]:
    """Validate if a lifecycle transition is allowed.

    Args:
        current: Current lifecycle state.
        target: Target lifecycle state.

    Returns:
        Tuple of (is_valid, error_message).
    """
    from src.schemas.structured_draft import DraftLifecycle

    # Valid transitions map
    valid_transitions: dict["DraftLifecycle", set["DraftLifecycle"]] = {
        DraftLifecycle.EMPTY: {DraftLifecycle.SINGLE_ITEM, DraftLifecycle.PLAN},
        DraftLifecycle.SINGLE_ITEM: {
            DraftLifecycle.PLAN,
            DraftLifecycle.APPROVED,
            DraftLifecycle.EMPTY,
        },
        DraftLifecycle.PLAN: {
            DraftLifecycle.PLAN_REFINED,
            DraftLifecycle.APPROVED,
            DraftLifecycle.EMPTY,
        },
        DraftLifecycle.PLAN_REFINED: {
            DraftLifecycle.APPROVED,
            DraftLifecycle.PLAN,
            DraftLifecycle.EMPTY,
        },
        DraftLifecycle.APPROVED: {
            DraftLifecycle.COMMITTED,
            DraftLifecycle.PLAN_REFINED,
            DraftLifecycle.SINGLE_ITEM,
            DraftLifecycle.PLAN,
        },
        DraftLifecycle.COMMITTED: set(),  # Terminal state
    }

    if current == target:
        return True, ""

    if target in valid_transitions.get(current, set()):
        return True, ""

    return False, f"Cannot transition from {current.value} to {target.value}"


def validate_item_content(item: "DraftItem") -> list[str]:
    """Validate a draft item's content.

    Args:
        item: The DraftItem to validate.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors = []

    if not item.title.strip():
        errors.append(f"Item {item.id[:8]} has no title")

    if item.issue_type == IssueType.EPIC:
        if not item.goal.strip() and not item.problem.strip():
            errors.append(f"Epic {item.id[:8]} should have a goal or problem statement")

    if item.issue_type == IssueType.STORY:
        if not item.acceptance_criteria:
            # Warning, not error
            pass  # Stories without AC are allowed but not ideal

    return errors


def validate_draft_structure(draft: "StructuredDraft") -> list[str]:
    """Validate the overall structure of a draft.

    Checks for:
    - Orphaned stories (parent_id pointing to non-existent epic)
    - Circular references
    - Invalid parent types

    Args:
        draft: The StructuredDraft to validate.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors = []

    # Build item ID set for reference checking
    item_ids = {item.id for item in draft.items}

    for item in draft.items:
        # Check orphaned references
        if item.parent_id and item.parent_id not in item_ids:
            errors.append(f"Item {item.id[:8]} references non-existent parent {item.parent_id[:8]}")

        # Check parent type validity
        if item.parent_id:
            parent = next((i for i in draft.items if i.id == item.parent_id), None)
            if parent and parent.issue_type != IssueType.EPIC:
                errors.append(
                    f"Item {item.id[:8]} has parent {parent.id[:8]} "
                    f"which is not an epic (is {parent.issue_type.value})"
                )

    return errors


def validate_draft_for_commit(draft: "StructuredDraft") -> list[str]:
    """Validate a draft is ready for commit to Jira.

    Args:
        draft: The StructuredDraft to validate.

    Returns:
        List of validation error messages (empty if valid).
    """
    from src.schemas.structured_draft import DraftItemStatus, DraftLifecycle

    errors = []

    # Check lifecycle
    if draft.lifecycle != DraftLifecycle.APPROVED:
        errors.append(f"Draft must be APPROVED to commit (is {draft.lifecycle.value})")

    # Check all items are approved
    for item in draft.items:
        if item.status != DraftItemStatus.APPROVED:
            errors.append(f"Item {item.id[:8]} is not approved (is {item.status.value})")

    # Validate item content
    for item in draft.items:
        content_errors = validate_item_content(item)
        errors.extend(content_errors)

    # Validate structure
    structure_errors = validate_draft_structure(draft)
    errors.extend(structure_errors)

    return errors


def validate_item_for_approval(item: "DraftItem") -> list[str]:
    """Validate an item is ready for approval.

    Args:
        item: The DraftItem to validate.

    Returns:
        List of validation error messages (empty if valid).
    """
    from src.schemas.structured_draft import DraftItemStatus

    errors = []

    if item.status != DraftItemStatus.PROPOSED:
        errors.append(f"Item must be PROPOSED to approve (is {item.status.value})")

    if not item.title.strip():
        errors.append("Item must have a title")

    # For epics, require goal or problem
    if item.issue_type == IssueType.EPIC:
        if not item.goal.strip() and not item.problem.strip():
            errors.append("Epic must have a goal or problem statement")

    return errors


def get_missing_fields(item: "DraftItem") -> list[str]:
    """Get list of missing/empty fields on an item.

    Args:
        item: The DraftItem to check.

    Returns:
        List of field names that are missing or empty.
    """
    missing = []

    if not item.title.strip():
        missing.append("title")
    if not item.goal.strip():
        missing.append("goal")
    if not item.problem.strip():
        missing.append("problem")
    if not item.proposed_solution.strip():
        missing.append("proposed_solution")
    if not item.acceptance_criteria:
        missing.append("acceptance_criteria")
    if not item.constraints:
        missing.append("constraints")

    return missing


def calculate_item_completeness(item: "DraftItem") -> float:
    """Calculate completeness score for an item (0.0 to 1.0).

    Scoring weights:
    - title: 0.2
    - goal: 0.2
    - problem: 0.1
    - proposed_solution: 0.2
    - acceptance_criteria: 0.2
    - constraints: 0.1

    Args:
        item: The DraftItem to score.

    Returns:
        Completeness score from 0.0 to 1.0.
    """
    score = 0.0

    if item.title.strip():
        score += 0.2
    if item.goal.strip():
        score += 0.2
    if item.problem.strip():
        score += 0.1
    if item.proposed_solution.strip():
        score += 0.2
    if item.acceptance_criteria:
        score += 0.2
    if item.constraints:
        score += 0.1

    return min(score, 1.0)


def calculate_draft_completeness(draft: "StructuredDraft") -> float:
    """Calculate overall completeness score for a draft.

    Average of all item completeness scores.

    Args:
        draft: The StructuredDraft to score.

    Returns:
        Completeness score from 0.0 to 1.0.
    """
    if not draft.items:
        return 0.0

    total = sum(calculate_item_completeness(item) for item in draft.items)
    return total / len(draft.items)
