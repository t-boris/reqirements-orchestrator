"""
Graph API endpoints.

Provides REST access to requirements graphs for the web dashboard.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from src.core.events.store import EventStore
from src.core.services.graph_service import GraphService

router = APIRouter()

# Dependency injection (simplified - in production use proper DI)
_event_store = EventStore()
_graph_service = GraphService(_event_store)


def get_graph_service() -> GraphService:
    """Get graph service instance."""
    return _graph_service


class NodeResponse(BaseModel):
    """Response model for a graph node."""

    id: str
    type: str
    title: str
    description: str
    status: str
    attributes: dict
    external_ref: dict | None = None
    created_at: str
    updated_at: str


class EdgeResponse(BaseModel):
    """Response model for a graph edge."""

    source_id: str
    target_id: str
    type: str
    attributes: dict


class MetricsResponse(BaseModel):
    """Response model for graph metrics."""

    completeness_score: float
    conflict_ratio: float
    orphan_count: int
    unlinked_stories: int
    blocking_questions: int
    total_nodes: int
    total_edges: int


class GraphResponse(BaseModel):
    """Response model for a complete graph."""

    channel_id: str
    nodes: list[NodeResponse]
    edges: list[EdgeResponse]
    metrics: MetricsResponse
    updated_at: str


@router.get("/{channel_id}", response_model=GraphResponse)
async def get_graph(
    channel_id: str,
    graph_service: GraphService = Depends(get_graph_service),
) -> GraphResponse:
    """
    Get the requirements graph for a channel.

    Args:
        channel_id: Slack channel ID.

    Returns:
        Complete graph with nodes, edges, and metrics.
    """
    try:
        state = graph_service.get_graph_state(channel_id)

        return GraphResponse(
            channel_id=channel_id,
            nodes=[
                NodeResponse(
                    id=n["id"],
                    type=n["type"],
                    title=n["title"],
                    description=n["description"],
                    status=n["status"],
                    attributes=n["attributes"],
                    external_ref=n.get("external_ref"),
                    created_at=n["created_at"],
                    updated_at=n["updated_at"],
                )
                for n in state.get("nodes", [])
            ],
            edges=[
                EdgeResponse(
                    source_id=e["source_id"],
                    target_id=e["target_id"],
                    type=e["type"],
                    attributes=e["attributes"],
                )
                for e in state.get("edges", [])
            ],
            metrics=MetricsResponse(**state.get("metrics", {})),
            updated_at=state.get("updated_at", ""),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{channel_id}/metrics", response_model=MetricsResponse)
async def get_graph_metrics(
    channel_id: str,
    graph_service: GraphService = Depends(get_graph_service),
) -> MetricsResponse:
    """
    Get metrics for a channel's graph.

    Args:
        channel_id: Slack channel ID.

    Returns:
        Graph quality metrics.
    """
    try:
        state = graph_service.get_graph_state(channel_id)
        return MetricsResponse(**state.get("metrics", {}))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{channel_id}/validation")
async def validate_graph(
    channel_id: str,
    graph_service: GraphService = Depends(get_graph_service),
) -> dict:
    """
    Validate a channel's graph.

    Returns validation issues (orphans, conflicts, etc.)

    Args:
        channel_id: Slack channel ID.

    Returns:
        Validation results.
    """
    try:
        issues = graph_service.validate_graph(channel_id)
        has_issues = any(issues.values())

        return {
            "valid": not has_issues,
            "issues": issues,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{channel_id}/history")
async def get_graph_history(
    channel_id: str,
    limit: int = 50,
) -> dict:
    """
    Get change history for a channel's graph.

    Args:
        channel_id: Slack channel ID.
        limit: Maximum events to return.

    Returns:
        List of recent events.
    """
    try:
        events = _event_store.get_events(channel_id)
        recent = events[-limit:] if len(events) > limit else events

        return {
            "channel_id": channel_id,
            "total_events": len(events),
            "events": [
                {
                    "id": e.id,
                    "type": e.type.value,
                    "user_id": e.user_id,
                    "timestamp": e.timestamp.isoformat(),
                    "payload": e.payload,
                }
                for e in reversed(recent)
            ],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
