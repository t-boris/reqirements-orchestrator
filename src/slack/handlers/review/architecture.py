"""Architecture approval handler.

Handles posting architecture decisions to the main channel.
"""

import json
import logging
import re
from datetime import datetime, timezone
import hashlib

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async
from src.slack.session import SessionIdentity
from src.graph.runner import get_runner

logger = logging.getLogger(__name__)


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

    try:
        llm = get_llm()
        extraction_prompt = f'''Based on this architecture review, extract ALL ACTUAL DECISIONS made.

Review: {review_summary[:3000]}

Return a JSON object with array of decisions:
{{
    "decisions": [
        {{"topic": "Short title (5-10 words)", "decision": "DETAILED description of the chosen approach. Include reasoning and key points."}},
        {{"topic": "Another short title", "decision": "Another detailed description with rationale."}}
    ]
}}

CRITICAL RULES:
- ONLY extract DECISIONS (statements of what WAS chosen/decided)
- DO NOT extract questions ("How should we...?", "What if...?")
- DO NOT extract recommendations that are phrased as questions
- topic: SHORT title (5-10 words max) - becomes the card header, NOT a question
- decision: DETAILED description - preserve the full reasoning, don't summarize
- Extract EACH distinct decision as a separate item
- If only one decision was made, return array with one item

GOOD examples (decisions):
- topic: "Azure Functions for serverless" decision: "We will use Azure Functions instead of AWS Lambda..."
- topic: "PostgreSQL for data storage" decision: "The database choice is PostgreSQL with JSONB..."

BAD examples (NOT decisions, do not extract):
- "How should we handle retries?" -> This is a question, not a decision
- "What if we don't have AWS access?" -> This is a question, not a decision
- "I recommend using X" -> Only extract if it was APPROVED, not just recommended
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
            # Topic should be short title - truncate only if extremely long
            extracted_topic = dec.get("topic", topic)
            if len(extracted_topic) > 150:
                extracted_topic = extracted_topic[:147] + "..."

            # Description can be detailed - only truncate at Slack limit
            decision_text = dec.get("decision", "Approved")
            if len(decision_text) > 2900:
                decision_text = decision_text[:2897] + "..."

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

                decision_record = await decision_store.create(
                    channel_id=channel_id,
                    decision_type=DecisionType.ARCH,
                    title=extracted_topic,
                    description=decision_text,
                    created_by=user_id,
                    context_before=f"From {persona} review" if persona else None,
                    rationale=[],
                    alternatives=[],
                    consequences=[],
                )

                # Approve immediately since it's from an approved review
                decision_record = await decision_store.approve(
                    decision_id=str(decision_record.id),
                    approved_by=user_id,
                )

            # Build and post rich decision card to CHANNEL
            decision_blocks = build_approved_card(decision_record)

            response = client.chat_postMessage(
                channel=channel_id,
                blocks=decision_blocks,
                text=f"Architecture Decision: {extracted_topic}",
            )

            # Create anchor linking this message to the decision
            posted_ts = response.get("ts")
            if posted_ts:
                # Pin the decision card to the channel
                try:
                    client.pins_add(channel=channel_id, timestamp=posted_ts)
                    logger.debug(f"Pinned decision card at {posted_ts}")
                except Exception as e:
                    logger.warning(f"Could not pin decision card: {e}")

                # Create anchor for thread lookups
                try:
                    from src.db.anchor_store import AnchorStore
                    from src.schemas.anchor import AnchorType

                    async with get_connection() as conn:
                        anchor_store = AnchorStore(conn)
                        await anchor_store.create_anchor(
                            anchor_type=AnchorType.DECISION,
                            object_id=str(decision_record.id),
                            channel_id=channel_id,
                            message_ts=posted_ts,
                            created_by=user_id,
                        )
                        logger.debug(f"Created anchor for decision {decision_record.id} at {posted_ts}")
                except Exception as e:
                    logger.warning(f"Could not create anchor for decision: {e}")

        # Warn about all conflicts in thread (after posting decisions)
        if all_conflicts:
            conflict_lines = [f":warning: *Potential conflicts detected ({len(all_conflicts)}):*\n"]
            for new_topic, c in all_conflicts[:5]:  # Show max 5
                conflict_lines.append(
                    f"* *{new_topic}* may conflict with *{c['topic']}*\n  _{c.get('conflict_reason', 'Check for contradiction')}_"
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
            confirm_msg += " Check conflict warning above."
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=confirm_msg,
        )

        # Freeze review_context to review_artifact (Phase 20)
        # Use first decision as primary topic for artifact
        primary_topic = decisions[0].get("topic", topic) if decisions else topic
        if review_context:
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
