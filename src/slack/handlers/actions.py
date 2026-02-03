"""Button and interactive action handlers.

Ref: RESEARCH.md - Pattern 2: Action Handler with ack()
Ref: RESEARCH.md - Pitfall 1: Not Acknowledging Actions Fast Enough
"""
import json
import logging
import re
from slack_bolt.async_app import AsyncApp

from src.domain.entities import ProposedEntity, ApprovedEntity, get_lifecycle
from src.domain.transitions import TransitionError
from src.domain.types import EntityId, UserId
from src.infrastructure.aggregate_loader import load_aggregate, save_events
from src.intent import classify_intent, RouterContext
from src.modes import dispatch_mode

logger = logging.getLogger(__name__)

# Pattern for entity action buttons: approve_{entity_id}, object_{entity_id}, discuss_{entity_id}
ENTITY_ACTION_PATTERN = re.compile(r"^(approve|object|discuss)_(.+)$")

# Pattern for follow-up question answer buttons: answer_q_{uuid}_{index}
QUESTION_ANSWER_PATTERN = re.compile(r"^answer_q_.+$")


def register_action_handlers(app: AsyncApp) -> None:
    """Register all action handlers on the Bolt app."""

    @app.action(ENTITY_ACTION_PATTERN)
    async def handle_entity_action(ack, body: dict, action: dict, say, logger) -> None:
        """Handle approve/object/discuss button clicks.

        CRITICAL: ack() MUST be called first, within 3 seconds.
        """
        # Acknowledge immediately (required by Slack)
        await ack()

        action_id = action.get("action_id", "")
        action_value = action.get("value", "")

        # Parse action type and entity ID
        match = ENTITY_ACTION_PATTERN.match(action_id)
        if not match:
            logger.warning(f"Unexpected action_id format: {action_id}")
            return

        action_type = match.group(1)  # approve, object, or discuss
        entity_id = match.group(2)

        user_id = body.get("user", {}).get("id")
        channel_id = body.get("channel", {}).get("id")
        thread_ts = body.get("message", {}).get("thread_ts")

        logger.info(f"Action {action_type} on entity {entity_id} by {user_id}")

        try:
            aggregate = await load_aggregate(channel_id)
            entity = aggregate.get_entity(EntityId(entity_id))

            if entity is None:
                await say(
                    text=f":x: Entity `{entity_id}` not found.",
                    thread_ts=thread_ts,
                )
                return

            if action_type == "approve":
                if not isinstance(entity, ProposedEntity):
                    await say(
                        text=f":x: Entity must be in proposed state to approve. Current: {type(entity).__name__}",
                        thread_ts=thread_ts,
                    )
                    return

                is_work_item = hasattr(entity.content, "issue_type")
                if is_work_item:
                    result = aggregate.approve_work_item(
                        entity_id=EntityId(entity_id),
                        actor_id=UserId(user_id),
                    )
                else:
                    result = aggregate.approve_decision(
                        entity_id=EntityId(entity_id),
                        actor_id=UserId(user_id),
                    )

                await save_events(aggregate)

                if isinstance(result, ApprovedEntity):
                    entity_type = "work item" if is_work_item else "decision"
                    title = getattr(result.content, "title", entity_id)
                    blocks = [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f":white_check_mark: *{title}* approved by <@{user_id}>",
                            },
                        },
                    ]
                    if is_work_item:
                        blocks.append({
                            "type": "actions",
                            "elements": [{
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Commit to Jira"},
                                "style": "primary",
                                "action_id": "commit_to_jira",
                                "value": entity_id,
                            }],
                        })
                    await say(
                        text=f"{title} approved by <@{user_id}>",
                        blocks=blocks,
                        thread_ts=thread_ts,
                    )
                else:
                    await say(
                        text=f":thumbsup: <@{user_id}> approved. Waiting for more approvals.",
                        thread_ts=thread_ts,
                    )

            elif action_type == "object":
                if not isinstance(entity, ProposedEntity):
                    await say(
                        text=f":x: Entity must be in proposed state to object.",
                        thread_ts=thread_ts,
                    )
                    return

                aggregate.raise_entity_objection(
                    entity_id=EntityId(entity_id),
                    actor_id=UserId(user_id),
                    reason="Objection raised via button (reply in thread with details)",
                )
                await save_events(aggregate)

                title = getattr(entity.content, "title", entity_id)
                await say(
                    text=f":no_entry_sign: <@{user_id}> raised an objection to *{title}*. Please discuss in thread.",
                    thread_ts=thread_ts,
                )

            elif action_type == "discuss":
                title = getattr(entity.content, "title", entity_id)
                await say(
                    text=f":speech_balloon: <@{user_id}> wants to discuss *{title}*. Reply in this thread.",
                    thread_ts=thread_ts,
                )

        except TransitionError as e:
            await say(
                text=f":x: Action failed: {e}",
                thread_ts=thread_ts,
            )
        except Exception as e:
            logger.error(f"Error handling entity action: {e}", exc_info=True)
            await say(
                text=":x: An error occurred processing your action. Please try again.",
                thread_ts=thread_ts,
            )

    @app.action(QUESTION_ANSWER_PATTERN)
    async def handle_question_answer(ack, body: dict, action: dict, client, say) -> None:
        """Handle follow-up question answer button clicks.

        Updates original message to show selected answer (disables buttons),
        then posts the answer as a thread message for continued conversation.
        """
        await ack()

        value = json.loads(action.get("value", "{}"))
        answer = value.get("answer", "")
        question = value.get("question_text", "")
        thread_ts = value.get("thread_ts")

        channel_id = body.get("channel", {}).get("id")
        message_ts = body.get("message", {}).get("ts")
        user_id = body.get("user", {}).get("id")

        logger.info(
            f"Question answer by {user_id}: Q='{question[:50]}' A='{answer[:50]}'"
        )

        # Update original message to show selection (replace buttons with Q/A text)
        if message_ts and channel_id:
            try:
                # Get original message text to preserve it
                original_text = body.get("message", {}).get("text", "")
                original_blocks = body.get("message", {}).get("blocks", [])

                # Keep non-actions blocks, replace actions with Q/A summary
                updated_blocks = [
                    block for block in original_blocks
                    if block.get("type") != "actions"
                ]
                updated_blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Q:* {question}\n*A:* {answer if answer != '__freeform__' else '(typing...)'}"
                    },
                })

                await client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    blocks=updated_blocks,
                    text=f"Q: {question} A: {answer}",
                )
            except Exception as e:
                logger.warning(f"Failed to update message with answer: {e}")

        # If "Something else" was clicked, prompt for free-form input
        if answer == "__freeform__":
            await say(
                text=f"<@{user_id}> Go ahead, type your answer:",
                thread_ts=thread_ts,
            )
            return

        # Post the answer as a visible thread message (for conversation record)
        await say(
            text=answer,
            thread_ts=thread_ts,
        )

        # Directly invoke classification + dispatch pipeline.
        # The posted message above is a bot message and will be filtered by the
        # event handler (events.py:88-90), so we must classify and dispatch here.
        try:
            # Fetch thread history for classification context
            thread_messages = []
            thread_summary = ""
            if thread_ts:
                try:
                    replies = await client.conversations_replies(
                        channel=channel_id, ts=thread_ts, limit=50,
                    )
                    thread_messages = [
                        {"role": "assistant" if msg.get("bot_id") else "user",
                         "content": msg.get("text", "")}
                        for msg in replies.get("messages", [])
                    ]
                    thread_summary = "\n".join(
                        f"{'Bot' if m['role'] == 'assistant' else 'User'}: {m['content'][:200]}"
                        for m in thread_messages[-10:]
                    )
                except Exception as e:
                    logger.warning(f"Failed to fetch thread history for question answer: {e}")

            # Build entity summaries for context
            entity_summaries = "No existing entities"
            try:
                aggregate = await load_aggregate(channel_id)
                if aggregate.entities:
                    summaries = []
                    for eid, entity in list(aggregate.entities.items())[:20]:
                        title = getattr(entity.content, "title", str(eid)[:8])
                        state = get_lifecycle(entity).value
                        etype = entity.entity_type.value
                        summaries.append(f"- {title} ({etype}, {state}) [id: {eid}]")
                    entity_summaries = "\n".join(summaries)
            except Exception as e:
                logger.debug(f"Could not load entity summaries: {e}")

            # Resolve channel name
            channel_name = channel_id
            try:
                info = await client.conversations_info(channel=channel_id)
                channel_name = info.get("channel", {}).get("name", channel_id)
            except Exception:
                pass

            context = RouterContext(
                channel_id=channel_id,
                channel_name=channel_name,
                thread_ts=thread_ts,
                thread_summary=thread_summary,
                entity_summaries=entity_summaries,
                active_process_threads=set(),
            )

            # Compose message with question context for accurate classification
            contextual_message = f"{question}: {answer}" if question else answer

            intent = await classify_intent(
                message=contextual_message,
                event_type="message",
                context=context,
            )

            logger.info(
                f"Question answer classified: mode={intent.mode}, "
                f"confidence={intent.confidence:.2f}, answer='{answer[:50]}'"
            )

            result = await dispatch_mode(
                message=contextual_message,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                intent=intent,
                thread_messages=thread_messages,
            )

            if result.response_text:
                if result.response_blocks:
                    await say(
                        text=result.response_text,
                        blocks=result.response_blocks,
                        thread_ts=thread_ts,
                    )
                else:
                    await say(
                        text=result.response_text,
                        thread_ts=thread_ts,
                    )

        except Exception as e:
            logger.error(f"Error processing question answer: {e}", exc_info=True)
            await say(
                text="Sorry, I encountered an error processing your answer. Please try again.",
                thread_ts=thread_ts,
            )

    # Catch-all for any unhandled actions (MUST be registered last)
    @app.action(re.compile(".*"))
    async def handle_unknown_action(ack, action: dict, logger) -> None:
        """Handle any unmatched action (fallback)."""
        await ack()
        logger.warning(f"Unhandled action: {action.get('action_id')}")

    logger.info("Action handlers registered")
