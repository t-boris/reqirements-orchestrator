"""Result dispatching and content extraction logic.

INVARIANT I1: SuperMode = sole UI contract
All user-facing messages use super_mode, never intent.
Intent is internal routing detail only.

Handles dispatching graph results to appropriate skills and extracting
content for ticket updates and comments.

Phase 29.4: Preflight Sync integration.
- Check for conflicts before ticket updates and transitions
- Show preflight UI when conflicts detected
- Handle user choices via button handlers
"""

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner

if TYPE_CHECKING:
    from src.slack.progress import ProgressTracker
    from src.sync.preflight import PreflightResult
    from src.graph.state import AgentState
    from src.schemas.intent import SuperMode

# Phase 35: TaskPlan imports
from src.schemas.task_plan import TaskPlan, TaskPlanStatus, TaskStatus
from src.slack.blocks.task_plan import (
    build_multi_intent_announcement,
    build_plan_complete_message,
)
from src.slack.task_status_updater import TaskStatusUpdater

logger = logging.getLogger(__name__)

# Decision extraction prompt for architecture decisions (Phase 14)
DECISION_EXTRACTION_PROMPT = '''Based on this architecture review, extract the decision:

Review: {review_summary}
User's approval: {approval_message}

Return a JSON object:
{{
    "topic": "What was being decided (1 line)",
    "decision": "The chosen approach (1-2 sentences)"
}}

Be concise. This will be posted to the channel as a permanent record.
'''

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


async def resolve_attachment_context(
    state: "AgentState",
    mode: "SuperMode",
) -> "AgentState":
    """Resolve attachment context based on mode policy.

    Called after intent classification to populate attachment_context
    in state before graph nodes process the request.

    Intent-scoped rules:
    - CHAT: Don't include, offer available attachments
    - THINK: Pinned auto + top-K chunks if retrieval high
    - BUILD: Pinned auto + structural (requirements, AC)
    - OPERATE: Only logs, JSON, stacktraces via retrieval
    - DECIDE: Pinned + cited chunks with source refs

    Args:
        state: Current AgentState with channel_id and thread_ts.
        mode: SuperMode determining attachment policy.

    Returns:
        Updated AgentState with attachment_context populated.
    """
    from src.documents.retriever import AttachmentRetriever

    channel_id = state.get("channel_id")
    thread_ts = state.get("thread_ts")
    message = state.get("user_message", "")

    if not channel_id:
        return state

    try:
        retriever = AttachmentRetriever()
        context = await retriever.get_context(
            channel_id=channel_id,
            thread_ts=thread_ts,
            mode=mode,
            query=message,
        )

        state["attachment_context"] = context

        logger.debug(
            "Resolved attachment context",
            extra={
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "mode": mode.value,
                "pinned_count": len(context.pinned),
                "retrieved_count": len(context.retrieved_chunks),
                "available_count": len(context.offer_available),
                "total_tokens": context.total_tokens,
            }
        )

    except Exception as e:
        logger.warning(f"Failed to resolve attachment context: {e}")
        # Non-blocking - continue without attachment context

    return state


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


async def _dispatch_result(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
    runner,
    tracker: "ProgressTracker | None" = None,
):
    """Dispatch graph result to appropriate skill via dispatcher.

    Clean separation:
    - Runner: manages graph execution, returns DecisionResult
    - Dispatcher: calls appropriate skill based on decision
    - Handler: orchestrates and handles Slack-specific response

    Args:
        result: Graph result dict with action and data
        identity: Session identity
        client: Slack WebClient
        runner: Graph runner instance
        tracker: Optional ProgressTracker for status updates
    """
    from src.skills.dispatcher import SkillDispatcher
    from src.graph.nodes.decision import DecisionResult

    action = result.get("action", "continue")

    if action == "intro" or action == "nudge" or action == "hint":
        # Empty draft - send contextual hint message
        message = result.get("message", "Tell me what you'd like to work on.")
        show_buttons = result.get("show_buttons", False)
        buttons = result.get("buttons", [])

        if show_buttons and buttons:
            # Build message with buttons
            from src.slack.blocks import build_hint_with_buttons
            blocks = build_hint_with_buttons(message, buttons)
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=message,
                blocks=blocks,
            )
        else:
            # Simple text message
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=message,
            )

    elif action == "ask":
        # Build DecisionResult from runner result
        decision = DecisionResult(
            action="ask",
            questions=result.get("questions", []),
            reason=result.get("reason", ""),
            is_reask=result.get("pending_questions", {}).get("re_ask_count", 0) > 0 if result.get("pending_questions") else False,
            reask_count=result.get("pending_questions", {}).get("re_ask_count", 0) if result.get("pending_questions") else 0,
        )

        # Get state_version and ui_version from runner for state-bound approvals (Phase 27.4)
        state = await runner._get_current_state()
        state_version = state.get("state_version", 0)
        ui_version = state.get("ui_version", 0)

        dispatcher = SkillDispatcher(client, identity, tracker)
        skill_result = await dispatcher.dispatch(
            decision, result.get("draft"), state_version=state_version, ui_version=ui_version
        )

        # Store pending questions in runner state
        if skill_result.get("success") and skill_result.get("pending_questions"):
            await runner.store_pending_questions(skill_result["pending_questions"])

    elif action == "preview":
        draft = result.get("draft")
        if draft:
            decision = DecisionResult(
                action="preview",
                reason=result.get("reason", ""),
                potential_duplicates=result.get("potential_duplicates", []),
            )

            # Get state_version and ui_version from runner for state-bound approvals (Phase 27.4)
            state = await runner._get_current_state()
            state_version = state.get("state_version", 0)
            ui_version = state.get("ui_version", 0)

            dispatcher = SkillDispatcher(client, identity, tracker)
            await dispatcher.dispatch(decision, draft, state_version=state_version, ui_version=ui_version)

    elif action == "ready":
        # Approved - notify user
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="Ticket approved and ready to create in Jira!",
        )

    elif action == "discussion":
        # Discussion response - single reply, no thread creation
        # Key: Discussion should respond WHERE the user mentioned us
        # No state updates, no progress tracker, just respond and stop
        discussion_msg = result.get("message", "")
        if discussion_msg:
            # Post directly to channel/thread where mentioned (no new thread)
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts if identity.thread_ts else None,
                text=discussion_msg,
            )

    elif action == "ops":
        # OPS response - debug or explain (Phase 25.2)
        await _handle_ops_response(result, identity, client)

    elif action == "draft_refine":
        # DRAFT_REFINE - user asking about draft structure (Phase 26)
        decision_result = result.get("decision_result", {})
        refinement_prompt = decision_result.get("refinement_prompt", "")

        if refinement_prompt:
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": refinement_prompt,
                    },
                }
            ]
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                blocks=blocks,
                text=refinement_prompt[:200],  # Fallback for notifications
            )
            logger.info(
                "Posted draft refinement response",
                extra={
                    "session_id": identity.session_id,
                    "prompt_length": len(refinement_prompt),
                },
            )
        else:
            # Fallback if no refinement prompt generated
            fallback_text = "I understand you're asking about the draft structure. Could you be more specific about what you'd like to adjust?"
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": fallback_text,
                    },
                }
            ]
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                blocks=blocks,
                text=fallback_text,
            )

    elif action == "review_continuation":
        # Review continuation - synthesized response to user's answers
        continuation_msg = result.get("message", "")
        persona = result.get("persona", "")
        topic = result.get("topic", "")

        if persona:
            prefix = f"*{persona}:*\n\n"
        else:
            prefix = ""

        if continuation_msg:
            # Use same chunking logic as review (Slack block text limit is 3000 chars)
            full_text = prefix + continuation_msg
            MAX_MESSAGE_LENGTH = 2900

            # Split into message-sized chunks at natural boundaries
            message_chunks = []
            remaining = full_text
            while remaining:
                if len(remaining) <= MAX_MESSAGE_LENGTH:
                    message_chunks.append(remaining)
                    break

                split_at = MAX_MESSAGE_LENGTH
                para_break = remaining.rfind("\n\n", 0, MAX_MESSAGE_LENGTH)
                if para_break > MAX_MESSAGE_LENGTH // 2:
                    split_at = para_break + 2
                else:
                    line_break = remaining.rfind("\n", 0, MAX_MESSAGE_LENGTH)
                    if line_break > MAX_MESSAGE_LENGTH // 2:
                        split_at = line_break + 1
                    else:
                        space = remaining.rfind(" ", 0, MAX_MESSAGE_LENGTH)
                        if space > MAX_MESSAGE_LENGTH // 2:
                            split_at = space + 1

                message_chunks.append(remaining[:split_at].rstrip())
                remaining = remaining[split_at:].lstrip()

            logger.info(f"Sending review_continuation: {len(full_text)} chars in {len(message_chunks)} message(s)")

            # Send each chunk as a separate Slack message
            for i, chunk in enumerate(message_chunks):
                is_last_message = (i == len(message_chunks) - 1)

                blocks = [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": chunk}
                    }
                ]

                # Add action buttons only to the last message
                if is_last_message:
                    ticket_button_value = json.dumps({
                        "review_text": continuation_msg[:1500],
                        "topic": (topic or "")[:100],
                        "persona": persona or "",
                    })
                    approve_button_value = json.dumps({
                        "topic": (topic or "")[:100],
                        "persona": persona or "",
                    })
                    blocks.append({
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Approve & Post Decision"},
                                "action_id": "approve_architecture",
                                "value": approve_button_value,
                                "style": "primary",
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Turn into Jira ticket"},
                                "action_id": "review_to_ticket",
                                "value": ticket_button_value,
                            }
                        ]
                    })

                client.chat_postMessage(
                    channel=identity.channel_id,
                    thread_ts=identity.thread_ts if identity.thread_ts else None,
                    blocks=blocks,
                    text=chunk[:200],
                )

    elif action == "review":
        # Review response - persona-based analysis without Jira operations
        # Like discussion, responds where mentioned. Longer, thoughtful analysis.
        review_msg = result.get("message", "")
        persona = result.get("persona", "")
        topic = result.get("topic", "")

        # Format as review (persona indicator + analysis)
        if persona:
            prefix = f"*{persona} Review:*\n\n"
        else:
            prefix = ""

        if review_msg:
            # Split into multiple Slack messages to avoid collapse
            # Slack block text limit is 3000 chars, so we split at 2900 to be safe
            full_text = prefix + review_msg
            MAX_MESSAGE_LENGTH = 2900  # Keep under Slack's 3000 char block text limit

            # Split into message-sized chunks at natural boundaries
            message_chunks = []
            remaining = full_text
            while remaining:
                if len(remaining) <= MAX_MESSAGE_LENGTH:
                    message_chunks.append(remaining)
                    break

                # Find a good split point (prefer double newline, then single newline)
                split_at = MAX_MESSAGE_LENGTH
                # Try to find paragraph break
                para_break = remaining.rfind("\n\n", 0, MAX_MESSAGE_LENGTH)
                if para_break > MAX_MESSAGE_LENGTH // 2:
                    split_at = para_break + 2
                else:
                    # Try single newline
                    line_break = remaining.rfind("\n", 0, MAX_MESSAGE_LENGTH)
                    if line_break > MAX_MESSAGE_LENGTH // 2:
                        split_at = line_break + 1
                    else:
                        # Fall back to space
                        space = remaining.rfind(" ", 0, MAX_MESSAGE_LENGTH)
                        if space > MAX_MESSAGE_LENGTH // 2:
                            split_at = space + 1

                message_chunks.append(remaining[:split_at].rstrip())
                remaining = remaining[split_at:].lstrip()

            # Log chunking info
            logger.info(f"Sending review: {len(full_text)} chars in {len(message_chunks)} message(s)")

            # Send each chunk as a separate Slack message
            for i, chunk in enumerate(message_chunks):
                is_last_message = (i == len(message_chunks) - 1)

                blocks = [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": chunk}
                    }
                ]

                # Add action buttons only to the last message
                if is_last_message:
                    ticket_button_value = json.dumps({
                        "review_text": review_msg[:1500],
                        "topic": (topic or "")[:100],
                        "persona": persona or "",
                    })
                    approve_button_value = json.dumps({
                        "topic": (topic or "")[:100],
                        "persona": persona or "",
                    })
                    blocks.append({
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Approve & Post Decision"},
                                "action_id": "approve_architecture",
                                "value": approve_button_value,
                                "style": "primary",
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Turn into Jira ticket"},
                                "action_id": "review_to_ticket",
                                "value": ticket_button_value,
                            }
                        ]
                    })

                client.chat_postMessage(
                    channel=identity.channel_id,
                    thread_ts=identity.thread_ts if identity.thread_ts else None,
                    blocks=blocks,
                    text=chunk[:200],  # Fallback text
                )

    elif action == "jira_command_confirm":
        # Handle Jira command confirmation (Phase 21)
        from src.slack.handlers.jira_commands import handle_jira_command_confirm
        await handle_jira_command_confirm(result, identity, client)

    elif action == "jira_command_ambiguous":
        # Handle ambiguous Jira command target (Phase 21)
        from src.slack.handlers.jira_commands import handle_jira_command_ambiguous
        await handle_jira_command_ambiguous(result, identity, client)

    elif action == "ticket_action":
        # Handle operations on existing tickets (Phase 13.1)
        await _handle_ticket_action(result, identity, client)

    elif action == "decision_approval":
        # Architecture decision approval (Phase 14)
        await _handle_decision_approval(result, identity, client)

    elif action == "scope_gate":
        # AMBIGUOUS intent - show 3-button scope gate (Phase 20)
        from src.slack.blocks.scope_gate import build_scope_gate_blocks

        message_preview = result.get("message_preview", "")[:100]
        blocks = build_scope_gate_blocks(message_preview)

        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="How would you like me to help?",
            blocks=blocks,
        )

    elif action == "sync_request":
        # Sync request - trigger Jira sync analysis (Phase 21-04)
        await _handle_sync_request(result, identity, client)

    elif action == "jira_search":
        # Jira search - search for existing issues
        await _handle_jira_search(result, identity, client)

    elif action == "change_request_preview":
        # Change request - diff-based updates (Phase 25.3)
        await _handle_change_request_preview(client, identity.channel_id, identity.thread_ts, result)

    elif action == "change_request_error":
        # Change request error
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f":warning: {result.get('error', 'Unknown error')}",
        )

    elif action == "transform_applied":
        # DRAFT_TRANSFORM completed - show new structure (Phase 28.6, R8)
        await _handle_transform_applied(result, identity, client)

    elif action == "conflict":
        # Draft conflict detected - post conflict UI (Phase 27.3)
        await _handle_draft_conflict(result, identity, client)

    # Phase 35: TaskPlan action handlers
    elif action == "task_plan_created":
        await _handle_task_plan_created(client, result, identity)

    elif action == "task_confirmation_required":
        await _handle_task_confirmation(client, result, identity)

    elif action == "task_plan_complete":
        await _handle_task_plan_complete(client, result, identity)

    elif action == "task_plan_blocked":
        await _handle_task_plan_blocked(client, result, identity)

    elif action == "task_failed":
        await _handle_task_failed(client, result, identity)

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


async def _handle_ticket_action(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
):
    """Handle operations on existing tickets (Phase 13.1).

    Phase 29.4: Adds preflight checks before update operations.
    """
    ticket_key = result.get("ticket_key")
    action_type = result.get("action_type")
    already_bound_to_same = result.get("already_bound_to_same", False)

    # Validate ticket_key before any operations
    if not ticket_key:
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="I couldn't determine which ticket you're referring to. Please mention the ticket key (e.g., SCRUM-123).",
        )
        return

    if action_type == "create_subtask":
        # Check if already bound to same ticket - do action, don't re-link
        if already_bound_to_same:
            # Proceed with subtask creation context
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=f"Working on subtasks for *{ticket_key}*. What subtasks should I create?",
            )
        else:
            # Bind thread to ticket, then provide subtask context
            from src.slack.thread_bindings import get_binding_store

            binding_store = get_binding_store()
            await binding_store.bind(
                channel_id=identity.channel_id,
                thread_ts=identity.thread_ts,
                issue_key=ticket_key,
                bound_by="system",  # Auto-bound by ticket action
            )

            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=f"Linked to *{ticket_key}*. What subtasks should I create?",
            )

    elif action_type == "link":
        # Normal link flow
        from src.slack.thread_bindings import get_binding_store

        binding_store = get_binding_store()
        await binding_store.bind(
            channel_id=identity.channel_id,
            thread_ts=identity.thread_ts,
            issue_key=ticket_key,
            bound_by="system",
        )

        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f"Linked this thread to *{ticket_key}*.",
        )

    elif action_type == "update":
        # Show update preview with confirmation flow (conversational)
        # Phase 29.4: Check preflight before showing preview
        from src.jira.client import JiraService
        from src.config.settings import get_settings
        from src.slack.blocks.update_preview import build_update_preview_blocks
        from src.slack.blocks.preflight import build_preflight_blocks
        from src.schemas.state import PendingAction, WorkflowStep
        from src.sync.preflight import ConflictType

        jira_service = None
        try:
            settings = get_settings()
            jira_service = JiraService(settings)

            # Fetch existing issue to get current description
            existing_issue = await jira_service.get_issue(ticket_key)
            existing_description = existing_issue.description or ""
            ticket_url = existing_issue.url

            # Extract proposed update content from thread conversation
            update_content = await _extract_update_content(
                result, client, identity.channel_id, identity.thread_ts
            )

            if not update_content or update_content.strip() == "":
                client.chat_postMessage(
                    channel=identity.channel_id,
                    thread_ts=identity.thread_ts,
                    text=f"I couldn't find specific content to add to *{ticket_key}*. What details would you like to add?",
                )
                return

            # Phase 29.4: Preflight check before showing preview
            preflight_result = await _check_preflight_for_action(
                channel_id=identity.channel_id,
                ticket_key=ticket_key,
                action_type="update",
                fields_to_update={"description": update_content},
            )

            if preflight_result:
                if preflight_result.conflict_type == ConflictType.IDEMPOTENT:
                    # Already done - notify user
                    client.chat_postMessage(
                        channel=identity.channel_id,
                        thread_ts=identity.thread_ts,
                        text=f":information_source: {preflight_result.message}\nNo update needed.",
                    )
                    return

                # Conflict detected - show preflight UI with pending action stored
                runner = get_runner(identity)
                state = await runner._get_current_state()

                # Store pending action for button handlers
                pending_preflight = {
                    "action_type": "update",
                    "ticket_key": ticket_key,
                    "ticket_url": ticket_url,
                    "proposed_content": update_content,
                    "conflict_type": preflight_result.conflict_type.value,
                }
                state["pending_preflight"] = pending_preflight
                await runner.update_state(state)

                # Build and show preflight blocks
                preflight_blocks = build_preflight_blocks(preflight_result)

                # Add pending action info to button payloads
                # The blocks already have JSON payloads, we need to extend them
                for block in preflight_blocks:
                    if block.get("type") == "actions":
                        for element in block.get("elements", []):
                            if element.get("type") == "button" and element.get("value"):
                                try:
                                    payload = json.loads(element["value"])
                                    payload["channel_id"] = identity.channel_id
                                    payload["thread_ts"] = identity.thread_ts
                                    payload["pending_action"] = pending_preflight
                                    element["value"] = json.dumps(payload)
                                except json.JSONDecodeError:
                                    pass

                client.chat_postMessage(
                    channel=identity.channel_id,
                    thread_ts=identity.thread_ts,
                    blocks=preflight_blocks,
                    text=f"Conflict detected for {ticket_key}",
                )

                logger.info(
                    "Preflight conflict shown for update",
                    extra={
                        "ticket_key": ticket_key,
                        "conflict_type": preflight_result.conflict_type.value,
                    }
                )
                return

            # No conflict - proceed with normal preview flow
            # Get runner to store pending update state
            runner = get_runner(identity)
            state = await runner._get_current_state()

            # Build preview blocks
            ui_version = state.get("ui_version", 0) + 1
            preview_blocks = build_update_preview_blocks(
                ticket_key=ticket_key,
                ticket_url=ticket_url,
                current_description=existing_description,
                proposed_content=update_content,
                update_mode="append",
                ui_version=ui_version,
            )

            # Add conversational hint
            preview_blocks.insert(1, {
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": "You can click the buttons below, or just reply to refine the update."
                }]
            })

            # Post preview
            result_msg = client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                blocks=preview_blocks,
                text=f"Preview update for {ticket_key}",
            )

            # Store pending update in state
            pending_update = {
                "ticket_key": ticket_key,
                "ticket_url": ticket_url,
                "current_description": existing_description,
                "proposed_content": update_content,
                "update_mode": "append",
                "preview_message_ts": result_msg["ts"],
            }

            state["pending_update"] = pending_update
            state["pending_action"] = PendingAction.WAITING_UPDATE_CONFIRM
            state["workflow_step"] = WorkflowStep.UPDATE_PREVIEW
            state["ui_version"] = ui_version
            await runner.update_state(state)

            logger.info(
                "Update preview shown",
                extra={
                    "ticket_key": ticket_key,
                    "proposed_content_length": len(update_content),
                }
            )

        except Exception as e:
            logger.error(f"Failed to show update preview: {e}", exc_info=True)
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=f"Failed to prepare update for *{ticket_key}*: {str(e)}",
            )
        finally:
            if jira_service:
                await jira_service.close()

    elif action_type == "add_comment":
        # Add comment to ticket
        from src.jira.client import JiraService
        from src.config.settings import get_settings

        jira_service = None
        try:
            settings = get_settings()
            jira_service = JiraService(settings)

            # Extract comment content
            comment_content = await _extract_comment_content(result)

            # Add comment to the ticket
            await jira_service.add_comment(ticket_key, comment_content)

            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=f"Added comment to *{ticket_key}*.",
            )
        except Exception as e:
            logger.error(f"Failed to add comment: {e}", exc_info=True)
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=f"Failed to add comment to *{ticket_key}*: {str(e)}",
            )
        finally:
            if jira_service:
                await jira_service.close()

    elif action_type == "create_stories":
        # Create user stories under an existing epic
        await _handle_create_stories(result, identity, client, ticket_key)

    else:
        # Unknown action type
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f"I'm not sure how to help with *{ticket_key}*. Try 'create subtasks for {ticket_key}' or 'link to {ticket_key}'.",
        )


STORY_GENERATION_PROMPT = '''Based on this Epic, generate user stories that break down the work.

Epic Key: {epic_key}
Epic Title: {epic_title}
Epic Description:
{epic_description}

Generate 3-5 user stories that together achieve the Epic's goal.
Each story should be:
- Independent (can be worked on separately)
- Valuable (delivers user value)
- Estimable (clear enough to estimate)

Return a JSON array:
[
  {{
    "title": "User story title (action-oriented, e.g., 'Add voice command recognition')",
    "description": "Brief description of what needs to be built and why",
    "acceptance_criteria": ["Criterion 1", "Criterion 2"]
  }}
]

Be specific and technical. These will become Jira tickets.
'''


async def _handle_create_stories(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
    ticket_key: str,
):
    """Handle creating user stories under an existing epic."""
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.llm import get_llm
    import re

    settings = get_settings()
    jira_service = JiraService(settings)

    try:
        # Fetch the epic from Jira
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f"Fetching *{ticket_key}* from Jira...",
        )

        epic = await jira_service.get_issue(ticket_key)

        if not epic:
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=f"Could not find *{ticket_key}* in Jira. Please check the ticket key.",
            )
            return

        logger.info(
            "Fetched epic for story generation",
            extra={
                "epic_key": epic.key,
                "epic_title": epic.summary,
                "epic_description_length": len(epic.description or ""),
            }
        )

        # Generate stories using LLM
        llm = get_llm()
        prompt = STORY_GENERATION_PROMPT.format(
            epic_key=epic.key,
            epic_title=epic.summary,
            epic_description=epic.description or "No description provided",
        )

        generation_result = await llm.chat(prompt)

        # Parse JSON from response
        json_match = re.search(r'\[[\s\S]*\]', generation_result)
        if not json_match:
            raise ValueError("Could not parse stories from LLM response")

        stories = json.loads(json_match.group())

        if not stories:
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=f"Could not generate stories for *{ticket_key}*. The epic may need more detail.",
            )
            return

        # Build preview of generated stories
        preview_blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":clipboard: *Generated {len(stories)} User Stories for {epic.key}*\n_{epic.summary}_"
                }
            },
            {"type": "divider"},
        ]

        for i, story in enumerate(stories, 1):
            title = story.get("title", f"Story {i}")
            description = story.get("description", "")
            criteria = story.get("acceptance_criteria", [])

            story_text = f"*{i}. {title}*\n{description}"
            if criteria:
                story_text += "\n_Acceptance Criteria:_\n" + "\n".join(f"• {c}" for c in criteria[:3])

            # Truncate if too long for Slack block
            if len(story_text) > 2900:
                story_text = story_text[:2897] + "..."

            preview_blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": story_text}
            })

        # Store stories in pending store (button value has 2000 char limit)
        from src.slack.pending_stories import get_pending_stories_store
        store = get_pending_stories_store()
        pending_id = store.store(epic.key, stories)

        # Add action buttons with short pending_id instead of full data
        preview_blocks.append({"type": "divider"})
        preview_blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"Create {len(stories)} Stories"},
                    "action_id": "create_stories_confirm",
                    "value": pending_id,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "action_id": "create_stories_cancel",
                    "value": pending_id,
                },
            ]
        })

        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f"Generated {len(stories)} user stories for {epic.key}",
            blocks=preview_blocks,
        )

    except Exception as e:
        logger.error(f"Failed to generate stories: {e}", exc_info=True)
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f"Failed to generate stories for *{ticket_key}*: {str(e)}",
        )
    finally:
        await jira_service.close()


async def _handle_decision_approval(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
):
    """Handle architecture decision approval (Phase 14)."""
    review_context = result.get("review_context")

    if not review_context:
        # No recent review to approve
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="No recent review to approve. I can only record a decision after giving you a review.",
        )
    else:
        # Extract decision from review context using LLM
        from src.llm import get_llm
        from src.slack.blocks import build_decision_blocks
        import re

        try:
            # Get latest human message for context
            approval_message = result.get("approval_message", "approved")

            llm = get_llm()
            extraction_prompt = DECISION_EXTRACTION_PROMPT.format(
                review_summary=review_context.get("review_summary", ""),
                approval_message=approval_message,
            )

            extraction_result = await llm.chat(extraction_prompt)

            # Parse JSON response
            # Try to extract JSON from response (handles markdown code blocks)
            json_match = re.search(r'\{[^{}]*\}', extraction_result, re.DOTALL)
            if json_match:
                decision_data = json.loads(json_match.group())
            else:
                decision_data = json.loads(extraction_result)

            topic = decision_data.get("topic", review_context.get("topic", "Architecture decision"))
            decision_text = decision_data.get("decision", "Approved")

            # Get user who approved
            user_id = result.get("user_id", "unknown")
            thread_ts = review_context.get("thread_ts", identity.thread_ts)
            channel_id = review_context.get("channel_id", identity.channel_id)

            logger.info(
                "Architecture decision detected",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "topic": topic,
                    "user_id": user_id,
                }
            )

            # Build and post decision blocks to CHANNEL (not thread!)
            decision_blocks = build_decision_blocks(
                topic=topic,
                decision=decision_text,
                channel_id=channel_id,
                thread_ts=thread_ts,
                user_id=user_id,
            )

            # Post to channel (no thread_ts = channel root)
            client.chat_postMessage(
                channel=channel_id,
                blocks=decision_blocks,
                text=f"Architecture Decision: {topic}",  # Fallback text
            )

            # Confirm in thread
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text="Decision recorded in channel.",
            )

            # NEW: Link to Jira (Phase 21-05)
            await _link_decision_to_jira(
                topic=topic,
                decision_text=decision_text,
                channel_id=channel_id,
                thread_ts=thread_ts,
                user_id=user_id,
                identity=identity,
                client=client,
            )

        except Exception as e:
            logger.error(f"Failed to extract/post decision: {e}", exc_info=True)
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text="I understood that as approval, but couldn't extract the decision. The review is still available above.",
            )


async def _link_decision_to_jira(
    topic: str,
    decision_text: str,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    identity: SessionIdentity,
    client: WebClient,
):
    """Link approved decision to related Jira issues.

    Flow:
    1. Find related issues using DecisionLinker
    2. If single match with high confidence: auto-update
    3. If multiple matches or low confidence: ask user
    """
    from datetime import datetime, timezone
    from src.slack.decision_linker import DecisionLinker
    from src.slack.thread_bindings import get_binding_store

    try:
        linker = DecisionLinker()

        # Check for thread binding
        binding_store = get_binding_store()
        binding = await binding_store.get_binding(channel_id, thread_ts)
        thread_binding = binding.issue_key if binding else None

        # Find related issues
        related_issues = await linker.find_related_issues(
            decision_topic=topic,
            decision_text=decision_text,
            channel_id=channel_id,
            thread_binding=thread_binding,
        )

        if not related_issues:
            # No related issues found now, but record for later sync
            logger.debug("No related Jira issues found for decision - recording for sync")
            await linker.record_decision_sync(
                channel_id=channel_id,
                decision_ts=thread_ts,
                topic=topic,
                decision_text=decision_text,
                related_issues=[],
                synced_to_jira=False,  # Not synced yet - will appear in /maro sync
            )
            await linker.close()
            return

        # Build Slack thread link
        slack_link = f"https://slack.com/archives/{channel_id}/p{thread_ts.replace('.', '')}"

        # Format decision for Jira
        timestamp = datetime.now(timezone.utc).isoformat()
        formatted_decision = linker.format_decision_for_jira(
            topic=topic,
            decision=decision_text,
            approver=f"<@{user_id}>",
            timestamp=timestamp,
            slack_link=slack_link,
        )

        if len(related_issues) == 1:
            # High confidence single match - auto-update
            issue_key = related_issues[0]
            success = await linker.apply_decision_to_issue(
                issue_key,
                formatted_decision,
                mode="add_comment",
                add_label=True,
                channel_id=channel_id,
                decision_ts=thread_ts,
                topic=topic,
            )

            if success:
                client.chat_postMessage(
                    channel=identity.channel_id,
                    thread_ts=identity.thread_ts,
                    text=f"Decision added to *{issue_key}*.",
                )
        else:
            # Multiple matches - ask user
            await _prompt_decision_link(
                issues=related_issues,
                topic=topic,
                decision_text=decision_text,
                user_id=user_id,
                identity=identity,
                client=client,
            )

        await linker.close()

    except Exception as e:
        logger.warning(f"Failed to link decision to Jira: {e}", exc_info=True)
        # Non-blocking - decision was already posted to channel


async def _prompt_decision_link(
    issues: list[str],
    topic: str,
    decision_text: str,
    user_id: str,
    identity: SessionIdentity,
    client: WebClient,
):
    """Prompt user to select which Jira issue to link decision to.

    Shows up to 5 related issues with Link buttons.
    """
    from src.jira.client import JiraService
    from src.config.settings import get_settings

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "Link this decision to a Jira ticket?"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{topic}*\n{decision_text[:200]}..."}
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Related tickets:*"}
        },
    ]

    # Fetch issue summaries for context
    try:
        settings = get_settings()
        jira = JiraService(settings)

        for key in issues[:5]:  # Max 5 options
            try:
                issue = await jira.get_issue(key)
                summary = issue.summary[:60] + "..." if len(issue.summary) > 60 else issue.summary
            except Exception:
                summary = "(Could not fetch summary)"

            # Store data needed for linking in button value
            button_value = json.dumps({
                "key": key,
                "topic": topic[:100],
                "decision": decision_text[:500],
                "user_id": user_id,
            })

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{key}*: {summary}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Link"},
                    "action_id": f"link_decision_{key}",
                    "value": button_value,
                }
            })

        await jira.close()

    except Exception as e:
        logger.warning(f"Failed to fetch issue summaries: {e}")
        # Show keys without summaries
        for key in issues[:5]:
            button_value = json.dumps({
                "key": key,
                "topic": topic[:100],
                "decision": decision_text[:500],
                "user_id": user_id,
            })
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{key}*"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Link"},
                    "action_id": f"link_decision_{key}",
                    "value": button_value,
                }
            })

    # Add skip button
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Skip"},
                "action_id": "skip_decision_link"
            }
        ]
    })

    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        blocks=blocks,
        text="Link decision to Jira?",
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


# --- OPS Response Handler (Phase 25.2) ---

async def _handle_ops_response(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
) -> None:
    """Handle OPS response - debug or explain.

    Formats response based on subtype:
    - DEBUG: System operator style with triage info
    - EXPLAIN: Policy trace format

    Args:
        result: Decision result with message and subtype
        identity: Session identity
        client: Slack WebClient
    """
    ops_msg = result.get("message", "")
    subtype = result.get("subtype", "debug")
    timestamp = result.get("timestamp", "")

    if not ops_msg:
        ops_msg = "I couldn't generate a response."

    # Format prefix based on subtype
    if subtype == "explain":
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


# --- Draft Conflict Handler (Phase 27.3) ---

async def _handle_draft_conflict(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
) -> None:
    """Handle draft conflict detected during extraction.

    Posts conflict UI with resolution buttons for each detected conflict.

    Args:
        result: Decision result with conflicts list
        identity: Session identity
        client: Slack WebClient
    """
    from src.slack.blocks.draft_conflict import build_draft_conflict_blocks
    from src.schemas.conflict import DraftConflict

    conflicts_data = result.get("conflicts", [])
    if not conflicts_data:
        logger.warning("No conflicts data in conflict result")
        return

    # Post each conflict with its resolution buttons
    for conflict_data in conflicts_data:
        try:
            conflict = DraftConflict(**conflict_data)
            blocks = build_draft_conflict_blocks(conflict)

            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                blocks=blocks,
                text=f"Conflict detected in {conflict.field_name}",
            )

            logger.info(
                "Posted conflict UI",
                extra={
                    "conflict_id": conflict.conflict_id,
                    "field_name": conflict.field_name,
                    "channel_id": identity.channel_id,
                    "thread_ts": identity.thread_ts,
                },
            )
        except Exception as e:
            logger.error(f"Failed to post conflict UI: {e}", exc_info=True)

    # Post summary if multiple conflicts
    if len(conflicts_data) > 1:
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f":warning: {len(conflicts_data)} conflicts detected. Please resolve each one above.",
        )


# --- Transform Applied Handler (Phase 28.6) ---

async def _handle_transform_applied(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
) -> None:
    """Handle transform_applied action - show new structure.

    R8: After each Draft form change, bot must show the new form.

    Posts structure visualization with version-bound buttons after
    any structural mutation to the draft.

    Args:
        result: Decision result with transform_result and structured_draft
        identity: Session identity
        client: Slack WebClient
    """
    from src.slack.blocks.draft_structure import build_structure_blocks
    from src.schemas.structured_draft import StructuredDraft

    transform_result = result.get("transform_result", {})
    operation = result.get("operation", "unknown")
    reason = result.get("reason", "")

    # Get structured draft from result or fetch from runner
    structured_draft_data = result.get("structured_draft")

    if structured_draft_data is None:
        # Try to get from runner state
        runner = get_runner(identity)
        state = await runner._get_current_state()
        structured_draft = state.get("structured_draft")
    elif isinstance(structured_draft_data, dict):
        # Reconstruct from dict
        structured_draft = StructuredDraft(**structured_draft_data)
    else:
        structured_draft = structured_draft_data

    if not structured_draft:
        # No draft to show
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f"Transform applied: {reason}",
        )
        return

    # Build structure blocks with actions
    structure_blocks = build_structure_blocks(
        draft=structured_draft,
        show_actions=True,
        include_version=True,
    )

    # Post the structure visualization
    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        blocks=structure_blocks,
        text=f"Draft structure updated (version {structured_draft.version})",
    )

    logger.info(
        "Posted structure after transform",
        extra={
            "operation": operation,
            "success": transform_result.get("success"),
            "draft_id": structured_draft.id,
            "version": structured_draft.version,
            "item_count": len(structured_draft.items),
            "channel_id": identity.channel_id,
            "thread_ts": identity.thread_ts,
        },
    )


# --- Phase 35: TaskPlan Handlers ---

async def _handle_task_plan_created(
    client: WebClient,
    result: dict,
    identity: SessionIdentity,
) -> None:
    """Handle newly created TaskPlan - post status card and announcement.

    Called when task_decomposer creates a new TaskPlan from multi-intent.
    Posts the canonical announcement and status card.

    Args:
        client: Slack WebClient
        result: Decision result with task_plan data
        identity: Session identity
    """
    task_plan_data = result.get("task_plan")
    if not task_plan_data:
        logger.warning("task_plan_created action without task_plan data")
        return

    task_plan = TaskPlan.model_validate(task_plan_data)

    # Post announcement message
    announcement = build_multi_intent_announcement(task_plan)
    await client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text=announcement,
    )

    # Post status card
    updater = TaskStatusUpdater(client)
    await updater.post_initial_card(
        task_plan,
        identity.channel_id,
        identity.thread_ts,
    )

    logger.info(
        f"Posted TaskPlan {task_plan.plan_id} with {len(task_plan.tasks)} tasks",
        extra={
            "plan_id": task_plan.plan_id,
            "task_count": len(task_plan.tasks),
            "auto_count": result.get("auto_count", 0),
            "channel_id": identity.channel_id,
            "thread_ts": identity.thread_ts,
        },
    )


async def _handle_task_confirmation(
    client: WebClient,
    result: dict,
    identity: SessionIdentity,
) -> None:
    """Handle task needing confirmation - update status card.

    Called when a task with REQUIRES_CONFIRMATION safety level is reached.

    Args:
        client: Slack WebClient
        result: Decision result with task_plan and task info
        identity: Session identity
    """
    task_plan_data = result.get("task_plan")
    if not task_plan_data:
        return

    task_plan = TaskPlan.model_validate(task_plan_data)

    # Update status card to show blocked task
    updater = TaskStatusUpdater(client)
    await updater.update_card(
        task_plan,
        identity.channel_id,
        event="task_blocked",
    )

    # Post reminder about which task needs approval
    task_title = result.get("task_title", "Unknown task")
    await client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text=f":double_vertical_bar: Waiting for approval: *{task_title}*\nUse the buttons above to approve or reject.",
    )

    logger.info(
        f"Task confirmation required for {task_title}",
        extra={
            "plan_id": task_plan.plan_id,
            "task_title": task_title,
            "channel_id": identity.channel_id,
        },
    )


async def _handle_task_plan_complete(
    client: WebClient,
    result: dict,
    identity: SessionIdentity,
) -> None:
    """Handle completed TaskPlan - post summary to channel.

    Called when all tasks in the plan are DONE.

    Args:
        client: Slack WebClient
        result: Decision result with task_plan data
        identity: Session identity
    """
    task_plan_data = result.get("task_plan")
    if not task_plan_data:
        return

    task_plan = TaskPlan.model_validate(task_plan_data)

    # Final status card update
    updater = TaskStatusUpdater(client)
    await updater.flush_pending(task_plan.plan_id, identity.channel_id)
    await updater.update_card(
        task_plan,
        identity.channel_id,
        event="plan_completed",
    )

    # Post completion summary to channel (not just thread)
    summary = build_plan_complete_message(task_plan)
    await client.chat_postMessage(
        channel=identity.channel_id,
        text=summary,
    )

    logger.info(
        f"TaskPlan {task_plan.plan_id} completed",
        extra={
            "plan_id": task_plan.plan_id,
            "completed_tasks": len([t for t in task_plan.tasks if t.status == TaskStatus.DONE]),
            "channel_id": identity.channel_id,
        },
    )


async def _handle_task_plan_blocked(
    client: WebClient,
    result: dict,
    identity: SessionIdentity,
) -> None:
    """Handle TaskPlan that's blocked waiting for user input.

    Called when plan cannot progress because tasks are blocked.

    Args:
        client: Slack WebClient
        result: Decision result with task_plan data
        identity: Session identity
    """
    task_plan_data = result.get("task_plan")
    if not task_plan_data:
        return

    task_plan = TaskPlan.model_validate(task_plan_data)

    # Update status card
    updater = TaskStatusUpdater(client)
    await updater.update_card(
        task_plan,
        identity.channel_id,
        event="task_blocked",
    )

    # Find blocked tasks
    blocked = [t for t in task_plan.tasks if t.status == TaskStatus.BLOCKED]
    if blocked:
        task_names = ", ".join(t.title for t in blocked[:3])
        if len(blocked) > 3:
            task_names += f", and {len(blocked) - 3} more"
        await client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f":double_vertical_bar: Waiting for: {task_names}",
        )

    logger.info(
        f"TaskPlan {task_plan.plan_id} blocked",
        extra={
            "plan_id": task_plan.plan_id,
            "blocked_count": len(blocked),
            "channel_id": identity.channel_id,
        },
    )


async def _handle_task_failed(
    client: WebClient,
    result: dict,
    identity: SessionIdentity,
) -> None:
    """Handle failed task - show error.

    Called when a task execution fails.

    Args:
        client: Slack WebClient
        result: Decision result with task_plan, task_id, and error
        identity: Session identity
    """
    task_plan_data = result.get("task_plan")
    if not task_plan_data:
        return

    task_plan = TaskPlan.model_validate(task_plan_data)

    # Update status card
    updater = TaskStatusUpdater(client)
    await updater.update_card(
        task_plan,
        identity.channel_id,
        event="task_failed",
    )

    # Post error message
    task_id = result.get("task_id", "unknown")
    error = result.get("error", "Unknown error")
    await client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text=f":x: Task failed: {error}\nYou can retry or cancel the plan.",
    )

    logger.error(
        f"Task {task_id} failed in plan {task_plan.plan_id}",
        extra={
            "plan_id": task_plan.plan_id,
            "task_id": task_id,
            "error": error,
            "channel_id": identity.channel_id,
        },
    )
