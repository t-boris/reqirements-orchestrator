"""CREATE mode handler - creates new entities from conversation.

Ref: BOT_DESIGN.md - CREATE Mode
"""

import logging
from datetime import datetime

from pydantic import BaseModel, Field

from src.domain.channel import ChannelAggregate
from src.domain.content import Attribution, IssueType, WorkItemContent
from src.domain.entities import DraftEntity, get_lifecycle
from src.domain.types import ChannelId, EntityId, EntityType, ThreadTs, UserId, Version
from src.infrastructure.aggregate_loader import load_aggregate
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


class ExtractedWorkItems(BaseModel):
    """Multiple work items extracted from existing entities in a channel."""

    work_items: list[ExtractedWorkItem] = Field(
        description="One work item per relevant entity/decision area"
    )


class ExtractedDecision(BaseModel):
    """A single architectural decision extracted from thread."""

    title: str = Field(description="Clear decision title, e.g. 'Use Monolith Architecture'")
    decision_type: str = Field(
        default="architecture",
        description="Decision type: architecture, technology, process, scope, constraint, priority, structure"
    )
    context: str = Field(description="What problem or question prompted this decision")
    decision: str = Field(description="The actual decision that was made")
    rationale: str = Field(
        description=(
            "Why this decision was made, with specific attribution: "
            "WHO proposed it (user, bot, consensus), "
            "HOW it was decided (stated as requirement, chosen from options, agreed in discussion), "
            "WHY this option over alternatives"
        )
    )
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

EXTRACT_BATCH_WORK_ITEMS_SYSTEM = """You are generating structured work items from existing architectural decisions and entities in a channel.

The user wants to create work items (epics/stories/tasks) based on the existing decisions and entities.
Generate ONE work item per relevant entity/decision area.

For each work item:
- Title should read like a Jira ticket title (5-15 words)
- Issue type: epic for large decision areas, story for specific features, task for implementation chores
- Description should reference the related decision and explain what needs to be built
- Include acceptance criteria derived from the decision's rationale and constraints
- Include relevant technical constraints from the decision

Be professional and concise. Each work item should be independently actionable."""

EXTRACT_BATCH_WORK_ITEMS_USER = """Existing entities in this channel:
{entity_context}

Thread conversation:
{thread_context}

User's request:
"{message}"

Generate one work item per relevant entity/decision area."""

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

Each title should read like an ADR title, e.g. "Use Monolith Architecture for Initial Release".

For each decision's rationale, be SPECIFIC:
- WHO proposed it (user, bot, consensus)
- HOW decided (stated as requirement, chosen from options, agreed in discussion)
- WHY this option over alternatives
Bad: 'This was chosen for the project'
Good: 'Proposed by the user as an explicit requirement. PostgreSQL preferred for ACID guarantees.'"""

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
        2. Extract content from message/thread (or from plan step context)
        3. Create draft entity via ChannelAggregate
        4. Return preview with "Propose" button

        When executing as a plan step, uses plan_step_context (analysis from
        previous steps like ARCHITECT mode) to generate batch work items.
        """
        # Safety check - CREATE requires confirmation
        if not context.safety_check.allowed:
            return ModeResult(
                response_text=context.safety_check.reason or "Action not allowed",
                requires_confirmation=False,
            )

        if context.safety_check.requires_confirmation and not context.entity_data:
            # First pass - extract content and show preview
            # If this is a plan step with context from ARCHITECT, use batch mode
            if context.is_plan_step and context.plan_step_context:
                return await self._create_batch_from_plan_context(context)
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

    async def _build_entity_context(self, channel_id: str) -> str:
        """Build entity summaries for LLM context (reuses ARCHITECT pattern)."""
        try:
            aggregate = await load_aggregate(channel_id)
            if not aggregate.entities:
                return "(No existing entities)"

            summaries = []
            for eid, entity in list(aggregate.entities.items())[:20]:
                title = getattr(entity.content, "title", str(eid)[:8])
                state = get_lifecycle(entity).value
                etype = entity.entity_type.value

                parts = [f"- *{title}* ({etype}, {state}) [id: {eid}]"]

                if etype == "decision":
                    rationale = getattr(entity.content, "rationale", "")
                    if rationale:
                        parts.append(f"  Rationale: {rationale[:200]}")
                    desc = getattr(entity.content, "description", "")
                    if desc:
                        parts.append(f"  Decision: {desc[:200]}")
                elif etype == "work_item":
                    desc = getattr(entity.content, "description", "")
                    if desc:
                        parts.append(f"  Description: {desc[:200]}")

                summaries.append("\n".join(parts))

            return "\n".join(summaries)
        except Exception as e:
            logger.debug(f"Could not load entity context: {e}")
            return "(No existing entities)"

    def _is_batch_work_item_intent(self, message: str) -> bool:
        """Detect if the message intends to create work items from existing entities."""
        import re
        batch_patterns = [
            r"(?:create|make|generate|build)\s+(?:epics?|stories|tasks|work items?|tickets?)\s+(?:for|from|based on)",
            r"(?:for|from|based on)\s+(?:the\s+)?(?:architecture|decisions?|ADRs?|entities)",
            r"(?:create|make|generate)\s+(?:epics?|stories|tasks)\s+(?:for\s+)?(?:each|all|every)",
        ]
        lower = message.lower()
        return any(re.search(p, lower) for p in batch_patterns)

    async def _create_preview(self, context: ModeContext) -> ModeResult:
        """Extract content using LLM and show preview for confirmation."""
        entity_type = context.intent.entity_type or "work_item"
        thread_context = self._build_thread_context(context)

        if entity_type == "work_item":
            # Check for batch intent referencing existing entities
            if self._is_batch_work_item_intent(context.message):
                return await self._create_batch_work_items_preview(context, thread_context)
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

    async def _create_batch_from_plan_context(self, context: ModeContext) -> ModeResult:
        """Create batch work items using analysis from plan step context.

        This is called when CREATE mode is executing as part of a multi-step plan,
        with the previous ARCHITECT step's analysis in plan_step_context.
        """
        analysis_context = context.plan_step_context or ""
        entity_context = await self._build_entity_context(context.channel_id)
        thread_context = self._build_thread_context(context)

        # Enhanced prompt that uses the analysis from the previous step
        system_prompt = """You are generating structured work items based on an architectural analysis.

The ARCHITECT has analyzed the existing decisions and provided recommendations. Now create
actionable work items (epics/stories/tasks) that implement this analysis.

For each work item:
- Title should read like a Jira ticket title (5-15 words)
- Issue type: epic for large areas, story for specific features, task for implementation chores
- Description should reference the related analysis and explain what needs to be built
- Include acceptance criteria derived from the analysis
- Include relevant technical constraints

Create multiple work items to cover all implementation areas identified in the analysis.
Be professional and concise. Each work item should be independently actionable."""

        user_prompt = f"""Architectural Analysis (from previous step):
{analysis_context}

Existing entities in channel:
{entity_context}

Thread conversation:
{thread_context}

User's original request:
"{context.message}"

Generate work items based on the architectural analysis above."""

        try:
            extracted = await structured_completion(
                response_model=ExtractedWorkItems,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            work_items = [w.model_dump() for w in extracted.work_items]
        except Exception as e:
            logger.warning(f"LLM batch work item extraction from plan context failed: {e}")
            # Fall back to regular batch mode
            return await self._create_batch_work_items_preview(context, thread_context)

        if not work_items:
            return await self._create_batch_work_items_preview(context, thread_context)

        return ModeResult(
            response_text=f"*Draft Work Items* ({len(work_items)} generated from analysis)",
            requires_confirmation=True,
            confirmation_data={
                "action": "create_batch_work_items",
                "content": {"work_items": work_items},
            },
            response_blocks=self._build_work_items_preview_blocks(work_items),
        )

    async def _create_batch_work_items_preview(
        self, context: ModeContext, thread_context: str
    ) -> ModeResult:
        """Extract and preview multiple work items from existing entities using LLM."""
        entity_context = await self._build_entity_context(context.channel_id)

        if entity_context == "(No existing entities)":
            # Fall back to single work item mode
            return await self._create_work_item_preview(context, thread_context)

        try:
            extracted = await structured_completion(
                response_model=ExtractedWorkItems,
                messages=[
                    {"role": "system", "content": EXTRACT_BATCH_WORK_ITEMS_SYSTEM},
                    {"role": "user", "content": EXTRACT_BATCH_WORK_ITEMS_USER.format(
                        entity_context=entity_context,
                        thread_context=thread_context,
                        message=context.message,
                    )},
                ],
            )
            work_items = [w.model_dump() for w in extracted.work_items]
        except Exception as e:
            logger.warning(f"LLM batch work item extraction failed: {e}")
            # Fall back to single work item mode
            return await self._create_work_item_preview(context, thread_context)

        if not work_items:
            return await self._create_work_item_preview(context, thread_context)

        return ModeResult(
            response_text=f"*Draft Work Items* ({len(work_items)} generated from entities)",
            requires_confirmation=True,
            confirmation_data={
                "action": "create_batch_work_items",
                "content": {"work_items": work_items},
            },
            response_blocks=self._build_work_items_preview_blocks(work_items),
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
            ctx = ""
            if d.get("context"):
                ctx = f"\n  _Context: {d['context']}_"
            alts = ""
            if d.get("alternatives_considered"):
                alts = "\n  _Alternatives: " + ", ".join(d["alternatives_considered"]) + "_"

            decision_blocks.append(
                f"*{i}. {d['title']}*\n"
                f"  {d['decision']}"
                f"{ctx}\n"
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

        # Handle decision creation
        if action == "create_decisions":
            decisions_data = content_data.get("decisions", [])
            if not decisions_data:
                return ModeResult(
                    response_text="No decisions to create.",
                )

            from src.domain.content import DecisionContent, DecisionType

            created_ids = []
            for d in decisions_data:
                try:
                    dt = DecisionType(d.get("decision_type", "architecture").lower())
                except ValueError:
                    dt = DecisionType.ARCHITECTURE

                decision_content = DecisionContent(
                    decision_type=dt,
                    title=d.get("title", "Untitled Decision"),
                    description=d.get("decision", d.get("description", "")),
                    rationale=d.get("rationale", ""),
                    alternatives_considered=d.get("alternatives_considered", []),
                )

                draft = aggregate.record_decision(
                    actor_id=UserId(context.user_id),
                    thread_ts=ThreadTs(context.thread_ts or ""),
                    content=decision_content,
                )
                created_ids.append((str(draft.id), decision_content.title))

            events = aggregate.clear_pending_events()

            titles_text = "\n".join(f"- {title}" for _, title in created_ids)
            return ModeResult(
                response_text=(
                    f":white_check_mark: Recorded {len(created_ids)} decisions:\n{titles_text}"
                ),
                entity_created=created_ids[0][0] if created_ids else None,
                events_emitted=[e.event_type for e in events],
            )

        return ModeResult(
            response_text="Unknown creation action.",
        )

    def _build_preview_blocks(self, content: dict) -> list[dict]:
        """Build Slack blocks for work item preview."""
        import json

        # Store content as JSON in button values (same pattern as RECORD mode)
        content_json = json.dumps(content)

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
                        "value": content_json,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Edit"},
                        "action_id": "edit_draft",
                        "value": content_json,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Cancel"},
                        "action_id": "cancel_draft",
                        "value": content_json,
                    },
                ],
            },
        ]

    def _build_decisions_preview_blocks(self, decisions: list[dict]) -> list[dict]:
        """Build Slack blocks for multiple decision previews with per-ADR buttons."""
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Draft Decision Records ({len(decisions)} found)",
                },
            },
        ]

        for i, d in enumerate(decisions):
            alts = ""
            if d.get("alternatives_considered"):
                alts = f"\n_Alternatives: {', '.join(d['alternatives_considered'])}_"

            context = ""
            if d.get("context"):
                context = f"\n_Context: {d['context']}_"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{i + 1}. {d['title']}*\n"
                        f"{d['decision']}"
                        f"{context}\n"
                        f"_Rationale: {d['rationale']}_"
                        f"{alts}"
                    ),
                },
            })
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✓ Record"},
                        "style": "primary",
                        "action_id": f"adr_record_{i}",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✎ Edit"},
                        "action_id": f"adr_edit_{i}",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✕ Delete"},
                        "style": "danger",
                        "action_id": f"adr_delete_{i}",
                    },
                ],
            })
            blocks.append({"type": "divider"})

        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Record All Remaining"},
                    "style": "primary",
                    "action_id": "record_all_decisions",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel All"},
                    "action_id": "cancel_decisions",
                },
            ],
        })

        return blocks

    def _build_work_items_preview_blocks(self, work_items: list[dict]) -> list[dict]:
        """Build Slack blocks for multiple work item previews with per-item buttons."""
        import json

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Draft Work Items ({len(work_items)} generated)",
                },
            },
        ]

        for i, w in enumerate(work_items):
            ac_text = ""
            if w.get("acceptance_criteria"):
                ac_items = "\n".join(f"  \u2022 {ac}" for ac in w["acceptance_criteria"])
                ac_text = f"\n_Acceptance Criteria:_\n{ac_items}"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{i + 1}. {w['title']}*\n"
                        f"Type: {w.get('issue_type', 'story').title()}\n"
                        f"{w.get('description', '')[:500]}"
                        f"{ac_text}"
                    ),
                },
            })
            # Truncate button value to stay within Slack's 2000 char limit
            compact_item = {
                "title": w["title"][:200],
                "issue_type": w.get("issue_type", "story"),
                "description": w.get("description", "")[:500],
                "acceptance_criteria": [ac[:100] for ac in w.get("acceptance_criteria", [])[:5]],
                "constraints": [c[:100] for c in w.get("constraints", [])[:3]],
            }
            content_json = json.dumps(compact_item)
            # Final safety: if still over limit, strip description further
            if len(content_json) > 1900:
                compact_item["description"] = compact_item["description"][:200]
                compact_item["acceptance_criteria"] = compact_item["acceptance_criteria"][:3]
                content_json = json.dumps(compact_item)

            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Propose"},
                        "style": "primary",
                        "action_id": f"wi_propose_{i}",
                        "value": content_json,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Delete"},
                        "style": "danger",
                        "action_id": f"wi_delete_{i}",
                        "value": content_json,
                    },
                ],
            })
            blocks.append({"type": "divider"})

        # Global actions — value is just a marker; handler extracts data
        # from per-item buttons to avoid Slack's 2000 char value limit
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Propose All"},
                    "style": "primary",
                    "action_id": "propose_all_work_items",
                    "value": "propose_all",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel All"},
                    "action_id": "cancel_all_work_items",
                    "value": "cancel",
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
