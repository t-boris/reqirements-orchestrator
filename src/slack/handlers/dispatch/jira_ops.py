"""Jira operations dispatch handlers.

Handles sync, search, change requests, and OPS responses.
Ticket action handlers are in ticket_action.py.
"""

import logging
from typing import TYPE_CHECKING, Optional

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity

if TYPE_CHECKING:
    from src.sync.preflight import PreflightResult

logger = logging.getLogger(__name__)

# Content extraction prompts for ticket operations (Phase 16)
UPDATE_EXTRACTION_PROMPT = '''Based on this conversation, extract what should be added to the Jira ticket description.

User request: {user_message}

Review context (if available):
{review_context}

Return the content to add to the ticket description.
Be concise and structured. Use Jira formatting:
- h3. for headers
- * for bullet points
- Keep it factual and actionable
'''

COMMENT_EXTRACTION_PROMPT = '''Extract a comment to add to the Jira ticket based on this request.

User request: {user_message}

Review context (if available):
{review_context}

Return a concise comment summarizing the key points. 1-3 sentences.
'''

# Re-export STORY_GENERATION_PROMPT from ticket_action
from src.slack.handlers.dispatch.ticket_action import STORY_GENERATION_PROMPT


async def _extract_update_content(
    result: dict,
    client: WebClient,
    channel_id: str,
    thread_ts: str,
) -> str:
    """Extract update content from conversation context using LLM.

    Fetches thread history to provide actual context for the update.
    """
    from src.llm import get_llm
    from src.slack.history import fetch_thread_history, format_messages_for_context

    # Get user message and review context
    user_message = result.get("user_message", "")
    review_context = result.get("review_context", {})
    review_summary = review_context.get("review_summary", "") if review_context else ""

    # Fetch thread history for actual context
    thread_context = ""
    if thread_ts:
        thread_messages = fetch_thread_history(client, channel_id, thread_ts)
        if thread_messages:
            thread_context = format_messages_for_context(thread_messages)

    llm = get_llm()

    # Enhanced prompt with thread context
    enhanced_prompt = f'''Based on this conversation, extract what should be added to the Jira ticket description.

User request: {user_message}

Thread conversation:
{thread_context if thread_context else "No thread context available"}

Review context (if available):
{review_summary or "No review context available"}

Return the content to add to the ticket description.
Be concise and structured. Use Jira formatting:
- h3. for headers
- * for bullet points
- Keep it factual and actionable

Focus on extracting key requirements, decisions, and technical details from the conversation.
'''

    return await llm.chat(enhanced_prompt)


async def _extract_comment_content(
    result: dict,
) -> str:
    """Extract comment content from conversation context using LLM."""
    from src.llm import get_llm

    user_message = result.get("user_message", "")
    review_context = result.get("review_context", {})
    review_summary = review_context.get("review_summary", "") if review_context else ""

    llm = get_llm()
    prompt = COMMENT_EXTRACTION_PROMPT.format(
        user_message=user_message,
        review_context=review_summary or "No review context available",
    )

    return await llm.chat(prompt)


async def _check_preflight_for_action(
    channel_id: str,
    ticket_key: str,
    action_type: str,
    fields_to_update: Optional[dict] = None,
    target_status: Optional[str] = None,
) -> Optional["PreflightResult"]:
    """Check preflight before ticket action.

    Runs preflight check for update or transition operations.

    Args:
        channel_id: Slack channel ID.
        ticket_key: Jira ticket key.
        action_type: Type of action ("update" or "transition").
        fields_to_update: Dict of fields to update (for update action).
        target_status: Target status (for transition action).

    Returns:
        PreflightResult if conflict detected, None if safe to proceed.
    """
    from src.sync.preflight import PreflightService, ConflictType
    from src.jira.client import JiraService
    from src.db.jira_registry import JiraRegistryStore
    from src.db import get_connection
    from src.config.settings import get_settings

    try:
        settings = get_settings()
        jira_service = JiraService(settings)

        async with get_connection() as conn:
            registry = JiraRegistryStore(conn)
            await registry.create_tables()

            preflight = PreflightService(jira_service, registry)

            if action_type == "transition" and target_status:
                result = await preflight.check_transition(
                    channel_id, ticket_key, target_status
                )
            elif action_type == "update" and fields_to_update:
                result = await preflight.check_update(
                    channel_id, ticket_key, fields_to_update
                )
            else:
                await jira_service.close()
                return None

            await jira_service.close()

            # IDEMPOTENT auto-succeeds without UI
            if result.conflict_type == ConflictType.IDEMPOTENT:
                logger.info(
                    "Preflight: IDEMPOTENT - operation already done",
                    extra={
                        "ticket_key": ticket_key,
                        "action_type": action_type,
                    }
                )
                return result  # Return so caller can handle auto-success messaging

            # For SAFE_DRIFT, REAL_CONFLICT, STRUCTURAL - return result for UI
            if result.needs_choice:
                return result

            return None

    except Exception as e:
        logger.warning(f"Preflight check failed, proceeding: {e}")
        return None


# Re-export ticket action handlers for backward compatibility
from src.slack.handlers.dispatch.ticket_action import (
    _handle_ticket_action,
    _handle_create_stories,
)


async def _handle_sync_request(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
) -> None:
    """Handle sync_request action - run sync analysis and show summary.

    Triggered by "@Maro update Jira issues" or similar sync phrases.
    Uses the new JiraSyncService for comprehensive reconciliation report (Phase 29-03).
    """
    from src.slack.handlers.sync import handle_sync_command

    channel_id = result.get("channel_id") or identity.channel_id
    user_id = identity.user_id if hasattr(identity, "user_id") else "system"
    thread_ts = result.get("thread_ts") or identity.thread_ts

    # Run sync analysis with new diagnostic command
    await handle_sync_command(
        client=client,
        channel_id=channel_id,
        user_id=user_id,
        thread_ts=thread_ts,
    )


async def _handle_jira_search(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
) -> None:
    """Handle jira_search action - search Jira for existing issues.

    Triggered by "check Jira for similar issues" or similar search phrases.
    """
    from src.skills.jira_search import jira_search
    from src.jira.client import JiraService
    from src.config import get_settings

    search_query = result.get("search_query")
    channel_id = result.get("channel_id") or identity.channel_id
    thread_ts = result.get("thread_ts") or identity.thread_ts

    if not search_query:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="I couldn't determine what to search for. Please be more specific about what issues you're looking for.",
        )
        return

    # Post searching status
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f":mag: Searching Jira for: *{search_query[:100]}*...",
    )

    settings = get_settings()
    jira_service = JiraService(settings)

    try:
        search_result = await jira_search(
            query=search_query,
            jira_service=jira_service,
            limit=10,
        )

        if not search_result.issues:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"No existing issues found for: *{search_query[:100]}*\n\nYou can ask me to create a new ticket if needed.",
            )
            return

        # Format results
        issues = search_result.issues
        jira_base_url = settings.jira_base_url.rstrip("/")

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":mag: Found *{len(issues)}* existing issue(s) for: *{search_query[:100]}*",
                }
            },
            {"type": "divider"},
        ]

        for issue in issues[:10]:
            issue_url = f"{jira_base_url}/browse/{issue.key}"
            status = issue.status or "Unknown"
            issue_type = issue.issue_type or "Issue"

            # Build issue summary block
            issue_text = f"<{issue_url}|*{issue.key}*> - {issue.summary}\n"
            issue_text += f"Type: {issue_type} | Status: {status}"
            if issue.assignee:
                issue_text += f" | Assignee: {issue.assignee}"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": issue_text,
                }
            })

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=blocks,
            text=f"Found {len(issues)} existing issues",
        )

    except Exception as e:
        logger.error(f"Jira search failed: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Sorry, I encountered an error searching Jira: {str(e)}",
        )
    finally:
        await jira_service.close()


async def _handle_change_request_preview(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    result: dict,
) -> None:
    """Handle change request preview display."""
    from src.slack.blocks.change_request import build_change_preview_blocks
    from src.schemas.change_request import ChangePreview, ChangeRequest

    preview = ChangePreview(**result["preview"])
    request = ChangeRequest(**result["request"])

    blocks = build_change_preview_blocks(preview, request)

    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=blocks,
        text="Change request preview",
    )


async def _handle_ops_response(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
) -> None:
    """Handle OPS response - debug, explain, or expand.

    Formats response based on subtype:
    - DEBUG: System operator style with triage info
    - EXPLAIN: Policy trace format (about bot's reasoning)
    - EXPAND: Show object details (decision rationale, alternatives, etc.)

    Args:
        result: Decision result with message and subtype
        identity: Session identity
        client: Slack WebClient
    """
    # Import expand handler from decision module
    from src.slack.handlers.dispatch.decision import _handle_expand_decision

    ops_msg = result.get("message", "")
    subtype = result.get("subtype", "debug")
    timestamp = result.get("timestamp", "")

    # EXPAND subtype: Show rich decision card if decision_id present
    if subtype == "expand":
        decision_id = result.get("decision_id")
        if decision_id:
            await _handle_expand_decision(
                decision_id=decision_id,
                identity=identity,
                client=client,
                additional_context=ops_msg,
            )
            return
        # Fall through to text response if no decision_id

    if not ops_msg:
        ops_msg = "I couldn't generate a response."

    # Format prefix based on subtype
    if subtype == "expand":
        prefix = ":mag: *Decision Details*\n\n"
    elif subtype == "explain":
        prefix = ":brain: *MARO Explain*\n\n"
    else:  # debug
        prefix = ":wrench: *MARO Debug*\n\n"

    # Build blocks for richer formatting
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": prefix + ops_msg
            }
        }
    ]

    # Add timestamp context for debug responses
    if timestamp and subtype == "debug":
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Analysis generated at {timestamp[:19]}"
                }
            ]
        })

    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts if identity.thread_ts else None,
        blocks=blocks,
        text=ops_msg[:200],  # Fallback text
    )

    logger.info(
        "OPS response sent",
        extra={
            "channel_id": identity.channel_id,
            "thread_ts": identity.thread_ts,
            "subtype": subtype,
        }
    )
