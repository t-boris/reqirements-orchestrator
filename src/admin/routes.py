"""
Admin Web UI Routes - HTML dashboards for Zep memory and LangGraph state.

Provides web-based monitoring:
- Dashboard with system status
- Zep session listing and memory inspection
- LangGraph thread state viewing
- Graph visualization
"""

import json
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from src.config.settings import get_settings

logger = structlog.get_logger()
settings = get_settings()

router = APIRouter(prefix="/admin", tags=["admin"])


# =============================================================================
# HTML Templates
# =============================================================================

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - MARO Admin</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            line-height: 1.6;
            padding: 20px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ color: #38bdf8; margin-bottom: 20px; font-size: 1.8rem; }}
        h2 {{ color: #94a3b8; margin: 20px 0 10px; font-size: 1.2rem; }}
        .nav {{
            display: flex;
            gap: 15px;
            margin-bottom: 30px;
            padding: 15px;
            background: #1e293b;
            border-radius: 8px;
        }}
        .nav a {{
            color: #38bdf8;
            text-decoration: none;
            padding: 8px 16px;
            border-radius: 6px;
            transition: background 0.2s;
        }}
        .nav a:hover {{ background: #334155; }}
        .nav a.active {{ background: #0284c7; color: white; }}
        .card {{
            background: #1e293b;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        .status {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 500;
        }}
        .status.connected {{ background: #065f46; color: #34d399; }}
        .status.error {{ background: #7f1d1d; color: #fca5a5; }}
        .status.unknown {{ background: #374151; color: #9ca3af; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }}
        .stat-card {{
            background: #1e293b;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
        }}
        .stat-value {{ font-size: 2.5rem; font-weight: bold; color: #38bdf8; }}
        .stat-label {{ color: #94a3b8; margin-top: 5px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ text-align: left; padding: 12px 15px; border-bottom: 1px solid #334155; }}
        th {{ color: #94a3b8; font-weight: 500; background: #0f172a; }}
        tr:hover {{ background: #334155; }}
        .thread-id {{ font-family: monospace; font-size: 0.9rem; color: #38bdf8; }}
        .time {{ color: #64748b; font-size: 0.85rem; }}
        .btn {{
            display: inline-block;
            padding: 6px 12px;
            background: #0284c7;
            color: white;
            border-radius: 4px;
            text-decoration: none;
            font-size: 0.85rem;
        }}
        .btn:hover {{ background: #0369a1; }}
        .btn.danger {{ background: #dc2626; }}
        .btn.danger:hover {{ background: #b91c1c; }}
        pre {{
            background: #0f172a;
            padding: 15px;
            border-radius: 6px;
            overflow-x: auto;
            font-size: 0.85rem;
        }}
        .empty {{ text-align: center; color: #64748b; padding: 40px; }}
        .phase {{
            display: inline-block;
            padding: 2px 8px;
            background: #7c3aed;
            color: white;
            border-radius: 4px;
            font-size: 0.8rem;
        }}
        .refresh {{ float: right; }}
    </style>
</head>
<body>
    <div class="container">
        <nav class="nav">
            <a href="/admin/dashboard" class="{nav_dashboard}">Dashboard</a>
            <a href="/admin/zep/sessions" class="{nav_zep}">Zep Sessions</a>
            <a href="/admin/zep/knowledge-graph" class="{nav_knowledge}">Knowledge Graph</a>
            <a href="/admin/graph/threads" class="{nav_graph}">Graph Threads</a>
            <a href="/admin/graph/visualize" class="{nav_visualize}">Workflow (D3.js)</a>
        </nav>
        {content}
    </div>
    <script>
        // Auto-refresh every 30 seconds
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>
"""


def render_page(title: str, content: str, active: str = "") -> str:
    """Render a page with the base template."""
    return BASE_TEMPLATE.format(
        title=title,
        content=content,
        nav_dashboard="active" if active == "dashboard" else "",
        nav_zep="active" if active == "zep" else "",
        nav_knowledge="active" if active == "knowledge" else "",
        nav_graph="active" if active == "graph" else "",
        nav_visualize="active" if active == "visualize" else "",
    )


def format_time(iso_str: str | None) -> str:
    """Format ISO timestamp for display."""
    if not iso_str:
        return "-"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_str


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
# Knowledge Graph Visualization
# =============================================================================


@router.get("/zep/knowledge-graph", response_class=HTMLResponse)
async def zep_knowledge_graph():
    """Interactive D3.js knowledge graph showing entities and facts from Zep memory."""
    from src.memory.zep_client import get_http_client

    # Collect all entities and facts from all sessions
    nodes = []
    edges = []
    node_ids = set()

    try:
        client = await get_http_client()

        # Get all sessions
        sessions_response = await client.get("/api/v1/sessions")
        if sessions_response.status_code == 200:
            sessions_data = sessions_response.json()
            sessions = sessions_data if isinstance(sessions_data, list) else sessions_data.get("sessions", [])

            for session in sessions:
                session_id = session.get("session_id", session.get("uuid"))
                if not session_id:
                    continue

                # Add session as a central node
                if session_id not in node_ids:
                    nodes.append({
                        "id": session_id,
                        "label": session_id.replace("channel-", ""),
                        "type": "session",
                        "description": f"Channel session",
                    })
                    node_ids.add(session_id)

                # Get memory with facts and entities
                memory_response = await client.get(f"/api/v1/sessions/{session_id}/memory")
                if memory_response.status_code == 200:
                    memory_data = memory_response.json()

                    # Process facts
                    for i, fact in enumerate(memory_data.get("facts", []) or []):
                        fact_text = fact if isinstance(fact, str) else fact.get("fact", str(fact))
                        fact_id = f"{session_id}_fact_{i}"

                        if fact_id not in node_ids:
                            nodes.append({
                                "id": fact_id,
                                "label": fact_text[:50] + "..." if len(fact_text) > 50 else fact_text,
                                "type": "fact",
                                "description": fact_text,
                            })
                            node_ids.add(fact_id)
                            edges.append({
                                "source": session_id,
                                "target": fact_id,
                                "label": "has_fact",
                            })

                    # Process entities from messages
                    for msg in memory_data.get("messages", []) or []:
                        metadata = msg.get("metadata", {}) or {}
                        entities = metadata.get("entities", []) or []
                        for entity in entities:
                            entity_name = entity.get("name", str(entity)) if isinstance(entity, dict) else str(entity)
                            entity_id = f"entity_{entity_name.lower().replace(' ', '_')}"

                            if entity_id not in node_ids:
                                entity_type = entity.get("type", "entity") if isinstance(entity, dict) else "entity"
                                nodes.append({
                                    "id": entity_id,
                                    "label": entity_name,
                                    "type": entity_type,
                                    "description": f"Entity: {entity_name}",
                                })
                                node_ids.add(entity_id)

                            edges.append({
                                "source": session_id,
                                "target": entity_id,
                                "label": "mentions",
                            })

    except Exception as e:
        logger.error("knowledge_graph_error", error=str(e))

    # If no data, add placeholder
    if not nodes:
        nodes = [
            {"id": "no_data", "label": "No Data Yet", "type": "info", "description": "Start conversations to build the knowledge graph"}
        ]
        edges = []

    graph_json = json.dumps({"nodes": nodes, "edges": edges})

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Knowledge Graph - MARO Admin</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            overflow: hidden;
        }}
        .container {{ display: flex; height: 100vh; }}
        #graph-container {{ flex: 1; position: relative; }}
        #property-panel {{
            width: 350px;
            background: #1e293b;
            border-left: 1px solid #334155;
            padding: 20px;
            overflow-y: auto;
        }}
        .panel-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }}
        .panel-title {{ color: #38bdf8; font-size: 1.2rem; font-weight: 600; }}
        .back-link {{ color: #64748b; text-decoration: none; font-size: 0.9rem; }}
        .back-link:hover {{ color: #94a3b8; }}
        .property-group {{ margin-bottom: 20px; }}
        .property-label {{
            color: #64748b;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 5px;
        }}
        .property-value {{
            color: #e2e8f0;
            font-size: 0.95rem;
            padding: 10px 12px;
            background: #0f172a;
            border-radius: 6px;
            word-wrap: break-word;
        }}
        .node-type {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 500;
        }}
        .type-session {{ background: #7c3aed; color: white; }}
        .type-fact {{ background: #0284c7; color: white; }}
        .type-entity {{ background: #16a34a; color: white; }}
        .type-person {{ background: #ea580c; color: white; }}
        .type-organization {{ background: #c026d3; color: white; }}
        .type-info {{ background: #64748b; color: white; }}
        .empty-state {{
            color: #64748b;
            font-style: italic;
            text-align: center;
            padding: 40px 20px;
        }}
        .legend {{
            position: absolute;
            bottom: 20px;
            left: 20px;
            background: #1e293b;
            padding: 15px;
            border-radius: 8px;
            font-size: 0.8rem;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            margin-bottom: 6px;
        }}
        .legend-item:last-child {{ margin-bottom: 0; }}
        .legend-dot {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }}
        .controls {{
            position: absolute;
            top: 20px;
            left: 20px;
            background: #1e293b;
            padding: 10px;
            border-radius: 8px;
        }}
        .controls button {{
            background: #334155;
            color: #e2e8f0;
            border: none;
            padding: 8px 12px;
            margin-right: 5px;
            border-radius: 4px;
            cursor: pointer;
        }}
        .controls button:hover {{ background: #475569; }}
        .stats {{
            position: absolute;
            top: 20px;
            right: 340px;
            background: #1e293b;
            padding: 10px 15px;
            border-radius: 8px;
            font-size: 0.85rem;
        }}
        svg {{ width: 100%; height: 100%; }}
        .link {{ stroke: #475569; stroke-opacity: 0.6; fill: none; }}
        .link-label {{ fill: #64748b; font-size: 9px; }}
        .node circle {{
            stroke: #1e293b;
            stroke-width: 2px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .node circle:hover {{ stroke: #38bdf8; stroke-width: 3px; }}
        .node.selected circle {{ stroke: #38bdf8; stroke-width: 4px; }}
        .node text {{ fill: #e2e8f0; font-size: 10px; pointer-events: none; }}
    </style>
</head>
<body>
    <div class="container">
        <div id="graph-container">
            <div class="controls">
                <button onclick="zoomIn()">Zoom +</button>
                <button onclick="zoomOut()">Zoom -</button>
                <button onclick="resetZoom()">Reset</button>
            </div>
            <div class="stats">
                Nodes: <strong>{len(nodes)}</strong> | Edges: <strong>{len(edges)}</strong>
            </div>
            <svg id="graph"></svg>
            <div class="legend">
                <div class="legend-item"><div class="legend-dot" style="background: #7c3aed;"></div> Session</div>
                <div class="legend-item"><div class="legend-dot" style="background: #0284c7;"></div> Fact</div>
                <div class="legend-item"><div class="legend-dot" style="background: #16a34a;"></div> Entity</div>
                <div class="legend-item"><div class="legend-dot" style="background: #ea580c;"></div> Person</div>
                <div class="legend-item"><div class="legend-dot" style="background: #c026d3;"></div> Organization</div>
            </div>
        </div>
        <div id="property-panel">
            <div class="panel-header">
                <span class="panel-title">Knowledge Graph</span>
                <a href="/admin/dashboard" class="back-link">← Dashboard</a>
            </div>
            <div id="properties-content">
                <p class="empty-state">Click on a node to view details</p>
                <div class="property-group" style="margin-top: 30px;">
                    <div class="property-label">About</div>
                    <div class="property-value">
                        This graph shows entities and facts extracted from Zep memory across all conversation sessions.
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const graphData = {graph_json};

        const typeColors = {{
            session: '#7c3aed',
            fact: '#0284c7',
            entity: '#16a34a',
            person: '#ea580c',
            organization: '#c026d3',
            info: '#64748b'
        }};

        const width = document.getElementById('graph-container').clientWidth;
        const height = document.getElementById('graph-container').clientHeight;

        const svg = d3.select('#graph').attr('viewBox', [0, 0, width, height]);

        svg.append('defs').append('marker')
            .attr('id', 'arrowhead')
            .attr('viewBox', '-0 -5 10 10')
            .attr('refX', 25)
            .attr('refY', 0)
            .attr('orient', 'auto')
            .attr('markerWidth', 6)
            .attr('markerHeight', 6)
            .append('path')
            .attr('d', 'M 0,-5 L 10,0 L 0,5')
            .attr('fill', '#475569');

        const g = svg.append('g');

        const zoom = d3.zoom()
            .scaleExtent([0.2, 4])
            .on('zoom', (event) => g.attr('transform', event.transform));

        svg.call(zoom);

        const simulation = d3.forceSimulation(graphData.nodes)
            .force('link', d3.forceLink(graphData.edges).id(d => d.id).distance(100))
            .force('charge', d3.forceManyBody().strength(-300))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius(35));

        const link = g.append('g')
            .selectAll('path')
            .data(graphData.edges)
            .join('path')
            .attr('class', 'link')
            .attr('marker-end', 'url(#arrowhead)');

        const linkLabels = g.append('g')
            .selectAll('text')
            .data(graphData.edges.filter(d => d.label))
            .join('text')
            .attr('class', 'link-label')
            .text(d => d.label);

        const node = g.append('g')
            .selectAll('g')
            .data(graphData.nodes)
            .join('g')
            .attr('class', 'node')
            .call(d3.drag()
                .on('start', dragstarted)
                .on('drag', dragged)
                .on('end', dragended))
            .on('click', selectNode);

        node.append('circle')
            .attr('r', d => d.type === 'session' ? 25 : 18)
            .attr('fill', d => typeColors[d.type] || typeColors.entity);

        node.append('text')
            .attr('dy', d => d.type === 'session' ? 40 : 30)
            .attr('text-anchor', 'middle')
            .text(d => d.label.length > 20 ? d.label.substring(0, 20) + '...' : d.label);

        simulation.on('tick', () => {{
            link.attr('d', d => `M${{d.source.x}},${{d.source.y}} L${{d.target.x}},${{d.target.y}}`);
            linkLabels
                .attr('x', d => (d.source.x + d.target.x) / 2)
                .attr('y', d => (d.source.y + d.target.y) / 2);
            node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
        }});

        function dragstarted(event) {{
            if (!event.active) simulation.alphaTarget(0.3).restart();
            event.subject.fx = event.subject.x;
            event.subject.fy = event.subject.y;
        }}

        function dragged(event) {{
            event.subject.fx = event.x;
            event.subject.fy = event.y;
        }}

        function dragended(event) {{
            if (!event.active) simulation.alphaTarget(0);
            event.subject.fx = null;
            event.subject.fy = null;
        }}

        function selectNode(event, d) {{
            d3.selectAll('.node').classed('selected', false);
            d3.select(this).classed('selected', true);

            const incoming = graphData.edges.filter(e => (e.target.id || e.target) === d.id);
            const outgoing = graphData.edges.filter(e => (e.source.id || e.source) === d.id);

            const panel = document.getElementById('properties-content');
            panel.innerHTML = `
                <div class="property-group">
                    <div class="property-label">ID</div>
                    <div class="property-value" style="font-family: monospace; font-size: 0.85rem;">${{d.id}}</div>
                </div>
                <div class="property-group">
                    <div class="property-label">Label</div>
                    <div class="property-value">${{d.label}}</div>
                </div>
                <div class="property-group">
                    <div class="property-label">Type</div>
                    <div class="property-value">
                        <span class="node-type type-${{d.type}}">${{d.type}}</span>
                    </div>
                </div>
                <div class="property-group">
                    <div class="property-label">Description</div>
                    <div class="property-value">${{d.description}}</div>
                </div>
                <div class="property-group">
                    <div class="property-label">Connections</div>
                    <div class="property-value">
                        Incoming: ${{incoming.length}}<br>
                        Outgoing: ${{outgoing.length}}
                    </div>
                </div>
            `;
        }}

        function zoomIn() {{ svg.transition().call(zoom.scaleBy, 1.3); }}
        function zoomOut() {{ svg.transition().call(zoom.scaleBy, 0.7); }}
        function resetZoom() {{ svg.transition().call(zoom.transform, d3.zoomIdentity); }}
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html)


# =============================================================================
# Graph Threads
# =============================================================================


@router.get("/graph/threads", response_class=HTMLResponse)
async def list_graph_threads_html():
    """List all LangGraph thread states with HTML UI."""
    threads = []
    error = None

    try:
        from src.graph.checkpointer import get_checkpointer

        checkpointer = await get_checkpointer()
        if checkpointer is None:
            error = "Checkpointer not initialized"
        elif checkpointer.pool is None:
            error = "Pool not available"
        else:
            async with checkpointer.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT DISTINCT thread_id, MAX(created_at) as last_updated
                    FROM langgraph_checkpoints
                    GROUP BY thread_id
                    ORDER BY last_updated DESC
                    LIMIT 100
                """)

                for row in rows:
                    threads.append({
                        "thread_id": row["thread_id"],
                        "last_updated": row["last_updated"].isoformat() if row["last_updated"] else None,
                    })

    except Exception as e:
        error = str(e)
        logger.error("graph_threads_error", error=error)

    if error:
        content = f"""
            <h1>Graph Threads</h1>
            <div class="card">
                <p class="empty" style="color: #fca5a5;">Error: {error}</p>
            </div>
        """
    elif not threads:
        content = """
            <h1>Graph Threads</h1>
            <div class="card">
                <p class="empty">No threads found. Threads are created when conversations start.</p>
            </div>
        """
    else:
        rows = ""
        for t in threads:
            # Parse channel and thread_ts from thread_id
            parts = t["thread_id"].split(":")
            channel = parts[0] if parts else "-"
            thread_ts = parts[1] if len(parts) > 1 else "-"

            rows += f"""
                <tr>
                    <td class="thread-id">{t["thread_id"]}</td>
                    <td>{channel}</td>
                    <td>{thread_ts}</td>
                    <td class="time">{format_time(t["last_updated"])}</td>
                    <td>
                        <a href="/admin/graph/threads/{t["thread_id"]}" class="btn">View State</a>
                    </td>
                </tr>
            """

        content = f"""
            <h1>Graph Threads ({len(threads)})</h1>
            <div class="card">
                <table>
                    <thead>
                        <tr>
                            <th>Thread ID</th>
                            <th>Channel</th>
                            <th>Thread TS</th>
                            <th>Last Updated</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows}
                    </tbody>
                </table>
            </div>
        """

    return render_page("Graph Threads", content, active="graph")


@router.get("/graph/threads/{thread_id:path}", response_class=HTMLResponse)
async def get_graph_thread_state_html(thread_id: str):
    """Get the current state of a LangGraph thread with HTML UI."""
    try:
        from src.graph.checkpointer import get_thread_state

        state = await get_thread_state(thread_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

        current_phase = state.get("current_phase", "-")
        intent = state.get("intent", "-")
        awaiting_human = state.get("awaiting_human", False)

        # Format state for display
        state_rows = ""
        for key, value in sorted(state.items()):
            if key == "messages":
                display_value = f"[{len(value)} messages]" if value else "[]"
            elif isinstance(value, list) and len(value) > 5:
                display_value = f"[{len(value)} items]"
            elif isinstance(value, dict):
                display_value = f"<pre>{json.dumps(value, indent=2, default=str)[:500]}</pre>"
            elif isinstance(value, str) and len(value) > 200:
                display_value = value[:200] + "..."
            else:
                display_value = str(value) if value is not None else "-"

            state_rows += f"""
                <tr>
                    <td style="font-weight: 500; color: #94a3b8;">{key}</td>
                    <td>{display_value}</td>
                </tr>
            """

        content = f"""
            <h1>Thread State</h1>
            <p><a href="/admin/graph/threads">← Back to Threads</a></p>

            <div class="card">
                <h2>Overview</h2>
                <table>
                    <tr><td>Thread ID</td><td class="thread-id">{thread_id}</td></tr>
                    <tr><td>Current Phase</td><td><span class="phase">{current_phase}</span></td></tr>
                    <tr><td>Intent</td><td>{intent}</td></tr>
                    <tr><td>Awaiting Human</td><td>{'Yes' if awaiting_human else 'No'}</td></tr>
                </table>
            </div>

            <div class="card">
                <h2>Full State</h2>
                <table>
                    <thead>
                        <tr><th>Key</th><th>Value</th></tr>
                    </thead>
                    <tbody>
                        {state_rows}
                    </tbody>
                </table>
            </div>
        """

        return render_page(f"Thread {thread_id}", content, active="graph")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("graph_state_error", thread_id=thread_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Graph Visualization
# =============================================================================


def _get_graph_data() -> dict[str, Any]:
    """Extract graph structure for D3.js visualization."""
    from src.graph.graph import create_graph

    graph = create_graph(checkpointer=None)
    drawable = graph.get_graph()

    # Node descriptions and metadata
    node_info = {
        "__start__": {"description": "Entry point", "type": "start"},
        "__end__": {"description": "Exit point", "type": "end"},
        "intake": {"description": "Classify intent and route message", "type": "router"},
        "memory_lookup": {"description": "Retrieve context from Zep memory", "type": "memory"},
        "discovery": {"description": "Ask clarifying questions", "type": "phase"},
        "architecture": {"description": "Present architecture options", "type": "phase"},
        "scope_confirmation": {"description": "Confirm project scope", "type": "phase"},
        "story_generation": {"description": "Generate user stories", "type": "phase"},
        "task_breakdown": {"description": "Break stories into tasks", "type": "phase"},
        "estimation": {"description": "Estimate effort and timeline", "type": "phase"},
        "security_review": {"description": "Security analysis", "type": "phase"},
        "validation": {"description": "Validate completeness", "type": "phase"},
        "review_summary": {"description": "Final review summary", "type": "phase"},
        "jira_sync": {"description": "Sync with Jira", "type": "integration"},
        "jira_command": {"description": "Handle Jira commands", "type": "integration"},
        "impact_analysis": {"description": "Analyze change impact", "type": "analysis"},
        "respond": {"description": "Format and send response", "type": "output"},
        "general_response": {"description": "Handle general queries", "type": "output"},
        "clarify": {"description": "Ask for clarification", "type": "output"},
    }

    nodes = []
    edges = []

    # Extract nodes
    for node_id in drawable.nodes:
        info = node_info.get(node_id, {"description": "Processing node", "type": "default"})
        nodes.append({
            "id": node_id,
            "label": node_id.replace("_", " ").title(),
            "description": info["description"],
            "type": info["type"],
        })

    # Extract edges
    for edge in drawable.edges:
        source = edge.source if hasattr(edge, 'source') else edge[0]
        target = edge.target if hasattr(edge, 'target') else edge[1]
        label = edge.data if hasattr(edge, 'data') else (edge[2] if len(edge) > 2 else "")
        edges.append({
            "source": source,
            "target": target,
            "label": label or "",
        })

    return {"nodes": nodes, "edges": edges}


@router.get("/graph/mermaid", response_class=HTMLResponse)
async def get_graph_mermaid_html():
    """Get Mermaid diagram of the workflow graph with HTML UI."""
    try:
        from src.graph.graph import create_graph

        graph = create_graph(checkpointer=None)
        mermaid = graph.get_graph().draw_mermaid()

        content = f"""
            <h1>Workflow Graph</h1>
            <p style="margin-bottom: 15px;">
                <a href="/admin/graph/visualize" class="btn">View Interactive D3.js Graph →</a>
            </p>

            <div class="card">
                <h2>Mermaid Diagram</h2>
                <p style="margin-bottom: 15px; color: #94a3b8;">
                    Copy the code below to
                    <a href="https://mermaid.live/" target="_blank" style="color: #38bdf8;">mermaid.live</a>
                    for editing.
                </p>
                <pre>{mermaid}</pre>
            </div>

            <div class="card">
                <h2>Rendered Preview</h2>
                <div class="mermaid">
                    {mermaid}
                </div>
            </div>

            <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
            <script>
                mermaid.initialize({{ startOnLoad: true, theme: 'dark' }});
            </script>
        """

        return render_page("Graph Diagram", content, active="mermaid")

    except Exception as e:
        logger.error("graph_mermaid_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph/visualize", response_class=HTMLResponse)
async def visualize_graph_d3():
    """Interactive D3.js knowledge graph visualization with property panel."""
    try:
        graph_data = _get_graph_data()
        graph_json = json.dumps(graph_data)

        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Knowledge Graph - MARO Admin</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            overflow: hidden;
        }}
        .container {{
            display: flex;
            height: 100vh;
        }}
        #graph-container {{
            flex: 1;
            position: relative;
        }}
        #property-panel {{
            width: 320px;
            background: #1e293b;
            border-left: 1px solid #334155;
            padding: 20px;
            overflow-y: auto;
        }}
        .panel-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }}
        .panel-title {{
            color: #38bdf8;
            font-size: 1.2rem;
            font-weight: 600;
        }}
        .back-link {{
            color: #64748b;
            text-decoration: none;
            font-size: 0.9rem;
        }}
        .back-link:hover {{ color: #94a3b8; }}
        .property-group {{
            margin-bottom: 20px;
        }}
        .property-label {{
            color: #64748b;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 5px;
        }}
        .property-value {{
            color: #e2e8f0;
            font-size: 0.95rem;
            padding: 8px 12px;
            background: #0f172a;
            border-radius: 6px;
        }}
        .node-type {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 500;
        }}
        .type-start {{ background: #065f46; color: #34d399; }}
        .type-end {{ background: #7f1d1d; color: #fca5a5; }}
        .type-router {{ background: #7c3aed; color: white; }}
        .type-phase {{ background: #0284c7; color: white; }}
        .type-memory {{ background: #c026d3; color: white; }}
        .type-integration {{ background: #ea580c; color: white; }}
        .type-analysis {{ background: #0891b2; color: white; }}
        .type-output {{ background: #16a34a; color: white; }}
        .type-default {{ background: #475569; color: white; }}
        .connections-list {{
            list-style: none;
        }}
        .connections-list li {{
            padding: 6px 0;
            border-bottom: 1px solid #334155;
            font-size: 0.9rem;
        }}
        .connections-list li:last-child {{ border-bottom: none; }}
        .connection-arrow {{ color: #64748b; margin: 0 8px; }}
        .empty-state {{
            color: #64748b;
            font-style: italic;
            text-align: center;
            padding: 40px 20px;
        }}
        .legend {{
            position: absolute;
            bottom: 20px;
            left: 20px;
            background: #1e293b;
            padding: 15px;
            border-radius: 8px;
            font-size: 0.8rem;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            margin-bottom: 6px;
        }}
        .legend-item:last-child {{ margin-bottom: 0; }}
        .legend-dot {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }}
        .controls {{
            position: absolute;
            top: 20px;
            left: 20px;
            background: #1e293b;
            padding: 10px;
            border-radius: 8px;
        }}
        .controls button {{
            background: #334155;
            color: #e2e8f0;
            border: none;
            padding: 8px 12px;
            margin-right: 5px;
            border-radius: 4px;
            cursor: pointer;
        }}
        .controls button:hover {{ background: #475569; }}
        svg {{ width: 100%; height: 100%; }}
        .link {{
            stroke: #475569;
            stroke-opacity: 0.6;
            fill: none;
        }}
        .link-label {{
            fill: #64748b;
            font-size: 10px;
        }}
        .node circle {{
            stroke: #1e293b;
            stroke-width: 2px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .node circle:hover {{
            stroke: #38bdf8;
            stroke-width: 3px;
        }}
        .node.selected circle {{
            stroke: #38bdf8;
            stroke-width: 4px;
        }}
        .node text {{
            fill: #e2e8f0;
            font-size: 11px;
            pointer-events: none;
        }}
        marker {{
            fill: #475569;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div id="graph-container">
            <div class="controls">
                <button onclick="zoomIn()">Zoom +</button>
                <button onclick="zoomOut()">Zoom -</button>
                <button onclick="resetZoom()">Reset</button>
            </div>
            <svg id="graph"></svg>
            <div class="legend">
                <div class="legend-item"><div class="legend-dot" style="background: #34d399;"></div> Start/End</div>
                <div class="legend-item"><div class="legend-dot" style="background: #7c3aed;"></div> Router</div>
                <div class="legend-item"><div class="legend-dot" style="background: #0284c7;"></div> Phase</div>
                <div class="legend-item"><div class="legend-dot" style="background: #c026d3;"></div> Memory</div>
                <div class="legend-item"><div class="legend-dot" style="background: #ea580c;"></div> Integration</div>
                <div class="legend-item"><div class="legend-dot" style="background: #16a34a;"></div> Output</div>
            </div>
        </div>
        <div id="property-panel">
            <div class="panel-header">
                <span class="panel-title">Properties</span>
                <a href="/admin/graph/mermaid" class="back-link">← Mermaid View</a>
            </div>
            <div id="properties-content">
                <p class="empty-state">Click on a node to view its properties</p>
            </div>
        </div>
    </div>

    <script>
        const graphData = {graph_json};

        // Color mapping
        const typeColors = {{
            start: '#34d399',
            end: '#f87171',
            router: '#7c3aed',
            phase: '#0284c7',
            memory: '#c026d3',
            integration: '#ea580c',
            analysis: '#0891b2',
            output: '#16a34a',
            default: '#64748b'
        }};

        const width = document.getElementById('graph-container').clientWidth;
        const height = document.getElementById('graph-container').clientHeight;

        const svg = d3.select('#graph')
            .attr('viewBox', [0, 0, width, height]);

        // Add arrow marker
        svg.append('defs').append('marker')
            .attr('id', 'arrowhead')
            .attr('viewBox', '-0 -5 10 10')
            .attr('refX', 20)
            .attr('refY', 0)
            .attr('orient', 'auto')
            .attr('markerWidth', 8)
            .attr('markerHeight', 8)
            .append('path')
            .attr('d', 'M 0,-5 L 10,0 L 0,5')
            .attr('fill', '#475569');

        const g = svg.append('g');

        // Zoom behavior
        const zoom = d3.zoom()
            .scaleExtent([0.3, 3])
            .on('zoom', (event) => g.attr('transform', event.transform));

        svg.call(zoom);

        // Create simulation
        const simulation = d3.forceSimulation(graphData.nodes)
            .force('link', d3.forceLink(graphData.edges).id(d => d.id).distance(120))
            .force('charge', d3.forceManyBody().strength(-400))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius(40));

        // Draw links
        const link = g.append('g')
            .selectAll('path')
            .data(graphData.edges)
            .join('path')
            .attr('class', 'link')
            .attr('marker-end', 'url(#arrowhead)');

        // Draw link labels
        const linkLabels = g.append('g')
            .selectAll('text')
            .data(graphData.edges.filter(d => d.label))
            .join('text')
            .attr('class', 'link-label')
            .text(d => d.label);

        // Draw nodes
        const node = g.append('g')
            .selectAll('g')
            .data(graphData.nodes)
            .join('g')
            .attr('class', 'node')
            .call(d3.drag()
                .on('start', dragstarted)
                .on('drag', dragged)
                .on('end', dragended))
            .on('click', selectNode);

        node.append('circle')
            .attr('r', d => d.type === 'start' || d.type === 'end' ? 15 : 20)
            .attr('fill', d => typeColors[d.type] || typeColors.default);

        node.append('text')
            .attr('dy', 35)
            .attr('text-anchor', 'middle')
            .text(d => d.label);

        // Update positions
        simulation.on('tick', () => {{
            link.attr('d', d => {{
                const dx = d.target.x - d.source.x;
                const dy = d.target.y - d.source.y;
                return `M${{d.source.x}},${{d.source.y}} L${{d.target.x}},${{d.target.y}}`;
            }});

            linkLabels
                .attr('x', d => (d.source.x + d.target.x) / 2)
                .attr('y', d => (d.source.y + d.target.y) / 2);

            node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
        }});

        // Drag functions
        function dragstarted(event) {{
            if (!event.active) simulation.alphaTarget(0.3).restart();
            event.subject.fx = event.subject.x;
            event.subject.fy = event.subject.y;
        }}

        function dragged(event) {{
            event.subject.fx = event.x;
            event.subject.fy = event.y;
        }}

        function dragended(event) {{
            if (!event.active) simulation.alphaTarget(0);
            event.subject.fx = null;
            event.subject.fy = null;
        }}

        // Select node and show properties
        let selectedNode = null;

        function selectNode(event, d) {{
            // Deselect previous
            d3.selectAll('.node').classed('selected', false);

            // Select current
            d3.select(this).classed('selected', true);
            selectedNode = d;

            // Find connections
            const incoming = graphData.edges.filter(e => e.target.id === d.id || e.target === d.id);
            const outgoing = graphData.edges.filter(e => e.source.id === d.id || e.source === d.id);

            // Update property panel
            const panel = document.getElementById('properties-content');
            panel.innerHTML = `
                <div class="property-group">
                    <div class="property-label">Node ID</div>
                    <div class="property-value">${{d.id}}</div>
                </div>
                <div class="property-group">
                    <div class="property-label">Label</div>
                    <div class="property-value">${{d.label}}</div>
                </div>
                <div class="property-group">
                    <div class="property-label">Type</div>
                    <div class="property-value">
                        <span class="node-type type-${{d.type}}">${{d.type}}</span>
                    </div>
                </div>
                <div class="property-group">
                    <div class="property-label">Description</div>
                    <div class="property-value">${{d.description}}</div>
                </div>
                <div class="property-group">
                    <div class="property-label">Incoming Connections (${{incoming.length}})</div>
                    <div class="property-value">
                        ${{incoming.length ? `<ul class="connections-list">
                            ${{incoming.map(e => `<li>${{typeof e.source === 'object' ? e.source.id : e.source}}<span class="connection-arrow">→</span>${{d.id}}${{e.label ? ` (${{e.label}})` : ''}}</li>`).join('')}}
                        </ul>` : '<em style="color: #64748b;">None</em>'}}
                    </div>
                </div>
                <div class="property-group">
                    <div class="property-label">Outgoing Connections (${{outgoing.length}})</div>
                    <div class="property-value">
                        ${{outgoing.length ? `<ul class="connections-list">
                            ${{outgoing.map(e => `<li>${{d.id}}<span class="connection-arrow">→</span>${{typeof e.target === 'object' ? e.target.id : e.target}}${{e.label ? ` (${{e.label}})` : ''}}</li>`).join('')}}
                        </ul>` : '<em style="color: #64748b;">None</em>'}}
                    </div>
                </div>
            `;
        }}

        // Zoom controls
        function zoomIn() {{
            svg.transition().call(zoom.scaleBy, 1.3);
        }}

        function zoomOut() {{
            svg.transition().call(zoom.scaleBy, 0.7);
        }}

        function resetZoom() {{
            svg.transition().call(zoom.transform, d3.zoomIdentity);
        }}
    </script>
</body>
</html>
"""
        return HTMLResponse(content=html)

    except Exception as e:
        logger.error("graph_visualize_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/graph/data")
async def get_graph_data_api() -> dict[str, Any]:
    """API: Get graph structure for visualization."""
    try:
        return _get_graph_data()
    except Exception as e:
        logger.error("api_graph_data_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


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
