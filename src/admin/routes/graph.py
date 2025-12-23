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

