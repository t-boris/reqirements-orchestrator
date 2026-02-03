"""CREATE mode handler - creates new entities from conversation.

Ref: BOT_DESIGN.md - CREATE Mode
"""

import logging
from datetime import datetime

from src.domain.channel import ChannelAggregate
from src.domain.content import Attribution, IssueType, WorkItemContent
from src.domain.entities import DraftEntity
from src.domain.types import ChannelId, EntityId, EntityType, ThreadTs, UserId, Version
from src.modes.base import ModeContext, ModeHandler, ModeResult

logger = logging.getLogger(__name__)


class CreateModeHandler(ModeHandler):
    """Handler for CREATE mode - creates new work items or decisions."""

    @property
    def mode_name(self) -> str:
        return "CREATE"

    async def handle(self, context: ModeContext) -> ModeResult:
        """Handle CREATE mode - extract and create draft entity.

        Flow:
        1. Check safety (confirmation required for side effects)
        2. Extract content from message/thread
        3. Create draft entity via ChannelAggregate
        4. Return preview with "Propose" button
        """
        # Safety check - CREATE requires confirmation
        if not context.safety_check.allowed:
            return ModeResult(
                response_text=context.safety_check.reason or "Action not allowed",
                requires_confirmation=False,
            )

        if context.safety_check.requires_confirmation and not context.entity_data:
            # First pass - extract content and show preview
            return await self._create_preview(context)

        # User confirmed - create the entity
        return await self._create_entity(context)

    async def _create_preview(self, context: ModeContext) -> ModeResult:
        """Extract content and show preview for confirmation."""
        # TODO: Use LLM to extract structured content from message
        # For now, use basic extraction

        entity_type = context.intent.entity_type or "work_item"

        if entity_type == "work_item":
            # Basic title extraction from message
            title = context.message[:80].strip()
            if len(context.message) > 80:
                title = title[:77] + "..."

            preview_content = {
                "issue_type": "story",
                "title": title,
                "description": context.message,
                "acceptance_criteria": [],
                "constraints": [],
            }

            preview_text = (
                f"*Draft Work Item*\n\n"
                f"*Type:* Story\n"
                f"*Title:* {title}\n"
                f"*Description:* {context.message[:200]}...\n\n"
                "_Click 'Propose' to submit for team approval_"
            )

            return ModeResult(
                response_text=preview_text,
                requires_confirmation=True,
                confirmation_data={
                    "action": "create_work_item",
                    "content": preview_content,
                },
                response_blocks=self._build_preview_blocks(preview_content),
            )

        # Decision type
        preview_content = {
            "decision_type": "architecture",
            "title": context.message[:80],
            "description": context.message,
            "rationale": "",
        }

        return ModeResult(
            response_text=f"Draft Decision: {preview_content['title']}",
            requires_confirmation=True,
            confirmation_data={
                "action": "create_decision",
                "content": preview_content,
            },
        )

    async def _create_entity(self, context: ModeContext) -> ModeResult:
        """Create the entity after confirmation."""
        if not context.channel_aggregate:
            # Create a new aggregate if not provided
            # In production, this would be loaded from the event store
            aggregate = ChannelAggregate(channel_id=ChannelId(context.channel_id))
        else:
            aggregate = context.channel_aggregate

        confirmation = context.entity_data or {}
        action = confirmation.get("action", "create_work_item")
        content_data = confirmation.get("content", {})

        if action == "create_work_item":
            content = WorkItemContent(
                issue_type=IssueType(content_data.get("issue_type", "story")),
                title=content_data.get("title", "Untitled"),
                description=content_data.get("description", ""),
                acceptance_criteria=content_data.get("acceptance_criteria", []),
                constraints=content_data.get("constraints", []),
            )

            draft = aggregate.draft_work_item(
                actor_id=UserId(context.user_id),
                thread_ts=ThreadTs(context.thread_ts or ""),
                content=content,
            )

            events = aggregate.clear_pending_events()

            return ModeResult(
                response_text=f"Created draft work item: {content.title}",
                entity_created=str(draft.id),
                events_emitted=[e.event_type for e in events],
                draft_entity=draft,
                response_blocks=self._build_draft_blocks(draft),
            )

        # Handle decision creation similarly
        return ModeResult(
            response_text="Decision creation not yet implemented",
        )

    def _build_preview_blocks(self, content: dict) -> list[dict]:
        """Build Slack blocks for work item preview."""
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Draft Work Item*\n\n*Type:* {content['issue_type'].title()}\n*Title:* {content['title']}",
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
                        "text": {"type": "plain_text", "text": "Propose to Channel"},
                        "style": "primary",
                        "action_id": "propose_draft",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Edit"},
                        "action_id": "edit_draft",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Cancel"},
                        "action_id": "cancel_draft",
                    },
                ],
            },
        ]

    def _build_draft_blocks(self, draft: DraftEntity) -> list[dict]:
        """Build Slack blocks for created draft."""
        content = draft.content
        if hasattr(content, "title"):
            title = content.title
        else:
            title = str(draft.id)

        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":memo: *Draft Created*\n\n*{title}*\n\nReady to propose for approval.",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Propose to Channel"},
                        "style": "primary",
                        "action_id": f"propose_{draft.id}",
                    },
                ],
            },
        ]
