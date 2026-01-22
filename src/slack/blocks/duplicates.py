"""Slack blocks for duplicate ticket handling.

Implements Rule 7: Explicit choice buttons for duplicate detection.
Shows different UI based on match confidence:
- EXACT_MATCH (>85%): Warning block with "Link" (recommended), "Update", "Create new anyway"
- LIKELY_DUPLICATE (60-85%): Info block with same buttons, no recommendation highlight
- NO_MATCH (<60%): Skip duplicate UI entirely
"""
from typing import Optional

from src.schemas.preflight import DuplicateMatch


def _get_confidence_label(confidence: float) -> str:
    """Convert confidence score to human-readable label.

    Args:
        confidence: Score from 0.0 to 1.0.

    Returns:
        Label like "92% confident" or "high confidence".
    """
    percentage = int(confidence * 100)
    return f"{percentage}% confident"


def _get_confidence_emoji(match_state: DuplicateMatch) -> str:
    """Get emoji for match state.

    Args:
        match_state: DuplicateMatch enum value.

    Returns:
        Emoji string.
    """
    if match_state == DuplicateMatch.EXACT_MATCH:
        return ":warning:"
    elif match_state == DuplicateMatch.LIKELY_DUPLICATE:
        return ":mag:"
    return ":information_source:"


def _get_source_indicator(source: str) -> tuple[str, str]:
    """Get emoji and label for match source.

    Args:
        source: Source of the match - 'channel' or 'jira'

    Returns:
        Tuple of (emoji, label) for display.
    """
    if source == "channel":
        return ":file_folder:", "Channel Registry"
    else:
        return ":jira:", "Jira"


def build_preflight_blocks(
    preflight_result: dict,
    session_id: str,
    draft_hash: str,
) -> list[dict]:
    """Build blocks for preflight duplicate detection with explicit choice buttons.

    Shows rich duplicate display with match explanation and action buttons:
    - For EXACT_MATCH: Primary = "Link to existing" (Recommended), "Update existing", Danger = "Create new anyway"
    - For LIKELY_DUPLICATE: Show info, all buttons equal weight

    Args:
        preflight_result: PreflightResult dict with match_state, duplicates, best_match
        session_id: Session ID for button value encoding
        draft_hash: Hash of draft content for version checking

    Returns:
        List of Slack block dicts for duplicate display
    """
    match_state = DuplicateMatch(preflight_result.get("match_state", "no_match"))
    duplicates = preflight_result.get("duplicates", [])
    best_match = preflight_result.get("best_match")

    if not duplicates or match_state == DuplicateMatch.NO_MATCH:
        return []

    blocks = []

    # Get best match details
    if best_match:
        key = best_match.get("key", "Unknown")
        summary = best_match.get("summary", "")[:60]
        if len(best_match.get("summary", "")) > 60:
            summary += "..."
        url = best_match.get("url", "#")
        status = best_match.get("status", "Unknown")
        assignee = best_match.get("assignee", "Unassigned") or "Unassigned"
        confidence = best_match.get("confidence", 0.0)
        match_reason = best_match.get("match_reason", "")
        source = best_match.get("source", "jira")
    else:
        # Fallback to first duplicate
        dup = duplicates[0]
        key = dup.get("key", "Unknown")
        summary = dup.get("summary", "")[:60]
        url = dup.get("url", "#")
        status = dup.get("status", "Unknown")
        assignee = dup.get("assignee", "Unassigned") or "Unassigned"
        confidence = dup.get("confidence", 0.0)
        match_reason = dup.get("match_reason", "")
        source = dup.get("source", "jira")

    emoji = _get_confidence_emoji(match_state)
    confidence_label = _get_confidence_label(confidence)
    source_emoji, source_label = _get_source_indicator(source)

    # Header based on match state and source
    if match_state == DuplicateMatch.EXACT_MATCH:
        header_text = f"{emoji} *EXACT MATCH FOUND* ({confidence_label})"
        if source == "channel":
            subtext = f"{source_emoji} _This item is already in your channel registry._"
        else:
            subtext = f"{source_emoji} _Found in Jira (not yet in channel registry)._"
    else:
        if source == "channel":
            header_text = f"{source_emoji} *Existing Work Item Found* ({confidence_label})"
            subtext = "_This item is already in your channel registry._"
        else:
            header_text = f":mag: *Similar Jira Issue Found* ({confidence_label})"
            subtext = "_Found in Jira (not yet in channel registry)._"

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": header_text,
        }
    })

    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": subtext,
        }]
    })

    blocks.append({"type": "divider"})

    # Main ticket info with source indicator
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"{source_emoji} *<{url}|{key}>*: {summary}\n"
                    f"Status: *{status}* | Assignee: {assignee} | Source: {source_label}"
        }
    })

    # Match reason (if available)
    if match_reason:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f":bulb: *Match reason:* {match_reason}"
            }]
        })

    blocks.append({"type": "divider"})

    # Question prompt
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*What would you like to do?*"
        }
    })

    # Action buttons
    # Button value encoding: session_id:draft_hash:issue_key
    has_more = len(duplicates) > 1

    if match_state == DuplicateMatch.EXACT_MATCH:
        # EXACT_MATCH: Link is primary (recommended), Create new is danger
        action_buttons = [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Link to " + key + " (Recommended)",
                    "emoji": True
                },
                "value": f"{session_id}:{draft_hash}:{key}",
                "action_id": "link_duplicate",
                "style": "primary",
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Update " + key + " with new info",
                    "emoji": True
                },
                "value": f"{session_id}:{draft_hash}:{key}",
                "action_id": "update_existing",
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Create new anyway",
                    "emoji": True
                },
                "value": f"{session_id}:{draft_hash}",
                "action_id": "create_anyway_confirm",
                "style": "danger",
            },
        ]
    else:
        # LIKELY_DUPLICATE: All buttons equal weight
        action_buttons = [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Link to " + key,
                    "emoji": True
                },
                "value": f"{session_id}:{draft_hash}:{key}",
                "action_id": "link_duplicate",
                "style": "primary",
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Update " + key,
                    "emoji": True
                },
                "value": f"{session_id}:{draft_hash}:{key}",
                "action_id": "update_existing",
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Create new",
                    "emoji": True
                },
                "value": f"{session_id}:{draft_hash}",
                "action_id": "create_anyway",
            },
        ]

    # Add "Show more" button if there are additional matches
    if has_more:
        action_buttons.append({
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": f"Show more ({len(duplicates) - 1})",
                "emoji": True
            },
            "value": f"{session_id}:{draft_hash}",
            "action_id": "show_more_duplicates",
        })

    blocks.append({
        "type": "actions",
        "elements": action_buttons
    })

    return blocks


def build_duplicate_blocks(
    potential_duplicates: list[dict],
    session_id: str,
    draft_hash: str,
    preflight_result: Optional[dict] = None,
) -> list[dict]:
    """Build blocks for duplicate detection with action buttons.

    If preflight_result is provided, uses the new preflight UI.
    Otherwise, falls back to legacy duplicate display.

    Args:
        potential_duplicates: List of dicts with key, summary, url, status, assignee, updated, match_reason
        session_id: Session ID for button value encoding
        draft_hash: Hash of draft content for version checking
        preflight_result: Optional PreflightResult dict for enhanced display

    Returns:
        List of Slack block dicts for duplicate display
    """
    # Use new preflight UI if result provided
    if preflight_result:
        return build_preflight_blocks(preflight_result, session_id, draft_hash)

    # Legacy fallback for backward compatibility
    if not potential_duplicates:
        return []

    blocks = []

    # Best match (first duplicate)
    best = potential_duplicates[0]
    key = best.get("key", "Unknown")
    summary = best.get("summary", "")[:60]
    if len(best.get("summary", "")) > 60:
        summary += "..."
    url = best.get("url", "#")
    status = best.get("status", "Unknown")
    assignee = best.get("assignee", "Unassigned") or "Unassigned"
    updated = best.get("updated", "Unknown")
    match_reason = best.get("match_reason", "")
    confidence = best.get("confidence", 0.0)
    source = best.get("source", "jira")

    # Get source indicator
    source_emoji, source_label = _get_source_indicator(source)

    # Header based on source
    if source == "channel":
        header_text = f"{source_emoji} *Existing Work Item Found*"
        intro_text = "_This item is already in your channel registry._"
    else:
        header_text = ":mag: *Similar Jira Issue Found*"
        intro_text = "_Found in Jira (not yet in channel registry)._"

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": header_text,
        }
    })

    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": intro_text,
        }]
    })

    # Main ticket info with confidence and source
    info_text = f"{source_emoji} *<{url}|{key}>* - \"{summary}\"\n"
    info_text += f"Status: {status} | Assignee: {assignee} | Source: {source_label}"
    if confidence > 0:
        info_text += f" | Confidence: {int(confidence * 100)}%"

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": info_text
        }
    })

    # Match reason (if available)
    if match_reason:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f":bulb: *This matches because:* {match_reason}"
            }]
        })

    # Action buttons
    # Button value encoding: action:session_id:draft_hash:issue_key
    has_more = len(potential_duplicates) > 1

    action_buttons = [
        {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "Link to this",
                "emoji": True
            },
            "value": f"{session_id}:{draft_hash}:{key}",
            "action_id": "link_duplicate",
            "style": "primary",
        },
        {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "Update existing",
                "emoji": True
            },
            "value": f"{session_id}:{draft_hash}:{key}",
            "action_id": "update_existing",
        },
        {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "Create new",
                "emoji": True
            },
            "value": f"{session_id}:{draft_hash}",
            "action_id": "create_anyway",
        },
    ]

    # Add "Show more" button if there are additional matches
    if has_more:
        action_buttons.append({
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": f"Show more ({len(potential_duplicates) - 1})",
                "emoji": True
            },
            "value": f"{session_id}:{draft_hash}",
            "action_id": "show_more_duplicates",
        })

    blocks.append({
        "type": "actions",
        "elements": action_buttons
    })

    return blocks


def build_create_anyway_confirmation_blocks(
    session_id: str,
    draft_hash: str,
    best_match_key: str,
    confidence: float,
) -> list[dict]:
    """Build confirmation blocks for "Create new anyway" on EXACT_MATCH.

    Requires explicit confirmation before creating a likely duplicate.

    Args:
        session_id: Session ID for button value encoding
        draft_hash: Hash of draft content for version checking
        best_match_key: The Jira key of the best match being bypassed
        confidence: Confidence score of the match being bypassed

    Returns:
        List of Slack block dicts for confirmation dialog
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: *Are you sure you want to create a new ticket?*\n\n"
                        f"This looks like a duplicate of *{best_match_key}* "
                        f"({int(confidence * 100)}% confident).\n\n"
                        f"Creating a duplicate may cause confusion and extra work."
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Go back",
                        "emoji": True
                    },
                    "value": f"{session_id}:{draft_hash}",
                    "action_id": "cancel_create_anyway",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Yes, create new ticket",
                        "emoji": True
                    },
                    "value": f"{session_id}:{draft_hash}",
                    "action_id": "create_anyway",
                    "style": "danger",
                },
            ]
        }
    ]
