"""Button and interactive action handlers.

Ref: RESEARCH.md - Pattern 2: Action Handler with ack()
Ref: RESEARCH.md - Pitfall 1: Not Acknowledging Actions Fast Enough
"""
import json
import logging
import re
from slack_bolt.async_app import AsyncApp

from src.domain.content import DecisionContent, DecisionType
from src.domain.entities import ProposedEntity, ApprovedEntity, DraftEntity, get_lifecycle
from src.domain.transitions import TransitionError
from src.domain.types import EntityId, ThreadTs, UserId
from src.infrastructure.aggregate_loader import load_aggregate, save_events
from src.intent import classify_intent, RouterContext
from src.modes import dispatch_mode
from src.slack.client import SlackClient
from src.slack.dashboard import DashboardManager

logger = logging.getLogger(__name__)

# Pattern for entity action buttons: approve_{entity_id}, object_{entity_id}, discuss_{entity_id}
ENTITY_ACTION_PATTERN = re.compile(r"^(approve|object|discuss)_(.+)$")

# Pattern for follow-up question answer buttons: answer_q_{uuid}_{index}
QUESTION_ANSWER_PATTERN = re.compile(r"^answer_q_.+$")

# Pattern for decision preview action buttons: record_all_decisions, cancel_decisions
DECISION_PREVIEW_PATTERN = re.compile(r"^(record_all|cancel)_decisions$")

# Pattern for per-ADR action buttons: adr_record_0, adr_edit_1, adr_delete_2
ADR_ACTION_PATTERN = re.compile(r"^adr_(record|edit|delete)_(\d+)$")


def _parse_decisions_from_blocks(blocks: list[dict]) -> list[dict]:
    """Parse decision data from preview message blocks.

    Blocks are built by CreateModeHandler._build_decisions_preview_blocks:
    header, then repeating [section, actions, divider] for each decision, then global actions.
    Section text format: *{i}. {title}*\n{decision}\n_Context: ..._\n_Rationale: ..._\n_Alternatives: ..._
    Already-handled ADRs are replaced with context blocks and won't match *N. pattern.
    """
    decisions = []
    for block in blocks:
        if block.get("type") != "section":
            continue
        text = block.get("text", {}).get("text", "")
        if not text or not re.match(r"^\*\d+\.", text):
            continue

        lines = text.split("\n")

        # Title from "*1. Title*"
        title_line = lines[0]
        title = re.sub(r"^\*\d+\.\s*", "", title_line).rstrip("*").strip()

        decision_text = ""
        context = ""
        rationale = ""
        alternatives = []

        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("_Context:"):
                context = stripped.replace("_Context:", "").strip().rstrip("_").strip()
            elif stripped.startswith("_Rationale:"):
                rationale = stripped.replace("_Rationale:", "").strip().rstrip("_").strip()
            elif stripped.startswith("_Alternatives:"):
                alts_raw = stripped.replace("_Alternatives:", "").strip().rstrip("_").strip()
                alternatives = [a.strip() for a in alts_raw.split(",") if a.strip()]
            elif stripped and not stripped.startswith("_"):
                decision_text = stripped

        if title:
            decisions.append({
                "decision_type": "architecture",
                "title": title,
                "context": context,
                "decision": decision_text,
                "rationale": rationale,
                "alternatives_considered": alternatives,
            })

    return decisions


async def _record_all_decisions(
    client, say, channel_id: str, message_ts: str, thread_ts: str | None,
    user_id: str, original_blocks: list[dict],
) -> None:
    """Record all decisions from a preview message and update dashboard."""
    decisions = _parse_decisions_from_blocks(original_blocks)
    if not decisions:
        await say(text=":x: Could not parse decisions from message.", thread_ts=thread_ts)
        return

    try:
        aggregate = await load_aggregate(channel_id)

        created = []
        for d in decisions:
            try:
                dt = DecisionType(d.get("decision_type", "architecture").lower())
            except ValueError:
                dt = DecisionType.ARCHITECTURE

            content = DecisionContent(
                decision_type=dt,
                title=d["title"],
                description=d["decision"],
                rationale=d.get("rationale", ""),
                alternatives_considered=d.get("alternatives_considered", []),
            )

            draft = aggregate.record_decision(
                actor_id=UserId(user_id),
                thread_ts=ThreadTs(thread_ts or ""),
                content=content,
            )
            created.append((str(draft.id), content.title))

        await save_events(aggregate)

        logger.info(f"Recorded {len(created)} decisions in {channel_id} by {user_id}")

        # Update original message — replace buttons with confirmation
        updated_blocks = [b for b in original_blocks if b.get("type") != "actions"]
        updated_blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":white_check_mark: *{len(created)} decisions recorded* by <@{user_id}>",
            },
        })

        await client.chat_update(
            channel=channel_id, ts=message_ts,
            blocks=updated_blocks,
            text=f"{len(created)} decisions recorded",
        )

        # Update channel dashboard with current entity counts
        try:
            counts = {"pending": 0, "approved": 0, "committed": 0, "decisions": 0}
            pending_items = []
            for entity in aggregate.entities.values():
                if entity.entity_type.value == "decision":
                    counts["decisions"] += 1
                    if isinstance(entity, (DraftEntity, ProposedEntity)):
                        pending_items.append({
                            "title": getattr(entity.content, "title", str(entity.id)[:8]),
                            "id": str(entity.id),
                        })
                else:
                    lifecycle = get_lifecycle(entity)
                    lc = lifecycle.value
                    if lc in ("draft", "proposed"):
                        counts["pending"] += 1
                    elif lc == "approved":
                        counts["approved"] += 1
                    elif lc == "committed":
                        counts["committed"] += 1

            slack_client = SlackClient(client)
            dashboard_mgr = DashboardManager(slack_client)
            await dashboard_mgr.create_or_update(
                channel_id=channel_id,
                pending_count=counts["pending"],
                approved_count=counts["approved"],
                committed_count=counts["committed"],
                decisions_count=counts["decisions"],
                pending_items=pending_items,
            )
        except Exception as e:
            logger.warning(f"Failed to update dashboard after recording decisions: {e}")

    except Exception as e:
        logger.error(f"Error recording decisions: {e}", exc_info=True)
        await say(
            text=f":x: Failed to record decisions: {e}",
            thread_ts=thread_ts,
        )


def _find_adr_section_index(blocks: list[dict], adr_index: int) -> int | None:
    """Find the block index of the section block for a specific ADR (0-based).

    Scans for section block whose text starts with *{adr_index+1}. to avoid
    positional math issues when blocks shift after record/delete.
    Returns the index into the blocks list, or None if not found.
    """
    prefix = f"*{adr_index + 1}. "
    for i, block in enumerate(blocks):
        if block.get("type") != "section":
            continue
        text = block.get("text", {}).get("text", "")
        if text.startswith(prefix):
            return i
    return None


def _parse_single_decision_from_section(section_block: dict) -> dict:
    """Parse a single decision dict from a section block's mrkdwn text."""
    text = section_block.get("text", {}).get("text", "")
    lines = text.split("\n")

    title_line = lines[0] if lines else ""
    title = re.sub(r"^\*\d+\.\s*", "", title_line).rstrip("*").strip()

    decision_text = ""
    context = ""
    rationale = ""
    alternatives = []

    for line in lines[1:]:
        stripped = line.strip()
        if stripped.startswith("_Context:"):
            context = stripped.replace("_Context:", "").strip().rstrip("_").strip()
        elif stripped.startswith("_Rationale:"):
            rationale = stripped.replace("_Rationale:", "").strip().rstrip("_").strip()
        elif stripped.startswith("_Alternatives:"):
            alts_raw = stripped.replace("_Alternatives:", "").strip().rstrip("_").strip()
            alternatives = [a.strip() for a in alts_raw.split(",") if a.strip()]
        elif stripped and not stripped.startswith("_"):
            decision_text = stripped

    return {
        "decision_type": "architecture",
        "title": title,
        "context": context,
        "decision": decision_text,
        "rationale": rationale,
        "alternatives_considered": alternatives,
    }


def _replace_adr_blocks(blocks: list[dict], section_idx: int, replacement_block: dict) -> list[dict]:
    """Replace an ADR's section + actions + divider blocks with a single replacement block.

    Starting at section_idx, removes the section block and any immediately
    following actions/divider blocks that belong to this ADR.
    """
    updated = list(blocks)
    # Count how many blocks to remove: section + optional actions + optional divider
    remove_count = 1
    for offset in range(1, 3):
        if section_idx + offset < len(updated):
            btype = updated[section_idx + offset].get("type")
            if btype in ("actions", "divider"):
                remove_count += 1
            else:
                break
        else:
            break

    updated[section_idx:section_idx + remove_count] = [replacement_block]
    return updated


async def _update_dashboard_after_decision(client, channel_id: str, aggregate) -> None:
    """Update the channel dashboard after a decision change."""
    try:
        counts = {"pending": 0, "approved": 0, "committed": 0, "decisions": 0}
        pending_items = []
        for entity in aggregate.entities.values():
            if entity.entity_type.value == "decision":
                counts["decisions"] += 1
                if isinstance(entity, (DraftEntity, ProposedEntity)):
                    pending_items.append({
                        "title": getattr(entity.content, "title", str(entity.id)[:8]),
                        "id": str(entity.id),
                    })
            else:
                lifecycle = get_lifecycle(entity)
                lc = lifecycle.value
                if lc in ("draft", "proposed"):
                    counts["pending"] += 1
                elif lc == "approved":
                    counts["approved"] += 1
                elif lc == "committed":
                    counts["committed"] += 1

        slack_client = SlackClient(client)
        dashboard_mgr = DashboardManager(slack_client)
        await dashboard_mgr.create_or_update(
            channel_id=channel_id,
            pending_count=counts["pending"],
            approved_count=counts["approved"],
            committed_count=counts["committed"],
            decisions_count=counts["decisions"],
            pending_items=pending_items,
        )
    except Exception as e:
        logger.warning(f"Failed to update dashboard: {e}")


async def _record_single_decision(
    client, say, channel_id: str, message_ts: str, thread_ts: str | None,
    user_id: str, blocks: list[dict], adr_index: int,
) -> None:
    """Record a single ADR from the preview message."""
    section_idx = _find_adr_section_index(blocks, adr_index)
    if section_idx is None:
        await say(text=f":x: Could not find ADR #{adr_index + 1} in message.", thread_ts=thread_ts)
        return

    decision = _parse_single_decision_from_section(blocks[section_idx])

    try:
        aggregate = await load_aggregate(channel_id)

        try:
            dt = DecisionType(decision.get("decision_type", "architecture").lower())
        except ValueError:
            dt = DecisionType.ARCHITECTURE

        content = DecisionContent(
            decision_type=dt,
            title=decision["title"],
            description=decision["decision"],
            rationale=decision.get("rationale", ""),
            alternatives_considered=decision.get("alternatives_considered", []),
        )

        aggregate.record_decision(
            actor_id=UserId(user_id),
            thread_ts=ThreadTs(thread_ts or ""),
            content=content,
        )
        await save_events(aggregate)

        logger.info(f"Recorded single decision '{decision['title']}' in {channel_id} by {user_id}")

        confirmation = {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f":white_check_mark: *{decision['title']}* recorded by <@{user_id}>"}],
        }
        updated_blocks = _replace_adr_blocks(blocks, section_idx, confirmation)

        await client.chat_update(
            channel=channel_id, ts=message_ts,
            blocks=updated_blocks,
            text=f"Decision '{decision['title']}' recorded",
        )

        await _update_dashboard_after_decision(client, channel_id, aggregate)

    except Exception as e:
        logger.error(f"Error recording single decision: {e}", exc_info=True)
        await say(text=f":x: Failed to record decision: {e}", thread_ts=thread_ts)


async def _delete_single_decision(
    client, say, channel_id: str, message_ts: str, thread_ts: str | None,
    user_id: str, blocks: list[dict], adr_index: int,
) -> None:
    """Delete (remove) a single ADR from the preview — no domain event needed."""
    section_idx = _find_adr_section_index(blocks, adr_index)
    if section_idx is None:
        await say(text=f":x: Could not find ADR #{adr_index + 1} in message.", thread_ts=thread_ts)
        return

    decision = _parse_single_decision_from_section(blocks[section_idx])

    removal = {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f":wastebasket: *{decision['title']}* removed by <@{user_id}>"}],
    }
    updated_blocks = _replace_adr_blocks(blocks, section_idx, removal)

    try:
        await client.chat_update(
            channel=channel_id, ts=message_ts,
            blocks=updated_blocks,
            text=f"Decision '{decision['title']}' removed",
        )
    except Exception as e:
        logger.warning(f"Failed to update message after delete: {e}")


async def _open_edit_modal(
    client, trigger_id: str, blocks: list[dict], adr_index: int,
    channel_id: str, message_ts: str, thread_ts: str | None,
) -> None:
    """Open modal for editing a single ADR."""
    from src.slack.blocks.decisions import build_edit_adr_modal

    section_idx = _find_adr_section_index(blocks, adr_index)
    if section_idx is None:
        logger.warning(f"Could not find ADR #{adr_index + 1} for edit modal")
        return

    decision = _parse_single_decision_from_section(blocks[section_idx])
    modal = build_edit_adr_modal(
        adr_index=adr_index,
        decision=decision,
        channel_id=channel_id,
        message_ts=message_ts,
        thread_ts=thread_ts,
    )

    await client.views_open(trigger_id=trigger_id, view=modal)


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

    @app.action(ADR_ACTION_PATTERN)
    async def handle_adr_action(ack, body: dict, action: dict, client, say) -> None:
        """Handle per-ADR Record / Edit / Delete button clicks."""
        await ack()

        action_id = action.get("action_id", "")
        match = ADR_ACTION_PATTERN.match(action_id)
        if not match:
            return

        action_type = match.group(1)
        adr_index = int(match.group(2))

        channel_id = body.get("channel", {}).get("id")
        message_ts = body.get("message", {}).get("ts")
        user_id = body.get("user", {}).get("id")
        thread_ts = body.get("message", {}).get("thread_ts")
        blocks = body.get("message", {}).get("blocks", [])

        if action_type == "record":
            await _record_single_decision(
                client, say, channel_id, message_ts, thread_ts, user_id, blocks, adr_index,
            )
        elif action_type == "edit":
            trigger_id = body.get("trigger_id")
            if trigger_id:
                await _open_edit_modal(
                    client, trigger_id, blocks, adr_index,
                    channel_id, message_ts, thread_ts,
                )
        elif action_type == "delete":
            await _delete_single_decision(
                client, say, channel_id, message_ts, thread_ts, user_id, blocks, adr_index,
            )

    @app.action(DECISION_PREVIEW_PATTERN)
    async def handle_decision_preview_action(ack, body: dict, action: dict, client, say) -> None:
        """Handle Record All Remaining / Cancel All buttons on decision previews."""
        await ack()

        action_id = action.get("action_id", "")
        channel_id = body.get("channel", {}).get("id")
        message_ts = body.get("message", {}).get("ts")
        user_id = body.get("user", {}).get("id")
        thread_ts = body.get("message", {}).get("thread_ts")
        original_blocks = body.get("message", {}).get("blocks", [])

        if "record_all" in action_id:
            await _record_all_decisions(
                client, say, channel_id, message_ts, thread_ts, user_id, original_blocks,
            )
        elif "cancel" in action_id:
            updated_blocks = [b for b in original_blocks if b.get("type") != "actions"]
            updated_blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "_Cancelled_"}],
            })
            try:
                await client.chat_update(
                    channel=channel_id, ts=message_ts,
                    blocks=updated_blocks, text="Decisions cancelled",
                )
            except Exception as e:
                logger.warning(f"Failed to update cancelled message: {e}")

    # Catch-all for any unhandled actions (MUST be registered last)
    @app.action(re.compile(".*"))
    async def handle_unknown_action(ack, action: dict, logger) -> None:
        """Handle any unmatched action (fallback)."""
        await ack()
        logger.warning(f"Unhandled action: {action.get('action_id')}")

    logger.info("Action handlers registered")
