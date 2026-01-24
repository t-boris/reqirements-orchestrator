"""Question Catalog with hybrid question generators.

Phase 36: Question Engine - Conversation Driver

This module provides:
- Template-based generators for deterministic questions (CONFIRM_SCOPE, RESOLVE_CONFLICT)
- LLM-based generator for flexible field collection (COLLECT_FIELD)
- Freeform fallback for unknown patterns (ASK_USER)

The QuestionCatalog facade provides a unified interface routing to appropriate generators.
"""
from typing import Any, Optional

from src.schemas.question import QuestionOption, QuestionTask, QuestionType


class ScopeQuestionTemplates:
    """Templates for scope confirmation questions.

    These templates generate deterministic questions for common scope patterns:
    - Parent selection (which Epic to create stories under)
    - Draft scope (epics only vs full plan)
    - Generation mode (how to generate stories)
    """

    @staticmethod
    def parent_selection(parent_key: str, parent_summary: str) -> QuestionTask:
        """Template: 'Stories only under {parent}?'

        Args:
            parent_key: The Jira key of the parent (e.g., 'PROJ-123').
            parent_summary: Summary text of the parent issue.

        Returns:
            QuestionTask for confirming parent selection.
        """
        return QuestionTask(
            question_type=QuestionType.CONFIRM_SCOPE,
            question_text=f"Creating stories under {parent_key}. Confirm scope:",
            target_field="parent_key",
            options=[
                QuestionOption(
                    option_id="confirm_parent",
                    label=f"Yes, under {parent_key}",
                    description=parent_summary[:100] if parent_summary else "",
                    value=parent_key,
                    is_recommended=True,
                ),
                QuestionOption(
                    option_id="different_parent",
                    label="Different parent",
                    description="Choose another Epic or create new",
                    value=None,
                ),
                QuestionOption(
                    option_id="new_epic",
                    label="Create new Epic first",
                    description="Start with a new Epic",
                    value="NEW_EPIC",
                ),
            ],
        )

    @staticmethod
    def draft_scope(current_scope: str) -> QuestionTask:
        """Template: 'Epics only or full plan?'

        Args:
            current_scope: Current scope setting (e.g., 'SINGLE', 'EPIC', 'FULL').

        Returns:
            QuestionTask for confirming draft scope.
        """
        options = [
            QuestionOption(
                option_id="single_story",
                label="Single story",
                description="Just this one story",
                value="SINGLE",
                is_recommended=current_scope == "SINGLE",
            ),
            QuestionOption(
                option_id="epics_only",
                label="Epics only",
                description="Create epics without stories",
                value="EPIC",
                is_recommended=current_scope == "EPIC",
            ),
            QuestionOption(
                option_id="full_plan",
                label="Full plan",
                description="Create epics with stories underneath",
                value="FULL",
                is_recommended=current_scope == "FULL",
            ),
        ]
        return QuestionTask(
            question_type=QuestionType.CONFIRM_SCOPE,
            question_text="What scope should I create?",
            target_field="draft_scope",
            options=options,
        )

    @staticmethod
    def generation_mode() -> QuestionTask:
        """Template: 'How should I generate stories?'

        Returns:
            QuestionTask for selecting story generation mode.
        """
        return QuestionTask(
            question_type=QuestionType.CONFIRM_SCOPE,
            question_text="How should I generate stories?",
            target_field="generation_mode",
            options=[
                QuestionOption(
                    option_id="suggest_workstreams",
                    label="Suggest 5-7 workstreams",
                    description="I'll categorize the work into logical groups",
                    value="SUGGEST_WORKSTREAMS",
                    is_recommended=True,
                ),
                QuestionOption(
                    option_id="give_titles",
                    label="Give me titles",
                    description="You provide specific story titles",
                    value="USER_TITLES",
                ),
                QuestionOption(
                    option_id="infer_decisions",
                    label="Infer from decisions",
                    description="Derive stories from existing decisions",
                    value="FROM_DECISIONS",
                ),
            ],
        )


class ConflictQuestionTemplates:
    """Templates for conflict resolution questions.

    These templates generate deterministic questions for sync conflicts
    between local (Slack) and remote (Jira) values.
    """

    @staticmethod
    def field_conflict(field: str, local_value: str, remote_value: str) -> QuestionTask:
        """Template: 'A or B?' for sync conflicts.

        Args:
            field: The field name with conflicting values.
            local_value: The value from Slack/local source.
            remote_value: The value from Jira/remote source.

        Returns:
            QuestionTask for resolving the conflict.
        """
        return QuestionTask(
            question_type=QuestionType.RESOLVE_CONFLICT,
            question_text=f"Conflict on {field}. Which version to keep?",
            target_field=field,
            options=[
                QuestionOption(
                    option_id="keep_local",
                    label="Keep Slack version",
                    description=local_value[:100] if local_value else "",
                    value=local_value,
                ),
                QuestionOption(
                    option_id="keep_remote",
                    label="Keep Jira version",
                    description=remote_value[:100] if remote_value else "",
                    value=remote_value,
                ),
            ],
        )


class FieldQuestionGenerator:
    """LLM-based question generation for field collection.

    Uses LLM to generate natural, conversational questions for collecting
    specific field values. Includes field-specific guidance prompts.
    """

    FIELD_PROMPTS: dict[str, str] = {
        "acceptance_criteria": "Ask for specific, testable acceptance criteria. Don't be abstract.",
        "title": "Ask for a clear, action-oriented title. Keep it concise.",
        "problem": "Ask what problem we're solving. Focus on impact.",
        "proposed_solution": "Ask how they envision solving this. Be specific.",
        "description": "Ask for a detailed description of the work. Focus on what needs to be done.",
        "priority": "Ask how urgent or important this work is relative to other items.",
        "story_points": "Ask for an estimate of effort or complexity.",
        "assignee": "Ask who should work on this.",
        "labels": "Ask for any tags or categories to apply.",
    }

    # Cache for repeated field questions to avoid asking the same thing twice
    _field_question_cache: dict[str, str] = {}

    @staticmethod
    async def generate(
        field: str,
        draft_context: dict[str, Any],
        llm: Any,
    ) -> QuestionTask:
        """Generate field-specific question using LLM.

        Args:
            field: The field name to collect (e.g., 'acceptance_criteria').
            draft_context: Current draft context with existing field values.
            llm: LLM client instance (UnifiedChatClient).

        Returns:
            QuestionTask with LLM-generated question text.
        """
        # Check cache first
        cache_key = f"{field}:{draft_context.get('title', '')}"
        if cache_key in FieldQuestionGenerator._field_question_cache:
            question_text = FieldQuestionGenerator._field_question_cache[cache_key]
        else:
            prompt = FieldQuestionGenerator._build_prompt(field, draft_context)
            question_text = await llm.chat(prompt)
            question_text = question_text.strip()
            # Cache for future use
            FieldQuestionGenerator._field_question_cache[cache_key] = question_text

        return QuestionTask(
            question_type=QuestionType.COLLECT_FIELD,
            question_text=question_text,
            target_field=field,
            options=None,  # Free-form response expected
        )

    @staticmethod
    def _build_prompt(field: str, context: dict[str, Any]) -> str:
        """Build LLM prompt for question generation.

        Args:
            field: The field name to collect.
            context: Current draft context.

        Returns:
            Formatted prompt string for the LLM.
        """
        guidance = FieldQuestionGenerator.FIELD_PROMPTS.get(field, "Ask for this field.")
        return f'''Generate a natural, conversational question to collect the "{field}" for a Jira ticket.

Guidance: {guidance}

Current draft context:
- Title: {context.get('title', 'Not set')}
- Type: {context.get('issue_type', 'Story')}

Requirements:
1. One short question (max 15 words)
2. Conversational, not formal
3. No markdown formatting
4. End with question mark

Question:'''


class QuestionCatalog:
    """Unified interface for question generation.

    Routes to appropriate generator based on question type:
    - CONFIRM_SCOPE: Templates (deterministic)
    - COLLECT_FIELD: LLM-generated (flexible)
    - RESOLVE_CONFLICT: Templates (deterministic)
    - ASK_USER: LLM fallback (freeform)
    """

    @staticmethod
    def confirm_scope(context: dict[str, Any], template: str = "generation_mode") -> QuestionTask:
        """Generate scope confirmation question using templates.

        Args:
            context: Context dict with relevant fields for the template.
            template: Template name ('parent_selection', 'draft_scope', or 'generation_mode').

        Returns:
            QuestionTask for scope confirmation.
        """
        if template == "parent_selection":
            return ScopeQuestionTemplates.parent_selection(
                context["parent_key"],
                context.get("parent_summary", ""),
            )
        elif template == "draft_scope":
            return ScopeQuestionTemplates.draft_scope(context.get("current_scope", "SINGLE"))
        else:
            return ScopeQuestionTemplates.generation_mode()

    @staticmethod
    async def collect_field(
        field: str,
        draft_context: dict[str, Any],
        llm: Optional[Any] = None,
    ) -> QuestionTask:
        """Generate field collection question using LLM.

        Args:
            field: The field name to collect.
            draft_context: Current draft context.
            llm: Optional LLM client. If not provided, uses default.

        Returns:
            QuestionTask for field collection.
        """
        if llm is None:
            from src.llm import get_llm
            llm = get_llm()
        return await FieldQuestionGenerator.generate(field, draft_context, llm)

    @staticmethod
    def resolve_conflict(
        field: str,
        local_value: str,
        remote_value: str,
    ) -> QuestionTask:
        """Generate conflict resolution question using template.

        Args:
            field: The field name with conflict.
            local_value: Value from Slack/local source.
            remote_value: Value from Jira/remote source.

        Returns:
            QuestionTask for conflict resolution.
        """
        return ConflictQuestionTemplates.field_conflict(field, local_value, remote_value)

    @staticmethod
    async def ask_user(
        context: str,
        llm: Optional[Any] = None,
    ) -> QuestionTask:
        """Fallback: generate freeform question when no template fits.

        Args:
            context: Description of what we need to clarify.
            llm: Optional LLM client. If not provided, uses default.

        Returns:
            QuestionTask for freeform user input.
        """
        if llm is None:
            from src.llm import get_llm
            llm = get_llm()

        prompt = f'''Generate a simple clarifying question for this context:

{context}

Requirements:
1. One short question (max 20 words)
2. Conversational
3. Helps move the conversation forward

Question:'''

        question_text = await llm.chat(prompt)
        return QuestionTask(
            question_type=QuestionType.ASK_USER,
            question_text=question_text.strip(),
            target_field=None,
            options=None,
        )
