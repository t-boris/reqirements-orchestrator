"""Button and interactive action handlers.

Ref: RESEARCH.md - Pattern 2: Action Handler with ack()
Ref: RESEARCH.md - Pitfall 1: Not Acknowledging Actions Fast Enough
"""
import json
import logging
import re
from slack_bolt.async_app import AsyncApp

from src.domain.content import DecisionContent, DecisionType
from src.domain.entities import (
    ApprovedEntity,
    CommittedEntity,
    DeprecatedEntity,
    DraftEntity,
    ProposedEntity,
    get_lifecycle,
)
from src.domain.transitions import TransitionError
from src.domain.types import EntityId, ThreadTs, UserId
from src.infrastructure.aggregate_loader import load_aggregate, save_events
from src.intent import classify_intent, RouterContext
from src.modes import dispatch_mode
from src.slack.blocks.decisions import build_adr_post_blocks
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

# Pattern for RECORD mode confirm/edit/cancel/amend buttons
RECORD_CONFIRM_PATTERN = re.compile(r"^(confirm_record|confirm_amend|edit|cancel)_decision$")

# Fixed action_id for deprecate button on committed decisions (entity ID in value)
DEPRECATE_DECISION_ACTION = "deprecate_decision"

# Pattern for deprecation confirmation: confirm_deprecate or cancel_deprecate (entity ID in value)
DEPRECATE_CONFIRM_PATTERN = re.compile(r"^(confirm|cancel)_deprecate$")

# Pattern for ADR pinned message lifecycle buttons: adr_propose, adr_approve, adr_object, adr_deprecate
ADR_LIFECYCLE_PATTERN = re.compile(r"^adr_(propose|approve|object|deprecate)$")


def _build_slack_permalink(channel_id: str, message_ts: str) -> str:
    """Build a Slack deep-link URL from channel ID and message timestamp."""
    ts_no_dot = message_ts.replace(".", "")
    return f"https://slack.com/archives/{channel_id}/p{ts_no_dot}"


async def _post_and_pin_adr(client, channel_id: str, decision: dict, user_id: str) -> str | None:
    """Post a formatted ADR message to the channel and pin it.

    Returns the message timestamp on success, or None on failure.
    """
    blocks = build_adr_post_blocks(
        title=decision.get("title", "Untitled"),
        decision_type=decision.get("decision_type", "architecture"),
        decision=decision.get("decision", ""),
        rationale=decision.get("rationale", ""),
        alternatives=decision.get("alternatives_considered"),
        recorded_by=user_id,
    )

    try:
        result = await client.chat_postMessage(
            channel=channel_id,
            blocks=blocks,
            text=f"ADR: {decision.get('title', 'Untitled')}",
        )
        adr_ts = result.get("ts")
        if adr_ts:
            try:
                await client.pins_add(channel=channel_id, timestamp=adr_ts)
            except Exception as e:
                logger.warning(f"Failed to pin ADR message in {channel_id}: {e}")
        return adr_ts
    except Exception as e:
        logger.warning(f"Failed to post ADR message in {channel_id}: {e}")
        return None


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
            # Post and pin ADR first to get adr_ts for persistence
            adr_ts = await _post_and_pin_adr(client, channel_id, d, user_id)

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
                adr_message_ts=adr_ts,
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

        # Update each pinned ADR message with status badge + lifecycle buttons
        for eid, _title in created:
            entity = aggregate.get_entity(EntityId(eid))
            if entity:
                await _update_adr_pinned_message(client, channel_id, entity, aggregate)

        await _update_dashboard_after_decision(client, channel_id, aggregate)

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


async def _update_dashboard_after_decision(
    client, channel_id: str, aggregate,
) -> None:
    """Update the channel dashboard after a decision change."""
    try:
        counts = {"pending": 0, "approved": 0, "committed": 0, "decisions": 0}
        pending_items = []
        decision_items = []
        for entity in aggregate.entities.values():
            if entity.entity_type.value == "decision":
                counts["decisions"] += 1
                entity_id = str(entity.id)
                title = getattr(entity.content, "title", entity_id[:8])
                lifecycle = get_lifecycle(entity)
                item: dict[str, str] = {
                    "title": title,
                    "id": entity_id,
                    "status": lifecycle.value,
                }
                adr_ts = getattr(entity, 'adr_message_ts', None)
                if adr_ts:
                    item["link"] = _build_slack_permalink(channel_id, adr_ts)
                if isinstance(entity, DeprecatedEntity) and entity.superseded_by:
                    item["superseded_by"] = str(entity.superseded_by)
                decision_items.append(item)
            else:
                lifecycle = get_lifecycle(entity)
                lc = lifecycle.value
                if lc in ("draft", "proposed"):
                    counts["pending"] += 1
                    pending_items.append({
                        "title": getattr(entity.content, "title", str(entity.id)[:8]),
                        "id": str(entity.id),
                    })
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
            decision_items=decision_items,
        )
    except Exception as e:
        logger.warning(f"Failed to update dashboard: {e}")


async def _update_adr_pinned_message(client, channel_id: str, entity, aggregate) -> None:
    """Update a pinned ADR message to reflect current lifecycle state.

    Rebuilds the ADR post blocks with the current status badge and
    appropriate lifecycle buttons, then calls chat_update.
    """
    adr_ts = getattr(entity, 'adr_message_ts', None)
    if not adr_ts:
        return

    lifecycle = get_lifecycle(entity)
    status = lifecycle.value
    title = getattr(entity.content, "title", "Untitled")
    decision_type = getattr(entity.content, "decision_type", None)
    decision_type_str = decision_type.value if decision_type else "architecture"
    description = getattr(entity.content, "description", "")
    rationale = getattr(entity.content, "rationale", "")
    alternatives = getattr(entity.content, "alternatives_considered", [])
    recorded_by = getattr(entity.attribution, "proposed_by", None)

    blocks = build_adr_post_blocks(
        title=title,
        decision_type=decision_type_str,
        decision=description,
        rationale=rationale,
        alternatives=alternatives if alternatives else None,
        recorded_by=str(recorded_by) if recorded_by else None,
        status=status,
        entity_id=str(entity.id),
    )

    try:
        await client.chat_update(
            channel=channel_id,
            ts=adr_ts,
            blocks=blocks,
            text=f"ADR: {title} ({status})",
        )
    except Exception as e:
        logger.warning(f"Failed to update pinned ADR message: {e}")


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
        # Post and pin ADR first to get adr_ts for persistence
        adr_ts = await _post_and_pin_adr(client, channel_id, decision, user_id)

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

        draft = aggregate.record_decision(
            actor_id=UserId(user_id),
            thread_ts=ThreadTs(thread_ts or ""),
            content=content,
            adr_message_ts=adr_ts,
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

        # Update pinned ADR message with status badge + lifecycle buttons
        recorded_entity = aggregate.get_entity(draft.id)
        if recorded_entity:
            await _update_adr_pinned_message(client, channel_id, recorded_entity, aggregate)

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
    async def handle_entity_action(ack, body: dict, action: dict, client, say, logger) -> None:
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

                # Update pinned ADR message if this is a decision
                if not is_work_item:
                    updated_entity = aggregate.get_entity(EntityId(entity_id))
                    if updated_entity:
                        await _update_adr_pinned_message(client, channel_id, updated_entity, aggregate)

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

    @app.action(RECORD_CONFIRM_PATTERN)
    async def handle_record_confirm(ack, body: dict, action: dict, client, say) -> None:
        """Handle Record Decision / Edit / Cancel buttons from RECORD mode preview."""
        await ack()

        action_id = action.get("action_id", "")
        channel_id = body.get("channel", {}).get("id")
        message_ts = body.get("message", {}).get("ts")
        user_id = body.get("user", {}).get("id")
        thread_ts = body.get("message", {}).get("thread_ts")
        blocks = body.get("message", {}).get("blocks", [])

        if action_id == "cancel_decision":
            # Replace buttons with cancelled context
            updated_blocks = [b for b in blocks if b.get("type") != "actions"]
            updated_blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "_Cancelled_"}],
            })
            try:
                await client.chat_update(
                    channel=channel_id, ts=message_ts,
                    blocks=updated_blocks, text="Decision cancelled",
                )
            except Exception as e:
                logger.warning(f"Failed to update cancelled message: {e}")
            return

        if action_id == "confirm_amend_decision":
            # Read decision data + entity_id from button value JSON
            try:
                button_value = json.loads(action.get("value", "{}"))
                entity_id_str = button_value.get("entity_id")
                decision = {
                    "decision_type": button_value.get("decision_type", "architecture"),
                    "title": button_value.get("title", ""),
                    "decision": button_value.get("decision", ""),
                    "rationale": button_value.get("rationale", ""),
                    "alternatives_considered": button_value.get("alternatives_considered", []),
                }
            except (json.JSONDecodeError, TypeError):
                entity_id_str = None
                decision = None

            if not entity_id_str:
                await say(text=":x: Could not determine which decision to amend.", thread_ts=thread_ts)
                return

            if not decision or not decision.get("title"):
                await say(text=":x: Could not parse amendment content.", thread_ts=thread_ts)
                return

            try:
                aggregate = await load_aggregate(channel_id)
                entity = aggregate.get_entity(EntityId(entity_id_str))

                if entity is None:
                    await say(text=f":x: Decision `{entity_id_str[:8]}` not found.", thread_ts=thread_ts)
                    return

                # Check if entity is amendable (only Draft and Proposed)
                if isinstance(entity, (ApprovedEntity,)):
                    await say(
                        text=f":x: This decision is already *Approved*. To change it, deprecate and record a new one.",
                        thread_ts=thread_ts,
                    )
                    return

                if not isinstance(entity, (DraftEntity, ProposedEntity)):
                    state_name = type(entity).__name__.replace("Entity", "")
                    await say(
                        text=f":x: This decision is already *{state_name}*. To change it, deprecate and record a new one.",
                        thread_ts=thread_ts,
                    )
                    return

                # Build new content
                try:
                    dt = DecisionType(decision.get("decision_type", "architecture").lower())
                except ValueError:
                    dt = DecisionType.ARCHITECTURE

                new_content = DecisionContent(
                    decision_type=dt,
                    title=decision["title"],
                    description=decision.get("decision", ""),
                    rationale=decision.get("rationale", ""),
                    alternatives_considered=decision.get("alternatives_considered", []),
                )

                # Post and pin new ADR message
                adr_ts = await _post_and_pin_adr(client, channel_id, decision, user_id)

                # Get old ADR message ts before amending
                old_adr_ts = getattr(entity, 'adr_message_ts', None)

                # Amend decision via aggregate
                aggregate.amend_decision(
                    entity_id=EntityId(entity_id_str),
                    actor_id=UserId(user_id),
                    new_content=new_content,
                    reason="Amended via thread discussion",
                    new_adr_message_ts=adr_ts,
                )
                await save_events(aggregate)

                logger.info(f"Amended decision '{decision['title']}' in {channel_id} by {user_id}")

                # Mark old ADR message as amended (prepend notice)
                if old_adr_ts:
                    try:
                        old_msg = await client.conversations_history(
                            channel=channel_id, latest=old_adr_ts, inclusive=True, limit=1,
                        )
                        old_blocks = old_msg.get("messages", [{}])[0].get("blocks", [])
                        amended_notice = {
                            "type": "context",
                            "elements": [{"type": "mrkdwn", "text": ":warning: _This decision has been amended. See updated version above._"}],
                        }
                        updated_old_blocks = [amended_notice] + old_blocks
                        await client.chat_update(
                            channel=channel_id, ts=old_adr_ts,
                            blocks=updated_old_blocks,
                            text="This decision has been amended.",
                        )
                    except Exception as e:
                        logger.warning(f"Failed to update old ADR message: {e}")

                # Update new pinned ADR message with status badge + lifecycle buttons
                amended_entity = aggregate.get_entity(EntityId(entity_id_str))
                if amended_entity:
                    await _update_adr_pinned_message(client, channel_id, amended_entity, aggregate)

                # Replace buttons with confirmation on the preview message
                updated_blocks = [b for b in blocks if b.get("type") != "actions"]
                updated_blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f":white_check_mark: *{decision['title']}* amended by <@{user_id}>"}],
                })

                await client.chat_update(
                    channel=channel_id, ts=message_ts,
                    blocks=updated_blocks,
                    text=f"Decision '{decision['title']}' amended",
                )

                await _update_dashboard_after_decision(client, channel_id, aggregate)

            except Exception as e:
                logger.error(f"Error amending decision: {e}", exc_info=True)
                await say(text=f":x: Failed to amend decision: {e}", thread_ts=thread_ts)
            return

        # Read decision data from button value JSON
        try:
            decision = json.loads(action.get("value", "{}"))
            if not decision.get("title"):
                decision = None
        except (json.JSONDecodeError, TypeError):
            decision = None

        if action_id == "edit_decision":
            from src.slack.blocks.decisions import build_edit_adr_modal

            trigger_id = body.get("trigger_id")
            if trigger_id and decision:
                modal = build_edit_adr_modal(
                    adr_index=0,
                    decision=decision,
                    channel_id=channel_id,
                    message_ts=message_ts,
                    thread_ts=thread_ts,
                )
                await client.views_open(trigger_id=trigger_id, view=modal)
            return

        if action_id == "confirm_record_decision":
            if not decision:
                await say(text=":x: Could not read decision data. Please try again.", thread_ts=thread_ts)
                return

            try:
                # Post and pin ADR first to get adr_ts
                adr_ts = await _post_and_pin_adr(client, channel_id, decision, user_id)

                aggregate = await load_aggregate(channel_id)

                try:
                    dt = DecisionType(decision.get("decision_type", "architecture").lower())
                except ValueError:
                    dt = DecisionType.ARCHITECTURE

                content = DecisionContent(
                    decision_type=dt,
                    title=decision["title"],
                    description=decision.get("decision", ""),
                    rationale=decision.get("rationale", ""),
                    alternatives_considered=decision.get("alternatives_considered", []),
                )

                draft = aggregate.record_decision(
                    actor_id=UserId(user_id),
                    thread_ts=ThreadTs(thread_ts or ""),
                    content=content,
                    adr_message_ts=adr_ts,
                )
                await save_events(aggregate)

                logger.info(f"Confirmed record decision '{decision['title']}' in {channel_id} by {user_id}")

                # Replace buttons with confirmation
                updated_blocks = [b for b in blocks if b.get("type") != "actions"]
                updated_blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f":white_check_mark: *{decision['title']}* recorded by <@{user_id}>"}],
                })

                await client.chat_update(
                    channel=channel_id, ts=message_ts,
                    blocks=updated_blocks,
                    text=f"Decision '{decision['title']}' recorded",
                )

                # Update pinned ADR message with status badge + lifecycle buttons
                recorded_entity = aggregate.get_entity(draft.id)
                if recorded_entity:
                    await _update_adr_pinned_message(client, channel_id, recorded_entity, aggregate)

                await _update_dashboard_after_decision(client, channel_id, aggregate)

            except Exception as e:
                logger.error(f"Error confirming record decision: {e}", exc_info=True)
                await say(text=f":x: Failed to record decision: {e}", thread_ts=thread_ts)

    @app.action(DEPRECATE_DECISION_ACTION)
    async def handle_deprecate_decision(ack, body: dict, action: dict, client, say) -> None:
        """Handle deprecate button click on committed decisions.

        Shows a confirmation prompt before deprecating.
        Entity ID is read from action["value"].
        """
        await ack()

        entity_id_str = action.get("value", "")
        if not entity_id_str:
            return

        channel_id = body.get("channel", {}).get("id")
        message_ts = body.get("message", {}).get("ts")
        thread_ts = body.get("message", {}).get("thread_ts")

        try:
            aggregate = await load_aggregate(channel_id)
            entity = aggregate.get_entity(EntityId(entity_id_str))

            if entity is None:
                await say(text=f":x: Entity `{entity_id_str[:8]}` not found.", thread_ts=thread_ts)
                return

            if not isinstance(entity, CommittedEntity):
                state_name = type(entity).__name__.replace("Entity", "")
                await say(
                    text=f":x: Only committed decisions can be deprecated. Current state: *{state_name}*.",
                    thread_ts=thread_ts,
                )
                return

            title = getattr(entity.content, "title", entity_id_str[:8])

            # Show confirmation prompt
            confirm_blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":warning: *Deprecate decision: {title}?*\nThis decision will be marked as deprecated.",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Confirm Deprecate"},
                            "style": "danger",
                            "action_id": "confirm_deprecate",
                            "value": entity_id_str,
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Cancel"},
                            "action_id": "cancel_deprecate",
                            "value": entity_id_str,
                        },
                    ],
                },
            ]

            await client.chat_update(
                channel=channel_id, ts=message_ts,
                blocks=confirm_blocks,
                text=f"Deprecate decision: {title}?",
            )

        except Exception as e:
            logger.error(f"Error showing deprecation confirmation: {e}", exc_info=True)
            await say(text=f":x: Failed to show deprecation confirmation: {e}", thread_ts=thread_ts)

    @app.action(DEPRECATE_CONFIRM_PATTERN)
    async def handle_deprecate_confirm(ack, body: dict, action: dict, client, say) -> None:
        """Handle confirm/cancel deprecation buttons.

        Entity ID is read from action["value"].
        """
        await ack()

        action_id = action.get("action_id", "")
        match = DEPRECATE_CONFIRM_PATTERN.match(action_id)
        if not match:
            return

        confirm_or_cancel = match.group(1)
        entity_id_str = action.get("value", "")
        if not entity_id_str:
            return

        channel_id = body.get("channel", {}).get("id")
        message_ts = body.get("message", {}).get("ts")
        thread_ts = body.get("message", {}).get("thread_ts")
        user_id = body.get("user", {}).get("id")

        if confirm_or_cancel == "cancel":
            # Replace confirmation buttons with cancelled context
            cancelled_blocks = [
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "_Deprecation cancelled_"}],
                },
            ]
            try:
                await client.chat_update(
                    channel=channel_id, ts=message_ts,
                    blocks=cancelled_blocks,
                    text="Deprecation cancelled",
                )
            except Exception as e:
                logger.warning(f"Failed to update cancelled deprecation message: {e}")
            return

        # confirm_or_cancel == "confirm"
        try:
            aggregate = await load_aggregate(channel_id)
            entity = aggregate.get_entity(EntityId(entity_id_str))

            if entity is None:
                await say(text=f":x: Decision `{entity_id_str[:8]}` not found.", thread_ts=thread_ts)
                return

            if not isinstance(entity, CommittedEntity):
                state_name = type(entity).__name__.replace("Entity", "")
                await say(
                    text=f":x: Only committed decisions can be deprecated. Current state: *{state_name}*.",
                    thread_ts=thread_ts,
                )
                return

            title = getattr(entity.content, "title", entity_id_str[:8])

            # Deprecate via aggregate
            deprecated = aggregate.deprecate_decision(
                entity_id=EntityId(entity_id_str),
                actor_id=UserId(user_id),
                reason="Deprecated via Slack",
            )
            await save_events(aggregate)

            logger.info(f"Deprecated decision '{title}' in {channel_id} by {user_id}")

            # Jira notification is handled asynchronously by JiraNotificationProjection
            # via the outbox pattern — no synchronous Jira call needed here.

            # Update pinned ADR message with new status badge + no buttons
            deprecated_entity = aggregate.get_entity(EntityId(entity_id_str))
            if deprecated_entity:
                await _update_adr_pinned_message(client, channel_id, deprecated_entity, aggregate)

            # Update dashboard
            await _update_dashboard_after_decision(client, channel_id, aggregate)

            # Replace confirmation buttons with result
            result_blocks = [
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f":no_entry_sign: *{title}* deprecated by <@{user_id}>"}],
                },
            ]
            await client.chat_update(
                channel=channel_id, ts=message_ts,
                blocks=result_blocks,
                text=f"Decision '{title}' deprecated",
            )

        except Exception as e:
            logger.error(f"Error deprecating decision: {e}", exc_info=True)
            await say(text=f":x: Failed to deprecate decision: {e}", thread_ts=thread_ts)

    @app.action(ADR_LIFECYCLE_PATTERN)
    async def handle_adr_lifecycle(ack, body: dict, action: dict, client, say) -> None:
        """Handle lifecycle action buttons on pinned ADR messages.

        Supports: adr_propose, adr_approve, adr_object, adr_deprecate.
        Entity ID is read from action["value"].
        """
        await ack()

        action_id = action.get("action_id", "")
        match = ADR_LIFECYCLE_PATTERN.match(action_id)
        if not match:
            return

        lifecycle_action = match.group(1)
        entity_id_str = action.get("value", "")
        if not entity_id_str:
            return

        channel_id = body.get("channel", {}).get("id")
        message_ts = body.get("message", {}).get("ts")
        user_id = body.get("user", {}).get("id")

        try:
            aggregate = await load_aggregate(channel_id)
            entity = aggregate.get_entity(EntityId(entity_id_str))

            if entity is None:
                await say(text=f":x: Decision `{entity_id_str[:8]}` not found.")
                return

            title = getattr(entity.content, "title", entity_id_str[:8])

            if lifecycle_action == "propose":
                if not isinstance(entity, DraftEntity):
                    await say(text=f":x: Decision must be in draft state to propose. Current: {type(entity).__name__}")
                    return

                proposed = aggregate.propose_decision(
                    entity_id=EntityId(entity_id_str),
                    actor_id=UserId(user_id),
                    canonical_message_ts=message_ts or "",
                )
                await save_events(aggregate)

                logger.info(f"ADR lifecycle: proposed '{title}' in {channel_id} by {user_id}")
                await _update_adr_pinned_message(client, channel_id, aggregate.get_entity(EntityId(entity_id_str)), aggregate)
                await say(text=f":hourglass: *{title}* proposed for approval by <@{user_id}>.")
                await _update_dashboard_after_decision(client, channel_id, aggregate)

            elif lifecycle_action == "approve":
                if not isinstance(entity, ProposedEntity):
                    await say(text=f":x: Decision must be in proposed state to approve. Current: {type(entity).__name__}")
                    return

                result = aggregate.approve_decision(
                    entity_id=EntityId(entity_id_str),
                    actor_id=UserId(user_id),
                )
                await save_events(aggregate)

                if isinstance(result, ApprovedEntity):
                    logger.info(f"ADR lifecycle: approved '{title}' in {channel_id} by {user_id}")
                    await say(text=f":white_check_mark: *{title}* approved by <@{user_id}>.")
                else:
                    await say(text=f":thumbsup: <@{user_id}> approved *{title}*. Waiting for more approvals.")

                await _update_adr_pinned_message(client, channel_id, aggregate.get_entity(EntityId(entity_id_str)), aggregate)
                await _update_dashboard_after_decision(client, channel_id, aggregate)

            elif lifecycle_action == "object":
                if not isinstance(entity, ProposedEntity):
                    await say(text=f":x: Decision must be in proposed state to object. Current: {type(entity).__name__}")
                    return

                aggregate.raise_entity_objection(
                    entity_id=EntityId(entity_id_str),
                    actor_id=UserId(user_id),
                    reason="Objection raised via ADR pinned message (reply in thread with details)",
                )
                await save_events(aggregate)

                logger.info(f"ADR lifecycle: objection on '{title}' in {channel_id} by {user_id}")
                await say(text=f":no_entry_sign: <@{user_id}> raised an objection to *{title}*. Please discuss in thread.")
                await _update_dashboard_after_decision(client, channel_id, aggregate)

            elif lifecycle_action == "deprecate":
                if not isinstance(entity, CommittedEntity):
                    # For approved decisions, show a message suggesting to commit first
                    state_name = type(entity).__name__.replace("Entity", "")
                    await say(text=f":x: Only committed decisions can be deprecated. Current state: *{state_name}*.")
                    return

                deprecated = aggregate.deprecate_decision(
                    entity_id=EntityId(entity_id_str),
                    actor_id=UserId(user_id),
                    reason="Deprecated via ADR pinned message",
                )
                await save_events(aggregate)

                logger.info(f"ADR lifecycle: deprecated '{title}' in {channel_id} by {user_id}")
                await _update_adr_pinned_message(client, channel_id, aggregate.get_entity(EntityId(entity_id_str)), aggregate)
                await say(text=f":no_entry_sign: *{title}* deprecated by <@{user_id}>.")
                await _update_dashboard_after_decision(client, channel_id, aggregate)

        except TransitionError as e:
            await say(text=f":x: Action failed: {e}")
        except Exception as e:
            logger.error(f"Error handling ADR lifecycle action: {e}", exc_info=True)
            await say(text=":x: An error occurred processing your action. Please try again.")

    # Catch-all for any unhandled actions (MUST be registered last)
    @app.action(re.compile(".*"))
    async def handle_unknown_action(ack, action: dict, logger) -> None:
        """Handle any unmatched action (fallback)."""
        await ack()
        logger.warning(f"Unhandled action: {action.get('action_id')}")

    logger.info("Action handlers registered")
