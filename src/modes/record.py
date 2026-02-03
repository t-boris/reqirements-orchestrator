"""RECORD mode handler - captures decisions from conversation.

Ref: BOT_DESIGN.md - RECORD Mode
"""

import logging

from src.domain.channel import ChannelAggregate
from src.domain.content import DecisionContent, DecisionType
from src.domain.types import ChannelId, ThreadTs, UserId
from src.modes.base import ModeContext, ModeHandler, ModeResult

logger = logging.getLogger(__name__)


class RecordModeHandler(ModeHandler):
    """Handler for RECORD mode - captures decisions from conversation."""

    @property
    def mode_name(self) -> str:
        return "RECORD"

    async def handle(self, context: ModeContext) -> ModeResult:
        """Handle RECORD mode - capture a decision.

        Flow:
        1. Check safety
        2. Extract decision from conversation
        3. Create draft decision
        4. Return preview for confirmation
        """
        # Safety check
        if not context.safety_check.allowed:
            return ModeResult(
                response_text=context.safety_check.reason or "Action not allowed",
            )

        # If not confirmed yet, show preview
        if context.safety_check.requires_confirmation and not context.entity_data:
            return await self._create_decision_preview(context)

        # Create the decision
        return await self._record_decision(context)

    async def _create_decision_preview(self, context: ModeContext) -> ModeResult:
        """Extract decision and show preview."""
        # TODO: Use LLM to extract structured decision
        # For now, use basic extraction

        # Try to infer decision type from keywords
        message_lower = context.message.lower()
        if any(kw in message_lower for kw in ["architecture", "design", "pattern", "technology"]):
            decision_type = DecisionType.ARCHITECTURE
        elif any(kw in message_lower for kw in ["scope", "include", "exclude", "out of scope"]):
            decision_type = DecisionType.SCOPE
        elif any(kw in message_lower for kw in ["constraint", "must", "requirement", "non-negotiable"]):
            decision_type = DecisionType.CONSTRAINT
        elif any(kw in message_lower for kw in ["priority", "first", "before", "after"]):
            decision_type = DecisionType.PRIORITY
        else:
            decision_type = DecisionType.ARCHITECTURE  # Default

        # Extract title (first sentence or up to 80 chars)
        title = context.message.split(".")[0][:80].strip()

        preview_content = {
            "decision_type": decision_type.value,
            "title": title,
            "description": context.message,
            "rationale": "",  # Will be extracted by LLM in future
        }

        preview_text = (
            f"*Draft Decision*\n\n"
            f"*Type:* {decision_type.value.title()}\n"
            f"*Title:* {title}\n"
            f"*Description:* {context.message[:200]}...\n\n"
            "_Click 'Record' to capture this decision_"
        )

        return ModeResult(
            response_text=preview_text,
            requires_confirmation=True,
            confirmation_data={
                "action": "record_decision",
                "content": preview_content,
            },
            response_blocks=self._build_decision_preview_blocks(preview_content),
        )

    async def _record_decision(self, context: ModeContext) -> ModeResult:
        """Record the decision after confirmation."""
        if not context.channel_aggregate:
            aggregate = ChannelAggregate(channel_id=ChannelId(context.channel_id))
        else:
            aggregate = context.channel_aggregate

        confirmation = context.entity_data or {}
        content_data = confirmation.get("content", {})

        content = DecisionContent(
            decision_type=DecisionType(content_data.get("decision_type", "architecture")),
            title=content_data.get("title", "Untitled Decision"),
            description=content_data.get("description", ""),
            rationale=content_data.get("rationale", ""),
        )

        draft = aggregate.record_decision(
            actor_id=UserId(context.user_id),
            thread_ts=ThreadTs(context.thread_ts or ""),
            content=content,
        )

        events = aggregate.clear_pending_events()

        return ModeResult(
            response_text=f":white_check_mark: Recorded decision: {content.title}",
            entity_created=str(draft.id),
            events_emitted=[e.event_type for e in events],
            draft_entity=draft,
            response_blocks=self._build_recorded_blocks(draft, content),
        )

    def _build_decision_preview_blocks(self, content: dict) -> list[dict]:
        """Build Slack blocks for decision preview."""
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Draft Decision*\n\n*Type:* {content['decision_type'].title()}\n*Title:* {content['title']}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Description:*\n{content['description'][:500]}",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Record Decision"},
                        "style": "primary",
                        "action_id": "confirm_record_decision",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Edit"},
                        "action_id": "edit_decision",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Cancel"},
                        "action_id": "cancel_decision",
                    },
                ],
            },
        ]

    def _build_recorded_blocks(self, draft, content: DecisionContent) -> list[dict]:
        """Build Slack blocks for recorded decision."""
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":memo: *Decision Recorded*\n\n*{content.title}*\n\n_{content.decision_type.value.title()} decision_",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Propose for Approval"},
                        "style": "primary",
                        "action_id": f"propose_{draft.id}",
                    },
                ],
            },
        ]
