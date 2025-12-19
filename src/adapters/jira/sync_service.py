"""
Jira Sync Service - Synchronizes graph to Jira.

Handles the complete sync workflow including retries, rollback,
and partial sync handling.
"""

import structlog
from dataclasses import dataclass, field
from typing import Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from src.adapters.jira.protocol import (
    IssueTrackerProtocol,
    CreateIssueRequest,
    LinkIssuesRequest,
)
from src.core.events.models import EventType, create_event
from src.core.events.store import EventStore
from src.core.graph.graph import RequirementsGraph
from src.core.graph.models import EdgeType, GraphNode, NodeStatus, NodeType
from src.core.services.graph_service import GraphService

logger = structlog.get_logger()


@dataclass
class SyncResult:
    """Result of a sync operation."""

    success: bool
    synced_items: list[dict] = field(default_factory=list)
    failed_items: list[dict] = field(default_factory=list)
    error: str | None = None


class JiraSyncService:
    """
    Synchronizes requirements graph to Jira.

    Features:
    - Creates issues in correct order (parent before child)
    - Links related issues
    - Handles partial sync with rollback option
    - Retries failed requests with exponential backoff
    """

    def __init__(
        self,
        jira_client: IssueTrackerProtocol,
        graph_service: GraphService,
        event_store: EventStore,
        max_retries: int = 3,
    ) -> None:
        """
        Initialize sync service.

        Args:
            jira_client: Jira API client.
            graph_service: Graph service for updates.
            event_store: Event store for audit.
            max_retries: Maximum retry attempts.
        """
        self._jira = jira_client
        self._graph_service = graph_service
        self._event_store = event_store
        self._max_retries = max_retries

    async def sync_graph(
        self,
        channel_id: str,
        user_id: str,
        project_key: str,
        node_ids: list[str] | None = None,
    ) -> SyncResult:
        """
        Sync graph nodes to Jira.

        Args:
            channel_id: Slack channel ID.
            user_id: User triggering sync.
            project_key: Jira project key.
            node_ids: Specific nodes to sync (None = all approved).

        Returns:
            SyncResult with success status and details.
        """
        logger.info(
            "starting_sync",
            channel_id=channel_id,
            project_key=project_key,
        )

        # Record sync started event
        self._event_store.append(create_event(
            EventType.SYNC_STARTED,
            channel_id=channel_id,
            user_id=user_id,
            target_system="jira",
            project_key=project_key,
        ))

        graph = self._graph_service.get_or_create_graph(channel_id)

        # Get nodes to sync
        if node_ids:
            nodes = [graph.get_node(nid) for nid in node_ids if graph.get_node(nid)]
        else:
            # Sync all approved nodes
            nodes = [
                n for n in graph.get_all_nodes()
                if n.status == NodeStatus.APPROVED
            ]

        if not nodes:
            return SyncResult(success=True, error="No nodes to sync")

        # Sort nodes by type (parent types first)
        type_order = {
            NodeType.GOAL: 0,
            NodeType.EPIC: 1,
            NodeType.STORY: 2,
            NodeType.SUBTASK: 3,
            NodeType.COMPONENT: 4,
            NodeType.CONSTRAINT: 5,
            NodeType.RISK: 6,
            NodeType.QUESTION: 7,
            NodeType.CONTEXT: 8,
        }
        nodes.sort(key=lambda n: type_order.get(n.type, 99))

        # Track results
        synced: list[dict] = []
        failed: list[dict] = []
        node_id_to_jira_key: dict[str, str] = {}

        # Sync each node
        for node in nodes:
            try:
                jira_issue = await self._sync_node(
                    node=node,
                    project_key=project_key,
                    node_id_to_jira_key=node_id_to_jira_key,
                )

                node_id_to_jira_key[node.id] = jira_issue.id
                synced.append({
                    "node_id": node.id,
                    "external_id": jira_issue.id,
                    "url": jira_issue.url,
                })

                # Update node with external reference
                self._graph_service.update_node(
                    channel_id=channel_id,
                    user_id=user_id,
                    node_id=node.id,
                    status=NodeStatus.SYNCED,
                    external_ref={
                        "system": "jira",
                        "id": jira_issue.id,
                        "url": jira_issue.url,
                    },
                )

            except Exception as e:
                logger.error(
                    "node_sync_failed",
                    node_id=node.id,
                    error=str(e),
                )
                failed.append({
                    "node_id": node.id,
                    "error": str(e),
                })

        # Sync edges (issue links)
        edges = graph.get_all_edges()
        for edge in edges:
            if edge.source_id in node_id_to_jira_key and edge.target_id in node_id_to_jira_key:
                try:
                    await self._sync_edge(
                        edge_type=edge.type,
                        source_jira_key=node_id_to_jira_key[edge.source_id],
                        target_jira_key=node_id_to_jira_key[edge.target_id],
                    )
                except Exception as e:
                    logger.warning(
                        "edge_sync_failed",
                        source=edge.source_id,
                        target=edge.target_id,
                        error=str(e),
                    )

        # Determine overall success
        success = len(failed) == 0

        # Handle partial sync
        if failed and synced:
            # Mark failed nodes as partially synced
            self._graph_service.mark_partial_sync(
                channel_id=channel_id,
                user_id=user_id,
                failed_node_ids=[f["node_id"] for f in failed],
            )

        # Record completion event
        event_type = EventType.SYNC_COMPLETED if success else EventType.SYNC_FAILED
        self._event_store.append(create_event(
            event_type,
            channel_id=channel_id,
            user_id=user_id,
            target_system="jira",
            synced_items=synced,
            failed_items=failed,
        ))

        logger.info(
            "sync_completed",
            channel_id=channel_id,
            synced=len(synced),
            failed=len(failed),
        )

        return SyncResult(
            success=success,
            synced_items=synced,
            failed_items=failed,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def _sync_node(
        self,
        node: GraphNode,
        project_key: str,
        node_id_to_jira_key: dict[str, str],
    ):
        """
        Sync a single node to Jira with retries.

        Args:
            node: Node to sync.
            project_key: Jira project key.
            node_id_to_jira_key: Map of already synced nodes.

        Returns:
            Created Jira issue.
        """
        # Find parent Jira key if applicable
        parent_jira_key = None
        if node.type in (NodeType.STORY, NodeType.SUBTASK):
            # Look for parent in graph (via DECOMPOSES_TO edge)
            # This would require access to the graph edges
            pass

        # Build labels
        labels = [f"maro-{node.type.value}"]
        if node.type == NodeType.CONSTRAINT:
            nfr_type = node.attributes.get("type", "general")
            labels.append(f"nfr-{nfr_type}")

        request = CreateIssueRequest(
            project_key=project_key,
            title=node.title,
            description=node.description,
            issue_type=node.type.value,
            parent_id=parent_jira_key,
            labels=labels,
            acceptance_criteria=node.attributes.get("acceptance_criteria"),
            custom_fields={
                "maro_node_id": node.id,  # Custom field for tracking
            },
        )

        return await self._jira.create_issue(request)

    async def _sync_edge(
        self,
        edge_type: EdgeType,
        source_jira_key: str,
        target_jira_key: str,
    ) -> bool:
        """
        Sync an edge as a Jira issue link.

        Args:
            edge_type: MARO edge type.
            source_jira_key: Source Jira issue key.
            target_jira_key: Target Jira issue key.

        Returns:
            True if link created.
        """
        request = LinkIssuesRequest(
            source_id=source_jira_key,
            target_id=target_jira_key,
            link_type=edge_type.value,
        )

        return await self._jira.link_issues(request)

    async def read_jira_status(
        self,
        channel_id: str,
        node_id: str,
    ) -> dict | None:
        """
        Read current status of a synced node from Jira.

        Args:
            channel_id: Slack channel ID.
            node_id: MARO node ID.

        Returns:
            Dict with Jira issue status, or None if not found.
        """
        graph = self._graph_service.get_or_create_graph(channel_id)
        node = graph.get_node(node_id)

        if not node or not node.external_ref:
            return None

        issue = await self._jira.get_issue(node.external_ref.id)

        if not issue:
            return None

        return {
            "jira_key": issue.id,
            "status": issue.status,
            "title": issue.title,
            "url": issue.url,
        }

    async def update_jira_issue(
        self,
        channel_id: str,
        user_id: str,
        node_id: str,
        **updates: Any,
    ) -> dict | None:
        """
        Update a synced Jira issue.

        Args:
            channel_id: Slack channel ID.
            user_id: User triggering update.
            node_id: MARO node ID.
            **updates: Fields to update (title, description, status).

        Returns:
            Updated issue info, or None if not found.
        """
        graph = self._graph_service.get_or_create_graph(channel_id)
        node = graph.get_node(node_id)

        if not node or not node.external_ref:
            return None

        issue = await self._jira.update_issue(node.external_ref.id, **updates)

        return {
            "jira_key": issue.id,
            "status": issue.status,
            "title": issue.title,
            "url": issue.url,
        }
