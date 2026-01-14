"""Slack event handlers with fast-ack pattern."""

import asyncio
import logging
from slack_bolt import Ack, BoltContext
from slack_bolt.kwargs_injection.args import Args
from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner

logger = logging.getLogger(__name__)


def handle_app_mention(event: dict, say, client: WebClient, context: BoltContext):
    """Handle @mention events - start or continue conversation.

    Pattern: Ack fast, process async.
    """
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")  # Reply in thread
    user = event.get("user")
    text = event.get("text", "")

    logger.info(
        "App mention received",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "user": user,
            "text_preview": text[:100] if text else "",
        }
    )

    # Create session identity
    team_id = context.get("team_id", "")
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    # Run async processing in background
    asyncio.ensure_future(_process_mention(identity, text, user, client, thread_ts, channel))


async def _process_mention(
    identity: SessionIdentity,
    text: str,
    user: str,
    client: WebClient,
    thread_ts: str,
    channel: str,
):
    """Async processing for @mention - runs graph."""
    try:
        runner = get_runner(identity)
        result = await runner.run_with_message(text, user)

        # Handle result
        if result["action"] == "ask":
            # Format questions as bullet list
            questions_text = "I need a bit more information:\n"
            for q in result["questions"]:
                questions_text += f"• {q}\n"
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=questions_text,
            )
        elif result["action"] == "preview":
            # Show preview with approval buttons
            from src.slack.blocks import build_draft_preview_blocks
            blocks = build_draft_preview_blocks(result["draft"])
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Here's the ticket preview:",
                blocks=blocks,
            )
        elif result["action"] == "ready":
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Ticket approved and ready to create in Jira!",
            )
        elif result["action"] == "error":
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"Sorry, I encountered an error: {result.get('error', 'Unknown error')}",
            )
        else:
            # Continue - no response needed
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Got it! I'm collecting the requirements.",
            )

    except Exception as e:
        logger.error(f"Error processing mention: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Sorry, something went wrong. Please try again.",
        )


def handle_message(event: dict, say, client: WebClient, context: BoltContext):
    """Handle message events in threads where bot is already participating.

    Only processes:
    - Messages in threads (has thread_ts)
    - Non-bot messages
    - Non-edited messages
    """
    # Skip non-thread messages (channel root)
    if "thread_ts" not in event:
        return

    # Skip bot messages
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    # Skip message edits/deletes
    subtype = event.get("subtype")
    if subtype in ("message_changed", "message_deleted"):
        return

    channel = event.get("channel")
    thread_ts = event["thread_ts"]
    user = event.get("user")
    text = event.get("text", "")

    logger.info(
        "Thread message received",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "user": user,
        }
    )

    # Create session identity
    team_id = context.get("team_id", "")
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    # Check if we have an active session for this thread
    from src.graph.runner import _runners
    if identity.session_id in _runners:
        # Active session - process message
        asyncio.ensure_future(_process_thread_message(identity, text, user, client, thread_ts, channel))


async def _process_thread_message(
    identity: SessionIdentity,
    text: str,
    user: str,
    client: WebClient,
    thread_ts: str,
    channel: str,
):
    """Async processing for thread message - continues graph."""
    try:
        runner = get_runner(identity)
        result = await runner.run_with_message(text, user)

        # Handle result (same as _process_mention)
        if result["action"] == "ask":
            questions_text = "I need a bit more information:\n"
            for q in result["questions"]:
                questions_text += f"• {q}\n"
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=questions_text,
            )
        elif result["action"] == "preview":
            from src.slack.blocks import build_draft_preview_blocks
            blocks = build_draft_preview_blocks(result["draft"])
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Here's the ticket preview:",
                blocks=blocks,
            )
        elif result["action"] == "ready":
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Ticket approved and ready to create in Jira!",
            )
        elif result["action"] == "error":
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"Sorry, I encountered an error: {result.get('error', 'Unknown error')}",
            )
        # For "continue" - no response needed, silently processing

    except Exception as e:
        logger.error(f"Error processing thread message: {e}", exc_info=True)


def handle_jira_command(ack: Ack, command: dict, say, client: WebClient):
    """Handle /jira slash command with subcommands.

    Subcommands:
    - /jira create [type] - Start new ticket session
    - /jira search <query> - Search existing tickets
    - /jira status - Show current session status
    """
    ack()  # Ack immediately

    channel = command.get("channel_id")
    user = command.get("user_id")
    text = command.get("text", "").strip()

    # Parse subcommand
    parts = text.split(maxsplit=1)
    subcommand = parts[0].lower() if parts else "help"
    args = parts[1] if len(parts) > 1 else ""

    logger.info(
        "Jira command received",
        extra={
            "channel": channel,
            "user": user,
            "subcommand": subcommand,
            "args": args,
        }
    )

    if subcommand == "create":
        ticket_type = args.capitalize() if args else None
        say(
            text=f"Starting new ticket session{' for ' + ticket_type if ticket_type else ''}...",
            channel=channel,
        )
        # TODO: Route to session creation in 04-04

    elif subcommand == "search":
        if not args:
            say(text="Usage: /jira search <query>", channel=channel)
            return
        say(text=f"Searching for: {args}...", channel=channel)
        # TODO: Implement Jira search in Phase 7

    elif subcommand == "status":
        say(text="No active session in this channel.", channel=channel)
        # TODO: Query session status in 04-04

    else:
        say(
            text="Available commands:\n• `/jira create [type]` - Start new ticket\n• `/jira search <query>` - Search tickets\n• `/jira status` - Session status",
            channel=channel,
        )


async def handle_epic_selection(ack, body, client: WebClient, action):
    """Handle Epic selection button click.

    Called when user clicks one of the Epic selection buttons in the selector UI.
    Binds the session to the selected Epic and posts a session card.
    """
    ack()

    epic_key = action.get("value")
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    team_id = body["team"]["id"]

    logger.info(
        "Epic selection received",
        extra={
            "epic_key": epic_key,
            "channel": channel,
            "thread_ts": thread_ts,
        }
    )

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    if epic_key == "new":
        # User wants to create new Epic
        # For now, create a placeholder - full creation in Phase 7
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Creating new Epic... (This will create a Jira Epic in Phase 7)",
        )
        return

    # Bind to selected Epic
    from src.slack.binding import bind_epic
    from src.db.session_store import SessionStore
    from src.db.connection import get_connection

    async with get_connection() as conn:
        store = SessionStore(conn)
        await bind_epic(identity, epic_key, store, client)


def handle_epic_selection_sync(ack, body, client: WebClient, action):
    """Synchronous wrapper for handle_epic_selection.

    Bolt may call handlers from a sync context. This wraps the async handler.
    """
    ack()

    # Run the async handler in the event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Create a future and run the coroutine
            asyncio.ensure_future(_handle_epic_selection_async(body, client, action))
        else:
            loop.run_until_complete(_handle_epic_selection_async(body, client, action))
    except RuntimeError:
        # No event loop, create one
        asyncio.run(_handle_epic_selection_async(body, client, action))


async def _handle_epic_selection_async(body, client: WebClient, action):
    """Async implementation of epic selection handling."""
    epic_key = action.get("value")
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    team_id = body["team"]["id"]

    logger.info(
        "Epic selection received",
        extra={
            "epic_key": epic_key,
            "channel": channel,
            "thread_ts": thread_ts,
        }
    )

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    if epic_key == "new":
        # User wants to create new Epic
        # For now, create a placeholder - full creation in Phase 7
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Creating new Epic... (This will create a Jira Epic in Phase 7)",
        )
        return

    # Bind to selected Epic
    from src.slack.binding import bind_epic
    from src.db.session_store import SessionStore
    from src.db.connection import get_connection

    async with get_connection() as conn:
        store = SessionStore(conn)
        await bind_epic(identity, epic_key, store, client)


async def handle_merge_context(ack, body, client, action):
    """Handle 'Merge context' button click.

    Links the related thread in session card and Epic summary.
    """
    ack()

    similar_session_id = action.get("value")
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]

    logger.info(
        f"Merge context requested",
        extra={
            "current_thread": thread_ts,
            "similar_session": similar_session_id,
        }
    )

    # Acknowledge the merge
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Context linked from related thread. I'll consider both discussions when gathering requirements.",
    )

    # TODO: Update session card with linked thread reference
    # TODO: Update Epic summary with cross-reference


async def handle_ignore_dedup(ack, body, client):
    """Handle 'Ignore' button click on dedup suggestion."""
    ack()

    # Just acknowledge - user chose to continue independently
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]

    # Delete the suggestion message
    message_ts = body["message"]["ts"]
    try:
        client.chat_delete(channel=channel, ts=message_ts)
    except Exception:
        pass  # May not have permission to delete


# --- Contradiction Resolution Handlers ---

async def handle_contradiction_conflict(ack, body, client, action):
    """Handle 'Mark as conflict' button - flags both values as conflicting."""
    ack()

    value = action.get("value", "")
    _, data = value.split(":", 1)
    subject, proposed_value, thread_ts = data.split("|")

    channel = body["channel"]["id"]
    message_thread = body["message"].get("thread_ts") or body["message"]["ts"]

    logger.info(
        f"Contradiction marked as conflict",
        extra={"subject": subject, "proposed": proposed_value}
    )

    # TODO: Update constraint status to 'conflicted' in KG
    # TODO: Add to Epic summary as unresolved conflict

    client.chat_postMessage(
        channel=channel,
        thread_ts=message_thread,
        text=f"Marked `{subject}` as having conflicting requirements. This needs team alignment.",
    )


async def handle_contradiction_override(ack, body, client, action):
    """Handle 'Override previous' button - new value supersedes old."""
    ack()

    value = action.get("value", "")
    _, data = value.split(":", 1)
    subject, proposed_value, thread_ts = data.split("|")

    channel = body["channel"]["id"]
    message_thread = body["message"].get("thread_ts") or body["message"]["ts"]

    logger.info(
        f"Contradiction resolved by override",
        extra={"subject": subject, "new_value": proposed_value}
    )

    # TODO: Mark old constraint as 'deprecated'
    # TODO: Mark new constraint as 'accepted'

    client.chat_postMessage(
        channel=channel,
        thread_ts=message_thread,
        text=f"Updated `{subject}` to `{proposed_value}`. Previous value deprecated.",
    )


async def handle_contradiction_both(ack, body, client, action):
    """Handle 'Keep both' button - intentional dual values."""
    ack()

    value = action.get("value", "")
    _, data = value.split(":", 1)
    subject, proposed_value, thread_ts = data.split("|")

    channel = body["channel"]["id"]
    message_thread = body["message"].get("thread_ts") or body["message"]["ts"]

    logger.info(
        f"Contradiction accepted as intentional",
        extra={"subject": subject, "proposed": proposed_value}
    )

    # TODO: Mark both as 'accepted' with note about intentional dual values

    client.chat_postMessage(
        channel=channel,
        thread_ts=message_thread,
        text=f"Noted - keeping both values for `{subject}` as intentional.",
    )


# --- Draft Approval Handlers ---

async def handle_approve_draft(ack, body, client: WebClient, action):
    """Handle 'Approve & Create' button click on draft preview.

    Implements version-checked approval:
    1. Parse session_id:draft_hash from button value
    2. Check if already approved (duplicate click)
    3. Compute current draft hash and compare
    4. Record approval if valid
    5. Update preview message to show approved state
    """
    ack()

    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    message_ts = body["message"]["ts"]  # Preview message to update
    team_id = body["team"]["id"]
    user_id = body["user"]["id"]

    # Parse session_id:draft_hash from button value
    button_value = action.get("value", "")
    if ":" in button_value:
        session_id, button_hash = button_value.rsplit(":", 1)
    else:
        # Legacy format - just session_id
        session_id = button_value
        button_hash = ""

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    logger.info(
        "Draft approval requested",
        extra={
            "session_id": session_id,
            "button_hash": button_hash,
            "user_id": user_id,
        }
    )

    # Import dependencies
    from src.db import ApprovalStore, get_connection
    from src.skills.preview_ticket import compute_draft_hash

    # Check for existing approval
    async with get_connection() as conn:
        approval_store = ApprovalStore(conn)
        await approval_store.create_tables()  # Ensure table exists

        # Check if already approved for this hash
        if button_hash:
            existing = await approval_store.get_approval(session_id, button_hash)
            if existing:
                # Already approved - notify user
                approver = existing.approved_by
                client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"This draft was already approved by <@{approver}>.",
                )
                return

        # Get current draft from runner state
        runner = get_runner(identity)
        state = runner._get_current_state()
        draft = state.get("draft")

        if not draft:
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Error: Could not find draft. Please start a new session.",
            )
            return

        # Compute current draft hash
        current_hash = compute_draft_hash(draft)

        # Version check - compare button hash with current draft
        if button_hash and button_hash != current_hash:
            # Draft changed since preview was posted - require re-review
            logger.warning(
                "Draft version mismatch",
                extra={
                    "button_hash": button_hash,
                    "current_hash": current_hash,
                    "session_id": session_id,
                }
            )

            # Post new preview with updated content
            from src.slack.blocks import build_draft_preview_blocks_with_hash
            new_blocks = build_draft_preview_blocks_with_hash(
                draft=draft,
                session_id=session_id,
                draft_hash=current_hash,
            )

            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="The draft has changed since you saw this preview. Please review the updated version:",
                blocks=new_blocks,
            )
            return

        # Record approval (first wins)
        hash_to_record = current_hash if current_hash else "no-hash"
        is_new = await approval_store.record_approval(
            session_id=session_id,
            draft_hash=hash_to_record,
            approved_by=user_id,
            status="approved",
        )

        if not is_new:
            # Race condition - another approval just happened
            approver = await approval_store.get_approver(session_id, hash_to_record)
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"This draft was just approved by <@{approver}>.",
            )
            return

    # Approval successful - update runner state
    result = await runner.handle_approval(approved=True)

    # Update original preview message to show approved state
    try:
        # Build approved message blocks (remove action buttons)
        approved_blocks = _build_approved_preview_blocks(draft, user_id)
        client.chat_update(
            channel=channel,
            ts=message_ts,
            text=f"Ticket approved by <@{user_id}>",
            blocks=approved_blocks,
        )
    except Exception as e:
        logger.warning(f"Failed to update preview message: {e}")

    # Confirm approval in thread
    if result["action"] == "ready":
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Ticket approved by <@{user_id}> and ready to create in Jira!",
        )
    else:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Approved by <@{user_id}>. Processing...",
        )


def _build_approved_preview_blocks(draft: "TicketDraft", approved_by: str) -> list[dict]:
    """Build preview blocks with approval status (no action buttons).

    Used to update the preview message after approval.
    """
    from src.schemas.draft import TicketDraft
    from datetime import datetime

    blocks = []

    # Header with approved status
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Ticket Approved",
            "emoji": True
        }
    })

    # Title
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Title:* {draft.title or '_Not set_'}"
        }
    })

    # Problem
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Problem:*\n{draft.problem or '_Not set_'}"
        }
    })

    # Solution (if present)
    if draft.proposed_solution:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Proposed Solution:*\n{draft.proposed_solution}"
            }
        })

    # Acceptance Criteria
    if draft.acceptance_criteria:
        ac_text = "*Acceptance Criteria:*\n"
        for i, ac in enumerate(draft.acceptance_criteria, 1):
            ac_text += f"{i}. {ac}\n"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ac_text
            }
        })

    # Divider
    blocks.append({"type": "divider"})

    # Approval context (instead of buttons)
    approval_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"Approved by <@{approved_by}> at {approval_time}"
        }]
    })

    return blocks


async def handle_reject_draft(ack, body, client: WebClient, action):
    """Handle 'Needs Changes' button click on draft preview."""
    ack()

    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    team_id = body["team"]["id"]

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    logger.info(
        "Draft rejected for changes",
        extra={"session_id": identity.session_id}
    )

    runner = get_runner(identity)
    await runner.handle_approval(approved=False)

    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="No problem! Tell me what needs to be changed.",
    )
