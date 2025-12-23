"""
Admin API Routes - Debug and monitoring endpoints for Zep memory and LangGraph state.

Provides:
- Zep session listing and memory inspection
- LangGraph thread state viewing
- Graph visualization
"""

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query

from src.config.settings import get_settings

logger = structlog.get_logger()
settings = get_settings()

router = APIRouter(prefix="/admin", tags=["admin"])


# =============================================================================
# Zep Memory Endpoints
# =============================================================================


@router.get("/zep/sessions")
async def list_zep_sessions() -> dict[str, Any]:
    """List all Zep sessions (channels with memory)."""
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
        logger.error("zep_sessions_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/zep/sessions/{session_id}")
async def get_zep_session(session_id: str) -> dict[str, Any]:
    """Get details for a specific Zep session including memory and facts."""
    from src.memory.zep_client import get_http_client

    try:
        client = await get_http_client()

        # Get session info
        session_response = await client.get(f"/api/v1/sessions/{session_id}")
        if session_response.status_code != 200:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        session_data = session_response.json()

        # Get memory (messages + facts)
        memory_response = await client.get(f"/api/v1/sessions/{session_id}/memory")
        memory_data = memory_response.json() if memory_response.status_code == 200 else {}

        return {
            "session": {
                "session_id": session_data.get("session_id", session_data.get("uuid")),
                "metadata": session_data.get("metadata", {}),
                "created_at": session_data.get("created_at"),
                "updated_at": session_data.get("updated_at"),
            },
            "memory": {
                "messages": memory_data.get("messages", []),
                "message_count": len(memory_data.get("messages", [])),
            },
            "facts": memory_data.get("facts", []),
            "summary": memory_data.get("summary", {}).get("content") if memory_data.get("summary") else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("zep_session_error", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/zep/sessions/{session_id}")
async def delete_zep_session(session_id: str) -> dict[str, Any]:
    """Delete a Zep session and all its memory."""
    from src.memory.zep_client import get_http_client

    try:
        client = await get_http_client()

        # Delete memory first
        await client.delete(f"/api/v1/sessions/{session_id}/memory")

        # Delete session
        response = await client.delete(f"/api/v1/sessions/{session_id}")

        if response.status_code in (200, 204, 404):
            return {"deleted": True, "session_id": session_id}
        else:
            return {"deleted": False, "error": f"Status {response.status_code}"}

    except Exception as e:
        logger.error("zep_delete_error", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/zep/sessions/{session_id}/search")
async def search_zep_memory(
    session_id: str,
    query: str = Query(..., description="Search query"),
    limit: int = Query(10, ge=1, le=100),
) -> dict[str, Any]:
    """Semantic search within a session's memory."""
    from src.memory.zep_client import get_http_client

    try:
        client = await get_http_client()
        response = await client.post(
            f"/api/v1/sessions/{session_id}/search",
            json={"text": query, "metadata": {}},
            params={"limit": limit},
        )

        if response.status_code != 200:
            return {"results": [], "error": f"Status {response.status_code}"}

        data = response.json() or []
        results = []
        for result in data:
            msg = result.get("message", {})
            results.append({
                "content": msg.get("content", ""),
                "role": msg.get("role", ""),
                "score": result.get("score", 0.0),
                "metadata": msg.get("metadata", {}),
            })

        return {"results": results, "count": len(results), "query": query}

    except Exception as e:
        logger.error("zep_search_error", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# LangGraph State Endpoints
# =============================================================================


@router.get("/graph/threads")
async def list_graph_threads() -> dict[str, Any]:
    """List all LangGraph thread states from checkpointer."""
    try:
        from src.graph.checkpointer import get_checkpointer

        checkpointer = await get_checkpointer()
        if checkpointer is None:
            return {"threads": [], "error": "Checkpointer not initialized"}

        # Get connection from pool (asyncpg uses acquire(), not connection())
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
        logger.error("graph_threads_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph/threads/{thread_id}")
async def get_graph_thread_state(thread_id: str) -> dict[str, Any]:
    """Get the current state of a LangGraph thread."""
    try:
        from src.graph.checkpointer import get_thread_state

        state = await get_thread_state(thread_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

        # Convert state to safe JSON format
        safe_state = {}
        for key, value in state.items():
            if key == "messages":
                # Truncate message list for display
                safe_state[key] = f"[{len(value)} messages]" if value else []
            elif isinstance(value, (str, int, float, bool, type(None))):
                safe_state[key] = value
            elif isinstance(value, list):
                safe_state[key] = f"[{len(value)} items]" if len(value) > 5 else value
            elif isinstance(value, dict):
                safe_state[key] = value
            else:
                safe_state[key] = str(value)

        return {
            "thread_id": thread_id,
            "state": safe_state,
            "current_phase": state.get("current_phase"),
            "intent": state.get("intent"),
            "awaiting_human": state.get("awaiting_human", False),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("graph_state_error", thread_id=thread_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/graph/threads/{thread_id}")
async def delete_graph_thread(thread_id: str) -> dict[str, Any]:
    """Delete a LangGraph thread checkpoint."""
    try:
        from src.graph.checkpointer import clear_thread

        await clear_thread(thread_id)
        return {"deleted": True, "thread_id": thread_id}

    except Exception as e:
        logger.error("graph_delete_error", thread_id=thread_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Graph Visualization
# =============================================================================


@router.get("/graph/mermaid")
async def get_graph_mermaid() -> dict[str, Any]:
    """Get Mermaid diagram of the workflow graph."""
    try:
        from src.graph.graph import create_graph

        graph = create_graph(checkpointer=None)
        mermaid = graph.get_graph().draw_mermaid()

        return {
            "mermaid": mermaid,
            "viewer_url": "https://mermaid.live/",
            "tip": "Paste the mermaid code into the viewer to visualize",
        }

    except Exception as e:
        logger.error("graph_mermaid_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Combined Dashboard
# =============================================================================


@router.get("/dashboard")
async def admin_dashboard() -> dict[str, Any]:
    """Get combined admin dashboard data."""
    from src.memory.zep_client import get_http_client

    dashboard = {
        "zep": {"status": "unknown", "sessions": 0},
        "graph": {"status": "unknown", "threads": 0},
        "health": "ok",
    }

    # Check Zep
    try:
        client = await get_http_client()
        response = await client.get("/api/v1/sessions")
        if response.status_code == 200:
            data = response.json()
            count = len(data) if isinstance(data, list) else len(data.get("sessions", []))
            dashboard["zep"] = {"status": "connected", "sessions": count}
        else:
            dashboard["zep"] = {"status": "error", "code": response.status_code}
    except Exception as e:
        dashboard["zep"] = {"status": "error", "error": str(e)}

    # Check LangGraph
    try:
        from src.graph.checkpointer import get_checkpointer

        checkpointer = await get_checkpointer()
        if checkpointer and checkpointer.pool:
            async with checkpointer.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT COUNT(DISTINCT thread_id) FROM langgraph_checkpoints")
                count = row[0] if row else 0
                dashboard["graph"] = {"status": "connected", "threads": count}
        else:
            dashboard["graph"] = {"status": "no_pool"}
    except Exception as e:
        dashboard["graph"] = {"status": "error", "error": str(e)}

    return dashboard
