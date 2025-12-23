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
# Zep Sessions
# =============================================================================


@router.get("/zep/sessions", response_class=HTMLResponse)
async def list_zep_sessions_html():
    """List all Zep sessions with HTML UI."""
    from src.memory.zep_client import get_http_client

    sessions = []
    error = None

    try:
        client = await get_http_client()
        response = await client.get("/api/v1/sessions")

        if response.status_code == 200:
            data = response.json()
            for session in data if isinstance(data, list) else data.get("sessions", []):
                sessions.append({
                    "session_id": session.get("session_id", session.get("uuid")),
                    "metadata": session.get("metadata", {}),
                    "created_at": session.get("created_at"),
                    "updated_at": session.get("updated_at"),
                })
        else:
            error = f"Zep returned status {response.status_code}"
    except Exception as e:
        error = str(e)
        logger.error("zep_sessions_error", error=error)

    if error:
        content = f"""
            <h1>Zep Sessions</h1>
            <div class="card">
                <p class="empty" style="color: #fca5a5;">Error: {error}</p>
            </div>
        """
    elif not sessions:
        content = """
            <h1>Zep Sessions</h1>
            <div class="card">
                <p class="empty">No sessions found. Memory sessions are created when users interact with the bot.</p>
            </div>
        """
    else:
        rows = ""
        for s in sessions:
            metadata = json.dumps(s["metadata"], indent=2) if s["metadata"] else "-"
            rows += f"""
                <tr>
                    <td class="thread-id">{s["session_id"]}</td>
                    <td class="time">{format_time(s["created_at"])}</td>
                    <td class="time">{format_time(s["updated_at"])}</td>
                    <td>
                        <a href="/admin/zep/sessions/{s["session_id"]}" class="btn">View</a>
                    </td>
                </tr>
            """

        content = f"""
            <h1>Zep Sessions ({len(sessions)})</h1>
            <div class="card">
                <table>
                    <thead>
                        <tr>
                            <th>Session ID</th>
                            <th>Created</th>
                            <th>Updated</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows}
                    </tbody>
                </table>
            </div>
        """

    return render_page("Zep Sessions", content, active="zep")


@router.get("/zep/sessions/{session_id}", response_class=HTMLResponse)
async def get_zep_session_html(session_id: str):
    """Get details for a specific Zep session with HTML UI."""
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

        messages = memory_data.get("messages", [])
        facts = memory_data.get("facts", [])
        summary = memory_data.get("summary", {}).get("content") if memory_data.get("summary") else None

        # Format messages
        messages_html = ""
        for msg in messages[-20:]:  # Last 20 messages
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            role_class = "color: #34d399;" if role == "assistant" else "color: #38bdf8;"
            messages_html += f"""
                <div style="margin-bottom: 10px; padding: 10px; background: #0f172a; border-radius: 6px;">
                    <strong style="{role_class}">{role}:</strong>
                    <span style="color: #e2e8f0;">{content[:500]}{'...' if len(content) > 500 else ''}</span>
                </div>
            """

        # Format facts
        facts_html = ""
        for fact in facts:
            fact_text = fact if isinstance(fact, str) else fact.get("fact", str(fact))
            facts_html += f"<li>{fact_text}</li>"

        content = f"""
            <h1>Session: {session_id}</h1>
            <p><a href="/admin/zep/sessions">← Back to Sessions</a></p>

            <div class="card">
                <h2>Session Info</h2>
                <table>
                    <tr><td>Session ID</td><td class="thread-id">{session_id}</td></tr>
                    <tr><td>Created</td><td class="time">{format_time(session_data.get("created_at"))}</td></tr>
                    <tr><td>Updated</td><td class="time">{format_time(session_data.get("updated_at"))}</td></tr>
                    <tr><td>Message Count</td><td>{len(messages)}</td></tr>
                    <tr><td>Facts Count</td><td>{len(facts)}</td></tr>
                </table>
            </div>

            {f'<div class="card"><h2>Summary</h2><p>{summary}</p></div>' if summary else ''}

            <div class="card">
                <h2>Facts ({len(facts)})</h2>
                {f'<ul style="margin-left: 20px;">{facts_html}</ul>' if facts else '<p class="empty">No facts extracted yet.</p>'}
            </div>

            <div class="card">
                <h2>Recent Messages (last 20)</h2>
                {messages_html if messages else '<p class="empty">No messages yet.</p>'}
            </div>
        """

        return render_page(f"Session {session_id}", content, active="zep")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("zep_session_error", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================