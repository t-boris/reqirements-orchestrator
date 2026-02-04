"""RECORD mode handler - captures decisions from conversation.

Ref: BOT_DESIGN.md - RECORD Mode
"""

import json
import logging

from pydantic import BaseModel, Field

from src.domain.channel import ChannelAggregate
from src.domain.content import DecisionContent, DecisionType
from src.domain.types import ChannelId, EntityType, ThreadTs, UserId
from src.infrastructure.aggregate_loader import load_aggregate
from src.llm.client import structured_completion
from src.modes.base import ModeContext, ModeHandler, ModeResult

logger = logging.getLogger(__name__)


class ExtractedRecordDecision(BaseModel):
    """LLM-extracted decision from an inline statement."""

    title: str = Field(description="Clear decision title, e.g. 'Use PostgreSQL for Storage'")
    decision_type: str = Field(
        description="One of: architecture, scope, constraint, priority, process, structure"
    )
    description: str = Field(description="Full description of what was decided and its context")
    rationale: str = Field(description="Why this decision was made, based on the conversation")
    alternatives_considered: list[str] = Field(
        default_factory=list,
        description="Alternatives mentioned in the conversation"
    )


EXTRACT_RECORD_DECISION_SYSTEM = """You are extracting a decision from an inline statement in a Slack conversation.

The user stated a decision or commitment directly (not a request to document). Extract:
- A clear ADR-style title (e.g. "Use PostgreSQL for Storage")
- The decision type: architecture, scope, constraint, priority, process, or structure
- A description of what was decided and its context
- The rationale (why this choice, based on conversation context)
- Any alternatives that were discussed

CRITICAL formatting rules (Slack mrkdwn):
- Bold: *text* (single asterisks)
- NEVER use **double asterisks**"""

EXTRACT_RECORD_DECISION_USER = """Thread conversation:
{thread_context}

User's statement (the decision):
"{message}"

Extract the decision from this inline statement."""


class RecordModeHandler(ModeHandler):
    """Handler for RECORD mode - captures decisions from conversation."""

    @property
    def mode_name(self) -> str:
        return "RECORD"

    async def handle(self, context: ModeContext) -> ModeResult:
        """Handle RECORD mode - capture a decision.

        Flow:
        1. Check safety
        2. Extract decision from conversation using LLM
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

    def _build_thread_context(self, context: ModeContext) -> str:
        """Build a text summary of the thread for LLM context."""
        if not context.thread_messages:
            return f"(No thread history)\nMessage: {context.message}"
        return "\n".join(
            f"{'Bot' if m['role'] == 'assistant' else 'User'}: {m['content']}"
            for m in context.thread_messages
        )

    async def _create_decision_preview(self, context: ModeContext) -> ModeResult:
        """Extract decision using LLM and show preview."""
        thread_context = self._build_thread_context(context)

        try:
            extracted = await structured_completion(
                response_model=ExtractedRecordDecision,
                messages=[
                    {"role": "system", "content": EXTRACT_RECORD_DECISION_SYSTEM},
                    {"role": "user", "content": EXTRACT_RECORD_DECISION_USER.format(
                        thread_context=thread_context,
                        message=context.message,
                    )},
                ],
            )

            # Map decision type string to enum
            try:
                decision_type = DecisionType(extracted.decision_type.lower())
            except ValueError:
                decision_type = DecisionType.ARCHITECTURE

            preview_content = {
                "decision_type": decision_type.value,
                "title": extracted.title,
                "description": extracted.description,
                "rationale": extracted.rationale,
                "alternatives_considered": extracted.alternatives_considered,
            }
        except Exception as e:
            logger.warning(f"LLM decision extraction failed: {e}")
            preview_content = {
                "decision_type": DecisionType.ARCHITECTURE.value,
                "title": context.message.split(".")[0][:80].strip(),
                "description": context.message,
                "rationale": "",
                "alternatives_considered": [],
            }

        # Check for existing decisions in this thread
        existing_decision = None
        if context.thread_ts:
            try:
                aggregate = await load_aggregate(context.channel_id)
                existing = aggregate.get_entities_in_thread(ThreadTs(context.thread_ts))
                existing_decisions = [
                    e for e in existing if e.entity_type == EntityType.DECISION
                ]
                if existing_decisions:
                    # Use the most recent one (last in list)
                    existing_decision = existing_decisions[-1]
            except Exception as e:
                logger.warning(f"Failed to check for existing decisions: {e}")

        if existing_decision is not None:
            # Show amendment preview instead of new decision preview
            return ModeResult(
                response_text=(
                    f"*Amend Existing Decision*\n\n"
                    f"Found existing decision: *{getattr(existing_decision.content, 'title', 'Untitled')}*\n\n"
                    f"New content:\n"
                    f"*Title:* {preview_content['title']}\n"
                    f"*Description:* {preview_content['description'][:300]}\n\n"
                    "_Choose to amend the existing decision, record as new, or cancel_"
                ),
                requires_confirmation=True,
                confirmation_data={
                    "action": "amend_decision",
                    "existing_entity_id": str(existing_decision.id),
                    "content": preview_content,
                },
                response_blocks=self._build_amendment_preview_blocks(
                    existing_decision, preview_content
                ),
            )

        alts = ""
        if preview_content["alternatives_considered"]:
            alts = "\n*Alternatives:* " + ", ".join(preview_content["alternatives_considered"])

        preview_text = (
            f"*Draft Decision*\n\n"
            f"*Type:* {preview_content['decision_type'].title()}\n"
            f"*Title:* {preview_content['title']}\n"
            f"*Description:* {preview_content['description'][:300]}\n"
            f"*Rationale:* {preview_content['rationale'][:200]}"
            f"{alts}\n\n"
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
            alternatives_considered=content_data.get("alternatives_considered", []),
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
        alts_text = ""
        if content.get("alternatives_considered"):
            alts_text = f"\n_Alternatives: {', '.join(content['alternatives_considered'])}_"

        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Draft Decision*\n\n"
                        f"*Type:* {content['decision_type'].title()}\n"
                        f"*Title:* {content['title']}"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Description:*\n{content['description'][:500]}\n\n"
                        f"*Rationale:*\n{content.get('rationale', 'N/A')[:300]}"
                        f"{alts_text}"
                    ),
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

    def _build_amendment_preview_blocks(self, existing, new_content: dict) -> list[dict]:
        """Build Slack blocks for amendment preview.

        Shows current decision content, a divider, then proposed new content,
        with Amend/Record as New/Cancel buttons.
        """
        existing_title = getattr(existing.content, "title", "Untitled")
        existing_desc = getattr(existing.content, "description", "")[:200]

        new_alts_text = ""
        if new_content.get("alternatives_considered"):
            new_alts_text = (
                f"\n_Alternatives: {', '.join(new_content['alternatives_considered'])}_"
            )

        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Amend Existing Decision*\n\n"
                        f"_Current:_ *{existing_title}*\n"
                        f"{existing_desc}"
                    ),
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Proposed Update:*\n\n"
                        f"*Type:* {new_content['decision_type'].title()}\n"
                        f"*Title:* {new_content['title']}\n\n"
                        f"*Description:*\n{new_content['description'][:500]}\n\n"
                        f"*Rationale:*\n{new_content.get('rationale', 'N/A')[:300]}"
                        f"{new_alts_text}"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Amend Decision"},
                        "style": "primary",
                        "action_id": "confirm_amend_decision",
                        "value": json.dumps({"entity_id": str(existing.id)}),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Record as New"},
                        "action_id": "confirm_record_decision",
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
