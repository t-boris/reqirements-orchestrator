"""TriageProvider - Generates targeted clarifying questions based on triage gaps.

Phase 44: Questions-First Collection Stage

Transforms triage gaps into actionable button-based questions using existing
Question Engine patterns. No LLM dependency - deterministic template questions.
"""
from enum import Enum
from typing import Any

from src.schemas.question import QuestionOption, QuestionTask, QuestionType


class TriageGap(str, Enum):
    """Gaps identified during triage - what's missing from context.

    Each gap maps to a specific clarifying question.
    """
    UNKNOWN_MODE = "unknown_mode"      # Can't determine BUILD vs THINK vs DECIDE
    UNKNOWN_TARGET = "unknown_target"  # No clear subject (what are we working on?)
    UNKNOWN_SCOPE = "unknown_scope"    # Don't know if epic/story/task
    MISSING_TOPIC = "missing_topic"    # For review, topic unclear
    AMBIGUOUS_INTENT = "ambiguous_intent"  # Multiple interpretations possible


# Gap priorities - lower number = ask first
GAP_PRIORITY = {
    TriageGap.UNKNOWN_MODE: 10,
    TriageGap.UNKNOWN_TARGET: 20,
    TriageGap.UNKNOWN_SCOPE: 30,
    TriageGap.MISSING_TOPIC: 40,
    TriageGap.AMBIGUOUS_INTENT: 50,
}


class TriageProvider:
    """Generates clarifying questions from triage gaps.

    Uses deterministic templates (no LLM) for fast, predictable questions.
    Each gap type has a predefined question with button options.
    """

    def __init__(self) -> None:
        """Initialize TriageProvider."""
        pass

    def get_target_type(self) -> str:
        """Return target state type."""
        return "triage"

    def generate_triage_question(
        self,
        gap: TriageGap,
        context: dict[str, Any],
    ) -> QuestionTask:
        """Generate a clarifying question for a specific triage gap.

        Args:
            gap: The TriageGap to generate a question for
            context: Current state context (may influence question phrasing)

        Returns:
            QuestionTask with appropriate question type and options
        """
        if gap == TriageGap.UNKNOWN_MODE:
            return self._question_unknown_mode(context)
        elif gap == TriageGap.UNKNOWN_TARGET:
            return self._question_unknown_target(context)
        elif gap == TriageGap.UNKNOWN_SCOPE:
            return self._question_unknown_scope(context)
        elif gap == TriageGap.MISSING_TOPIC:
            return self._question_missing_topic(context)
        elif gap == TriageGap.AMBIGUOUS_INTENT:
            return self._question_ambiguous_intent(context)
        else:
            # Fallback for unknown gaps
            return QuestionTask(
                question_type=QuestionType.ASK_USER,
                question_text="Could you tell me more about what you need?",
                target_field="triage.clarification",
            )

    def get_next_question(
        self,
        gaps: set[TriageGap],
        context: dict[str, Any],
    ) -> QuestionTask | None:
        """Get the highest priority question for the given gaps.

        Args:
            gaps: Set of TriageGaps detected
            context: Current state context

        Returns:
            QuestionTask for highest priority gap, or None if no gaps
        """
        if not gaps:
            return None

        # Sort gaps by priority (lowest priority number first)
        sorted_gaps = sorted(gaps, key=lambda g: GAP_PRIORITY.get(g, 100))

        # Return question for highest priority gap
        return self.generate_triage_question(sorted_gaps[0], context)

    def _question_unknown_mode(self, context: dict[str, Any]) -> QuestionTask:
        """Generate question for UNKNOWN_MODE gap."""
        return QuestionTask(
            question_type=QuestionType.CONFIRM_SCOPE,
            question_text="What would you like me to help with?",
            target_field="triage.mode_hint",
            options=[
                QuestionOption(
                    option_id="mode_build",
                    label="Build work items",
                    value="build",
                    description="Create epics, stories, or tasks in Jira",
                ),
                QuestionOption(
                    option_id="mode_think",
                    label="Architecture review",
                    value="think",
                    description="Get analysis and recommendations",
                ),
                QuestionOption(
                    option_id="mode_decide",
                    label="Record a decision",
                    value="decide",
                    description="Capture and track a decision",
                ),
                QuestionOption(
                    option_id="mode_chat",
                    label="Just chatting",
                    value="chat",
                    description="General conversation",
                ),
            ],
        )

    def _question_unknown_target(self, context: dict[str, Any]) -> QuestionTask:
        """Generate question for UNKNOWN_TARGET gap."""
        return QuestionTask(
            question_type=QuestionType.CONFIRM_SCOPE,
            question_text="What is this request about?",
            target_field="triage.target_hint",
            options=[
                QuestionOption(
                    option_id="target_jira_ref",
                    label="Existing ticket",
                    value="jira_ref",
                    description="Reference to a Jira issue (paste the key)",
                ),
                QuestionOption(
                    option_id="target_new_idea",
                    label="New idea",
                    value="new_idea",
                    description="Something we haven't tracked yet",
                ),
                QuestionOption(
                    option_id="target_prior_context",
                    label="Previous discussion",
                    value="prior_context",
                    description="Continuing an earlier thread",
                ),
            ],
        )

    def _question_unknown_scope(self, context: dict[str, Any]) -> QuestionTask:
        """Generate question for UNKNOWN_SCOPE gap."""
        return QuestionTask(
            question_type=QuestionType.CONFIRM_SCOPE,
            question_text="What type of work item should this be?",
            target_field="triage.scope_hint",
            options=[
                QuestionOption(
                    option_id="scope_epic",
                    label="Epic",
                    value="epic",
                    description="Large initiative with multiple stories",
                    is_recommended=True,
                ),
                QuestionOption(
                    option_id="scope_story",
                    label="Story",
                    value="story",
                    description="User-facing feature",
                ),
                QuestionOption(
                    option_id="scope_task",
                    label="Task",
                    value="task",
                    description="Technical work item",
                ),
                QuestionOption(
                    option_id="scope_bug",
                    label="Bug",
                    value="bug",
                    description="Something that needs fixing",
                ),
            ],
        )

    def _question_missing_topic(self, context: dict[str, Any]) -> QuestionTask:
        """Generate question for MISSING_TOPIC gap.

        Uses ASK_USER (text input) since topic needs free-form input.
        """
        return QuestionTask(
            question_type=QuestionType.ASK_USER,
            question_text="What topic should I focus on?",
            target_field="triage.topic",
            options=None,  # Text input, not buttons
        )

    def _question_ambiguous_intent(self, context: dict[str, Any]) -> QuestionTask:
        """Generate question for AMBIGUOUS_INTENT gap.

        Uses ASK_USER (text input) for open clarification.
        """
        return QuestionTask(
            question_type=QuestionType.ASK_USER,
            question_text="I want to make sure I understand. Can you tell me more about what you need?",
            target_field="triage.clarification",
            options=None,  # Text input, not buttons
        )
