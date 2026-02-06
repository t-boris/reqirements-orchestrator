"""JIRA mode handler.

Routes Jira-related questions to real Jira API calls via two-phase LLM flow:
1. Extract operation + parameters from user message (structured output)
2. Execute the Jira API call
3. Format results for Slack (structured output)

Read-only operations (search, get) execute immediately.
Write operations (update, comment) require confirmation before executing.
"""

import json
import logging
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from src.config import get_settings
from src.jira.factory import get_jira_client
from src.llm.client import structured_completion
from src.modes.base import ModeHandler, ModeContext, ModeResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 1 schemas — extract operation from user message
# ---------------------------------------------------------------------------

class JiraOperation(str, Enum):
    SEARCH = "search"
    GET = "get"
    UPDATE = "update"
    COMMENT = "comment"


class JiraIntent(BaseModel):
    """Structured extraction of the user's Jira intent."""

    operation: JiraOperation
    jql: str | None = Field(
        default=None, description="JQL query for search operations"
    )
    issue_key: str | None = Field(
        default=None, description="Issue key for get/update/comment (e.g. PROJ-123)"
    )
    fields: dict | None = Field(
        default=None, description="Field changes for update operations"
    )
    comment_text: str | None = Field(
        default=None, description="Comment body for comment operations"
    )
    explanation: str = Field(description="Why this operation was chosen")


EXTRACT_SYSTEM = """You extract structured Jira operations from user messages.

The default Jira project is {project_key}.

Rules:
- For search: generate proper JQL. Examples:
  - "what epics do we have?" → project = {project_key} AND type = Epic AND status != Done
  - "find open bugs" → project = {project_key} AND type = Bug AND status != Done
  - "issues assigned to me" → project = {project_key} AND assignee = currentUser()
  - If the user doesn't specify a project, default to {project_key}
- For get: extract the issue key exactly as mentioned (e.g. SCRUM-123)
- For update: extract the issue key and map requested changes to Jira field names
- For comment: extract the issue key and the comment text
- If the user references a previous message in thread context, use that context
- Always prefer search over get when the user asks a broad question"""

EXTRACT_USER = """Thread context:
{thread_context}

User message:
"{message}"

Extract the Jira operation."""


# ---------------------------------------------------------------------------
# Phase 3 schemas — format results for Slack
# ---------------------------------------------------------------------------

class FollowUpOption(BaseModel):
    label: str = Field(description="Short button label, max 75 chars")
    description: str = Field(description="What this option means")


class FollowUpQuestion(BaseModel):
    question_text: str = Field(description="The question to ask the user")
    question_type: Literal["choice", "confirmation", "open_ended"] = Field(
        description="choice = buttons, confirmation = yes/no, open_ended = free text"
    )
    options: list[FollowUpOption] = Field(
        default_factory=list,
        description="Options for choice/confirmation types. Empty for open_ended.",
    )
    priority: int = Field(
        default=0, description="Higher priority questions asked first"
    )


class JiraResponse(BaseModel):
    """LLM-formatted Slack response from Jira results."""

    response: str = Field(description="Slack mrkdwn formatted response")
    follow_up_questions: list[FollowUpQuestion] = Field(
        default_factory=list,
        description="Optional follow-up questions for the user",
    )


FORMAT_SYSTEM = """You format Jira API results into a concise Slack message.

Jira base URL: {jira_url}
Build links as: <{jira_url}/browse/KEY|KEY>

CRITICAL formatting rules (Slack mrkdwn, NOT standard markdown):
- Bold: *text* (single asterisks, NEVER **double**)
- Italic: _text_ (underscores)
- Code: `text` or ```block```
- Bullet points: • or - at line start
- Links: <url|label>
- NEVER use **double asterisks** — Slack renders them literally
- NEVER use # headings — Slack doesn't support them
- NEVER use --- horizontal rules

Rules:
- Only use data from the provided results. NEVER invent issue keys, titles, or data.
- Keep the response concise — this is Slack, not an essay.
- For search results, show a summary list with key, summary, status, and assignee.
- For single issue, show key details: summary, status, type, assignee, description excerpt.
- If there are no results, say so clearly.
- Maximum 2 follow-up questions per response."""

FORMAT_USER = """User's original question:
"{message}"

Jira API results ({operation}):
{results_json}

Format these results for Slack."""


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class JiraModeHandler(ModeHandler):
    """Handler for JIRA mode.

    Two-phase LLM flow:
    1. Extract operation + params from user message
    2. Execute Jira API call
    3. Format results as Slack mrkdwn
    """

    @property
    def mode_name(self) -> str:
        return "JIRA"

    async def handle(self, context: ModeContext) -> ModeResult:
        from src.infrastructure.channel_config import get_jira_project

        settings = get_settings()
        jira_url = settings.jira_url

        # Get channel-specific Jira project or fall back to default
        channel_project = await get_jira_project(context.channel_id)
        project_key = channel_project or settings.jira_default_project

        logger.info(
            f"JIRA mode: user={context.user_id}, "
            f"confidence={context.intent.confidence}"
        )

        # Build thread context
        thread_context = "(No thread history)"
        if context.thread_messages:
            thread_context = "\n".join(
                f"{'Bot' if m['role'] == 'assistant' else 'User'}: {m['content']}"
                for m in context.thread_messages
            )

        # Phase 1: Extract operation
        try:
            intent = await structured_completion(
                response_model=JiraIntent,
                messages=[
                    {
                        "role": "system",
                        "content": EXTRACT_SYSTEM.format(project_key=project_key),
                    },
                    {
                        "role": "user",
                        "content": EXTRACT_USER.format(
                            thread_context=thread_context,
                            message=context.message,
                        ),
                    },
                ],
            )
        except Exception as e:
            logger.error(f"Failed to extract Jira intent: {e}")
            return ModeResult(
                response_text="I couldn't understand that Jira request. Could you rephrase?",
            )

        logger.info(
            f"Jira intent: operation={intent.operation}, "
            f"key={intent.issue_key}, jql={intent.jql}"
        )

        # Phase 2: Execute Jira operation
        # Write operations require confirmation
        if intent.operation in (JiraOperation.UPDATE, JiraOperation.COMMENT):
            return self._build_confirmation(intent)

        # Read operations execute immediately
        try:
            results, operation_label = await self._execute(intent)
        except Exception as e:
            return self._handle_error(e)

        # Phase 3: Format results for Slack
        return await self._format_results(
            context.message, operation_label, results, jira_url
        )

    async def handle_confirmed(
        self, context: ModeContext, confirmation_data: dict
    ) -> ModeResult:
        """Execute a previously confirmed write operation."""
        settings = get_settings()
        jira_url = settings.jira_url

        intent = JiraIntent(**confirmation_data["intent"])

        try:
            results, operation_label = await self._execute(intent)
        except Exception as e:
            return self._handle_error(e)

        return await self._format_results(
            confirmation_data["original_message"],
            operation_label,
            results,
            jira_url,
        )

    # -- private helpers -----------------------------------------------------

    def _build_confirmation(self, intent: JiraIntent) -> ModeResult:
        """Build a confirmation prompt for write operations."""
        if intent.operation == JiraOperation.UPDATE:
            desc = (
                f"Update *{intent.issue_key}* with fields: "
                f"`{json.dumps(intent.fields, default=str)}`"
            )
        else:
            desc = f"Add a comment to *{intent.issue_key}*"

        return ModeResult(
            response_text=f"I'll {intent.operation.value} this issue. Please confirm:\n{desc}",
            requires_confirmation=True,
            confirmation_data={
                "mode": "jira",
                "intent": intent.model_dump(mode="json"),
                "original_message": "",
            },
        )

    async def _execute(
        self, intent: JiraIntent
    ) -> tuple[list | dict | str, str]:
        """Execute the Jira API call and return (results, label)."""
        jira = get_jira_client()

        if intent.operation == JiraOperation.SEARCH:
            issues = await jira.search(intent.jql, max_results=20)
            return issues, "search"

        if intent.operation == JiraOperation.GET:
            issue = await jira.get_issue(intent.issue_key)
            return issue, "get"

        if intent.operation == JiraOperation.UPDATE:
            await jira.update_issue(intent.issue_key, intent.fields or {})
            return f"Updated {intent.issue_key}", "update"

        if intent.operation == JiraOperation.COMMENT:
            await jira.add_comment(intent.issue_key, intent.comment_text or "")
            return f"Comment added to {intent.issue_key}", "comment"

        raise ValueError(f"Unknown operation: {intent.operation}")

    async def _format_results(
        self,
        original_message: str,
        operation: str,
        results: list | dict | str,
        jira_url: str,
    ) -> ModeResult:
        """Phase 3: Use LLM to format results for Slack."""
        # Serialize results for the LLM
        if isinstance(results, str):
            results_json = results
        else:
            results_json = json.dumps(results, default=str, indent=2)

        # Truncate very large results to avoid blowing up the context
        if len(results_json) > 15000:
            results_json = results_json[:15000] + "\n... (truncated)"

        try:
            formatted = await structured_completion(
                response_model=JiraResponse,
                messages=[
                    {
                        "role": "system",
                        "content": FORMAT_SYSTEM.format(jira_url=jira_url),
                    },
                    {
                        "role": "user",
                        "content": FORMAT_USER.format(
                            message=original_message,
                            operation=operation,
                            results_json=results_json,
                        ),
                    },
                ],
            )
            response_text = formatted.response
            follow_up_questions = formatted.follow_up_questions
        except Exception as e:
            logger.warning(f"LLM formatting failed, returning raw summary: {e}")
            response_text = f"Jira {operation} completed. Raw result:\n```{results_json[:2000]}```"
            follow_up_questions = []

        # Build Slack blocks with buttons if there are follow-up questions
        response_blocks = None
        if follow_up_questions:
            from src.slack.blocks.questions import build_question_blocks

            response_blocks = build_question_blocks(
                response_text=response_text,
                questions=follow_up_questions,
                thread_ts=None,
            )

        return ModeResult(
            response_text=response_text,
            response_blocks=response_blocks,
        )

    def _handle_error(self, error: Exception) -> ModeResult:
        """Convert Jira API errors to user-friendly messages."""
        error_str = str(error).lower()
        logger.error(f"Jira API error: {error}")

        if "401" in error_str or "403" in error_str or "permission" in error_str:
            return ModeResult(
                response_text="I don't have permission to do that in Jira. "
                "Check the bot's Jira permissions.",
            )
        if "404" in error_str or "not found" in error_str:
            return ModeResult(
                response_text="That issue wasn't found in Jira. "
                "Double-check the issue key and try again.",
            )
        if "429" in error_str or "rate limit" in error_str:
            return ModeResult(
                response_text="Jira is rate-limiting me right now. Please try again in a moment.",
            )
        return ModeResult(
            response_text=f"Couldn't complete the Jira operation: {error}",
        )
