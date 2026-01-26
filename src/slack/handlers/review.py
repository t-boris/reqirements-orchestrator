"""Review-to-ticket, scope gate, and architecture approval handlers.

INVARIANT I2: Slack = UI
Handlers are READ-ONLY for truth stores.
Mutations follow truth-first ordering:
  1. Database state update (TRUTH) - must succeed first
  2. Jira sync (PROJECTION) - proceeds regardless of Slack
  3. Slack message (PRESENTATION) - best effort, failures logged not raised
Message failures NEVER block state updates.

Handles turning review responses into Jira tickets and posting architecture decisions.
"""

import json
import logging

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async
from src.slack.session import SessionIdentity
from src.graph.runner import get_runner

logger = logging.getLogger(__name__)


def handle_review_to_ticket(ack, body, client: WebClient):
    """Handle "Turn into Jira ticket" button click from review response.

    Opens scope gate modal to let user choose what content becomes the ticket.
    Pattern: Sync wrapper with immediate ack.
    """
    ack()

    # Extract context from button value
    button_value = body["actions"][0].get("value", "{}")
    try:
        value = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse review_to_ticket button value: {button_value}")
        value = {}

    message = body.get("message", {})
    thread_ts = message.get("thread_ts") or message.get("ts")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]

    logger.info(
        "Review to ticket button clicked",
        extra={
            "channel": channel_id,
            "thread_ts": thread_ts,
            "user_id": user_id,
        }
    )

    # Show scope gate modal
    try:
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "review_scope_gate",
                "private_metadata": json.dumps({
                    "thread_ts": thread_ts,
                    "channel_id": channel_id,
                    "review_text": value.get("review_text", ""),
                    "topic": value.get("topic", ""),
                }),
                "title": {"type": "plain_text", "text": "Create Ticket"},
                "submit": {"type": "plain_text", "text": "Create Draft"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": "*What should become a ticket?*"}
                    },
                    {
                        "type": "input",
                        "block_id": "scope_select",
                        "element": {
                            "type": "radio_buttons",
                            "action_id": "scope_choice",
                            "options": [
                                {"text": {"type": "plain_text", "text": "Final decision only"}, "value": "decision"},
                                {"text": {"type": "plain_text", "text": "Full review/proposal"}, "value": "full"},
                                {"text": {"type": "plain_text", "text": "Specific part (I'll describe)"}, "value": "custom"},
                            ],
                            "initial_option": {"text": {"type": "plain_text", "text": "Full review/proposal"}, "value": "full"},
                        },
                        "label": {"type": "plain_text", "text": "Scope"},
                    },
                    {
                        "type": "input",
                        "block_id": "custom_scope",
                        "optional": True,
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "custom_input",
                            "placeholder": {"type": "plain_text", "text": "Describe what to include..."},
                        },
                        "label": {"type": "plain_text", "text": "Custom scope (if selected above)"},
                    }
                ]
            }
        )
    except Exception as e:
        logger.error(f"Failed to open scope gate modal: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Sorry, I couldn't open the scope selection. Please try again.",
        )


def handle_scope_gate_submit(ack, body, client: WebClient, view):
    """Handle scope gate modal submission.

    Creates a context message that triggers ticket flow with review content.
    Pattern: Sync wrapper delegates to async.
    """
    ack()
    _run_async(_handle_scope_gate_submit_async(body, client, view))


async def _handle_scope_gate_submit_async(body, client: WebClient, view):
    """Async handler for scope gate modal submission.

    Extracts items from review and routes to single or multi-ticket flow.
    """
    from src.slack.handlers.dispatch import _dispatch_result
    from src.schemas.state import UserIntent, WorkflowStep, PendingAction
    from src.graph.nodes.extraction import extract_multi_items_from_review
    from src.slack.blocks.multi_ticket import build_multi_ticket_preview_blocks

    values = view["state"]["values"]
    private_metadata_raw = view.get("private_metadata", "{}")

    # Parse private metadata
    try:
        metadata = json.loads(private_metadata_raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse scope gate private_metadata: {private_metadata_raw}")
        return

    scope = values["scope_select"]["scope_choice"]["selected_option"]["value"]
    custom_text = values.get("custom_scope", {}).get("custom_input", {}).get("value", "")

    channel_id = metadata.get("channel_id", "")
    thread_ts = metadata.get("thread_ts", "")
    review_text = metadata.get("review_text", "")
    topic = metadata.get("topic", "")

    # Get team_id from body
    team_id = body.get("team", {}).get("id") or body.get("user", {}).get("team_id", "")
    user_id = body.get("user", {}).get("id", "")

    logger.info(
        "Scope gate submitted",
        extra={
            "channel": channel_id,
            "thread_ts": thread_ts,
            "scope": scope,
        }
    )

    # Build context message for ticket extraction
    if scope == "decision":
        context_msg = f"Create a Jira ticket for the final decision from this review: {topic}"
    elif scope == "full":
        # Include review text for full context
        context_msg = f"Create a Jira ticket based on this review:\n\n{review_text[:1500]}"
    else:
        context_msg = f"Create a Jira ticket for: {custom_text}"

    # Post acknowledgment message
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text="Analyzing review for ticket creation...",
    )

    # Extract items from review
    items = await extract_multi_items_from_review(review_text, scope, topic)

    if len(items) == 0:
        logger.warning(
            "No items extracted from review",
            extra={
                "channel": channel_id,
                "thread_ts": thread_ts,
                "topic": topic,
            }
        )
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="I couldn't identify any specific items to create. Please describe what you'd like to turn into tickets.",
        )
        return

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )

    if len(items) == 1:
        # Single-item flow - existing behavior
        runner = get_runner(identity)

        # Force TICKET intent and set the context message as user input
        forced_intent_result = {
            "intent": UserIntent.TICKET.value,
            "confidence": 1.0,
            "reasons": ["review_scope_gate: single item extracted from review"],
        }

        # Get current state and update with forced intent
        state = await runner._get_current_state()
        state["intent_result"] = forced_intent_result
        state["user_message"] = context_msg
        state["pending_action"] = None
        state["workflow_step"] = None

        await runner.graph.aupdate_state(runner._config, state)

        # Run graph with the context message
        try:
            result = await runner.run_with_message(context_msg, user_id)
            await _dispatch_result(result, identity, client, runner, tracker=None)
        except Exception as e:
            logger.error(f"Failed to create ticket from review: {e}", exc_info=True)
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Sorry, I couldn't create the ticket. Please try again or create it manually.",
            )
    else:
        # Multi-item flow - show preview
        await _show_multi_ticket_preview(items, identity, client, metadata)


async def _show_multi_ticket_preview(
    items: list[dict],
    identity: SessionIdentity,
    client: WebClient,
    metadata: dict,
):
    """Show multi-ticket preview and update state.

    Args:
        items: List of extracted items (id, type, title, description, parent_id)
        identity: Session identity for state management
        client: Slack WebClient
        metadata: Original scope gate metadata (channel_id, thread_ts, topic)
    """
    from src.schemas.state import WorkflowStep, PendingAction
    from src.slack.blocks.multi_ticket import build_multi_ticket_preview_blocks

    channel_id = metadata.get("channel_id", "")
    thread_ts = metadata.get("thread_ts", "")
    topic = metadata.get("topic", "")

    runner = get_runner(identity)
    state = await runner._get_current_state()

    # Calculate total content size
    total_chars = sum(len(i.get("description", "")) + len(i.get("title", "")) for i in items)

    # Find epic ID if present
    epic_id = None
    for item in items:
        if item["type"] == "epic":
            epic_id = item["id"]
            break

    # Build MultiTicketState
    multi_ticket_state = {
        "items": items,
        "epic_id": epic_id,
        "total_chars": total_chars,
        "confirmed_quantity": False,
        "confirmed_size": False,
        "created_keys": [],
    }

    # Get current ui_version and increment
    ui_version = state.get("ui_version", 0) + 1

    # Update state
    await runner._update_state({
        "multi_ticket_state": multi_ticket_state,
        "workflow_step": WorkflowStep.MULTI_TICKET_PREVIEW,
        "pending_action": PendingAction.WAITING_STORY_EDIT,
        "ui_version": ui_version,
    })

    # Build and post preview blocks
    preview_blocks = build_multi_ticket_preview_blocks(items, ui_version, thread_ts=thread_ts)

    epic_count = sum(1 for i in items if i["type"] == "epic")
    story_count = sum(1 for i in items if i["type"] == "story")

    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=preview_blocks,
        text=f"Multi-ticket preview: {epic_count} epic(s), {story_count} story(ies)",
    )

    logger.info(
        "Posted multi-ticket preview",
        extra={
            "channel": channel_id,
            "thread_ts": thread_ts,
            "item_count": len(items),
            "epic_count": epic_count,
            "story_count": story_count,
            "topic": topic,
        }
    )


def handle_approve_architecture(ack, body, client: WebClient):
    """Handle "Approve & Post Decision" button click.

    Posts architecture decision to the main channel (not thread).
    Pattern: Sync wrapper with immediate ack, delegates to async.
    """
    ack()
    _run_async(_handle_approve_architecture_async(body, client))


async def _handle_approve_architecture_async(body, client: WebClient):
    """Async handler for architecture approval."""
    from src.slack.blocks.decision_cards import build_approved_card
    from src.db import get_connection
    from src.db.decision_store import DecisionStore
    from src.schemas.decision import Decision, DecisionStatus, DecisionType
    from datetime import datetime, timezone
    import uuid

    # Extract context from button value
    button_value = body["actions"][0].get("value", "{}")
    try:
        value = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse approve_architecture button value: {button_value}")
        value = {}

    message = body.get("message", {})
    thread_ts = message.get("thread_ts") or message.get("ts")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    team_id = body.get("team", {}).get("id", "")

    topic = value.get("topic", "Architecture Decision")
    persona = value.get("persona", "")

    # Show progress indicator immediately
    progress_msg = client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=":hourglass_flowing_sand: Posting decisions to channel...",
    )

    logger.info(
        "Approve architecture button clicked",
        extra={
            "channel": channel_id,
            "thread_ts": thread_ts,
            "user_id": user_id,
            "topic": topic,
        }
    )

    # Get review context from state
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )
    runner = get_runner(identity)
    state = await runner._get_current_state()
    review_context = state.get("review_context")

    if not review_context:
        # No review context - use message text as fallback
        message_text = message.get("text", "")
        review_summary = message_text[:1000] if message_text else "Architecture approved"
    else:
        review_summary = (
            review_context.get("updated_recommendation") or
            review_context.get("review_summary", "Architecture approved")
        )

    # Extract ALL decisions using LLM
    from src.llm import get_llm
    from src.slack.decision_linker import DecisionLinker
    import re

    try:
        llm = get_llm()
        extraction_prompt = f'''Based on this architecture review, extract ALL distinct decisions made.

Review: {review_summary[:3000]}

Return a JSON object with array of decisions:
{{
    "decisions": [
        {{"topic": "What was decided (1 line)", "decision": "The chosen approach (1-2 sentences)"}},
        {{"topic": "Another decision topic", "decision": "Another chosen approach"}}
    ]
}}

Rules:
- Extract EACH distinct decision as a separate item
- A decision is a concrete choice about technology, architecture, or approach
- If only one decision was made, return array with one item
- Be concise - this will be posted to the channel as permanent record
'''
        extraction_result = await llm.chat(extraction_prompt)

        # Parse JSON response - look for decisions array
        json_match = re.search(r'\{[^{}]*"decisions"\s*:\s*\[.*?\][^{}]*\}', extraction_result, re.DOTALL)
        if json_match:
            decision_data = json.loads(json_match.group())
            decisions = decision_data.get("decisions", [])
        else:
            # Fallback: try single decision format
            single_match = re.search(r'\{[^{}]*"topic"[^{}]*\}', extraction_result, re.DOTALL)
            if single_match:
                decisions = [json.loads(single_match.group())]
            else:
                decisions = [{"topic": topic, "decision": "Approved"}]

        if not decisions:
            decisions = [{"topic": topic, "decision": "Approved"}]

        logger.info(
            f"Extracted {len(decisions)} decision(s) from review",
            extra={"channel_id": channel_id, "decision_count": len(decisions)},
        )

        # Check for conflicts and post each decision
        conflict_linker = DecisionLinker()
        all_conflicts = []

        for i, dec in enumerate(decisions):
            extracted_topic = dec.get("topic", topic)
            decision_text = dec.get("decision", "Approved")

            # Check for conflicting decisions
            conflicts = await conflict_linker.find_conflicting_decisions(
                channel_id=channel_id,
                new_topic=extracted_topic,
                new_decision=decision_text,
            )
            if conflicts:
                all_conflicts.extend([(extracted_topic, c) for c in conflicts])

            # Create Decision record in database
            async with get_connection() as conn:
                decision_store = DecisionStore(conn)
                now = datetime.now(timezone.utc)

                decision_record = Decision(
                    id=str(uuid.uuid4()),
                    channel_id=channel_id,
                    title=extracted_topic,
                    description=decision_text,
                    decision_type=DecisionType.ARCH,
                    status=DecisionStatus.APPROVED,
                    version=1,
                    created_at=now,
                    created_by=user_id,
                    context=f"From {persona} review" if persona else None,
                    rationale=[],
                    alternatives=[],
                    consequences=[],
                )

                await decision_store.create(decision_record)

            # Build and post rich decision card to CHANNEL
            decision_blocks = build_approved_card(decision_record)

            client.chat_postMessage(
                channel=channel_id,
                blocks=decision_blocks,
                text=f"Architecture Decision: {extracted_topic}",
            )

        # Warn about all conflicts in thread (after posting decisions)
        if all_conflicts:
            conflict_lines = [f":warning: *Potential conflicts detected ({len(all_conflicts)}):*\n"]
            for new_topic, c in all_conflicts[:5]:  # Show max 5
                conflict_lines.append(
                    f"• *{new_topic}* may conflict with *{c['topic']}*\n  _{c.get('conflict_reason', 'Check for contradiction')}_"
                )
            if len(all_conflicts) > 5:
                conflict_lines.append(f"  _...and {len(all_conflicts) - 5} more_")
            conflict_msg = "\n".join(conflict_lines)
            conflict_msg += "\n\n_Decisions recorded. Consider reviewing for contradictions._"

            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=conflict_msg,
            )
            logger.warning(
                "Conflicting decisions detected",
                extra={
                    "channel_id": channel_id,
                    "conflict_count": len(all_conflicts),
                },
            )

        # Confirm in thread
        decision_count = len(decisions)
        if decision_count == 1:
            confirm_msg = "Decision recorded in channel."
        else:
            confirm_msg = f"{decision_count} decisions recorded in channel."
        if all_conflicts:
            confirm_msg += " ⚠️ Check conflict warning above."
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=confirm_msg,
        )

        # Freeze review_context to review_artifact (Phase 20)
        # Use first decision as primary topic for artifact
        primary_topic = decisions[0].get("topic", topic) if decisions else topic
        if review_context:
            import hashlib
            from datetime import datetime, timezone
            from src.schemas.state import ReviewState

            review_context["state"] = ReviewState.POSTED

            review_artifact = {
                "kind": "architecture" if "architect" in persona.lower() else "security" if "security" in persona.lower() else "pm_review",
                "version": review_context.get("version", 1),
                "summary": review_context.get("review_summary", ""),
                "updated_summary": review_context.get("updated_recommendation"),
                "topic": primary_topic,
                "decisions": decisions,  # Store all decisions
                "persona": persona,
                "frozen_at": datetime.now(timezone.utc).isoformat(),
                "thread_ts": thread_ts,
                "channel_id": channel_id,
                "content_hash": hashlib.sha256(
                    (review_context.get("review_summary", "") +
                     (review_context.get("updated_recommendation") or "")).encode()
                ).hexdigest()[:16],
            }

            # Update state
            await runner._update_state({
                "review_artifact": review_artifact,
                "review_context": None,
            })

            logger.info(
                "Froze review_context to review_artifact via button",
                extra={
                    "topic": primary_topic,
                    "decision_count": decision_count,
                    "content_hash": review_artifact["content_hash"],
                }
            )

        # Record ALL decisions for sync tracking (Phase 21-04)
        from src.slack.thread_bindings import get_binding_store

        linker = DecisionLinker()

        # Check for thread binding
        binding_store = get_binding_store()
        binding = await binding_store.get_binding(channel_id, thread_ts)
        thread_binding = binding.issue_key if binding else None

        # Record each decision
        for i, dec in enumerate(decisions):
            dec_topic = dec.get("topic", topic)
            dec_text = dec.get("decision", "Approved")

            # Find related issues
            related_issues = await linker.find_related_issues(
                decision_topic=dec_topic,
                decision_text=dec_text,
                channel_id=channel_id,
                thread_binding=thread_binding,
            )

            # Record decision with unique timestamp suffix for multiple decisions
            decision_ts = f"{thread_ts}_{i}" if i > 0 else thread_ts
            await linker.record_decision_sync(
                channel_id=channel_id,
                decision_ts=decision_ts,
                topic=dec_topic,
                decision_text=dec_text,
                related_issues=related_issues,
                synced_to_jira=False,
            )

        await linker.close()

        logger.info(
            "Decisions recorded for sync tracking",
            extra={
                "decision_count": decision_count,
                "primary_topic": primary_topic,
            }
        )

        # Delete progress message after completion
        try:
            client.chat_delete(
                channel=channel_id,
                ts=progress_msg["ts"],
            )
        except Exception as del_err:
            logger.debug(f"Could not delete progress message: {del_err}")

    except Exception as e:
        logger.error(f"Failed to extract/post decision: {e}", exc_info=True)
        # Delete progress message on error
        try:
            client.chat_delete(
                channel=channel_id,
                ts=progress_msg["ts"],
            )
        except Exception:
            pass
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="I understood that as approval, but couldn't extract the decision. The review is still available above.",
        )


def handle_review_approve(ack, body, client: WebClient):
    """Handle "Approve & Save" button click for artifact approval.

    Marks the review artifact as approved in the database.
    Pattern: Sync wrapper with immediate ack, delegates to async.
    """
    ack()
    _run_async(_handle_review_approve_async(body, client))


async def _handle_review_approve_async(body, client: WebClient):
    """Async handler for artifact approval.

    Follows INVARIANT I2 truth-first ordering:
    1. Approve artifact in database (TRUTH)
    2. Send Slack confirmation (PRESENTATION - best effort)
    """
    from src.db import get_connection
    from src.db.artifact_store import ArtifactStore

    # Extract artifact_id from button value
    artifact_id = body["actions"][0].get("value", "")
    if not artifact_id:
        logger.warning("No artifact_id in review_approve button")
        return

    message = body.get("message", {})
    thread_ts = message.get("thread_ts") or message.get("ts")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]

    logger.info(
        "Review approve button clicked",
        extra={
            "channel": channel_id,
            "thread_ts": thread_ts,
            "user_id": user_id,
            "artifact_id": artifact_id,
        }
    )

    artifact = None
    try:
        # =====================================================================
        # STEP 1: Database state update (TRUTH) - must succeed first
        # =====================================================================
        async with get_connection() as conn:
            store = ArtifactStore(conn)
            artifact = await store.approve(artifact_id, user_id)

        if not artifact:
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=":warning: Could not find artifact to approve.",
                )
            except Exception as slack_err:
                logger.warning(
                    "Slack message failed",
                    extra={"error": str(slack_err)}
                )
            return

        logger.info(
            "Artifact approved",
            extra={
                "artifact_id": artifact_id,
                "approved_by": user_id,
            }
        )

    except Exception as e:
        logger.error(f"Failed to approve artifact: {e}", exc_info=True)
        try:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Sorry, I couldn't save the approval. Please try again.",
            )
        except Exception as slack_err:
            logger.warning(
                "Slack error message failed",
                extra={"error": str(slack_err)}
            )
        return

    # =========================================================================
    # STEP 2: Slack message (PRESENTATION) - best effort, doesn't block state
    # =========================================================================
    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":white_check_mark: Review approved and saved as artifact `{artifact_id[:8]}...`",
        )
    except Exception as slack_err:
        # Slack message failed, but artifact is already approved
        logger.warning(
            "Slack confirmation failed, but artifact is approved",
            extra={
                "artifact_id": artifact_id,
                "error": str(slack_err),
            }
        )


def handle_turn_into_workitem(ack, body, client: WebClient):
    """Handle "Turn into Work Item" button click.

    Creates a WorkItem from the artifact and links them.
    Pattern: Sync wrapper with immediate ack, delegates to async.
    """
    ack()
    _run_async(_handle_turn_into_workitem_async(body, client))


async def _handle_turn_into_workitem_async(body, client: WebClient):
    """Async handler for turning artifact into workitem.

    Follows INVARIANT I2 truth-first ordering:
    1. Create workitem and link in database (TRUTH)
    2. Send Slack confirmation (PRESENTATION - best effort)
    """
    import uuid
    from src.db import get_connection
    from src.db.artifact_store import ArtifactStore
    from src.db.workitem_store import WorkItemStore
    from src.db.models import (
        ArtifactLinkType,
        ArtifactTargetType,
        WorkItem,
        WorkItemType,
        WorkItemStatus,
    )
    from datetime import datetime, timezone

    # Extract artifact_id from button value
    artifact_id = body["actions"][0].get("value", "")
    if not artifact_id:
        logger.warning("No artifact_id in review_to_workitem button")
        return

    message = body.get("message", {})
    thread_ts = message.get("thread_ts") or message.get("ts")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]

    logger.info(
        "Turn into workitem button clicked",
        extra={
            "channel": channel_id,
            "thread_ts": thread_ts,
            "user_id": user_id,
            "artifact_id": artifact_id,
        }
    )

    workitem = None
    try:
        # =====================================================================
        # STEP 1: Database operations (TRUTH) - must succeed first
        # =====================================================================
        async with get_connection() as conn:
            artifact_store = ArtifactStore(conn)
            artifact = await artifact_store.get(artifact_id)

            if not artifact:
                try:
                    client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        text=":warning: Could not find artifact.",
                    )
                except Exception as slack_err:
                    logger.warning(
                        "Slack message failed",
                        extra={"error": str(slack_err)}
                    )
                return

            # Create WorkItem from artifact
            workitem_store = WorkItemStore(conn)
            now = datetime.now(timezone.utc)

            workitem = WorkItem(
                id=str(uuid.uuid4()),
                channel_id=channel_id,
                item_type=WorkItemType.TASK,  # Default to task for review-derived work
                status=WorkItemStatus.DRAFT,
                summary=artifact.summary or f"Review: {artifact.kind.value}",
                description=artifact.full_content[:2000] if artifact.full_content else None,
                facts={
                    "from_review": True,
                    "artifact_id": artifact_id,
                    "decisions": artifact.decisions[:3] if artifact.decisions else [],
                    "risks": artifact.risks[:3] if artifact.risks else [],
                },
                source_thread_ts=thread_ts,
                created_by=user_id,
                created_at=now,
                updated_at=now,
            )

            await workitem_store.create(workitem)

            # Link artifact to workitem
            await artifact_store.add_link(
                artifact_id=artifact_id,
                target_type=ArtifactTargetType.WORKITEM,
                target_id=workitem.id,
                link_type=ArtifactLinkType.RESULTED_IN,
            )

        logger.info(
            "Created workitem from artifact",
            extra={
                "artifact_id": artifact_id,
                "workitem_id": workitem.id,
                "created_by": user_id,
            }
        )

    except Exception as e:
        logger.error(f"Failed to create workitem from artifact: {e}", exc_info=True)
        try:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Sorry, I couldn't create the work item. Please try again.",
            )
        except Exception as slack_err:
            logger.warning(
                "Slack error message failed",
                extra={"error": str(slack_err)}
            )
        return

    # =========================================================================
    # STEP 2: Slack message (PRESENTATION) - best effort, doesn't block state
    # =========================================================================
    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":white_check_mark: Created work item from artifact. Draft ID: `{workitem.id[:8]}...`\n\nUse `/maro status` to see your drafts.",
        )
    except Exception as slack_err:
        # Slack message failed, but workitem is already created
        logger.warning(
            "Slack confirmation failed, but workitem is created",
            extra={
                "workitem_id": workitem.id if workitem else None,
                "error": str(slack_err),
            }
        )


def handle_capture_as_decision(ack, body, client: WebClient):
    """Handle "Capture as Decision" button click from THINK mode review.

    Extracts decisions from the review artifact and creates formal Decision records.
    Pattern: Sync wrapper with immediate ack, delegates to async.
    """
    ack()
    _run_async(_handle_capture_as_decision_async(body, client))


async def _handle_capture_as_decision_async(body, client: WebClient):
    """Async handler for capturing review as formal Decision.

    Follows INVARIANT I2 truth-first ordering:
    1. Create Decision in database (TRUTH)
    2. Post decision card to channel (PRESENTATION)
    """
    from src.db import get_connection
    from src.db.artifact_store import ArtifactStore
    from src.db.decision_store import DecisionStore
    from src.schemas.decision import Decision, DecisionStatus, DecisionType
    from src.slack.blocks.decision_cards import build_approved_card
    from datetime import datetime, timezone
    import uuid

    # Extract context from button value
    button_value = body["actions"][0].get("value", "{}")
    try:
        value = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse capture_as_decision button value: {button_value}")
        value = {}

    artifact_id = value.get("artifact_id")
    topic = value.get("topic", "")
    persona = value.get("persona", "")

    message = body.get("message", {})
    message_ts = message.get("ts")
    thread_ts = message.get("thread_ts") or message_ts
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]

    if not artifact_id:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="No artifact found to capture as decision.",
        )
        return

    logger.info(
        "Capture as decision button clicked",
        extra={
            "channel": channel_id,
            "thread_ts": thread_ts,
            "user_id": user_id,
            "artifact_id": artifact_id,
        }
    )

    # Disable button by updating original message
    try:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="✓ Capturing as decision...",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":hourglass_flowing_sand: Capturing as decision...",
                    },
                }
            ],
        )
    except Exception as e:
        logger.warning(f"Could not update button message: {e}")

    try:
        async with get_connection() as conn:
            artifact_store = ArtifactStore(conn)
            decision_store = DecisionStore(conn)

            # Load artifact
            artifact = await artifact_store.get(artifact_id)
            if not artifact:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=":warning: Could not find the review artifact.",
                )
                return

            # Extract decisions from artifact
            decisions_to_create = artifact.decisions or []
            if not decisions_to_create:
                # Fallback: use artifact summary as the decision
                decisions_to_create = [artifact.summary or topic or "Review conclusion"]

            now = datetime.now(timezone.utc)
            created_decisions = []

            for i, decision_text in enumerate(decisions_to_create):
                # Determine title from decision text
                if isinstance(decision_text, dict):
                    title = decision_text.get("topic", decision_text.get("title", f"Decision {i+1}"))
                    description = decision_text.get("decision", decision_text.get("description", str(decision_text)))
                else:
                    # String decision - use first line as title
                    lines = str(decision_text).strip().split("\n")
                    title = lines[0][:100] if lines else f"Decision {i+1}"
                    description = str(decision_text)

                # Create Decision record
                decision = Decision(
                    id=str(uuid.uuid4()),
                    channel_id=channel_id,
                    title=title,
                    description=description,
                    decision_type=DecisionType.ARCH,  # Default to architecture
                    status=DecisionStatus.APPROVED,  # Already approved since captured from review
                    version=1,
                    created_at=now,
                    updated_at=now,  # Required field
                    created_by=user_id,
                    # Rich context from artifact
                    context=f"From {persona} review" if persona else "From review analysis",
                    rationale=[],  # Can be enhanced later
                    alternatives=[],
                    consequences=[],
                )

                await decision_store.create(decision)
                created_decisions.append(decision)

                # Post rich decision card to channel with edit/deprecate buttons
                decision_blocks = build_approved_card(decision)

                client.chat_postMessage(
                    channel=channel_id,
                    blocks=decision_blocks,
                    text=f"Architecture Decision: {title}",
                )

            # Update original message to show completion
            if created_decisions:
                decision_count = len(created_decisions)
                completion_text = (
                    f"✓ Captured as decision" if decision_count == 1
                    else f"✓ Captured {decision_count} decisions"
                )
                try:
                    client.chat_update(
                        channel=channel_id,
                        ts=message_ts,
                        text=completion_text,
                        blocks=[
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": completion_text,
                                },
                            }
                        ],
                    )
                except Exception as e:
                    logger.warning(f"Could not update completion message: {e}")

            # Confirm in thread
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":white_check_mark: {len(created_decisions)} decision(s) captured and posted to channel.",
            )

            logger.info(
                "Captured decisions from artifact",
                extra={
                    "artifact_id": artifact_id,
                    "decision_count": len(created_decisions),
                    "user_id": user_id,
                }
            )

    except Exception as e:
        logger.error(f"Failed to capture as decision: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Sorry, I couldn't capture this as a decision: {str(e)}",
        )
