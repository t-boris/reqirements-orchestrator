"""Jira search skill for duplicate detection.

Fast JQL search returning compact results for duplicate detection.
Serves as "last defense" before ticket creation.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from src.jira.client import JiraService
from src.jira.types import JiraIssue
from src.schemas.draft import TicketDraft


logger = logging.getLogger(__name__)


@dataclass
class JiraSearchResult:
    """Result of Jira search operation."""

    issues: list[JiraIssue]
    total_count: int
    query: str  # JQL used (for logging/debugging)


async def jira_search(
    query: str,
    jira_service: JiraService,
    project: Optional[str] = None,
    limit: int = 5,
) -> JiraSearchResult:
    """Search for Jira issues using text query.

    Builds JQL query with text search, optional project filter,
    and excludes closed/done tickets.

    Args:
        query: Text to search for in summary and description.
        jira_service: JiraService instance for API calls.
        project: Optional project key to filter by.
        limit: Maximum number of results (default 5).

    Returns:
        JiraSearchResult with matching issues and query info.
    """
    # Build JQL query
    # Escape special characters in query for JQL text search
    escaped_query = query.replace('"', '\\"')
    jql_parts = [f'text ~ "{escaped_query}"']

    if project:
        jql_parts.append(f'project = "{project}"')

    # Exclude closed/done tickets
    jql_parts.append("status NOT IN (Done, Closed, Resolved)")

    # Order by relevance (Jira's default for text search) and recency
    jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"

    logger.info(
        "Searching for potential duplicates",
        extra={
            "query_text": query[:100],
            "project": project,
            "jql": jql,
        },
    )

    try:
        issues = await jira_service.search_issues(jql, limit=limit)
        return JiraSearchResult(
            issues=issues,
            total_count=len(issues),
            query=jql,
        )
    except Exception as e:
        # Log error but don't fail the workflow - duplicates are a nice-to-have
        logger.warning(
            f"Failed to search for duplicates: {e}",
            extra={
                "error": str(e),
                "query": query[:100],
            },
        )
        return JiraSearchResult(
            issues=[],
            total_count=0,
            query=jql,
        )


async def search_similar_to_draft(
    draft: TicketDraft,
    jira_service: JiraService,
    limit: int = 5,
) -> JiraSearchResult:
    """Search for tickets similar to draft title.

    Convenience function that extracts search parameters from draft.

    Args:
        draft: TicketDraft to find similar tickets for.
        jira_service: JiraService instance for API calls.
        limit: Maximum number of results (default 5).

    Returns:
        JiraSearchResult with potentially similar tickets.
    """
    # Extract project from epic_id if available
    project = None
    if draft.epic_id:
        # Epic ID format: PROJ-123 -> extract PROJ
        project = draft.epic_id.split("-")[0] if "-" in draft.epic_id else None

    # Use draft title as search query
    query = draft.title

    if not query:
        # Fallback to problem if no title
        query = draft.problem[:100] if draft.problem else ""

    if not query:
        logger.debug("No search query available from draft")
        return JiraSearchResult(
            issues=[],
            total_count=0,
            query="",
        )

    return await jira_search(
        query=query,
        jira_service=jira_service,
        project=project,
        limit=limit,
    )
