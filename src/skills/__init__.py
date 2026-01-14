"""Skills - deterministic functions for agent actions.

Skills are async functions with explicit parameters (not graph nodes).
Each skill has clear input/output contracts.

Skills:
- ask_user: Post questions to Slack thread, handle interrupt/resume
- answer_matcher: Semantic matching of user responses to questions
- preview_ticket: Show draft for approval with version checking
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

from src.skills.preview_ticket import (
    preview_ticket,
    PreviewResult,
    compute_draft_hash,
)

__all__ = [
    # ask_user skill
    "ask_user",
    "QuestionSet",
    "AskResult",
    "QuestionStatus",
    # answer_matcher skill
    "match_answers",
    "AnswerMatch",
    "MatchResult",
    # preview_ticket skill
    "preview_ticket",
    "PreviewResult",
    "compute_draft_hash",
]
