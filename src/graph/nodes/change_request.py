"""Change request flow - diff-based updates to existing truth."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from src.schemas.change_request import (
    ChangeRequest,
    ChangePreview,
    ChangeTarget,
    ChangeTargetType,
    ChangeOperation,
    FieldChange,
)
from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


async def change_request_node(state: AgentState) -> dict[str, Any]:
    """Handle CHANGE_REQUEST intent.

    Flow:
    1. Identify targets (what to change)
    2. Extract changes from message
    3. Build diff preview
    4. Return preview for approval
    """
    channel_id = state.get("channel_id", "")
    thread_ts = state.get("thread_ts", "")
    user_id = state.get("user_id", "")
    message = state.get("user_message", "")

    # Extract targets from intent result
    intent_result = state.get("intent_result", {})
    target_keys = intent_result.get("change_targets", [])
    operation = intent_result.get("change_operation", "update")

    # Identify targets
    targets = await _identify_targets(channel_id, target_keys, state)

    if not targets:
        return {
            "decision_result": {
                "action": "change_request_error",
                "error": "Could not identify what you want to change. Please specify the work item or ticket.",
            }
        }

    # Extract changes using LLM
    changes = await _extract_changes(message, targets, state)

    # Build change request
    request = ChangeRequest(
        request_id=str(uuid.uuid4()),
        channel_id=channel_id,
        thread_ts=thread_ts,
        requester_id=user_id,
        operation=ChangeOperation(operation) if operation else ChangeOperation.UPDATE,
        targets=targets,
        changes=changes,
        reason=message,
        created_at=datetime.now(timezone.utc),
    )

    # Build preview
    preview = await _build_preview(request, state)

    logger.info(
        "Change request created",
        extra={
            "request_id": request.request_id,
            "operation": request.operation.value,
            "targets": [t.target_id for t in targets],
            "changes_count": len(changes),
        }
    )

    return {
        "decision_result": {
            "action": "change_request_preview",
            "request": request.model_dump(),
            "preview": preview.model_dump(),
        }
    }


async def _identify_targets(
    channel_id: str,
    target_keys: list[str],
    state: AgentState,
) -> list[ChangeTarget]:
    """Identify targets for the change request."""
    targets = []

    for key in target_keys:
        # Check if it's a Jira key (e.g., SCRUM-123)
        if "-" in key and key.split("-")[0].isalpha():
            targets.append(ChangeTarget(
                target_type=ChangeTargetType.JIRA_ISSUE,
                target_id=key,
                target_summary=None,  # Will be fetched
            ))
        else:
            # Assume workitem_id
            targets.append(ChangeTarget(
                target_type=ChangeTargetType.WORKITEM,
                target_id=key,
            ))

    # If no explicit targets, check for "last" or contextual references
    if not targets:
        last_workitem = state.get("last_workitem_id")
        if last_workitem:
            targets.append(ChangeTarget(
                target_type=ChangeTargetType.WORKITEM,
                target_id=last_workitem,
            ))

    return targets


async def _extract_changes(
    message: str,
    targets: list[ChangeTarget],
    state: AgentState,
) -> list[FieldChange]:
    """Extract field changes from message using LLM."""
    # For now, return placeholder - will use LLM extraction
    # Similar to ticket extraction but for changes

    changes = []

    # Simple pattern matching for common changes
    message_lower = message.lower()

    if "priority" in message_lower:
        if "high" in message_lower:
            changes.append(FieldChange(field="priority", old_value="Medium", new_value="High"))
        elif "critical" in message_lower:
            changes.append(FieldChange(field="priority", old_value="High", new_value="Critical"))

    if "rename" in message_lower or "title" in message_lower:
        # Would extract new title from message
        pass

    return changes


async def _build_preview(
    request: ChangeRequest,
    state: AgentState,
) -> ChangePreview:
    """Build human-readable preview of changes."""
    lines = []
    warnings = []

    for target in request.targets:
        lines.append(f"*Target:* {target.target_type.value} `{target.target_id}`")

    if request.changes:
        lines.append("\n*Changes:*")
        for change in request.changes:
            lines.append(f"- `{change.field}`: {change.old_value} -> {change.new_value}")
    else:
        lines.append("\n_No specific field changes detected._")
        warnings.append("Could not extract specific changes. Please clarify what you want to modify.")

    # Check if Jira sync needed
    requires_jira = any(
        t.target_type == ChangeTargetType.JIRA_ISSUE
        for t in request.targets
    )

    if requires_jira:
        lines.append("\n:warning: *This will update Jira.*")

    return ChangePreview(
        request=request,
        affected_items=[],  # Would fetch current state
        preview_text="\n".join(lines),
        warnings=warnings,
        requires_jira_sync=requires_jira,
    )
