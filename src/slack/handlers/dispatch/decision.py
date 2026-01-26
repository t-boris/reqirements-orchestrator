"""Decision-related dispatch handlers.

Handles architecture decision approval, linking to Jira, and decision expansion.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Decision extraction prompt for architecture decisions (Phase 14)
DECISION_EXTRACTION_PROMPT = '''Based on this architecture review, extract the decision for a permanent record.

Review/Analysis:
{review_summary}

User's approval: {approval_message}

Return a JSON object:
{{
    "topic": "Short descriptive title (5-10 words, e.g., 'Course Content Delivery Architecture', 'Redis Caching Strategy')",
    "decision": "DETAILED description of the chosen approach. Include: what was decided, key components, rationale highlights. Multiple sentences encouraged. Be comprehensive."
}}

IMPORTANT:
- topic: SHORT title (5-10 words max) - this becomes the decision card header
- decision: DETAILED description - include the full reasoning, not just a summary
- Extract the actual recommendation content, don't summarize it away
'''


async def _handle_decision_approval(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
):
    """Handle architecture decision approval (Phase 14).

    Creates proper Decision record in DB and posts rich decision card.
    Same flow as button handler for consistency.
    """
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.db.anchor_store import AnchorStore
    from src.schemas.anchor import AnchorType
    from src.schemas.decision import DecisionType
    from src.slack.blocks.decision_cards import build_approved_card
    from src.llm import get_llm

    review_context = result.get("review_context")

    if not review_context:
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="No recent review to approve. I can only record a decision after giving you a review.",
        )
        return

    try:
        # Extract decision using LLM
        approval_message = result.get("approval_message", "approved")
        effective_summary = (
            review_context.get("updated_recommendation") or
            review_context.get("review_summary", "")
        )

        llm = get_llm()
        extraction_prompt = DECISION_EXTRACTION_PROMPT.format(
            review_summary=effective_summary,
            approval_message=approval_message,
        )
        extraction_result = await llm.chat(extraction_prompt)

        # Parse JSON response
        json_match = re.search(r'\{[^{}]*\}', extraction_result, re.DOTALL)
        if json_match:
            decision_data = json.loads(json_match.group())
        else:
            decision_data = json.loads(extraction_result)

        topic = decision_data.get("topic", review_context.get("topic", "Architecture decision"))
        decision_text = decision_data.get("decision", "Approved")

        # Only truncate title if extremely long (Slack limit protection)
        if len(topic) > 150:
            topic = topic[:147] + "..."
        # Description can be long - only truncate if exceeds Slack block limit
        if len(decision_text) > 2900:
            decision_text = decision_text[:2897] + "..."

        user_id = result.get("user_id", "unknown")
        channel_id = review_context.get("channel_id", identity.channel_id)
        persona = review_context.get("persona", "")

        logger.info(
            "Architecture decision detected",
            extra={"channel_id": channel_id, "topic": topic, "user_id": user_id}
        )

        # Create Decision record in database
        async with get_connection() as conn:
            decision_store = DecisionStore(conn)

            decision = await decision_store.create(
                channel_id=channel_id,
                decision_type=DecisionType.ARCH,
                title=topic,
                description=decision_text,
                created_by=user_id,
                context_before=f"From {persona} review" if persona else None,
                rationale=[],
                alternatives=[],
                consequences=[],
            )

            # Approve immediately
            decision = await decision_store.approve(
                decision_id=str(decision.id),
                approved_by=user_id,
            )

        # Build and post rich decision card to CHANNEL
        decision_blocks = build_approved_card(decision)

        response = client.chat_postMessage(
            channel=channel_id,
            blocks=decision_blocks,
            text=f"Architecture Decision: {topic}",
        )

        # Pin and create anchor
        posted_ts = response.get("ts")
        if posted_ts:
            try:
                client.pins_add(channel=channel_id, timestamp=posted_ts)
            except Exception as e:
                logger.warning(f"Could not pin decision card: {e}")

            try:
                async with get_connection() as conn:
                    anchor_store = AnchorStore(conn)
                    await anchor_store.create_anchor(
                        anchor_type=AnchorType.DECISION,
                        object_id=str(decision.id),
                        channel_id=channel_id,
                        message_ts=posted_ts,
                        created_by=user_id,
                    )
            except Exception as e:
                logger.warning(f"Could not create anchor: {e}")

        # Confirm in thread
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="Decision recorded and pinned to channel.",
        )

    except Exception as e:
        logger.error(f"Failed to extract/post decision: {e}", exc_info=True)
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="I understood that as approval, but couldn't extract the decision. The review is still available above.",
        )


async def _link_decision_to_jira(
    topic: str,
    decision_text: str,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    identity: SessionIdentity,
    client: WebClient,
):
    """Link approved decision to related Jira issues.

    Flow:
    1. Find related issues using DecisionLinker
    2. If single match with high confidence: auto-update
    3. If multiple matches or low confidence: ask user
    """
    from src.slack.decision_linker import DecisionLinker
    from src.slack.thread_bindings import get_binding_store

    try:
        linker = DecisionLinker()

        # Check for thread binding
        binding_store = get_binding_store()
        binding = await binding_store.get_binding(channel_id, thread_ts)
        thread_binding = binding.issue_key if binding else None

        # Find related issues
        related_issues = await linker.find_related_issues(
            decision_topic=topic,
            decision_text=decision_text,
            channel_id=channel_id,
            thread_binding=thread_binding,
        )

        if not related_issues:
            # No related issues found now, but record for later sync
            logger.debug("No related Jira issues found for decision - recording for sync")
            await linker.record_decision_sync(
                channel_id=channel_id,
                decision_ts=thread_ts,
                topic=topic,
                decision_text=decision_text,
                related_issues=[],
                synced_to_jira=False,  # Not synced yet - will appear in /maro sync
            )
            await linker.close()
            return

        # Build Slack thread link
        slack_link = f"https://slack.com/archives/{channel_id}/p{thread_ts.replace('.', '')}"

        # Format decision for Jira
        timestamp = datetime.now(timezone.utc).isoformat()
        formatted_decision = linker.format_decision_for_jira(
            topic=topic,
            decision=decision_text,
            approver=f"<@{user_id}>",
            timestamp=timestamp,
            slack_link=slack_link,
        )

        if len(related_issues) == 1:
            # High confidence single match - auto-update
            issue_key = related_issues[0]
            success = await linker.apply_decision_to_issue(
                issue_key,
                formatted_decision,
                mode="add_comment",
                add_label=True,
                channel_id=channel_id,
                decision_ts=thread_ts,
                topic=topic,
            )

            if success:
                client.chat_postMessage(
                    channel=identity.channel_id,
                    thread_ts=identity.thread_ts,
                    text=f"Decision added to *{issue_key}*.",
                )
        else:
            # Multiple matches - ask user
            await _prompt_decision_link(
                issues=related_issues,
                topic=topic,
                decision_text=decision_text,
                user_id=user_id,
                identity=identity,
                client=client,
            )

        await linker.close()

    except Exception as e:
        logger.warning(f"Failed to link decision to Jira: {e}", exc_info=True)
        # Non-blocking - decision was already posted to channel


async def _prompt_decision_link(
    issues: list[str],
    topic: str,
    decision_text: str,
    user_id: str,
    identity: SessionIdentity,
    client: WebClient,
):
    """Prompt user to select which Jira issue to link decision to.

    Shows up to 5 related issues with Link buttons.
    """
    from src.jira.client import JiraService
    from src.config.settings import get_settings

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "Link this decision to a Jira ticket?"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{topic}*\n{decision_text[:200]}..."}
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Related tickets:*"}
        },
    ]

    # Fetch issue summaries for context
    try:
        settings = get_settings()
        jira = JiraService(settings)

        for key in issues[:5]:  # Max 5 options
            try:
                issue = await jira.get_issue(key)
                summary = issue.summary[:60] + "..." if len(issue.summary) > 60 else issue.summary
            except Exception:
                summary = "(Could not fetch summary)"

            # Store data needed for linking in button value
            button_value = json.dumps({
                "key": key,
                "topic": topic[:100],
                "decision": decision_text[:500],
                "user_id": user_id,
            })

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{key}*: {summary}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Link"},
                    "action_id": f"link_decision_{key}",
                    "value": button_value,
                }
            })

        await jira.close()

    except Exception as e:
        logger.warning(f"Failed to fetch issue summaries: {e}")
        # Show keys without summaries
        for key in issues[:5]:
            button_value = json.dumps({
                "key": key,
                "topic": topic[:100],
                "decision": decision_text[:500],
                "user_id": user_id,
            })
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{key}*"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Link"},
                    "action_id": f"link_decision_{key}",
                    "value": button_value,
                }
            })

    # Add skip button
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Skip"},
                "action_id": "skip_decision_link"
            }
        ]
    })

    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        blocks=blocks,
        text="Link decision to Jira?",
    )


async def _handle_expand_decision(
    decision_id: str,
    identity: SessionIdentity,
    client: WebClient,
    additional_context: str = "",
) -> None:
    """Handle EXPAND subtype: show rich decision details.

    Loads decision from DB and displays it with full context:
    rationale, alternatives, consequences, etc.

    Args:
        decision_id: UUID of the decision to expand
        identity: Session identity
        client: Slack WebClient
        additional_context: Optional additional text from LLM
    """
    from src.db.decision_store import DecisionStore
    from src.slack.blocks.decision_cards import build_approved_card

    try:
        async with DecisionStore() as store:
            decision = await store.get(decision_id)

        if not decision:
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text="Decision not found.",
            )
            return

        # Build rich decision card
        blocks = build_approved_card(decision)

        # Add additional context if provided
        if additional_context:
            blocks.insert(0, {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":mag: *Decision Details*\n\n{additional_context}"
                }
            })
            blocks.insert(1, {"type": "divider"})

        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            blocks=blocks,
            text=f"Decision: {decision.title}",
        )

        logger.info(
            "Expanded decision details",
            extra={
                "decision_id": decision_id,
                "channel_id": identity.channel_id,
            }
        )

    except Exception as e:
        logger.error(f"Failed to expand decision {decision_id}: {e}")
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f"Failed to load decision details: {e}",
        )
