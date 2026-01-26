"""Draft creation and preflight check helpers.

Contains preflight duplicate checking and block building for draft creation flow.

Phase 29.4: Preflight Sync integration.
- Check for duplicate tickets before creation
- Handle IDEMPOTENT (auto-link) and REAL_CONFLICT (similar exists) scenarios
"""

import json
import logging
from typing import TYPE_CHECKING, Optional

from slack_sdk.web import WebClient

if TYPE_CHECKING:
    from src.schemas.draft import TicketDraft
    from src.jira.client import JiraService
    from src.db.jira_registry import JiraRegistryStore

logger = logging.getLogger(__name__)


async def check_preflight_for_create(
    jira_service: "JiraService",
    registry: "JiraRegistryStore",
    channel_id: str,
    draft_title: str,
    draft_problem: Optional[str] = None,
) -> dict | None:
    """Check if similar ticket exists before create.

    For creates, we check if summary matches existing tracked ticket
    (potential duplicate scenario).

    Args:
        jira_service: JiraService instance for API calls.
        registry: JiraRegistryStore for local state lookups.
        channel_id: Slack channel ID.
        draft_title: Title/summary of the draft to create.
        draft_problem: Optional problem statement for better matching.

    Returns:
        None if no preflight needed (proceed normally).
        Dict with conflict info if duplicate detected:
        - conflict_type: "idempotent" or "potential_duplicate"
        - existing_key: Jira key of existing issue
        - existing_url: URL to existing issue
        - existing_summary: Summary of existing issue
        - message: Human-readable explanation
    """
    if not draft_title:
        return None

    # Check registry for issues with similar summary in this channel
    # Case-insensitive partial match
    channel_issues = await registry.get_channel_issues(channel_id, limit=100)

    draft_title_lower = draft_title.lower().strip()

    for issue in channel_issues:
        if not issue.summary:
            continue

        existing_summary_lower = issue.summary.lower().strip()

        # Check for exact match (idempotent)
        if draft_title_lower == existing_summary_lower:
            from src.config.settings import get_settings
            settings = get_settings()
            issue_url = f"{settings.jira_url.rstrip('/')}/browse/{issue.jira_key}"

            return {
                "conflict_type": "idempotent",
                "existing_key": issue.jira_key,
                "existing_url": issue_url,
                "existing_summary": issue.summary,
                "message": (
                    f"A ticket with the same title already exists: "
                    f"*{issue.jira_key}*\n\n"
                    f"Would you like to link to this existing ticket instead of creating a new one?"
                ),
            }

        # Check for high similarity (potential duplicate)
        # Simple check: if one title contains the other, or >80% word overlap
        if (draft_title_lower in existing_summary_lower or
            existing_summary_lower in draft_title_lower):
            # Potential duplicate
            from src.config.settings import get_settings
            settings = get_settings()
            issue_url = f"{settings.jira_url.rstrip('/')}/browse/{issue.jira_key}"

            return {
                "conflict_type": "potential_duplicate",
                "existing_key": issue.jira_key,
                "existing_url": issue_url,
                "existing_summary": issue.summary,
                "message": (
                    f"A similar ticket may already exist: "
                    f"*<{issue_url}|{issue.jira_key}>* - {issue.summary}\n\n"
                    f"Do you still want to create a new ticket?"
                ),
            }

    return None


def build_create_preflight_blocks(
    preflight_result: dict,
    session_id: str,
    draft_hash: str,
    channel_id: str,
    thread_ts: str,
) -> list[dict]:
    """Build Slack blocks for create preflight conflict.

    Shows conflict message and action buttons:
    - For idempotent: "Link to existing" / "Create anyway" / "Cancel"
    - For potential_duplicate: "Create anyway" / "View existing" / "Cancel"

    Args:
        preflight_result: Dict from check_preflight_for_create.
        session_id: Session ID for button payload.
        draft_hash: Draft hash for button payload.
        channel_id: Channel ID for button payload.
        thread_ts: Thread timestamp for button payload.

    Returns:
        List of Slack Block Kit blocks.
    """
    conflict_type = preflight_result["conflict_type"]
    existing_key = preflight_result["existing_key"]
    existing_url = preflight_result["existing_url"]
    existing_summary = preflight_result["existing_summary"]
    message = preflight_result["message"]

    blocks: list[dict] = []

    # Header based on conflict type
    if conflict_type == "idempotent":
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":information_source: *Duplicate Detected*\n\n{message}",
            },
        })
    else:  # potential_duplicate
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: *Similar Ticket Found*\n\n{message}",
            },
        })

    # Existing ticket details
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Existing:* <{existing_url}|{existing_key}> - {existing_summary}",
        },
    })

    blocks.append({"type": "divider"})

    # Build button payload
    payload = json.dumps({
        "session_id": session_id,
        "draft_hash": draft_hash,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "existing_key": existing_key,
        "conflict_type": conflict_type,
    })

    # Action buttons
    if conflict_type == "idempotent":
        # Exact match - offer to link instead
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Link to existing", "emoji": True},
                    "style": "primary",
                    "action_id": "preflight_link_existing",
                    "value": payload,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Create anyway", "emoji": True},
                    "action_id": "preflight_proceed",
                    "value": payload,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel", "emoji": True},
                    "action_id": "preflight_cancel",
                    "value": payload,
                },
            ],
        })
    else:
        # Potential duplicate - create is primary action
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Create anyway", "emoji": True},
                    "style": "primary",
                    "action_id": "preflight_proceed",
                    "value": payload,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View existing", "emoji": True},
                    "action_id": "preflight_view_existing",
                    "value": payload,
                    "url": existing_url,  # Opens in browser
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel", "emoji": True},
                    "action_id": "preflight_cancel",
                    "value": payload,
                },
            ],
        })

    return blocks


def build_ticket_announcement_blocks(
    draft: "TicketDraft",
    jira_key: str,
    jira_url: str,
    created_by: str,
    thread_ts: str,
    channel: str,
    client: WebClient,
) -> list[dict]:
    """Build announcement blocks for main channel notification.

    Uses status card format (Phase 27.6) for consistent channel visibility.
    Creates a card with:
    - Ticket key and title (linked)
    - Who created it
    - Link to the thread

    Args:
        draft: The ticket draft that was created
        jira_key: Created Jira ticket key (e.g., SCRUM-113)
        jira_url: URL to the Jira ticket
        created_by: Slack user ID who created the ticket
        thread_ts: Thread timestamp for permalink
        channel: Channel ID for permalink
        client: Slack client for getting permalink

    Returns:
        List of Slack blocks for the announcement
    """
    from src.slack.blocks.status_card import build_ticket_created_card

    # Get thread permalink
    thread_link = ""
    try:
        result = client.chat_getPermalink(channel=channel, message_ts=thread_ts)
        thread_link = result.get("permalink", "")
    except Exception as e:
        logger.warning(f"Failed to get thread permalink: {e}")

    # Use status card block builder for consistent format (Phase 27.6)
    return build_ticket_created_card(
        jira_key=jira_key,
        jira_url=jira_url,
        summary=draft.title or "Untitled",
        created_by=created_by,
        thread_link=thread_link or None,
        issue_type=draft.issue_type or "Task",
    )
