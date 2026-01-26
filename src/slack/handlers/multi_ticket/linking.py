"""Parent-child linking and utility functions for multi-ticket workflow.

Handles:
- Item ID extraction from action bodies
- UI version extraction for stale button detection
- Parent-child relationship utilities
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def extract_item_id(body: dict) -> Optional[str]:
    """Extract item ID from action_id.

    Action ID format: multi_ticket_edit_item:{item_id}:{ui_version}
    or multi_ticket_remove_item:{item_id}:{ui_version}

    Args:
        body: Slack action body

    Returns:
        Item ID or None if not found
    """
    actions = body.get("actions", [])
    if actions:
        action_id = actions[0].get("action_id", "")
        # Format: multi_ticket_edit_item:item_id:ui_version
        parts = action_id.split(":")
        if len(parts) >= 2:
            return parts[1]
    return None


# Alias for backward compatibility
extract_story_id = extract_item_id


def extract_ui_version(body: dict) -> int:
    """Extract ui_version from action value or action_id.

    UI version is used for stale button detection. Format in action_id:
    {action_type}:{identifier}:{ui_version}

    Or in action value: {value}:{ui_version}

    Args:
        body: Slack action body

    Returns:
        UI version number (0 if not found)
    """
    actions = body.get("actions", [])
    if not actions:
        return 0

    action = actions[0]

    # Try action_id first (format: action_type:id:version)
    action_id = action.get("action_id", "")
    parts = action_id.split(":")
    if len(parts) >= 3 and parts[-1].isdigit():
        return int(parts[-1])

    # Try action value (format: value:version)
    value = action.get("value", "")
    if ":" in value:
        version_part = value.split(":")[-1]
        if version_part.isdigit():
            return int(version_part)

    return 0


# Legacy aliases for backward compatibility with internal code
_extract_item_id = extract_item_id
_extract_story_id = extract_item_id
_extract_ui_version = extract_ui_version
