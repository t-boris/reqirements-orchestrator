"""Core decision extraction and creation logic.

Shared by approve_architecture and capture_as_decision handlers.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from slack_sdk.web import WebClient

from src.db import get_connection
from src.db.anchor_store import AnchorStore
from src.db.decision_store import DecisionStore
from src.schemas.anchor import AnchorType
from src.schemas.decision import DecisionType

logger = logging.getLogger(__name__)


@dataclass
class DecisionExtractionResult:
    """Result of decision extraction and creation."""
    decisions_created: int
    decision_ids: list[str]
    conflicts: list[tuple[str, dict]]  # (topic, conflict_info)


async def extract_decisions_from_text(review_text: str, max_length: int = 4000) -> list[dict]:
    """Extract structured decisions from review text using LLM.

    Returns list of dicts with 'topic' and 'decision' keys.
    """
    if not review_text:
        return []

    from src.llm import get_llm

    try:
        llm = get_llm()
        extraction_prompt = f'''Based on this architecture review, extract ALL ACTUAL DECISIONS made.

Review: {review_text[:max_length]}

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

        # Parse JSON response - robust extraction
        decisions = _parse_decisions_json(extraction_result)

        # Validate and clean decisions
        valid_decisions = []
        for dec in decisions:
            if isinstance(dec, dict) and dec.get("topic") and dec.get("decision"):
                # Ensure topic is SHORT (not raw text)
                dec_topic = dec.get("topic", "")
                if len(dec_topic) > 100:
                    dec["topic"] = dec_topic[:50] + "..."
                valid_decisions.append(dec)

        return valid_decisions

    except Exception as e:
        logger.warning(f"LLM decision extraction failed: {e}")
        return []


def _parse_decisions_json(text: str) -> list[dict]:
    """Parse decisions JSON from LLM response.

    Handles nested braces properly by finding first { and last }.
    """
    decisions = []

    # First try: extract everything between first { and last }
    try:
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = text[start_idx:end_idx + 1]
            decision_data = json.loads(json_str)
            decisions = decision_data.get("decisions", [])
            if decisions:
                return decisions
    except json.JSONDecodeError:
        pass

    # Second try: look for array directly
    try:
        array_match = re.search(r'\[[\s\S]*\]', text)
        if array_match:
            decisions = json.loads(array_match.group())
            return decisions
    except json.JSONDecodeError:
        pass

    return decisions


async def create_and_post_decisions(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    decisions: list[dict],
    persona: str = "",
    check_conflicts: bool = True,
    fallback_topic: str = "Architecture Decision",
    fallback_text: str = "",
) -> DecisionExtractionResult:
    """Create Decision records and post cards to channel.

    Args:
        client: Slack client
        channel_id: Channel to post to
        thread_ts: Thread timestamp
        user_id: User who approved
        decisions: List of dicts with 'topic' and 'decision' keys
        persona: Review persona (e.g., "Solutions Architect")
        check_conflicts: Whether to check for conflicting decisions
        fallback_topic: Topic to use if no decisions extracted
        fallback_text: Text to use if no decisions extracted

    Returns:
        DecisionExtractionResult with created decision info
    """
    from src.slack.blocks.decision_cards import build_approved_card
    from src.slack.decision_linker import DecisionLinker

    # Use fallback if no decisions
    if not decisions:
        decisions = [{"topic": fallback_topic, "decision": fallback_text[:500] if fallback_text else "Approved"}]

    all_conflicts = []
    created_decision_ids = []

    conflict_linker = DecisionLinker() if check_conflicts else None

    try:
        for i, dec in enumerate(decisions):
            # Topic should be short title
            extracted_topic = dec.get("topic", fallback_topic)
            if len(extracted_topic) > 150:
                extracted_topic = extracted_topic[:147] + "..."

            # Description can be detailed - only truncate at Slack limit
            decision_text = dec.get("decision", "Approved")
            if len(decision_text) > 2900:
                decision_text = decision_text[:2897] + "..."

            # Check for conflicting decisions
            if conflict_linker:
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

            created_decision_ids.append(str(decision_record.id))

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

        return DecisionExtractionResult(
            decisions_created=len(created_decision_ids),
            decision_ids=created_decision_ids,
            conflicts=all_conflicts,
        )

    finally:
        if conflict_linker:
            await conflict_linker.close()


async def record_decisions_for_sync(
    channel_id: str,
    thread_ts: str,
    decisions: list[dict],
    fallback_topic: str = "Architecture Decision",
) -> None:
    """Record decisions for Jira sync tracking.

    Args:
        channel_id: Channel ID
        thread_ts: Thread timestamp
        decisions: List of dicts with 'topic' and 'decision' keys
        fallback_topic: Fallback topic if decisions list is empty
    """
    from src.slack.decision_linker import DecisionLinker
    from src.slack.thread_bindings import get_binding_store

    linker = DecisionLinker()

    try:
        # Check for thread binding
        binding_store = get_binding_store()
        binding = await binding_store.get_binding(channel_id, thread_ts)
        thread_binding = binding.issue_key if binding else None

        # Record each decision
        for i, dec in enumerate(decisions):
            dec_topic = dec.get("topic", fallback_topic)
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

        logger.info(
            "Decisions recorded for sync tracking",
            extra={
                "decision_count": len(decisions),
                "channel_id": channel_id,
            }
        )
    finally:
        await linker.close()
