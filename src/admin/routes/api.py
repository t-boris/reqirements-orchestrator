"""Admin routes."""

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

logger = structlog.get_logger()

router = APIRouter()

from src.admin.routes.base import (
    render_page,
    format_time,
    BASE_TEMPLATE,
)

# =============================================================================
# API Endpoints (JSON) - Keep for programmatic access
# =============================================================================


@router.get("/api/zep/sessions")
async def api_list_zep_sessions() -> dict[str, Any]:
    """API: List all Zep sessions."""
    from src.memory.zep_client import get_http_client

    try:
        client = await get_http_client()
        response = await client.get("/api/v1/sessions")

        if response.status_code != 200:
            return {"sessions": [], "error": f"Zep returned {response.status_code}"}

        data = response.json()
        sessions = []
        for session in data if isinstance(data, list) else data.get("sessions", []):
            sessions.append({
                "session_id": session.get("session_id", session.get("uuid")),
                "metadata": session.get("metadata", {}),
                "created_at": session.get("created_at"),
                "updated_at": session.get("updated_at"),
            })

        return {"sessions": sessions, "count": len(sessions)}

    except Exception as e:
        logger.error("api_zep_sessions_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/graph/threads")
async def api_list_graph_threads() -> dict[str, Any]:
    """API: List all LangGraph thread states."""
    try:
        from src.graph.checkpointer import get_checkpointer

        checkpointer = await get_checkpointer()
        if checkpointer is None:
            return {"threads": [], "error": "Checkpointer not initialized"}

        pool = checkpointer.pool
        if pool is None:
            return {"threads": [], "error": "Pool not available"}

        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT thread_id, MAX(created_at) as last_updated
                FROM langgraph_checkpoints
                GROUP BY thread_id
                ORDER BY last_updated DESC
                LIMIT 100
            """)

            threads = []
            for row in rows:
                threads.append({
                    "thread_id": row["thread_id"],
                    "last_updated": row["last_updated"].isoformat() if row["last_updated"] else None,
                })

            return {"threads": threads, "count": len(threads)}

    except Exception as e:
        logger.error("api_graph_threads_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/zep/sessions/{session_id}")
async def api_delete_zep_session(session_id: str) -> dict[str, Any]:
    """API: Delete a Zep session."""
    from src.memory.zep_client import get_http_client

    try:
        client = await get_http_client()
        await client.delete(f"/api/v1/sessions/{session_id}/memory")
        response = await client.delete(f"/api/v1/sessions/{session_id}")

        if response.status_code in (200, 204, 404):
            return {"deleted": True, "session_id": session_id}
        else:
            return {"deleted": False, "error": f"Status {response.status_code}"}

    except Exception as e:
        logger.error("api_zep_delete_error", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/graph/threads/{thread_id}")
async def api_delete_graph_thread(thread_id: str) -> dict[str, Any]:
    """API: Delete a LangGraph thread."""
    try:
        from src.graph.checkpointer import clear_thread

        await clear_thread(thread_id)
        return {"deleted": True, "thread_id": thread_id}

    except Exception as e:
        logger.error("api_graph_delete_error", thread_id=thread_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/knowledge-graph")
async def api_get_knowledge_graph(session_id: str | None = None) -> dict[str, Any]:
    """
    API: Get knowledge graph data for D3.js visualization.

    Returns:
        - nodes: list of entity nodes with id, label, type, description, color
        - edges: list of relationships with source, target, type, label, color
        - metadata: statistics about the graph

    Query params:
        - session_id: Optional filter for a specific session
    """
    from src.memory.entity_extractor import (
        _knowledge_graphs,
        build_knowledge_graph_data,
    )
    from src.memory.zep_client import get_http_client

    try:
        # Get in-memory knowledge graphs
        if session_id:
            if session_id in _knowledge_graphs:
                kg = _knowledge_graphs[session_id]
                knowledge_by_session = {session_id: kg.to_dict()}
            else:
                knowledge_by_session = {}
        else:
            knowledge_by_session = {
                sid: kg.to_dict() for sid, kg in _knowledge_graphs.items()
            }

        # Build graph data from in-memory graphs
        graph_data = build_knowledge_graph_data(knowledge_by_session)

        # Also get additional data from Zep
        try:
            client = await get_http_client()

            if session_id:
                sessions = [{"session_id": session_id}]
            else:
                resp = await client.get("/api/v1/sessions")
                if resp.status_code == 200:
                    data = resp.json()
                    sessions = data if isinstance(data, list) else data.get("sessions", [])
                else:
                    sessions = []

            # Merge Zep data (entities from message metadata)
            existing_node_ids = {n["id"] for n in graph_data.get("nodes", [])}

            for session in sessions:
                sid = session.get("session_id", session.get("uuid"))
                if not sid:
                    continue

                memory_resp = await client.get(f"/api/v1/sessions/{sid}/memory")
                if memory_resp.status_code != 200:
                    continue

                memory_data = memory_resp.json()
                for msg in memory_data.get("messages", []) or []:
                    metadata = msg.get("metadata", {}) or {}

                    # Count entities and relationships from Zep
                    entity_count = len(metadata.get("entities", []))
                    rel_count = len(metadata.get("relationships", []))
                    gap_count = len(metadata.get("knowledge_gaps", []))

                    if entity_count > 0 or rel_count > 0:
                        graph_data.setdefault("metadata", {})
                        graph_data["metadata"]["zep_entity_count"] = (
                            graph_data["metadata"].get("zep_entity_count", 0) + entity_count
                        )
                        graph_data["metadata"]["zep_relationship_count"] = (
                            graph_data["metadata"].get("zep_relationship_count", 0) + rel_count
                        )

        except Exception as zep_err:
            logger.debug("api_knowledge_graph_zep_skip", error=str(zep_err))

        return {
            "nodes": graph_data.get("nodes", []),
            "edges": graph_data.get("edges", []),
            "metadata": {
                **graph_data.get("metadata", {}),
                "in_memory_sessions": list(_knowledge_graphs.keys()),
            },
        }

    except Exception as e:
        logger.error("api_knowledge_graph_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/knowledge-graph/session/{session_id}")
async def api_get_session_knowledge(session_id: str) -> dict[str, Any]:
    """
    API: Get detailed knowledge for a specific session.

    Returns entities, relationships, gaps, and suggested questions.
    """
    from src.memory.entity_extractor import get_knowledge_graph

    try:
        kg = get_knowledge_graph(session_id)

        return {
            "session_id": session_id,
            "entities": list(kg.entities.values()),
            "relationships": kg.relationships,
            "knowledge_gaps": kg.knowledge_gaps,
            "suggested_questions": kg.get_suggested_questions(),
            "message_count": kg.message_count,
            "stats": {
                "entity_count": len(kg.entities),
                "relationship_count": len(kg.relationships),
                "gap_count": len(kg.knowledge_gaps),
            },
        }

    except Exception as e:
        logger.error("api_session_knowledge_error", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
