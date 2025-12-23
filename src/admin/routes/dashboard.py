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
# Dashboard
# =============================================================================


@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard():
    """Admin dashboard with system status."""
    from src.memory.zep_client import get_http_client

    zep_status = "unknown"
    zep_sessions = 0
    graph_status = "unknown"
    graph_threads = 0

    # Check Zep
    try:
        client = await get_http_client()
        response = await client.get("/api/v1/sessions")
        if response.status_code == 200:
            data = response.json()
            zep_sessions = len(data) if isinstance(data, list) else len(data.get("sessions", []))
            zep_status = "connected"
        else:
            zep_status = "error"
    except Exception as e:
        zep_status = "error"
        logger.error("dashboard_zep_error", error=str(e))

    # Check LangGraph
    try:
        from src.graph.checkpointer import get_checkpointer

        checkpointer = await get_checkpointer()
        if checkpointer and checkpointer.pool:
            async with checkpointer.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT COUNT(DISTINCT thread_id) FROM langgraph_checkpoints")
                graph_threads = row[0] if row else 0
                graph_status = "connected"
        else:
            graph_status = "error"
    except Exception as e:
        graph_status = "error"
        logger.error("dashboard_graph_error", error=str(e))

    content = f"""
        <h1>MARO Admin Dashboard</h1>
        <a href="/admin/dashboard" class="btn refresh">↻ Refresh</a>

        <div class="grid">
            <div class="stat-card">
                <div class="stat-value">{zep_sessions}</div>
                <div class="stat-label">Zep Sessions</div>
                <div style="margin-top: 10px;">
                    <span class="status {zep_status}">{zep_status.upper()}</span>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{graph_threads}</div>
                <div class="stat-label">Graph Threads</div>
                <div style="margin-top: 10px;">
                    <span class="status {graph_status}">{graph_status.upper()}</span>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>Quick Links</h2>
            <p style="margin-top: 10px;">
                <a href="/admin/zep/sessions" class="btn">View Zep Sessions →</a>
                <a href="/admin/graph/threads" class="btn" style="margin-left: 10px;">View Graph Threads →</a>
                <a href="/admin/graph/mermaid" class="btn" style="margin-left: 10px;">View Graph Diagram →</a>
            </p>
        </div>

        <div class="card">
            <h2>Configuration</h2>
            <table>
                <tr><td>Environment</td><td>{settings.environment}</td></tr>
                <tr><td>Default LLM Model</td><td>{settings.default_llm_model}</td></tr>
                <tr><td>LangSmith Project</td><td>{settings.langchain_project}</td></tr>
                <tr><td>Zep API URL</td><td>{settings.zep_api_url}</td></tr>
            </table>
        </div>
    """

    return render_page("Dashboard", content, active="dashboard")

