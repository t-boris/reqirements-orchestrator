"""
Jira MCP Client - Integration with Jira via Model Context Protocol.

Uses langchain-mcp-adapters to connect to the jira-mcp server (cosmix/jira-mcp).
Provides async methods for CRUD operations on Jira issues.
"""

import json
from typing import Any

import structlog
from langchain_core.tools import BaseTool

from src.config.settings import get_settings

logger = structlog.get_logger()
settings = get_settings()


# =============================================================================
# MCP Client Singleton
# =============================================================================

_client: "JiraMCPClient | None" = None
_tools: dict[str, BaseTool] = {}


async def get_jira_client() -> "JiraMCPClient":
    """
    Get or create the singleton Jira MCP client.

    Initializes connection to the MCP server and loads available tools.

    Returns:
        JiraMCPClient instance.
    """
    global _client, _tools

    if _client is None:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        # Connect to the Jira MCP server
        mcp_client = MultiServerMCPClient(
            {
                "jira": {
                    "url": settings.jira_mcp_url,
                    "transport": "sse",  # Server-Sent Events transport
                }
            }
        )

        # Get available tools from the MCP server
        tools = await mcp_client.get_tools()

        # Index tools by name for easy access
        for tool in tools:
            _tools[tool.name] = tool

        _client = JiraMCPClient(mcp_client, _tools)
        logger.info(
            "jira_mcp_client_initialized",
            url=settings.jira_mcp_url,
            tool_count=len(tools),
        )

    return _client


# =============================================================================
# Jira MCP Client
# =============================================================================


class JiraMCPClient:
    """
    Client wrapper for Jira operations via MCP.

    Provides typed methods for common Jira operations using MCP tools.
    """

    def __init__(self, mcp_client: Any, tools: dict[str, BaseTool]):
        """
        Initialize the Jira MCP client.

        Args:
            mcp_client: The underlying MCP client.
            tools: Dictionary of available tools from MCP server.
        """
        self.mcp_client = mcp_client
        self.tools = tools

    async def _call_tool(self, tool_name: str, **kwargs) -> dict[str, Any]:
        """
        Call an MCP tool with the given arguments.

        Args:
            tool_name: Name of the MCP tool to call.
            **kwargs: Arguments to pass to the tool.

        Returns:
            Tool result as a dictionary.

        Raises:
            ValueError: If tool is not available.
        """
        if tool_name not in self.tools:
            available = ", ".join(self.tools.keys())
            raise ValueError(f"Tool '{tool_name}' not available. Available: {available}")

        tool = self.tools[tool_name]

        logger.debug("calling_mcp_tool", tool=tool_name, args=kwargs)

        result = await tool.ainvoke(kwargs)

        # Parse result if it's a JSON string
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                result = {"raw": result}

        logger.debug("mcp_tool_result", tool=tool_name, result_type=type(result).__name__)

        return result

    # =========================================================================
    # Issue CRUD Operations
    # =========================================================================

    async def create_issue(
        self,
        project_key: str,
        issue_type: str,
        summary: str,
        description: str | None = None,
        priority: str = "Medium",
        labels: list[str] | None = None,
        parent_key: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new Jira issue.

        Args:
            project_key: Jira project key (e.g., "MARO").
            issue_type: Issue type (Epic, Story, Task, Sub-task, Bug).
            summary: Issue title/summary.
            description: Issue description (supports Jira wiki markup).
            priority: Priority level (Lowest, Low, Medium, High, Highest).
            labels: List of labels to apply.
            parent_key: Parent issue key (for sub-tasks or stories under epics).
            custom_fields: Additional custom field values.

        Returns:
            Created issue data including key and id.
        """
        fields = {
            "project": {"key": project_key},
            "issuetype": {"name": issue_type},
            "summary": summary,
        }

        if description:
            fields["description"] = description

        if priority:
            fields["priority"] = {"name": priority}

        if labels:
            fields["labels"] = labels

        if parent_key:
            # For sub-tasks, use parent field
            if issue_type.lower() == "sub-task":
                fields["parent"] = {"key": parent_key}
            # For stories under epics, use custom field (varies by Jira instance)
            else:
                fields["customfield_10014"] = parent_key  # Epic Link field

        if custom_fields:
            fields.update(custom_fields)

        result = await self._call_tool(
            "jira_create_issue",
            fields=json.dumps(fields),
        )

        logger.info(
            "jira_issue_created",
            key=result.get("key"),
            project=project_key,
            type=issue_type,
        )

        return result

    async def update_issue(
        self,
        issue_key: str,
        summary: str | None = None,
        description: str | None = None,
        priority: str | None = None,
        labels: list[str] | None = None,
        status: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Update an existing Jira issue.

        Args:
            issue_key: Issue key (e.g., "MARO-123").
            summary: New summary/title.
            description: New description.
            priority: New priority.
            labels: New labels (replaces existing).
            status: New status (triggers transition).
            custom_fields: Additional custom field values.

        Returns:
            Updated issue data.
        """
        fields = {}

        if summary:
            fields["summary"] = summary

        if description:
            fields["description"] = description

        if priority:
            fields["priority"] = {"name": priority}

        if labels is not None:
            fields["labels"] = labels

        if custom_fields:
            fields.update(custom_fields)

        # Update fields
        if fields:
            await self._call_tool(
                "jira_update_issue",
                issue_key=issue_key,
                fields=json.dumps(fields),
            )

        # Handle status transition separately
        if status:
            await self._transition_issue(issue_key, status)

        logger.info("jira_issue_updated", key=issue_key)

        # Return fresh issue data
        return await self.get_issue(issue_key)

    async def get_issue(self, issue_key: str) -> dict[str, Any]:
        """
        Get a Jira issue by key.

        Args:
            issue_key: Issue key (e.g., "MARO-123").

        Returns:
            Issue data including all fields.
        """
        result = await self._call_tool(
            "jira_get_issue",
            issue_key=issue_key,
        )

        logger.debug("jira_issue_fetched", key=issue_key)

        return result

    async def search_issues(
        self,
        jql: str,
        max_results: int = 50,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for issues using JQL.

        Args:
            jql: JQL query string.
            max_results: Maximum number of results.
            fields: List of fields to include (default: key, summary, status).

        Returns:
            List of matching issues.
        """
        result = await self._call_tool(
            "jira_search",
            jql=jql,
            max_results=max_results,
            fields=",".join(fields) if fields else "key,summary,status,issuetype",
        )

        issues = result.get("issues", [])
        logger.debug("jira_search_complete", jql=jql[:50], count=len(issues))

        return issues

    async def delete_issue(self, issue_key: str) -> bool:
        """
        Delete a Jira issue.

        Args:
            issue_key: Issue key to delete.

        Returns:
            True if successful.
        """
        await self._call_tool(
            "jira_delete_issue",
            issue_key=issue_key,
        )

        logger.info("jira_issue_deleted", key=issue_key)
        return True

    # =========================================================================
    # Transition and Workflow
    # =========================================================================

    async def _transition_issue(self, issue_key: str, target_status: str) -> bool:
        """
        Transition an issue to a new status.

        Args:
            issue_key: Issue key.
            target_status: Target status name.

        Returns:
            True if successful.
        """
        # Get available transitions
        transitions = await self._call_tool(
            "jira_get_transitions",
            issue_key=issue_key,
        )

        # Find matching transition
        for transition in transitions.get("transitions", []):
            if transition.get("to", {}).get("name", "").lower() == target_status.lower():
                await self._call_tool(
                    "jira_transition_issue",
                    issue_key=issue_key,
                    transition_id=transition["id"],
                )
                logger.info(
                    "jira_issue_transitioned",
                    key=issue_key,
                    status=target_status,
                )
                return True

        logger.warning(
            "jira_transition_not_found",
            key=issue_key,
            target=target_status,
            available=[t.get("name") for t in transitions.get("transitions", [])],
        )
        return False

    # =========================================================================
    # Links and Relationships
    # =========================================================================

    async def link_issues(
        self,
        from_key: str,
        to_key: str,
        link_type: str = "Relates",
    ) -> bool:
        """
        Create a link between two issues.

        Args:
            from_key: Source issue key.
            to_key: Target issue key.
            link_type: Link type (Blocks, Relates, Duplicates, etc.).

        Returns:
            True if successful.
        """
        await self._call_tool(
            "jira_link_issues",
            inward_issue=from_key,
            outward_issue=to_key,
            link_type=link_type,
        )

        logger.info(
            "jira_issues_linked",
            from_key=from_key,
            to_key=to_key,
            type=link_type,
        )
        return True

    # =========================================================================
    # Comments
    # =========================================================================

    async def add_comment(
        self,
        issue_key: str,
        body: str,
    ) -> dict[str, Any]:
        """
        Add a comment to an issue.

        Args:
            issue_key: Issue key.
            body: Comment body (supports Jira wiki markup).

        Returns:
            Created comment data.
        """
        result = await self._call_tool(
            "jira_add_comment",
            issue_key=issue_key,
            body=body,
        )

        logger.debug("jira_comment_added", key=issue_key)
        return result


# =============================================================================
# Utility Functions
# =============================================================================


async def search_related_issues(
    project_key: str,
    keywords: list[str],
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """
    Search for issues related to given keywords.

    Useful for conflict detection and context gathering.

    Args:
        project_key: Jira project key.
        keywords: Keywords to search for.
        max_results: Maximum results.

    Returns:
        List of related issues.
    """
    client = await get_jira_client()

    # Build JQL with text search
    keyword_clause = " OR ".join(f'text ~ "{kw}"' for kw in keywords if kw)
    jql = f'project = "{project_key}" AND ({keyword_clause}) ORDER BY updated DESC'

    try:
        return await client.search_issues(
            jql=jql,
            max_results=max_results,
            fields=["key", "summary", "status", "issuetype", "description"],
        )
    except Exception as e:
        logger.warning("related_issues_search_failed", error=str(e))
        return []


async def sync_issue_to_memory(
    issue_key: str,
    channel_id: str,
) -> dict[str, Any] | None:
    """
    Fetch a Jira issue and update memory with its current state.

    Used for "re-read" functionality.

    Args:
        issue_key: Jira issue key.
        channel_id: Slack channel for memory context.

    Returns:
        Issue data if found.
    """
    from src.memory.zep_client import get_zep_client

    client = await get_jira_client()

    try:
        issue = await client.get_issue(issue_key)

        # Store in Zep memory
        zep = await get_zep_client()
        session_id = await zep.ensure_session(channel_id)

        fields = issue.get("fields", {})
        content = f"""Jira issue refreshed: {issue_key}
Summary: {fields.get('summary', '')}
Status: {fields.get('status', {}).get('name', '')}
Type: {fields.get('issuetype', {}).get('name', '')}
Description: {fields.get('description', '')[:500]}"""

        await zep.memory.add(
            session_id=session_id,
            messages=[
                {
                    "role": "system",
                    "content": content,
                    "metadata": {
                        "type": "jira_sync",
                        "issue_key": issue_key,
                    },
                }
            ],
        )

        logger.info("jira_issue_synced_to_memory", key=issue_key, channel=channel_id)
        return issue

    except Exception as e:
        logger.error("jira_sync_failed", key=issue_key, error=str(e))
        return None
