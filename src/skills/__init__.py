"""Skills - deterministic functions for agent actions.

Skills are async functions with explicit parameters (not graph nodes).
Each skill has clear input/output contracts.

Skills:
- ask_user: Post questions to Slack thread, handle interrupt/resume
- answer_matcher: Semantic matching of user responses to questions
- preview_ticket: Show draft for approval with version checking
- jira_search: Fast duplicate detection before ticket creation
- jira_create: Create Jira ticket with strict approval validation
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

from src.skills.jira_search import (
    jira_search,
    search_similar_to_draft,
    JiraSearchResult,
)

from src.skills.jira_create import (
    jira_create,
    JiraCreateResult,
)

from src.skills.dispatcher import SkillDispatcher

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
    # jira_search skill
    "jira_search",
    "search_similar_to_draft",
    "JiraSearchResult",
    # jira_create skill
    "jira_create",
    "JiraCreateResult",
    # dispatcher
    "SkillDispatcher",
]
