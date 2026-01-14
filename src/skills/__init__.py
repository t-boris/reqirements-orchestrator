"""Skills - deterministic functions for agent actions.

Skills are async functions with explicit parameters (not graph nodes).
Each skill has clear input/output contracts.

Skills:
- ask_user: Post questions to Slack thread, handle interrupt/resume
- answer_matcher: Semantic matching of user responses to questions
- preview_ticket: Show draft for approval (Phase 6 plan 2)
"""

from src.skills.ask_user import (
    ask_user,
    QuestionSet,
    AskResult,
    QuestionStatus,
)

from src.skills.answer_matcher import (
    match_answers,
    AnswerMatch,
    MatchResult,
)

__all__ = [
    "ask_user",
    "QuestionSet",
    "AskResult",
    "QuestionStatus",
    "match_answers",
    "AnswerMatch",
    "MatchResult",
]
