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
from src.slack.handlers.jira import handle_commit_to_jira, handle_create_anyway, handle_select_duplicate
from src.slack.response_gate import get_tracker

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

# Pattern for ADR pinned message lifecycle buttons: adr_propose, adr_approve, adr_object, adr_deprecate, adr_discard
ADR_LIFECYCLE_PATTERN = re.compile(r"^adr_(propose|approve|object|deprecate|discard)$")

# Pattern for work item draft preview buttons: propose_draft, edit_draft, cancel_draft
DRAFT_ACTION_PATTERN = re.compile(r"^(propose|edit|cancel)_draft$")

# Pattern for batch work item preview: wi_propose_0, wi_delete_1
WORK_ITEM_PREVIEW_PATTERN = re.compile(r"^wi_(propose|delete)_(\d+)$")

# Pattern for batch work item global actions: propose_all_work_items, cancel_all_work_items
WORK_ITEM_BATCH_PATTERN = re.compile(r"^(propose_all|cancel_all)_work_items$")

# Pattern for MODIFY mode apply/cancel buttons
MODIFY_ACTION_PATTERN = re.compile(r"^(apply|cancel)_modify$")

# Pattern for Jira duplicate selection buttons: select_duplicate_{jira_key}
JIRA_DUPLICATE_PATTERN = re.compile(r"^select_duplicate_.+$")


def _build_slack_permalink(channel_id: str, message_ts: str) -> str:
    """Build a Slack deep-link URL from channel ID and message timestamp."""
    ts_no_dot = message_ts.replace(".", "")
    return f"https://slack.com/archives/{channel_id}/p{ts_no_dot}"


async def _execute_action_plan(
    action: str,
    entity_ids: list[str],
    channel_id: str,
    user_id: str,
    thread_ts: str | None,
    client,
    say,
) -> None:
    """Execute an action plan directly on specified entities.

    Supports: approve, commit, propose, delete actions.
    This bypasses intent re-classification for deterministic execution.
    """
    logger.info(f"Executing action plan: {action} on {len(entity_ids)} entities")

    try:
        aggregate = await load_aggregate(channel_id)

        if action == "approve":
            approved_count = 0
            failed = []
            for eid in entity_ids:
                try:
                    entity = aggregate.get_entity(EntityId(eid))
                    if entity is None:
                        failed.append(f"{eid[:8]} (not found)")
                        continue
                    if not isinstance(entity, ProposedEntity):
                        failed.append(f"{eid[:8]} (not in proposed state)")
                        continue
                    aggregate.approve_entity(
                        entity_id=EntityId(eid),
                        actor_id=UserId(user_id),
                    )
                    approved_count += 1
                except TransitionError as e:
                    failed.append(f"{eid[:8]} ({e})")
                except Exception as e:
                    failed.append(f"{eid[:8]} (error: {e})")

            if approved_count > 0:
                await save_events(aggregate)
                # Refresh dashboard
                await _update_dashboard_after_decision(client, channel_id, aggregate)

            # Report results
            if approved_count > 0 and not failed:
                await say(
                    text=f":white_check_mark: Approved {approved_count} item(s).",
                    thread_ts=thread_ts,
                )
            elif approved_count > 0 and failed:
                await say(
                    text=f":white_check_mark: Approved {approved_count} item(s). Failed: {', '.join(failed)}",
                    thread_ts=thread_ts,
                )
            else:
                await say(
                    text=f":x: Could not approve any items. Issues: {', '.join(failed)}",
                    thread_ts=thread_ts,
                )

        elif action == "commit":
            # For commit, we need to trigger the Jira commit flow for each entity
            from src.config import get_settings
            from src.jira.factory import get_sync_service
            from src.domain.types import JiraKey

            settings = get_settings()
            sync_service = get_sync_service()
            committed_count = 0
            failed = []

            for eid in entity_ids:
                try:
                    entity = aggregate.get_entity(EntityId(eid))
                    if entity is None:
                        failed.append(f"{eid[:8]} (not found)")
                        continue
                    if not isinstance(entity, ApprovedEntity):
                        failed.append(f"{eid[:8]} (not approved)")
                        continue

                    # Check for parent epic key
                    epic_key = None
                    if hasattr(entity.content, "parent_id") and entity.content.parent_id:
                        parent = aggregate.get_entity(entity.content.parent_id)
                        if parent and hasattr(parent, "jira_link") and parent.jira_link:
                            epic_key = parent.jira_link.jira_key

                    jira_key = await sync_service.commit_work_item(
                        entity, settings.jira_default_project, epic_key=epic_key
                    )
                    aggregate.commit_work_item(
                        entity_id=EntityId(eid),
                        actor_id=UserId(user_id),
                        jira_key=JiraKey(jira_key),
                    )
                    committed_count += 1
                except Exception as e:
                    logger.warning(f"Failed to commit {eid}: {e}")
                    failed.append(f"{eid[:8]} ({e})")

            if committed_count > 0:
                await save_events(aggregate)
                await _update_dashboard_after_decision(client, channel_id, aggregate)

            if committed_count > 0 and not failed:
                await say(
                    text=f":rocket: Committed {committed_count} item(s) to Jira.",
                    thread_ts=thread_ts,
                )
            elif committed_count > 0 and failed:
                await say(
                    text=f":rocket: Committed {committed_count} item(s). Failed: {', '.join(failed)}",
                    thread_ts=thread_ts,
                )
            else:
                await say(
                    text=f":x: Could not commit any items. Issues: {', '.join(failed)}",
                    thread_ts=thread_ts,
                )

        elif action == "propose":
            proposed_count = 0
            failed = []
            for eid in entity_ids:
                try:
                    entity = aggregate.get_entity(EntityId(eid))
                    if entity is None:
                        failed.append(f"{eid[:8]} (not found)")
                        continue
                    if not isinstance(entity, DraftEntity):
                        failed.append(f"{eid[:8]} (not in draft state)")
                        continue
                    aggregate.propose_entity(
                        entity_id=EntityId(eid),
                        actor_id=UserId(user_id),
                    )
                    proposed_count += 1
                except TransitionError as e:
                    failed.append(f"{eid[:8]} ({e})")
                except Exception as e:
                    failed.append(f"{eid[:8]} (error: {e})")

            if proposed_count > 0:
                await save_events(aggregate)
                await _update_dashboard_after_decision(client, channel_id, aggregate)

            if proposed_count > 0 and not failed:
                await say(
                    text=f":ballot_box_with_ballot: Proposed {proposed_count} item(s) for approval.",
                    thread_ts=thread_ts,
                )
            elif proposed_count > 0 and failed:
                await say(
                    text=f":ballot_box_with_ballot: Proposed {proposed_count} item(s). Failed: {', '.join(failed)}",
                    thread_ts=thread_ts,
                )
            else:
                await say(
                    text=f":x: Could not propose any items. Issues: {', '.join(failed)}",
                    thread_ts=thread_ts,
                )

        elif action == "delete":
            deleted_count = 0
            failed = []
            for eid in entity_ids:
                try:
                    entity = aggregate.get_entity(EntityId(eid))
                    if entity is None:
                        failed.append(f"{eid[:8]} (not found)")
                        continue
                    # Only draft entities can be deleted
                    if not isinstance(entity, DraftEntity):
                        failed.append(f"{eid[:8]} (can only delete drafts)")
                        continue
                    aggregate.discard_entity(
                        entity_id=EntityId(eid),
                        actor_id=UserId(user_id),
                    )
                    deleted_count += 1
                except Exception as e:
                    failed.append(f"{eid[:8]} (error: {e})")

            if deleted_count > 0:
                await save_events(aggregate)
                await _update_dashboard_after_decision(client, channel_id, aggregate)

            if deleted_count > 0 and not failed:
                await say(
                    text=f":wastebasket: Deleted {deleted_count} draft item(s).",
                    thread_ts=thread_ts,
                )
            elif deleted_count > 0 and failed:
                await say(
                    text=f":wastebasket: Deleted {deleted_count} draft(s). Failed: {', '.join(failed)}",
                    thread_ts=thread_ts,
                )
            else:
                await say(
                    text=f":x: Could not delete any items. Issues: {', '.join(failed)}",
                    thread_ts=thread_ts,
                )

        else:
            await say(
                text=f":warning: Unknown action type: {action}",
                thread_ts=thread_ts,
            )

    except Exception as e:
        logger.error(f"Error executing action plan: {e}", exc_info=True)
        await say(
            text=f":x: Failed to execute action: {e}",
            thread_ts=thread_ts,
        )


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
            get_tracker().record_bot_response(channel_id, adr_ts)
            try:
                await client.pins_add(channel=channel_id, timestamp=adr_ts)
            except Exception as e:
                logger.warning(f"Failed to pin ADR message in {channel_id}: {e}")
        return adr_ts
    except Exception as e:
        logger.warning(f"Failed to post ADR message in {channel_id}: {e}")
        return None


def _build_work_item_pinned_blocks(
    entity_id: str,
    content,
    user_id: str,
    status: str = "proposed",
    approved_by: str | None = None,
    jira_key: str | None = None,
    parent_title: str | None = None,
    parent_jira_key: str | None = None,
) -> list[dict]:
    """Build blocks for work item pinned message based on lifecycle status.

    Args:
        entity_id: Entity ID for action buttons
        content: WorkItemContent with title, issue_type, description, acceptance_criteria
        user_id: User who proposed the item
        status: Lifecycle status (proposed, approved, committed)
        approved_by: User who approved (if status is approved or committed)
        jira_key: Jira issue key (if committed)
        parent_title: Title of parent entity (Epic/Feature) if linked
        parent_jira_key: Jira key of parent entity if committed

    Returns list of Slack blocks.
    """
    # Status badges
    STATUS_BADGES = {
        "proposed": ":mega: Proposed",
        "approved": ":white_check_mark: Approved",
        "committed": ":jira: In Jira",
    }
    badge = STATUS_BADGES.get(status, STATUS_BADGES["proposed"])

    ac_text = ""
    if hasattr(content, "acceptance_criteria") and content.acceptance_criteria:
        ac_items = "\n".join(f"  - {ac}" for ac in content.acceptance_criteria)
        ac_text = f"\n*Acceptance Criteria:*\n{ac_items}"

    issue_type = content.issue_type.value.title() if hasattr(content, "issue_type") else "Story"

    # Build header text
    title = getattr(content, "title", "Untitled")
    if jira_key:
        header = f"{badge}: *{jira_key} - {title}*"
    else:
        header = f"{badge}: *{title}*"

    # Build parent context line
    parent_text = ""
    if parent_title:
        if parent_jira_key:
            parent_text = f"\n*Parent:* {parent_jira_key} - {parent_title}"
        else:
            parent_text = f"\n*Parent:* {parent_title}"

    # Build footer
    footer_parts = [f"_Proposed by <@{user_id}>_"]
    if approved_by and status in ("approved", "committed"):
        footer_parts.append(f"_Approved by <@{approved_by}>_")

    description = getattr(content, "description", "")[:500]

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{header}\n"
                    f"*Type:* {issue_type}"
                    f"{parent_text}\n"
                    f"{description}"
                    f"{ac_text}\n\n"
                    + " | ".join(footer_parts)
                ),
            },
        },
    ]

    # Add lifecycle buttons based on status
    if status == "proposed":
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": f"approve_{entity_id}",
                    "value": str(entity_id),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Object"},
                    "style": "danger",
                    "action_id": f"object_{entity_id}",
                    "value": str(entity_id),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Discuss"},
                    "action_id": f"discuss_{entity_id}",
                    "value": str(entity_id),
                },
            ],
        })
    elif status == "approved":
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Commit to Jira"},
                    "style": "primary",
                    "action_id": "commit_to_jira",
                    "value": str(entity_id),
                },
            ],
        })
    # For committed status, no buttons needed

    return blocks


async def _update_work_item_pinned_message(
    client, channel_id: str, message_ts: str, entity_id: str, content,
    user_id: str, status: str, approved_by: str | None = None, jira_key: str | None = None,
    parent_title: str | None = None, parent_jira_key: str | None = None,
) -> None:
    """Update a work item's pinned message to reflect current lifecycle state."""
    blocks = _build_work_item_pinned_blocks(
        entity_id=entity_id,
        content=content,
        user_id=user_id,
        status=status,
        approved_by=approved_by,
        jira_key=jira_key,
        parent_title=parent_title,
        parent_jira_key=parent_jira_key,
    )

    title = getattr(content, "title", "Untitled")
    try:
        await client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=blocks,
            text=f"{status.title()}: {title}",
        )
    except Exception as e:
        logger.warning(f"Failed to update work item pinned message: {e}")


async def _post_and_pin_work_item(
    client, channel_id: str, entity_id: str, content, user_id: str,
    parent_title: str | None = None, parent_jira_key: str | None = None,
) -> str | None:
    """Post a formatted work item proposal to the channel and pin it.

    Args:
        client: Slack client
        channel_id: Channel to post in
        entity_id: Entity ID for action buttons
        content: WorkItemContent with title, issue_type, description, acceptance_criteria
        user_id: User who proposed the item
        parent_title: Title of parent entity (Epic/Feature) if linked
        parent_jira_key: Jira key of parent entity if committed

    Returns the message timestamp on success, or None on failure.
    """
    proposal_blocks = _build_work_item_pinned_blocks(
        entity_id=entity_id,
        content=content,
        user_id=user_id,
        status="proposed",
        parent_title=parent_title,
        parent_jira_key=parent_jira_key,
    )

    try:
        result = await client.chat_postMessage(
            channel=channel_id,
            blocks=proposal_blocks,
            text=f"Proposed: {getattr(content, 'title', 'Untitled')}",
        )
        wi_ts = result.get("ts")
        if wi_ts:
            get_tracker().record_bot_response(channel_id, wi_ts)
            try:
                await client.pins_add(channel=channel_id, timestamp=wi_ts)
            except Exception as e:
                logger.warning(f"Failed to pin work item in {channel_id}: {e}")
        return wi_ts
    except Exception as e:
        logger.warning(f"Failed to post work item in {channel_id}: {e}")
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
        if thread_ts:
            get_tracker().record_bot_response(channel_id, thread_ts)

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
    """Update the channel dashboard after a decision/work item change.

    Slack is the source of truth: only items with actual pinned messages
    are shown. If a pinned message is removed, the item won't appear.
    """
    from src.config import get_settings

    try:
        settings = get_settings()

        # Fetch actual pinned messages from Slack - this is the source of truth
        pinned_messages = {}  # message_ts -> message data
        try:
            result = await client.pins_list(channel=channel_id)
            for item in result.get("items", []):
                message = item.get("message", {})
                ts = message.get("ts")
                if ts:
                    pinned_messages[ts] = message
            logger.debug(f"Found {len(pinned_messages)} pinned messages in {channel_id}")
        except Exception as e:
            logger.warning(f"Failed to fetch pinned messages: {e}")
            # Continue with empty - dashboard will show no items

        counts = {"pending": 0, "approved": 0, "committed": 0, "decisions": 0}
        pending_items = []
        approved_items = []
        committed_items = []
        decision_items = []

        for entity in aggregate.entities.values():
            if entity.entity_type.value == "decision":
                # Check if ADR pinned message still exists
                adr_ts = getattr(entity, 'adr_message_ts', None)
                if not adr_ts or adr_ts not in pinned_messages:
                    # Pinned message removed - skip this decision
                    continue

                counts["decisions"] += 1
                entity_id = str(entity.id)
                title = getattr(entity.content, "title", entity_id[:8])
                lifecycle = get_lifecycle(entity)
                item: dict[str, str] = {
                    "title": title,
                    "id": entity_id,
                    "status": lifecycle.value,
                    "link": _build_slack_permalink(channel_id, adr_ts),
                }
                if isinstance(entity, DeprecatedEntity) and entity.superseded_by:
                    item["superseded_by"] = str(entity.superseded_by)
                decision_items.append(item)
            else:
                # Work items - check if pinned message exists
                pinned_ts = getattr(entity, 'canonical_message_ts', None)
                if not pinned_ts or pinned_ts not in pinned_messages:
                    # No pinned message - skip this work item
                    continue

                lifecycle = get_lifecycle(entity)
                lc = lifecycle.value
                entity_id = str(entity.id)
                title = getattr(entity.content, "title", entity_id[:8])
                pinned_link = _build_slack_permalink(channel_id, pinned_ts)

                # Look up parent info for hierarchy display
                parent_title = None
                parent_jira_key = None
                parent_id = getattr(entity.content, "parent_id", None)
                if parent_id:
                    parent = aggregate.get_entity(parent_id)
                    if parent and hasattr(parent.content, "title"):
                        parent_title = parent.content.title
                    if parent and hasattr(parent, "jira_link") and parent.jira_link:
                        parent_jira_key = parent.jira_link.jira_key

                if lc in ("draft", "proposed"):
                    counts["pending"] += 1
                    item_data = {
                        "title": title,
                        "id": entity_id,
                        "link": pinned_link,
                    }
                    if parent_title:
                        item_data["parent_title"] = parent_title
                    pending_items.append(item_data)
                elif lc == "approved":
                    counts["approved"] += 1
                    item_data = {
                        "title": title,
                        "id": entity_id,
                        "link": pinned_link,
                    }
                    if parent_title:
                        item_data["parent_title"] = parent_title
                    approved_items.append(item_data)
                elif lc == "committed":
                    counts["committed"] += 1
                    jira_key = ""
                    if hasattr(entity, "jira_link") and entity.jira_link:
                        jira_key = entity.jira_link.jira_key
                    item_data = {
                        "title": title,
                        "id": entity_id,
                        "jira_key": jira_key,
                        "link": pinned_link,
                    }
                    if parent_title:
                        item_data["parent_title"] = parent_title
                    if parent_jira_key:
                        item_data["parent_jira_key"] = parent_jira_key
                    committed_items.append(item_data)

        slack_client = SlackClient(client)
        dashboard_mgr = DashboardManager(slack_client)
        await dashboard_mgr.create_or_update(
            channel_id=channel_id,
            pending_count=counts["pending"],
            approved_count=counts["approved"],
            committed_count=counts["committed"],
            decisions_count=counts["decisions"],
            pending_items=pending_items,
            approved_items=approved_items,
            committed_items=committed_items,
            decision_items=decision_items,
            jira_url=settings.jira_url if settings.jira_url else None,
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
    patterns = getattr(entity.content, "patterns_referenced", [])
    tradeoffs = getattr(entity.content, "tradeoffs", [])
    recorded_by = getattr(entity.attribution, "proposed_by", None)

    blocks = build_adr_post_blocks(
        title=title,
        decision_type=decision_type_str,
        decision=description,
        rationale=rationale,
        alternatives=alternatives if alternatives else None,
        patterns_referenced=patterns if patterns else None,
        tradeoffs=tradeoffs if tradeoffs else None,
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
        if thread_ts:
            get_tracker().record_bot_response(channel_id, thread_ts)

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


async def _propose_single_work_item(
    client, say, channel_id: str, message_ts: str, thread_ts: str | None,
    user_id: str, blocks: list[dict], item_index: int, content_data: dict,
) -> None:
    """Propose a single work item from a batch preview."""
    from src.domain.content import IssueType, WorkItemContent
    from src.domain.types import EntityId

    try:
        aggregate = await load_aggregate(channel_id)

        # Get parent_id from content_data if present
        parent_id_str = content_data.get("parent_id")
        parent_id = EntityId(parent_id_str) if parent_id_str else None

        content = WorkItemContent(
            issue_type=IssueType(content_data.get("issue_type", "story").lower()),
            title=content_data["title"],
            description=content_data.get("description", ""),
            acceptance_criteria=content_data.get("acceptance_criteria", []),
            constraints=content_data.get("constraints", []),
        )

        draft = aggregate.draft_work_item(
            actor_id=UserId(user_id),
            thread_ts=ThreadTs(thread_ts or ""),
            content=content,
            parent_id=parent_id,
        )

        proposed = aggregate.propose_work_item(
            entity_id=draft.id,
            actor_id=UserId(user_id),
            canonical_message_ts=message_ts or "",
        )
        await save_events(aggregate)

        logger.info(f"Proposed work item '{content.title}' from batch in {channel_id} by {user_id}")
        if thread_ts:
            get_tracker().record_bot_response(channel_id, thread_ts)

        # Look up parent info for display
        parent_title = None
        parent_jira_key = None
        if parent_id:
            parent = aggregate.get_entity(parent_id)
            if parent and hasattr(parent.content, "title"):
                parent_title = parent.content.title
            if parent and hasattr(parent, "jira_link") and parent.jira_link:
                parent_jira_key = parent.jira_link.jira_key

        # Post pinned proposal message to the channel
        await _post_and_pin_work_item(
            client, channel_id, str(draft.id), content, user_id,
            parent_title=parent_title, parent_jira_key=parent_jira_key,
        )

        # Replace the item's blocks with confirmation
        target_text = f"*{item_index + 1}. "
        for i, block in enumerate(blocks):
            if block.get("type") == "section":
                text = block.get("text", {}).get("text", "")
                if text.startswith(target_text):
                    confirmation = {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": f":white_check_mark: *{content.title}* proposed by <@{user_id}>"}],
                    }
                    blocks = _replace_adr_blocks(blocks, i, confirmation)
                    break

        try:
            await client.chat_update(
                channel=channel_id, ts=message_ts,
                blocks=blocks, text=f"Work item '{content.title}' proposed",
            )
        except Exception as e:
            logger.warning(f"Failed to update preview message: {e}")

        await _update_dashboard_after_decision(client, channel_id, aggregate)

    except Exception as e:
        logger.error(f"Error proposing work item from batch: {e}", exc_info=True)
        await say(text=f":x: Failed to propose work item: {e}", thread_ts=thread_ts)


async def _propose_all_work_items(
    client, say, channel_id: str, message_ts: str, thread_ts: str | None,
    user_id: str, original_blocks: list[dict], work_items: list[dict],
) -> None:
    """Propose all work items from a batch preview."""
    from src.domain.content import IssueType, WorkItemContent
    from src.domain.types import EntityId

    try:
        aggregate = await load_aggregate(channel_id)

        created = []
        for w in work_items:
            # Get parent_id from work item data if present
            parent_id_str = w.get("parent_id")
            parent_id = EntityId(parent_id_str) if parent_id_str else None

            content = WorkItemContent(
                issue_type=IssueType(w.get("issue_type", "story").lower()),
                title=w["title"],
                description=w.get("description", ""),
                acceptance_criteria=w.get("acceptance_criteria", []),
                constraints=w.get("constraints", []),
            )

            draft = aggregate.draft_work_item(
                actor_id=UserId(user_id),
                thread_ts=ThreadTs(thread_ts or ""),
                content=content,
                parent_id=parent_id,
            )

            aggregate.propose_work_item(
                entity_id=draft.id,
                actor_id=UserId(user_id),
                canonical_message_ts=message_ts or "",
            )
            created.append((str(draft.id), content))

        await save_events(aggregate)

        logger.info(f"Proposed {len(created)} work items from batch in {channel_id} by {user_id}")
        if thread_ts:
            get_tracker().record_bot_response(channel_id, thread_ts)

        # Post pinned proposal messages to the channel for each work item
        for entity_id, content in created:
            # Look up parent info for display
            parent_title = None
            parent_jira_key = None
            entity = aggregate.get_entity(EntityId(entity_id))
            if entity and hasattr(entity.content, "parent_id") and entity.content.parent_id:
                parent = aggregate.get_entity(entity.content.parent_id)
                if parent and hasattr(parent.content, "title"):
                    parent_title = parent.content.title
                if parent and hasattr(parent, "jira_link") and parent.jira_link:
                    parent_jira_key = parent.jira_link.jira_key

            await _post_and_pin_work_item(
                client, channel_id, entity_id, content, user_id,
                parent_title=parent_title, parent_jira_key=parent_jira_key,
            )

        # Replace all buttons with confirmation
        updated_blocks = [b for b in original_blocks if b.get("type") != "actions"]
        updated_blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":white_check_mark: *{len(created)} work items proposed* by <@{user_id}>",
            },
        })

        await client.chat_update(
            channel=channel_id, ts=message_ts,
            blocks=updated_blocks,
            text=f"{len(created)} work items proposed",
        )

        await _update_dashboard_after_decision(client, channel_id, aggregate)

    except Exception as e:
        logger.error(f"Error proposing batch work items: {e}", exc_info=True)
        await say(
            text=f":x: Failed to propose work items: {e}",
            thread_ts=thread_ts,
        )


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
        message_ts = body.get("message", {}).get("ts")
        # Use thread_ts if in a thread, otherwise use message_ts to reply under the pinned message
        thread_ts = body.get("message", {}).get("thread_ts") or message_ts

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

                if thread_ts:
                    get_tracker().record_bot_response(channel_id, thread_ts)

                # Update pinned message based on entity type
                if is_work_item:
                    # Update work item pinned message to show "Commit to Jira" button
                    if isinstance(result, ApprovedEntity):
                        proposed_by = getattr(result.attribution, "proposed_by", None)
                        await _update_work_item_pinned_message(
                            client=client,
                            channel_id=channel_id,
                            message_ts=message_ts,  # The pinned message we clicked on
                            entity_id=entity_id,
                            content=result.content,
                            user_id=str(proposed_by) if proposed_by else user_id,
                            status="approved",
                            approved_by=user_id,
                        )
                else:
                    # Update pinned ADR message
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
                if thread_ts:
                    get_tracker().record_bot_response(channel_id, thread_ts)

            elif action_type == "discuss":
                title = getattr(entity.content, "title", entity_id)
                await say(
                    text=f":speech_balloon: <@{user_id}> wants to discuss *{title}*. Reply in this thread.",
                    thread_ts=thread_ts,
                )
                if thread_ts:
                    get_tracker().record_bot_response(channel_id, thread_ts)

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

        # Update original message: replace only the answered question's blocks,
        # preserve other unanswered questions' blocks.
        if message_ts and channel_id:
            try:
                original_blocks = body.get("message", {}).get("blocks", [])
                action_id = action.get("action_id", "")

                # Find the actions block that contains the clicked button
                answered_actions_idx = None
                for i, block in enumerate(original_blocks):
                    if block.get("type") != "actions":
                        continue
                    for elem in block.get("elements", []):
                        if elem.get("action_id") == action_id:
                            answered_actions_idx = i
                            break
                    if answered_actions_idx is not None:
                        break

                if answered_actions_idx is not None:
                    # Question blocks are a triplet: section (question text),
                    # actions (buttons), context (hint). Replace all three with
                    # a Q/A summary.
                    qa_summary = {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Q:* {question}\n*A:* {answer}",
                        },
                    }

                    # Determine the triplet range around the actions block
                    remove_start = answered_actions_idx
                    remove_end = answered_actions_idx + 1  # exclusive

                    # Check if preceding block is the question section
                    if remove_start > 0 and original_blocks[remove_start - 1].get("type") == "section":
                        text = original_blocks[remove_start - 1].get("text", {}).get("text", "")
                        # Question sections are bold: "*question text*"
                        if text.startswith("*") and text.endswith("*"):
                            remove_start -= 1

                    # Check if following block is the hint context
                    if remove_end < len(original_blocks) and original_blocks[remove_end].get("type") == "context":
                        ctx_text = ""
                        elems = original_blocks[remove_end].get("elements", [])
                        if elems:
                            ctx_text = elems[0].get("text", "")
                        if "Type your answer" in ctx_text:
                            remove_end += 1

                    updated_blocks = (
                        original_blocks[:remove_start]
                        + [qa_summary]
                        + original_blocks[remove_end:]
                    )
                else:
                    # Fallback: couldn't find the specific actions block
                    updated_blocks = [
                        block for block in original_blocks
                        if block.get("type") != "actions"
                    ]
                    updated_blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Q:* {question}\n*A:* {answer}",
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

        # Post the answer as a visible thread message (for conversation record)
        await say(
            text=answer,
            thread_ts=thread_ts,
        )
        if thread_ts:
            get_tracker().record_bot_response(channel_id, thread_ts)

        # Check for action plan - execute directly if present
        action_type = value.get("action")
        entity_ids = value.get("entity_ids", [])

        if action_type and entity_ids:
            # Execute action plan directly without re-classification
            await _execute_action_plan(
                action=action_type,
                entity_ids=entity_ids,
                channel_id=channel_id,
                user_id=user_id,
                thread_ts=thread_ts,
                client=client,
                say=say,
            )
            return

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
                if thread_ts:
                    get_tracker().record_bot_response(channel_id, thread_ts)

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
        # Use message_ts as thread_ts to reply under the pinned ADR message
        thread_ts = message_ts

        try:
            aggregate = await load_aggregate(channel_id)
            entity = aggregate.get_entity(EntityId(entity_id_str))

            if entity is None:
                await say(text=f":x: Decision `{entity_id_str[:8]}` not found.", thread_ts=thread_ts)
                return

            title = getattr(entity.content, "title", entity_id_str[:8])

            if lifecycle_action == "propose":
                if not isinstance(entity, DraftEntity):
                    await say(text=f":x: Decision must be in draft state to propose. Current: {type(entity).__name__}", thread_ts=thread_ts)
                    return

                proposed = aggregate.propose_decision(
                    entity_id=EntityId(entity_id_str),
                    actor_id=UserId(user_id),
                    canonical_message_ts=message_ts or "",
                )
                await save_events(aggregate)

                logger.info(f"ADR lifecycle: proposed '{title}' in {channel_id} by {user_id}")
                await _update_adr_pinned_message(client, channel_id, aggregate.get_entity(EntityId(entity_id_str)), aggregate)
                await say(text=f":hourglass: *{title}* proposed for approval by <@{user_id}>.", thread_ts=thread_ts)
                await _update_dashboard_after_decision(client, channel_id, aggregate)

            elif lifecycle_action == "approve":
                if not isinstance(entity, ProposedEntity):
                    await say(text=f":x: Decision must be in proposed state to approve. Current: {type(entity).__name__}", thread_ts=thread_ts)
                    return

                result = aggregate.approve_decision(
                    entity_id=EntityId(entity_id_str),
                    actor_id=UserId(user_id),
                )
                await save_events(aggregate)

                if isinstance(result, ApprovedEntity):
                    logger.info(f"ADR lifecycle: approved '{title}' in {channel_id} by {user_id}")
                    await say(text=f":white_check_mark: *{title}* approved by <@{user_id}>.", thread_ts=thread_ts)
                else:
                    await say(text=f":thumbsup: <@{user_id}> approved *{title}*. Waiting for more approvals.", thread_ts=thread_ts)

                await _update_adr_pinned_message(client, channel_id, aggregate.get_entity(EntityId(entity_id_str)), aggregate)
                await _update_dashboard_after_decision(client, channel_id, aggregate)

            elif lifecycle_action == "object":
                if not isinstance(entity, ProposedEntity):
                    await say(text=f":x: Decision must be in proposed state to object. Current: {type(entity).__name__}", thread_ts=thread_ts)
                    return

                aggregate.raise_entity_objection(
                    entity_id=EntityId(entity_id_str),
                    actor_id=UserId(user_id),
                    reason="Objection raised via ADR pinned message (reply in thread with details)",
                )
                await save_events(aggregate)

                logger.info(f"ADR lifecycle: objection on '{title}' in {channel_id} by {user_id}")
                await say(text=f":no_entry_sign: <@{user_id}> raised an objection to *{title}*. Please discuss in thread.", thread_ts=thread_ts)
                await _update_dashboard_after_decision(client, channel_id, aggregate)

            elif lifecycle_action == "deprecate":
                if not isinstance(entity, CommittedEntity):
                    # For approved decisions, show a message suggesting to commit first
                    state_name = type(entity).__name__.replace("Entity", "")
                    await say(text=f":x: Only committed decisions can be deprecated. Current state: *{state_name}*.", thread_ts=thread_ts)
                    return

                deprecated = aggregate.deprecate_decision(
                    entity_id=EntityId(entity_id_str),
                    actor_id=UserId(user_id),
                    reason="Deprecated via ADR pinned message",
                )
                await save_events(aggregate)

                logger.info(f"ADR lifecycle: deprecated '{title}' in {channel_id} by {user_id}")
                await _update_adr_pinned_message(client, channel_id, aggregate.get_entity(EntityId(entity_id_str)), aggregate)
                await say(text=f":no_entry_sign: *{title}* deprecated by <@{user_id}>.", thread_ts=thread_ts)
                await _update_dashboard_after_decision(client, channel_id, aggregate)

            elif lifecycle_action == "discard":
                if not isinstance(entity, (DraftEntity, ProposedEntity)):
                    state_name = type(entity).__name__.replace("Entity", "")
                    await say(text=f":x: Only Draft or Proposed decisions can be discarded. Current state: *{state_name}*.", thread_ts=thread_ts)
                    return

                adr_ts = getattr(entity, 'adr_message_ts', None)

                aggregate.discard_decision(
                    entity_id=EntityId(entity_id_str),
                    actor_id=UserId(user_id),
                    reason="Discarded via ADR pinned message",
                )
                await save_events(aggregate)

                logger.info(f"ADR lifecycle: discarded '{title}' in {channel_id} by {user_id}")

                # Update pinned ADR message to show discarded state with no buttons
                if adr_ts:
                    from src.slack.blocks.decisions import build_adr_post_blocks, STATUS_BADGES
                    discarded_blocks = build_adr_post_blocks(
                        title=title,
                        decision_type=getattr(entity.content, "decision_type", None),
                        decision=getattr(entity.content, "description", ""),
                        rationale=getattr(entity.content, "rationale", ""),
                        status="discarded",
                        entity_id=None,  # No buttons
                    )
                    try:
                        await client.chat_update(
                            channel=channel_id, ts=adr_ts,
                            blocks=discarded_blocks,
                            text=f"ADR: {title} (discarded)",
                        )
                    except Exception as e:
                        logger.warning(f"Failed to update discarded ADR message: {e}")

                    # Unpin the message
                    try:
                        await client.pins_remove(channel=channel_id, timestamp=adr_ts)
                    except Exception as e:
                        logger.warning(f"Failed to unpin discarded ADR message: {e}")

                await say(text=f":x: *{title}* discarded by <@{user_id}>.", thread_ts=thread_ts)
                await _update_dashboard_after_decision(client, channel_id, aggregate)

        except TransitionError as e:
            await say(text=f":x: Action failed: {e}", thread_ts=thread_ts)
        except Exception as e:
            logger.error(f"Error handling ADR lifecycle action: {e}", exc_info=True)
            await say(text=":x: An error occurred processing your action. Please try again.", thread_ts=thread_ts)

    @app.action(DRAFT_ACTION_PATTERN)
    async def handle_draft_action(ack, body: dict, action: dict, client, say) -> None:
        """Handle Propose / Edit / Cancel buttons on work item draft previews.

        Work item content is stored as JSON in button value.
        """
        await ack()

        action_id = action.get("action_id", "")
        match = DRAFT_ACTION_PATTERN.match(action_id)
        if not match:
            return

        draft_action = match.group(1)
        channel_id = body.get("channel", {}).get("id")
        message_ts = body.get("message", {}).get("ts")
        user_id = body.get("user", {}).get("id")
        thread_ts = body.get("message", {}).get("thread_ts")
        blocks = body.get("message", {}).get("blocks", [])

        if draft_action == "cancel":
            updated_blocks = [b for b in blocks if b.get("type") != "actions"]
            updated_blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "_Cancelled_"}],
            })
            try:
                await client.chat_update(
                    channel=channel_id, ts=message_ts,
                    blocks=updated_blocks, text="Draft cancelled",
                )
            except Exception as e:
                logger.warning(f"Failed to update cancelled draft message: {e}")
            return

        # Parse work item content from button value
        try:
            content_data = json.loads(action.get("value", "{}"))
        except (json.JSONDecodeError, TypeError):
            content_data = None

        if not content_data or not content_data.get("title"):
            await say(text=":x: Could not read draft data. Please try again.", thread_ts=thread_ts)
            return

        if draft_action == "edit":
            # TODO: Open edit modal for work items (similar to ADR edit)
            await say(
                text=":pencil2: Work item editing is not yet supported. Please cancel and re-create.",
                thread_ts=thread_ts,
            )
            return

        # draft_action == "propose"
        try:
            from src.domain.content import IssueType, WorkItemContent

            aggregate = await load_aggregate(channel_id)

            content = WorkItemContent(
                issue_type=IssueType(content_data.get("issue_type", "story").lower()),
                title=content_data["title"],
                description=content_data.get("description", ""),
                acceptance_criteria=content_data.get("acceptance_criteria", []),
                constraints=content_data.get("constraints", []),
            )

            draft = aggregate.draft_work_item(
                actor_id=UserId(user_id),
                thread_ts=ThreadTs(thread_ts or ""),
                content=content,
            )

            proposed = aggregate.propose_work_item(
                entity_id=draft.id,
                actor_id=UserId(user_id),
                canonical_message_ts=message_ts or "",
            )
            await save_events(aggregate)

            logger.info(f"Proposed work item '{content.title}' in {channel_id} by {user_id}")
            if thread_ts:
                get_tracker().record_bot_response(channel_id, thread_ts)

            # Build proposal blocks with approve/object/discuss buttons
            ac_text = ""
            if content.acceptance_criteria:
                ac_items = "\n".join(f"  - {ac}" for ac in content.acceptance_criteria)
                ac_text = f"\n*Acceptance Criteria:*\n{ac_items}"

            proposal_blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f":mega: *Proposed: {content.title}*\n"
                            f"*Type:* {content.issue_type.value.title()}\n"
                            f"{content.description[:500]}"
                            f"{ac_text}\n\n"
                            f"_Proposed by <@{user_id}>_"
                        ),
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Approve"},
                            "style": "primary",
                            "action_id": f"approve_{draft.id}",
                            "value": str(draft.id),
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Object"},
                            "style": "danger",
                            "action_id": f"object_{draft.id}",
                            "value": str(draft.id),
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Discuss"},
                            "action_id": f"discuss_{draft.id}",
                            "value": str(draft.id),
                        },
                    ],
                },
            ]

            # Post proposal to main channel (not in thread) and pin it
            try:
                result = await client.chat_postMessage(
                    channel=channel_id,
                    blocks=proposal_blocks,
                    text=f"Proposed: {content.title}",
                )
                proposal_ts = result.get("ts")
                if proposal_ts:
                    get_tracker().record_bot_response(channel_id, proposal_ts)
                    try:
                        await client.pins_add(channel=channel_id, timestamp=proposal_ts)
                    except Exception as e:
                        logger.warning(f"Failed to pin proposal in {channel_id}: {e}")
            except Exception as e:
                logger.warning(f"Failed to post proposal to channel: {e}")

            # Update the original thread preview to show confirmation
            confirmed_blocks = [b for b in blocks if b.get("type") != "actions"]
            confirmed_blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f":white_check_mark: *{content.title}* proposed to channel by <@{user_id}>"}],
            })
            try:
                await client.chat_update(
                    channel=channel_id, ts=message_ts,
                    blocks=confirmed_blocks,
                    text=f"Proposed: {content.title}",
                )
            except Exception as e:
                logger.warning(f"Failed to update preview message: {e}")

            await _update_dashboard_after_decision(client, channel_id, aggregate)

        except Exception as e:
            logger.error(f"Error proposing draft: {e}", exc_info=True)
            await say(text=f":x: Failed to propose work item: {e}", thread_ts=thread_ts)

    @app.action(MODIFY_ACTION_PATTERN)
    async def handle_modify_action(ack, body: dict, action: dict, client, say) -> None:
        """Handle Apply Changes / Cancel buttons from MODIFY mode preview.

        Apply reads entity_id + modifications from button value JSON,
        loads the aggregate, and applies changes via amend_decision or
        WorkItemUpdated depending on entity type.
        """
        await ack()

        action_id = action.get("action_id", "")
        channel_id = body.get("channel", {}).get("id")
        message_ts = body.get("message", {}).get("ts")
        user_id = body.get("user", {}).get("id")
        thread_ts = body.get("message", {}).get("thread_ts")
        blocks = body.get("message", {}).get("blocks", [])

        if action_id == "cancel_modify":
            updated_blocks = [b for b in blocks if b.get("type") != "actions"]
            updated_blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "_Modification cancelled_"}],
            })
            try:
                await client.chat_update(
                    channel=channel_id, ts=message_ts,
                    blocks=updated_blocks, text="Modification cancelled",
                )
            except Exception as e:
                logger.warning(f"Failed to update cancelled modify message: {e}")
            return

        # apply_modify
        try:
            value_data = json.loads(action.get("value", "{}"))
            entity_id_str = value_data.get("entity_id")
            modifications = value_data.get("modifications", [])
        except (json.JSONDecodeError, TypeError):
            await say(text=":x: Could not read modification data.", thread_ts=thread_ts)
            return

        if not entity_id_str or not modifications:
            await say(text=":x: Missing modification data.", thread_ts=thread_ts)
            return

        try:
            aggregate = await load_aggregate(channel_id)
            entity = aggregate.get_entity(EntityId(entity_id_str))

            if entity is None:
                await say(text=f":x: Entity `{entity_id_str[:8]}` not found.", thread_ts=thread_ts)
                return

            if not isinstance(entity, (DraftEntity, ProposedEntity)):
                state_name = type(entity).__name__.replace("Entity", "")
                await say(
                    text=f":x: Cannot modify entity in *{state_name}* state.",
                    thread_ts=thread_ts,
                )
                return

            title = getattr(entity.content, "title", entity_id_str[:8])
            is_decision = entity.entity_type.value == "decision"

            if is_decision:
                # Build new content by applying modifications to current content
                content_dict = entity.content.model_dump()
                for mod in modifications:
                    field = mod.get("field", "")
                    new_value = mod.get("new_value", "")
                    if field == "acceptance_criteria" or field == "constraints":
                        content_dict[field] = [v.strip() for v in new_value.split(",") if v.strip()]
                    elif field == "alternatives_considered":
                        content_dict[field] = [v.strip() for v in new_value.split(",") if v.strip()]
                    elif field in content_dict:
                        content_dict[field] = new_value

                new_content = DecisionContent(**content_dict)
                aggregate.amend_decision(
                    entity_id=EntityId(entity_id_str),
                    actor_id=UserId(user_id),
                    new_content=new_content,
                    reason="Modified via Slack",
                )
            else:
                # Work item — use WorkItemUpdated
                changes = {}
                for mod in modifications:
                    field = mod.get("field", "")
                    new_value = mod.get("new_value", "")
                    if field == "acceptance_criteria" or field == "constraints":
                        changes[field] = [v.strip() for v in new_value.split(",") if v.strip()]
                    elif field:
                        changes[field] = new_value

                from src.domain.events import WorkItemUpdated
                aggregate._emit(
                    WorkItemUpdated(
                        aggregate_id=aggregate.channel_id,
                        actor_id=user_id,
                        version=aggregate.next_version,
                        entity_id=entity_id_str,
                        changes=changes,
                        reason="Modified via Slack",
                    )
                )

            await save_events(aggregate)

            logger.info(f"Applied modifications to '{title}' in {channel_id} by {user_id}")

            # Update preview message
            updated_blocks = [b for b in blocks if b.get("type") != "actions"]
            change_summary = ", ".join(m.get("field", "") for m in modifications)
            updated_blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f":white_check_mark: Changes applied to *{title}* ({change_summary}) by <@{user_id}>"}],
            })

            await client.chat_update(
                channel=channel_id, ts=message_ts,
                blocks=updated_blocks,
                text=f"Changes applied to {title}",
            )

            # Update pinned ADR message if decision
            if is_decision:
                updated_entity = aggregate.get_entity(EntityId(entity_id_str))
                if updated_entity:
                    await _update_adr_pinned_message(client, channel_id, updated_entity, aggregate)

            await _update_dashboard_after_decision(client, channel_id, aggregate)

        except Exception as e:
            logger.error(f"Error applying modifications: {e}", exc_info=True)
            await say(text=f":x: Failed to apply modifications: {e}", thread_ts=thread_ts)

    @app.action(WORK_ITEM_PREVIEW_PATTERN)
    async def handle_work_item_preview_action(ack, body: dict, action: dict, client, say) -> None:
        """Handle per-work-item Propose / Delete buttons on batch preview."""
        await ack()

        action_id = action.get("action_id", "")
        match = WORK_ITEM_PREVIEW_PATTERN.match(action_id)
        if not match:
            return

        action_type = match.group(1)
        item_index = int(match.group(2))

        channel_id = body.get("channel", {}).get("id")
        message_ts = body.get("message", {}).get("ts")
        user_id = body.get("user", {}).get("id")
        thread_ts = body.get("message", {}).get("thread_ts")
        blocks = body.get("message", {}).get("blocks", [])

        if action_type == "delete":
            # Replace the item's section+actions+divider with removal notice
            target_text = f"*{item_index + 1}. "
            for i, block in enumerate(blocks):
                if block.get("type") == "section":
                    text = block.get("text", {}).get("text", "")
                    if text.startswith(target_text):
                        removal = {
                            "type": "context",
                            "elements": [{"type": "mrkdwn", "text": f":wastebasket: Item #{item_index + 1} removed by <@{user_id}>"}],
                        }
                        blocks = _replace_adr_blocks(blocks, i, removal)
                        break

            try:
                await client.chat_update(
                    channel=channel_id, ts=message_ts,
                    blocks=blocks, text="Work item removed",
                )
            except Exception as e:
                logger.warning(f"Failed to update after work item delete: {e}")
            return

        # action_type == "propose" — propose single work item
        try:
            content_data = json.loads(action.get("value", "{}"))
        except (json.JSONDecodeError, TypeError):
            await say(text=":x: Could not read work item data.", thread_ts=thread_ts)
            return

        await _propose_single_work_item(
            client, say, channel_id, message_ts, thread_ts,
            user_id, blocks, item_index, content_data,
        )

    @app.action(WORK_ITEM_BATCH_PATTERN)
    async def handle_work_item_batch_action(ack, body: dict, action: dict, client, say) -> None:
        """Handle Propose All / Cancel All buttons on batch work item previews."""
        await ack()

        action_id = action.get("action_id", "")
        channel_id = body.get("channel", {}).get("id")
        message_ts = body.get("message", {}).get("ts")
        user_id = body.get("user", {}).get("id")
        thread_ts = body.get("message", {}).get("thread_ts")
        blocks = body.get("message", {}).get("blocks", [])

        if "cancel_all" in action_id:
            updated_blocks = [b for b in blocks if b.get("type") != "actions"]
            updated_blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "_Cancelled_"}],
            })
            try:
                await client.chat_update(
                    channel=channel_id, ts=message_ts,
                    blocks=updated_blocks, text="Work items cancelled",
                )
            except Exception as e:
                logger.warning(f"Failed to update cancelled work items message: {e}")
            return

        # propose_all — extract work item data from individual per-item
        # propose buttons in the message blocks (avoids Slack 2000 char value limit)
        work_items = []
        for block in blocks:
            if block.get("type") != "actions":
                continue
            for elem in block.get("elements", []):
                aid = elem.get("action_id", "")
                if aid.startswith("wi_propose_"):
                    try:
                        item_data = json.loads(elem.get("value", "{}"))
                        if item_data.get("title"):
                            work_items.append(item_data)
                    except (json.JSONDecodeError, TypeError):
                        continue

        if not work_items:
            await say(text=":x: No work items to propose.", thread_ts=thread_ts)
            return

        await _propose_all_work_items(
            client, say, channel_id, message_ts, thread_ts,
            user_id, blocks, work_items,
        )

    @app.action("dashboard_show_all")
    async def handle_dashboard_show_all(ack, body: dict, action: dict, client, say) -> None:
        """Handle 'Show all items' button on the channel dashboard.

        Posts the full (untruncated) list of entities as a thread reply
        on the dashboard message.
        """
        await ack()

        channel_id = body.get("channel", {}).get("id") or action.get("value", "")
        message_ts = body.get("message", {}).get("ts")

        if not channel_id:
            return

        try:
            aggregate = await load_aggregate(channel_id)

            sections: list[str] = []

            # Decisions
            decisions = [
                e for e in aggregate.entities.values()
                if e.entity_type.value == "decision"
            ]
            if decisions:
                active = [e for e in decisions if get_lifecycle(e).value != "deprecated"]
                deprecated = [e for e in decisions if get_lifecycle(e).value == "deprecated"]

                if active:
                    lines = ["*Active Decisions*"]
                    for e in active:
                        title = getattr(e.content, "title", str(e.id)[:8])
                        status = get_lifecycle(e).value
                        adr_ts = getattr(e, 'adr_message_ts', None)
                        if status == "proposed":
                            display = f":hourglass: {title}"
                        elif status in ("approved", "committed"):
                            display = f":white_check_mark: {title}"
                        else:
                            display = f":pencil2: {title}"
                        if adr_ts:
                            link = _build_slack_permalink(channel_id, adr_ts)
                            lines.append(f"  \u2022 <{link}|{display}> ({status})")
                        else:
                            lines.append(f"  \u2022 {display} ({status})")
                    sections.append("\n".join(lines))

                if deprecated:
                    lines = ["*Deprecated Decisions*"]
                    for e in deprecated:
                        title = getattr(e.content, "title", str(e.id)[:8])
                        lines.append(f"  \u2022 ~{title}~")
                    sections.append("\n".join(lines))

            # Work items
            from src.config import get_settings
            settings = get_settings()
            jira_url = settings.jira_url if settings.jira_url else None

            work_items = [
                e for e in aggregate.entities.values()
                if e.entity_type.value == "work_item"
            ]
            if work_items:
                pending = [e for e in work_items if get_lifecycle(e).value in ("draft", "proposed")]
                committed = [e for e in work_items if get_lifecycle(e).value == "committed"]
                approved = [e for e in work_items if get_lifecycle(e).value == "approved"]

                if pending:
                    lines = ["*Pending Approval*"]
                    for e in pending:
                        title = getattr(e.content, "title", str(e.id)[:8])
                        lines.append(f"  \u2022 {title}")
                    sections.append("\n".join(lines))

                if approved:
                    lines = ["*Ready for Jira*"]
                    for e in approved:
                        title = getattr(e.content, "title", str(e.id)[:8])
                        lines.append(f"  \u2022 :white_check_mark: {title}")
                    sections.append("\n".join(lines))

                if committed:
                    lines = ["*In Jira*"]
                    for e in committed:
                        title = getattr(e.content, "title", str(e.id)[:8])
                        if hasattr(e, "jira_link") and e.jira_link:
                            jira_key = e.jira_link.jira_key
                            if jira_url:
                                lines.append(f"  \u2022 <{jira_url}/browse/{jira_key}|{jira_key}> {title}")
                            else:
                                lines.append(f"  \u2022 [{jira_key}] {title}")
                        else:
                            lines.append(f"  \u2022 {title}")
                    sections.append("\n".join(lines))

            if not sections:
                full_text = "_No items in this channel._"
            else:
                full_text = "\n\n".join(sections)

            # Post as thread reply on dashboard message
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=message_ts,
                text=full_text,
                blocks=[{
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": full_text[:3000]},
                }],
            )

        except Exception as e:
            logger.error(f"Error handling dashboard show all: {e}", exc_info=True)

    # Jira commit flow handlers
    app.action("commit_to_jira")(handle_commit_to_jira)
    app.action(JIRA_DUPLICATE_PATTERN)(handle_select_duplicate)
    app.action("create_anyway")(handle_create_anyway)

    # Catch-all for any unhandled actions (MUST be registered last)
    @app.action(re.compile(".*"))
    async def handle_unknown_action(ack, action: dict, logger) -> None:
        """Handle any unmatched action (fallback)."""
        await ack()
        logger.warning(f"Unhandled action: {action.get('action_id')}")

    logger.info("Action handlers registered")
