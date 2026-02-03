"""CREATE mode handler - creates new entities from conversation.

Ref: BOT_DESIGN.md - CREATE Mode
"""

import logging
from datetime import datetime

from pydantic import BaseModel, Field

from src.domain.channel import ChannelAggregate
from src.domain.content import Attribution, IssueType, WorkItemContent
from src.domain.entities import DraftEntity
from src.domain.types import ChannelId, EntityId, EntityType, ThreadTs, UserId, Version
from src.llm.client import structured_completion
from src.modes.base import ModeContext, ModeHandler, ModeResult

logger = logging.getLogger(__name__)


class ExtractedWorkItem(BaseModel):
    """LLM-extracted work item content from user message."""

    title: str = Field(description="Clear, concise title for the work item (5-15 words)")
    issue_type: str = Field(
        default="story",
        description="Issue type: story, task, bug, or spike"
    )
    description: str = Field(description="Detailed description of what needs to be done")
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Measurable acceptance criteria"
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Technical constraints or requirements"
    )


class ExtractedDecision(BaseModel):
    """A single architectural decision extracted from thread."""

    title: str = Field(description="Clear decision title, e.g. 'Use Monolith Architecture'")
    decision_type: str = Field(
        default="architecture",
        description="Decision type: architecture, technology, process, scope"
    )
    context: str = Field(description="What problem or question prompted this decision")
    decision: str = Field(description="The actual decision that was made")
    rationale: str = Field(description="Why this decision was made, based on the discussion")
    alternatives_considered: list[str] = Field(
        default_factory=list,
        description="Alternatives that were discussed but not chosen"
    )


class ExtractedDecisions(BaseModel):
    """Multiple decisions extracted from a thread conversation."""

    decisions: list[ExtractedDecision] = Field(
        description="All decisions found in the conversation, from initial requirements and discussion"
    )


EXTRACT_WORK_ITEM_SYSTEM = """You are extracting a structured work item from a Slack conversation.

The user wants to create a work item (ticket/story/task). Extract:
- A clear, concise TITLE (not the raw message - summarize the intent in 5-15 words)
- The appropriate issue type (story for features, task for chores, bug for defects, spike for research)
- A well-written description expanding on the user's intent
- Acceptance criteria if inferable from the conversation
- Technical constraints if mentioned

Use the FULL THREAD CONTEXT to understand what was discussed, not just the last message.
Be professional and concise. The title should read like a Jira ticket title."""

EXTRACT_WORK_ITEM_USER = """Thread conversation:
{thread_context}

User's latest message requesting creation:
"{message}"

Extract a work item based on the full conversation context."""

EXTRACT_DECISION_SYSTEM = """You are extracting ALL architectural decisions from a Slack thread discussion.

A thread often contains MULTIPLE decisions - from the initial requirements message AND from the conversation.
Extract EVERY decision as a separate ADR (Architecture Decision Record).

Examples of decisions to look for:
- Technology choices ("PostgreSQL for storage", "S3 for blobs")
- Architecture patterns ("Monolith", "Serverless", "Microservices")
- Design choices ("DB as source of truth", "webhooks for Slack communication")
- Scope decisions ("simple multi-option quizzes", "no specific latency requirements")

Use the FULL THREAD CONTEXT. Decisions come from:
1. The initial requirements/message (explicit tech choices, stated preferences)
2. Answers during the discussion (user confirming or choosing options)
3. Bot proposals that were accepted (if user agreed with a suggestion)

Each title should read like an ADR title, e.g. "Use Monolith Architecture for Initial Release"."""

EXTRACT_DECISION_USER = """Thread conversation:
{thread_context}

User's request:
"{message}"

Extract ALL architectural decisions from this entire conversation."""


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

    def _build_thread_context(self, context: ModeContext) -> str:
        """Build a text summary of the thread for LLM context."""
        if not context.thread_messages:
            return f"(No thread history)\nMessage: {context.message}"
        return "\n".join(
            f"{'Bot' if m['role'] == 'assistant' else 'User'}: {m['content']}"
            for m in context.thread_messages
        )

    async def _create_preview(self, context: ModeContext) -> ModeResult:
        """Extract content using LLM and show preview for confirmation."""
        entity_type = context.intent.entity_type or "work_item"
        thread_context = self._build_thread_context(context)

        if entity_type == "work_item":
            return await self._create_work_item_preview(context, thread_context)

        return await self._create_decision_preview(context, thread_context)

    async def _create_work_item_preview(
        self, context: ModeContext, thread_context: str
    ) -> ModeResult:
        """Extract and preview a work item using LLM."""
        try:
            extracted = await structured_completion(
                response_model=ExtractedWorkItem,
                messages=[
                    {"role": "system", "content": EXTRACT_WORK_ITEM_SYSTEM},
                    {"role": "user", "content": EXTRACT_WORK_ITEM_USER.format(
                        thread_context=thread_context,
                        message=context.message,
                    )},
                ],
            )

            preview_content = {
                "issue_type": extracted.issue_type,
                "title": extracted.title,
                "description": extracted.description,
                "acceptance_criteria": extracted.acceptance_criteria,
                "constraints": extracted.constraints,
            }
        except Exception as e:
            logger.warning(f"LLM extraction failed, using raw message: {e}")
            preview_content = {
                "issue_type": "story",
                "title": context.message,
                "description": context.message,
                "acceptance_criteria": [],
                "constraints": [],
            }

        ac_text = ""
        if preview_content["acceptance_criteria"]:
            ac_items = "\n".join(f"  • {ac}" for ac in preview_content["acceptance_criteria"])
            ac_text = f"\n*Acceptance Criteria:*\n{ac_items}"

        preview_text = (
            f"*Draft Work Item*\n\n"
            f"*Type:* {preview_content['issue_type'].title()}\n"
            f"*Title:* {preview_content['title']}\n"
            f"*Description:* {preview_content['description']}"
            f"{ac_text}\n\n"
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

    async def _create_decision_preview(
        self, context: ModeContext, thread_context: str
    ) -> ModeResult:
        """Extract and preview multiple decisions using LLM with thread context."""
        try:
            extracted = await structured_completion(
                response_model=ExtractedDecisions,
                messages=[
                    {"role": "system", "content": EXTRACT_DECISION_SYSTEM},
                    {"role": "user", "content": EXTRACT_DECISION_USER.format(
                        thread_context=thread_context,
                        message=context.message,
                    )},
                ],
            )
            decisions = [d.model_dump() for d in extracted.decisions]
        except Exception as e:
            logger.warning(f"LLM decision extraction failed: {e}")
            decisions = [{
                "decision_type": "architecture",
                "title": context.message,
                "context": "",
                "decision": context.message,
                "rationale": "",
                "alternatives_considered": [],
            }]

        # Build preview text for all decisions
        decision_blocks = []
        for i, d in enumerate(decisions, 1):
            alts = ""
            if d.get("alternatives_considered"):
                alts = "\n  _Alternatives: " + ", ".join(d["alternatives_considered"]) + "_"

            decision_blocks.append(
                f"*{i}. {d['title']}*\n"
                f"  {d['decision']}\n"
                f"  _Rationale: {d['rationale']}_"
                f"{alts}"
            )

        preview_text = (
            f"*Draft Decision Records* ({len(decisions)} found)\n\n"
            + "\n\n".join(decision_blocks)
            + "\n\n_Click 'Record All' to capture these decisions_"
        )

        return ModeResult(
            response_text=preview_text,
            requires_confirmation=True,
            confirmation_data={
                "action": "create_decisions",
                "content": {"decisions": decisions},
            },
            response_blocks=self._build_decisions_preview_blocks(decisions),
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

    def _build_decisions_preview_blocks(self, decisions: list[dict]) -> list[dict]:
        """Build Slack blocks for multiple decision previews."""
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Draft Decision Records ({len(decisions)} found)",
                },
            },
        ]

        for i, d in enumerate(decisions, 1):
            alts = ""
            if d.get("alternatives_considered"):
                alts = f"\n_Alternatives: {', '.join(d['alternatives_considered'])}_"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{i}. {d['title']}*\n"
                        f"{d['decision']}\n"
                        f"_Rationale: {d['rationale']}_"
                        f"{alts}"
                    ),
                },
            })
            blocks.append({"type": "divider"})

        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Record All"},
                    "style": "primary",
                    "action_id": "record_all_decisions",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit"},
                    "action_id": "edit_decisions",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "action_id": "cancel_decisions",
                },
            ],
        })

        return blocks

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
