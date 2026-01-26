"""Review completion handlers for artifacts and work items.

Handles review artifact approval, work item creation, and decision capture.

INVARIANT I2: Slack = UI
Handlers are READ-ONLY for truth stores.
Mutations follow truth-first ordering:
  1. Database state update (TRUTH) - must succeed first
  2. Jira sync (PROJECTION) - proceeds regardless of Slack
  3. Slack message (PRESENTATION) - best effort, failures logged not raised
Message failures NEVER block state updates.
"""

import json
import logging

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


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
    from src.db.anchor_store import AnchorStore
    from src.schemas.anchor import AnchorType
    from src.slack.blocks.decision_cards import build_approved_card
    from src.slack.handlers.review.decision_core import (
        extract_decisions_from_text,
        create_and_post_decisions,
    )

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
            text="Capturing as decision...",
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
            anchor_store = AnchorStore(conn)

            # Load artifact
            artifact = await artifact_store.get(artifact_id)
            if not artifact:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=":warning: Could not find the review artifact.",
                )
                return

            # Check if thread is anchored to an existing decision
            # If so, this should UPDATE that decision, not create a new one
            existing_anchor = await anchor_store.get_by_message(channel_id, thread_ts)

            if existing_anchor and existing_anchor.anchor_type == AnchorType.DECISION:
                # Thread is anchored to an existing decision - UPDATE it
                existing_decision = await decision_store.get(str(existing_anchor.object_id))
                if existing_decision:
                    logger.info(
                        f"Thread anchored to decision {existing_decision.id}, creating new version",
                        extra={"existing_version": existing_decision.version}
                    )

                    # Use artifact summary as the new description
                    new_description = artifact.summary or topic or "Updated based on review discussion"

                    # Update existing decision (creates new version automatically)
                    updated_decision = await decision_store.update(
                        decision_id=str(existing_decision.id),
                        description=new_description,
                        changed_by=user_id,
                        change_reason="Updated based on review in thread",
                    )

                    # Update the original decision card in channel
                    if existing_anchor.message_ts:
                        decision_blocks = build_approved_card(updated_decision)
                        try:
                            client.chat_update(
                                channel=channel_id,
                                ts=existing_anchor.message_ts,
                                blocks=decision_blocks,
                                text=f"Decision {updated_decision.title} - v{updated_decision.version}",
                            )
                        except Exception as e:
                            logger.warning(f"Could not update decision card: {e}")
                            # Post new card if update fails
                            client.chat_postMessage(
                                channel=channel_id,
                                blocks=decision_blocks,
                                text=f"Decision updated: {updated_decision.title}",
                            )

                    # Update original button message
                    try:
                        client.chat_update(
                            channel=channel_id,
                            ts=message_ts,
                            text=f"Decision updated to v{updated_decision.version}",
                            blocks=[{
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": f"Decision updated to v{updated_decision.version}"}
                            }],
                        )
                    except Exception as e:
                        logger.warning(f"Could not update button message: {e}")

                    # Confirm in thread
                    client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        text=f":white_check_mark: Updated DEC-{existing_decision.id[:8]} to v{updated_decision.version}.",
                    )

                    logger.info(
                        "Updated existing decision with new version",
                        extra={
                            "decision_id": str(existing_decision.id),
                            "new_version": updated_decision.version,
                            "user_id": user_id,
                        }
                    )
                    return

        # No existing decision anchor - create new decision(s)
        # Use shared LLM extraction
        review_text = artifact.summary or artifact.content or ""

        # Extract decisions using shared logic
        decisions = await extract_decisions_from_text(review_text)

        # Map to expected format (topic/decision instead of title/description)
        if decisions:
            decisions = [{"topic": d.get("topic", d.get("title", "")), "decision": d.get("decision", d.get("description", ""))} for d in decisions]

        # Create and post using shared logic
        result = await create_and_post_decisions(
            client=client,
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
            decisions=decisions,
            persona=persona,
            check_conflicts=False,  # capture_as_decision doesn't check conflicts
            fallback_topic=topic or "Architecture Decision",
            fallback_text=review_text,
        )

        # Update original message to show completion
        if result.decisions_created > 0:
            completion_text = (
                "Captured as decision" if result.decisions_created == 1
                else f"Captured {result.decisions_created} decisions"
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
            text=f":white_check_mark: {result.decisions_created} decision(s) captured and posted to channel.",
        )

        logger.info(
            "Captured decisions from artifact",
            extra={
                "artifact_id": artifact_id,
                "decision_count": result.decisions_created,
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
