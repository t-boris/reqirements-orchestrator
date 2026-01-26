"""Ticket action dispatch handlers.

Handles operations on existing Jira tickets (update, link, create subtasks, create stories).
"""

import json
import logging
import re
from typing import TYPE_CHECKING

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Story generation prompt
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


async def _handle_ticket_action(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
):
    """Handle operations on existing tickets (Phase 13.1).

    Phase 29.4: Adds preflight checks before update operations.
    """
    # Import helpers from jira_ops
    from src.slack.handlers.dispatch.jira_ops import (
        _extract_update_content,
        _extract_comment_content,
        _check_preflight_for_action,
    )

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
                story_text += "\n_Acceptance Criteria:_\n" + "\n".join(f"- {c}" for c in criteria[:3])

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
