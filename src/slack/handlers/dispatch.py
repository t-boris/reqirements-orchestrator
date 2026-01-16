"""Result dispatching and content extraction logic.

Handles dispatching graph results to appropriate skills and extracting
content for ticket updates and comments.
"""

import json
import logging
from typing import TYPE_CHECKING

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner

if TYPE_CHECKING:
    from src.slack.progress import ProgressTracker

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


async def _extract_update_content(
    result: dict,
    client: WebClient,
    channel_id: str,
    thread_ts: str,
) -> str:
    """Extract update content from conversation context using LLM."""
    from src.llm import get_llm

    # Get user message and review context
    user_message = result.get("user_message", "")
    review_context = result.get("review_context", {})
    review_summary = review_context.get("review_summary", "") if review_context else ""

    llm = get_llm()
    prompt = UPDATE_EXTRACTION_PROMPT.format(
        user_message=user_message,
        review_context=review_summary or "No review context available",
    )

    return await llm.chat(prompt)


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

        dispatcher = SkillDispatcher(client, identity, tracker)
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
                potential_duplicates=result.get("potential_duplicates", []),
            )

            dispatcher = SkillDispatcher(client, identity, tracker)
            await dispatcher.dispatch(decision, draft)

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


async def _handle_ticket_action(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
):
    """Handle operations on existing tickets (Phase 13.1)."""
    ticket_key = result.get("ticket_key")
    action_type = result.get("action_type")
    already_bound_to_same = result.get("already_bound_to_same", False)

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
        # Update ticket with extracted content
        from src.jira.client import JiraService
        from src.config.settings import get_settings

        try:
            settings = get_settings()
            jira_service = JiraService(settings)

            # Extract update content
            update_content = await _extract_update_content(
                result, client, identity.channel_id, identity.thread_ts
            )

            # Update the ticket (append to description)
            await jira_service.update_issue(
                ticket_key,
                {"description": update_content},
            )
            await jira_service.close()

            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=f"Updated *{ticket_key}* with the latest context.",
            )
        except Exception as e:
            logger.error(f"Failed to update ticket: {e}", exc_info=True)
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=f"Failed to update *{ticket_key}*: {str(e)}",
            )

    elif action_type == "add_comment":
        # Add comment to ticket
        from src.jira.client import JiraService
        from src.config.settings import get_settings

        try:
            settings = get_settings()
            jira_service = JiraService(settings)

            # Extract comment content
            comment_content = await _extract_comment_content(result)

            # Add comment to the ticket
            await jira_service.add_comment(ticket_key, comment_content)
            await jira_service.close()

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

    try:
        settings = get_settings()
        jira_service = JiraService(settings)

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
            await jira_service.close()
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
            await jira_service.close()
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

        await jira_service.close()

    except Exception as e:
        logger.error(f"Failed to generate stories: {e}", exc_info=True)
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f"Failed to generate stories for *{ticket_key}*: {str(e)}",
        )


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

        except Exception as e:
            logger.error(f"Failed to extract/post decision: {e}", exc_info=True)
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text="I understood that as approval, but couldn't extract the decision. The review is still available above.",
            )
