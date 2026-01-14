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
    """Async processing for @mention - runs graph and dispatches to skills."""
    try:
        runner = get_runner(identity)
        result = await runner.run_with_message(text, user)

        # Use dispatcher for skill execution
        await _dispatch_result(result, identity, client, runner)

    except Exception as e:
        logger.error(f"Error processing mention: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Sorry, something went wrong. Please try again.",
        )


async def _dispatch_result(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
    runner,
):
    """Dispatch graph result to appropriate skill via dispatcher.

    Clean separation:
    - Runner: manages graph execution, returns DecisionResult
    - Dispatcher: calls appropriate skill based on decision
    - Handler: orchestrates and handles Slack-specific response
    """
    from src.skills.dispatcher import SkillDispatcher
    from src.graph.nodes.decision import DecisionResult

    action = result.get("action", "continue")

    if action == "ask":
        # Build DecisionResult from runner result
        decision = DecisionResult(
            action="ask",
            questions=result.get("questions", []),
            reason=result.get("reason", ""),
            is_reask=result.get("pending_questions", {}).get("re_ask_count", 0) > 0 if result.get("pending_questions") else False,
            reask_count=result.get("pending_questions", {}).get("re_ask_count", 0) if result.get("pending_questions") else 0,
        )

        dispatcher = SkillDispatcher(client, identity)
        skill_result = await dispatcher.dispatch(decision, result.get("draft"))

        # Store pending questions in runner state
        if skill_result.get("success") and skill_result.get("pending_questions"):
            await runner.store_pending_questions(skill_result["pending_questions"])

    elif action == "preview":
        draft = result.get("draft")
        if draft:
            decision = DecisionResult(
                action="preview",
                reason=result.get("reason", ""),
            )

            dispatcher = SkillDispatcher(client, identity)
            await dispatcher.dispatch(decision, draft)

    elif action == "ready":
        # Approved - notify user
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="Ticket approved and ready to create in Jira!",
        )

    elif action == "error":
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f"Sorry, I encountered an error: {result.get('error', 'Unknown error')}",
        )

    else:
        # Continue - acknowledge receipt
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="Got it! I'm collecting the requirements.",
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
    """Async processing for thread message - continues graph and dispatches to skills."""
    try:
        runner = get_runner(identity)
        result = await runner.run_with_message(text, user)

        # Use dispatcher for skill execution (same as _process_mention)
        await _dispatch_result(result, identity, client, runner)

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
    1. Check in-memory dedup (handles Slack retries)
    2. Parse session_id:draft_hash from button value
    3. Check if already approved in DB (duplicate click)
    4. Compute current draft hash and compare
    5. Record approval if valid
    6. Update preview message to show approved state
    """
    ack()

    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    message_ts = body["message"]["ts"]  # Preview message to update
    team_id = body["team"]["id"]
    user_id = body["user"]["id"]

    # Parse session_id:draft_hash from button value
    button_value = action.get("value", "")
    action_id = action.get("action_id", "approve_draft")

    # In-memory dedup for Slack retries and rage-clicks
    from src.slack.dedup import try_process_button
    if not try_process_button(action_id, user_id, button_value):
        # Duplicate click - silently ignore (already processing)
        logger.debug(f"Ignoring duplicate approve click: {button_value}")
        return

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
    """Handle 'Needs Changes' button click on draft preview.

    Opens the edit modal for direct draft editing.
    Implements idempotent rejection handling:
    1. Check in-memory dedup (handles Slack retries)
    2. Open edit modal with current draft values
    """
    # Get trigger_id BEFORE ack (needed for modal)
    trigger_id = body.get("trigger_id")

    ack()

    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    message_ts = body["message"]["ts"]  # Preview message to update later
    team_id = body["team"]["id"]
    user_id = body["user"]["id"]

    # Parse button value (session_id:draft_hash)
    button_value = action.get("value", "")
    action_id = action.get("action_id", "reject_draft")

    # In-memory dedup for Slack retries and rage-clicks
    from src.slack.dedup import try_process_button
    if not try_process_button(action_id, user_id, button_value):
        # Duplicate click - silently ignore
        logger.debug(f"Ignoring duplicate reject click: {button_value}")
        return

    # Parse session_id and draft_hash from button value
    if ":" in button_value:
        session_id, draft_hash = button_value.rsplit(":", 1)
    else:
        session_id = button_value
        draft_hash = ""

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    logger.info(
        "Opening edit modal for draft changes",
        extra={
            "session_id": identity.session_id,
            "user_id": user_id,
        }
    )

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

    # Build and open edit modal
    from src.slack.modals import build_edit_draft_modal
    from src.skills.preview_ticket import compute_draft_hash

    current_hash = compute_draft_hash(draft)
    modal_view = build_edit_draft_modal(
        draft=draft,
        session_id=session_id,
        draft_hash=current_hash,
        preview_message_ts=message_ts,
    )

    try:
        client.views_open(
            trigger_id=trigger_id,
            view=modal_view,
        )
    except Exception as e:
        logger.error(f"Failed to open edit modal: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Sorry, I couldn't open the edit form. Please tell me what needs to be changed in the thread.",
        )


async def handle_edit_draft_submit(ack, body, client: WebClient, view):
    """Handle edit modal submission.

    Process modal submission flow:
    1. Parse submitted values from view state
    2. Parse private_metadata for session info
    3. Update draft in runner state
    4. Get updated draft and compute new hash
    5. Update original preview message with new draft
    6. Post confirmation message
    """
    ack()

    user_id = body["user"]["id"]
    view_state = view.get("state", {}).get("values", {})
    private_metadata_raw = view.get("private_metadata", "{}")

    # Parse private metadata
    import json
    try:
        private_metadata = json.loads(private_metadata_raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse private_metadata: {private_metadata_raw}")
        return

    session_id = private_metadata.get("session_id", "")
    preview_message_ts = private_metadata.get("preview_message_ts", "")

    logger.info(
        "Processing edit modal submission",
        extra={
            "session_id": session_id,
            "user_id": user_id,
        }
    )

    # Parse session_id to get identity parts
    # Format: team:channel:thread_ts
    parts = session_id.split(":")
    if len(parts) != 3:
        logger.error(f"Invalid session_id format: {session_id}")
        return

    team_id, channel, thread_ts = parts

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    # Parse submitted values
    from src.slack.modals import parse_modal_values
    values = parse_modal_values(view_state)

    # Get runner and current draft
    runner = get_runner(identity)
    state = runner._get_current_state()
    draft = state.get("draft")

    if not draft:
        logger.error(f"No draft found for session: {session_id}")
        return

    # Update draft with new values
    from src.schemas.draft import DraftConstraint, ConstraintStatus

    # Update basic fields
    if "title" in values:
        draft.title = values["title"]
    if "problem" in values:
        draft.problem = values["problem"]
    if "proposed_solution" in values:
        draft.proposed_solution = values["proposed_solution"]
    if "acceptance_criteria" in values:
        draft.acceptance_criteria = values["acceptance_criteria"]
    if "risks" in values:
        draft.risks = values["risks"]

    # Update constraints (parse key=value pairs)
    if "constraints_raw" in values:
        new_constraints = []
        for c in values["constraints_raw"]:
            new_constraints.append(DraftConstraint(
                key=c["key"],
                value=c["value"],
                status=ConstraintStatus.PROPOSED,
            ))
        draft.constraints = new_constraints

    # Increment version
    draft.version += 1

    # Update runner state with modified draft
    runner._update_draft(draft)

    # Compute new hash
    from src.skills.preview_ticket import compute_draft_hash
    new_hash = compute_draft_hash(draft)

    # Update original preview message with new draft
    from src.slack.blocks import build_draft_preview_blocks_with_hash
    new_blocks = build_draft_preview_blocks_with_hash(
        draft=draft,
        session_id=session_id,
        draft_hash=new_hash,
    )

    try:
        client.chat_update(
            channel=channel,
            ts=preview_message_ts,
            text=f"Updated ticket preview for: {draft.title or 'Untitled'}",
            blocks=new_blocks,
        )
    except Exception as e:
        logger.warning(f"Failed to update preview message: {e}")

    # Post confirmation
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Draft updated by <@{user_id}>. Please review the changes above.",
    )


def _build_rejected_preview_blocks(draft: "TicketDraft", rejected_by: str) -> list[dict]:
    """Build preview blocks with rejection status (no action buttons).

    Used to update the preview message after rejection.
    """
    from src.schemas.draft import TicketDraft
    from datetime import datetime

    blocks = []

    # Header with rejected status
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Changes Requested",
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

    # Problem (abbreviated)
    problem_preview = draft.problem[:100] if draft.problem else "_Not set_"
    if draft.problem and len(draft.problem) > 100:
        problem_preview += "..."
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Problem:* {problem_preview}"
        }
    })

    # Divider
    blocks.append({"type": "divider"})

    # Rejection context (instead of buttons)
    rejection_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"Changes requested by <@{rejected_by}> at {rejection_time}"
        }]
    })

    return blocks
