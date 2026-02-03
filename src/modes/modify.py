"""MODIFY mode handler - modifies existing entities.

Ref: BOT_DESIGN.md - MODIFY Mode
"""

import logging

from pydantic import BaseModel, Field

from src.domain.channel import ChannelAggregate, InvalidStateError
from src.domain.content import WorkItemContent, DecisionContent
from src.domain.entities import DraftEntity, ProposedEntity
from src.domain.transitions import can_modify
from src.domain.types import ChannelId, EntityId, UserId
from src.llm.client import structured_completion
from src.modes.base import ModeContext, ModeHandler, ModeResult

logger = logging.getLogger(__name__)


class ExtractedModification(BaseModel):
    """LLM-extracted modification from user message."""

    field: str = Field(
        description="Which field to modify: title, description, acceptance_criteria, "
                    "constraints, rationale, decision_type, issue_type"
    )
    new_value: str = Field(description="The new value for the field")
    summary: str = Field(description="Brief summary of the change for confirmation")


class ExtractedModifications(BaseModel):
    """Multiple modifications extracted from a message."""

    modifications: list[ExtractedModification] = Field(
        description="All modifications the user wants to make"
    )


EXTRACT_MODIFICATIONS_SYSTEM = """You are extracting modifications from a user's message about an existing entity.

Current entity:
{entity_summary}

Extract what the user wants to change. Possible fields:
- title: The entity title/summary
- description: The detailed description
- acceptance_criteria: List of acceptance criteria (for work items)
- constraints: List of constraints (for work items)
- rationale: Decision rationale (for decisions)
- decision_type: Type of decision (for decisions)
- issue_type: Type of issue - story, task, bug, spike (for work items)

For list fields (acceptance_criteria, constraints), provide the full updated list as a comma-separated string.

CRITICAL formatting rules (Slack mrkdwn):
- Bold: *text* (single asterisks)
- NEVER use **double asterisks**"""

EXTRACT_MODIFICATIONS_USER = """User's modification request:
"{message}"

Extract the modifications the user wants to make."""


class ModifyModeHandler(ModeHandler):
    """Handler for MODIFY mode - modifies existing entities."""

    @property
    def mode_name(self) -> str:
        return "MODIFY"

    async def handle(self, context: ModeContext) -> ModeResult:
        """Handle MODIFY mode - update an existing entity.

        Flow:
        1. Check safety (modification allowed?)
        2. Find target entity
        3. Validate entity state allows modification
        4. Extract changes using LLM
        5. Show preview with changes
        """
        # Safety check
        if not context.safety_check.allowed:
            return ModeResult(
                response_text=context.safety_check.reason or "Modification not allowed",
            )

        # Get target entity
        target_entity_id = context.intent.target_entity_id
        if not target_entity_id:
            return ModeResult(
                response_text="I couldn't identify which entity you want to modify. Please be more specific or mention the entity by name.",
            )

        # Check if we have the aggregate
        if not context.channel_aggregate:
            # Load from event store
            from src.infrastructure.aggregate_loader import load_aggregate
            try:
                aggregate = await load_aggregate(context.channel_id)
            except Exception as e:
                logger.error(f"Failed to load aggregate: {e}", exc_info=True)
                return ModeResult(
                    response_text="Failed to load channel data. Please try again.",
                )
        else:
            aggregate = context.channel_aggregate

        entity = aggregate.get_entity(EntityId(target_entity_id))

        if not entity:
            return ModeResult(
                response_text=f"Entity `{target_entity_id}` not found in this channel.",
            )

        # Check if entity can be modified
        can_mod, reason = can_modify(entity)
        if not can_mod:
            return ModeResult(
                response_text=f"Cannot modify this entity: {reason}",
            )

        # Extract modifications using LLM
        entity_summary = self._build_entity_summary(entity)

        try:
            extracted = await structured_completion(
                response_model=ExtractedModifications,
                messages=[
                    {"role": "system", "content": EXTRACT_MODIFICATIONS_SYSTEM.format(
                        entity_summary=entity_summary,
                    )},
                    {"role": "user", "content": EXTRACT_MODIFICATIONS_USER.format(
                        message=context.message,
                    )},
                ],
            )

            if not extracted.modifications:
                return ModeResult(
                    response_text="I couldn't determine what changes you want to make. Could you be more specific?",
                )

            # Build preview of changes
            changes_text = "\n".join(
                f"- *{m.field}*: {m.summary}" for m in extracted.modifications
            )

            return ModeResult(
                response_text=(
                    f"*Proposed changes:*\n{changes_text}\n\n"
                    "_Click 'Apply' to confirm these changes_"
                ),
                requires_confirmation=True,
                confirmation_data={
                    "action": "modify_entity",
                    "entity_id": target_entity_id,
                    "modifications": [m.model_dump() for m in extracted.modifications],
                },
                entity_modified=target_entity_id,
                response_blocks=self._build_modification_preview_blocks(
                    target_entity_id, extracted.modifications
                ),
            )

        except Exception as e:
            logger.warning(f"LLM modification extraction failed: {e}")
            entity_type = "work item" if isinstance(entity.content, WorkItemContent) else "decision"
            return ModeResult(
                response_text=(
                    f"I understand you want to modify the {entity_type} "
                    f"*{getattr(entity.content, 'title', target_entity_id)}*. "
                    f"What specific changes would you like to make?"
                ),
            )

    def _build_entity_summary(self, entity) -> str:
        """Build a text summary of the entity for LLM context."""
        content = entity.content
        lines = [f"Type: {type(entity).__name__}"]

        if hasattr(content, "title"):
            lines.append(f"Title: {content.title}")
        if hasattr(content, "issue_type"):
            lines.append(f"Issue Type: {content.issue_type}")
        if hasattr(content, "description") and content.description:
            lines.append(f"Description: {content.description[:200]}")
        if hasattr(content, "acceptance_criteria") and content.acceptance_criteria:
            lines.append(f"Acceptance Criteria: {', '.join(content.acceptance_criteria)}")
        if hasattr(content, "constraints") and content.constraints:
            lines.append(f"Constraints: {', '.join(content.constraints)}")
        if hasattr(content, "decision_type"):
            lines.append(f"Decision Type: {content.decision_type}")
        if hasattr(content, "rationale") and content.rationale:
            lines.append(f"Rationale: {content.rationale[:200]}")

        return "\n".join(lines)

    def _build_modification_preview_blocks(
        self, entity_id: str, modifications: list[ExtractedModification]
    ) -> list[dict]:
        """Build Slack blocks for modification preview."""
        changes_text = "\n".join(
            f"- *{m.field}*: {m.summary}" for m in modifications
        )

        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Proposed Changes* for `{entity_id[:8]}...`\n\n{changes_text}",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Apply Changes"},
                        "style": "primary",
                        "action_id": f"apply_modify_{entity_id}",
                        "value": entity_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Cancel"},
                        "action_id": f"cancel_modify_{entity_id}",
                        "value": entity_id,
                    },
                ],
            },
        ]
