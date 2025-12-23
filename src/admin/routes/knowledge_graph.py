"""Knowledge graph visualization."""

from typing import Any
import json

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from src.admin.routes.base import (
    render_page,
    format_time,
    BASE_TEMPLATE,
)

logger = structlog.get_logger()

router = APIRouter()

# Knowledge Graph Visualization
# =============================================================================


@router.get("/zep/knowledge-graph", response_class=HTMLResponse)
async def zep_knowledge_graph():
    """Interactive D3.js knowledge graph showing entities, relationships, and gaps."""
    from src.memory.zep_client import get_http_client
    from src.memory.entity_extractor import (
        _knowledge_graphs,
        build_knowledge_graph_data,
        ENTITY_TYPES,
        RELATIONSHIP_TYPES,
    )

    # Collect all entities and facts from all sessions
    nodes = []
    edges = []
    node_ids = {}  # name -> id mapping

    # Type colors for nodes
    type_colors = {
        "session": "#374151",
        "fact": "#0284c7",
        "requirement": "#0284c7",
        "constraint": "#dc2626",
        "acceptance_criteria": "#16a34a",
        "risk": "#ea580c",
        "dependency": "#7c3aed",
        "stakeholder": "#0891b2",
        "component": "#4f46e5",
        "integration": "#c026d3",
        "data_entity": "#65a30d",
        "user_action": "#0d9488",
        "business_rule": "#b91c1c",
        "priority": "#ca8a04",
        "timeline": "#6366f1",
        "technology": "#64748b",
        "gap": "#f97316",
    }

    # Relationship colors
    rel_colors = {
        "requires": "#dc2626",
        "implements": "#16a34a",
        "depends_on": "#7c3aed",
        "conflicts_with": "#ef4444",
        "refines": "#0284c7",
        "belongs_to": "#6366f1",
        "affects": "#f59e0b",
        "validates": "#10b981",
        "uses": "#8b5cf6",
        "owned_by": "#0891b2",
        "contains": "#64748b",
        "has_gap": "#f97316",
        "mentions": "#475569",
        "has_fact": "#475569",
    }

    # 1. Get data from in-memory knowledge graphs first
    if _knowledge_graphs:
        knowledge_by_session = {
            sid: kg.to_dict() for sid, kg in _knowledge_graphs.items()
        }
        graph_data = build_knowledge_graph_data(knowledge_by_session)
        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])
        node_ids = {n["label"]: n["id"] for n in nodes}

    # 2. Also get data from Zep memory
    try:
        client = await get_http_client()

        # Get all sessions
        sessions_response = await client.get("/api/v1/sessions")
        if sessions_response.status_code == 200:
            sessions_data = sessions_response.json()
            sessions = sessions_data if isinstance(sessions_data, list) else sessions_data.get("sessions", [])

            existing_node_ids = {n["id"] for n in nodes}

            for session in sessions:
                session_id = session.get("session_id", session.get("uuid"))
                if not session_id:
                    continue

                # Add session as a central node if not exists
                if session_id not in existing_node_ids:
                    nodes.append({
                        "id": session_id,
                        "label": session_id.replace("channel-", ""),
                        "type": "session",
                        "description": "Channel session",
                        "color": type_colors["session"],
                        "size": 15,
                    })
                    existing_node_ids.add(session_id)

                # Get memory with facts and entities
                memory_response = await client.get(f"/api/v1/sessions/{session_id}/memory")
                if memory_response.status_code == 200:
                    memory_data = memory_response.json()

                    # Process facts
                    for i, fact in enumerate(memory_data.get("facts", []) or []):
                        fact_text = fact if isinstance(fact, str) else fact.get("fact", str(fact))
                        fact_id = f"{session_id}_fact_{i}"

                        if fact_id not in existing_node_ids:
                            nodes.append({
                                "id": fact_id,
                                "label": fact_text[:50] + "..." if len(fact_text) > 50 else fact_text,
                                "type": "fact",
                                "description": fact_text,
                                "color": type_colors["fact"],
                                "size": 10,
                            })
                            existing_node_ids.add(fact_id)
                            edges.append({
                                "source": session_id,
                                "target": fact_id,
                                "type": "has_fact",
                                "label": "has fact",
                                "color": rel_colors["has_fact"],
                            })

                    # Process entities and relationships from messages
                    for msg in memory_data.get("messages", []) or []:
                        metadata = msg.get("metadata", {}) or {}

                        # Process entities
                        for entity in metadata.get("entities", []) or []:
                            if not isinstance(entity, dict):
                                continue
                            entity_name = entity.get("name", "")
                            if not entity_name:
                                continue

                            entity_type = entity.get("type", "requirement")
                            entity_id = f"{entity_type}_{entity_name.lower().replace(' ', '_')[:50]}"

                            if entity_id not in existing_node_ids:
                                nodes.append({
                                    "id": entity_id,
                                    "label": entity_name[:30],
                                    "type": entity_type,
                                    "description": entity.get("description", entity_name),
                                    "attributes": entity.get("attributes", {}),
                                    "color": type_colors.get(entity_type, "#64748b"),
                                    "size": 10,
                                })
                                existing_node_ids.add(entity_id)
                                node_ids[entity_name] = entity_id

                            # Link to session
                            edges.append({
                                "source": session_id,
                                "target": entity_id,
                                "type": "contains",
                                "label": "contains",
                                "color": rel_colors["contains"],
                            })

                        # Process relationships
                        for rel in metadata.get("relationships", []) or []:
                            if not isinstance(rel, dict):
                                continue
                            source_name = rel.get("source", "")
                            target_name = rel.get("target", "")
                            rel_type = rel.get("type", "affects")

                            source_id = node_ids.get(source_name)
                            target_id = node_ids.get(target_name)

                            if source_id and target_id:
                                edges.append({
                                    "source": source_id,
                                    "target": target_id,
                                    "type": rel_type,
                                    "label": rel_type.replace("_", " "),
                                    "description": rel.get("description", ""),
                                    "color": rel_colors.get(rel_type, "#64748b"),
                                })

                        # Process knowledge gaps
                        for i, gap in enumerate(metadata.get("knowledge_gaps", []) or []):
                            if not isinstance(gap, dict):
                                continue
                            gap_id = f"gap_{session_id}_{i}"

                            if gap_id not in existing_node_ids:
                                nodes.append({
                                    "id": gap_id,
                                    "label": f"Gap: {gap.get('gap_type', '')[:15]}",
                                    "type": "gap",
                                    "description": gap.get("description", "Unknown gap"),
                                    "color": type_colors["gap"],
                                    "size": 8,
                                    "dashed": True,
                                })
                                existing_node_ids.add(gap_id)

                                gap_entity = gap.get("entity")
                                if gap_entity and gap_entity in node_ids:
                                    edges.append({
                                        "source": node_ids[gap_entity],
                                        "target": gap_id,
                                        "type": "has_gap",
                                        "label": "has gap",
                                        "color": rel_colors["has_gap"],
                                        "dashed": True,
                                    })
                                else:
                                    edges.append({
                                        "source": session_id,
                                        "target": gap_id,
                                        "type": "has_gap",
                                        "label": "has gap",
                                        "color": rel_colors["has_gap"],
                                        "dashed": True,
                                    })

    except Exception as e:
        logger.error("knowledge_graph_error", error=str(e))

    # If no data, add placeholder
    if not nodes:
        nodes = [
            {"id": "no_data", "label": "No Data Yet", "type": "info", "description": "Start conversations to build the knowledge graph", "color": "#64748b", "size": 15}
        ]
        edges = []

    # Count entity types for stats
    entity_type_counts = {}
    gap_count = 0
    relationship_count = len(edges)
    for n in nodes:
        t = n.get("type", "unknown")
        if t == "gap":
            gap_count += 1
        elif t != "session" and t != "info":
            entity_type_counts[t] = entity_type_counts.get(t, 0) + 1

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
            width: 380px;
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
        .property-group {{ margin-bottom: 15px; }}
        .property-label {{
            color: #64748b;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 5px;
        }}
        .property-value {{
            color: #e2e8f0;
            font-size: 0.9rem;
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
            color: white;
        }}
        .connection-item {{
            padding: 6px 10px;
            margin: 4px 0;
            background: #334155;
            border-radius: 4px;
            font-size: 0.85rem;
        }}
        .connection-label {{
            color: #94a3b8;
            font-size: 0.75rem;
        }}
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
            font-size: 0.75rem;
            max-height: 300px;
            overflow-y: auto;
        }}
        .legend h4 {{ color: #94a3b8; margin-bottom: 10px; font-size: 0.8rem; }}
        .legend-section {{ margin-bottom: 12px; }}
        .legend-item {{
            display: flex;
            align-items: center;
            margin-bottom: 4px;
        }}
        .legend-dot {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 6px;
        }}
        .legend-line {{
            width: 20px;
            height: 2px;
            margin-right: 6px;
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
        .controls select {{
            background: #334155;
            color: #e2e8f0;
            border: none;
            padding: 8px;
            border-radius: 4px;
            margin-left: 10px;
        }}
        .stats {{
            position: absolute;
            top: 20px;
            right: 400px;
            background: #1e293b;
            padding: 10px 15px;
            border-radius: 8px;
            font-size: 0.8rem;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
        }}
        .stat-item {{ text-align: center; }}
        .stat-value {{ font-size: 1.3rem; font-weight: bold; color: #38bdf8; }}
        .stat-label {{ color: #64748b; font-size: 0.7rem; }}
        svg {{ width: 100%; height: 100%; }}
        .link {{ stroke-opacity: 0.6; fill: none; }}
        .link.dashed {{ stroke-dasharray: 5,5; }}
        .link-label {{ fill: #64748b; font-size: 8px; }}
        .node circle {{
            stroke: #1e293b;
            stroke-width: 2px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .node circle:hover {{ stroke: #38bdf8; stroke-width: 3px; }}
        .node.selected circle {{ stroke: #38bdf8; stroke-width: 4px; }}
        .node.gap circle {{ stroke-dasharray: 3,3; }}
        .node text {{ fill: #e2e8f0; font-size: 9px; pointer-events: none; }}
        .attr-list {{ margin-top: 10px; }}
        .attr-item {{
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            border-bottom: 1px solid #334155;
        }}
        .attr-key {{ color: #94a3b8; }}
        .attr-val {{ color: #e2e8f0; }}
    </style>
</head>
<body>
    <div class="container">
        <div id="graph-container">
            <div class="controls">
                <button onclick="zoomIn()">Zoom +</button>
                <button onclick="zoomOut()">Zoom -</button>
                <button onclick="resetZoom()">Reset</button>
                <select id="filter-type" onchange="filterByType(this.value)">
                    <option value="all">All Types</option>
                    <option value="session">Sessions</option>
                    <option value="requirement">Requirements</option>
                    <option value="constraint">Constraints</option>
                    <option value="component">Components</option>
                    <option value="stakeholder">Stakeholders</option>
                    <option value="risk">Risks</option>
                    <option value="gap">Knowledge Gaps</option>
                </select>
            </div>
            <div class="stats">
                <div class="stats-grid">
                    <div class="stat-item">
                        <div class="stat-value">{len(nodes)}</div>
                        <div class="stat-label">Nodes</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value">{len(edges)}</div>
                        <div class="stat-label">Edges</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value">{gap_count}</div>
                        <div class="stat-label">Gaps</div>
                    </div>
                </div>
            </div>
            <svg id="graph"></svg>
            <div class="legend">
                <div class="legend-section">
                    <h4>Entity Types</h4>
                    <div class="legend-item"><div class="legend-dot" style="background: #374151;"></div> Session</div>
                    <div class="legend-item"><div class="legend-dot" style="background: #0284c7;"></div> Requirement/Fact</div>
                    <div class="legend-item"><div class="legend-dot" style="background: #dc2626;"></div> Constraint</div>
                    <div class="legend-item"><div class="legend-dot" style="background: #16a34a;"></div> Acceptance Criteria</div>
                    <div class="legend-item"><div class="legend-dot" style="background: #ea580c;"></div> Risk</div>
                    <div class="legend-item"><div class="legend-dot" style="background: #7c3aed;"></div> Dependency</div>
                    <div class="legend-item"><div class="legend-dot" style="background: #0891b2;"></div> Stakeholder</div>
                    <div class="legend-item"><div class="legend-dot" style="background: #4f46e5;"></div> Component</div>
                    <div class="legend-item"><div class="legend-dot" style="background: #f97316;"></div> Knowledge Gap</div>
                </div>
                <div class="legend-section">
                    <h4>Relationships</h4>
                    <div class="legend-item"><div class="legend-line" style="background: #dc2626;"></div> requires</div>
                    <div class="legend-item"><div class="legend-line" style="background: #7c3aed;"></div> depends on</div>
                    <div class="legend-item"><div class="legend-line" style="background: #16a34a;"></div> implements</div>
                    <div class="legend-item"><div class="legend-line" style="background: #ef4444;"></div> conflicts with</div>
                    <div class="legend-item"><div class="legend-line" style="background: #f97316;"></div> has gap</div>
                </div>
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
                        This graph shows entities, relationships, and knowledge gaps extracted from conversations using LLM-based analysis.
                    </div>
                </div>
                <div class="property-group">
                    <div class="property-label">Entity Types Found</div>
                    <div class="property-value">
                        {', '.join(f'{k}: {v}' for k, v in sorted(entity_type_counts.items())[:5]) or 'None yet'}
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const graphData = {graph_json};
        let filteredData = {{ nodes: [...graphData.nodes], edges: [...graphData.edges] }};

        const width = document.getElementById('graph-container').clientWidth;
        const height = document.getElementById('graph-container').clientHeight;

        const svg = d3.select('#graph').attr('viewBox', [0, 0, width, height]);

        // Create multiple arrow markers with different colors
        const defs = svg.append('defs');
        const arrowColors = ['#475569', '#dc2626', '#16a34a', '#7c3aed', '#f97316', '#0284c7'];
        arrowColors.forEach((color, i) => {{
            defs.append('marker')
                .attr('id', `arrowhead-${{i}}`)
                .attr('viewBox', '-0 -5 10 10')
                .attr('refX', 20)
                .attr('refY', 0)
                .attr('orient', 'auto')
                .attr('markerWidth', 5)
                .attr('markerHeight', 5)
                .append('path')
                .attr('d', 'M 0,-5 L 10,0 L 0,5')
                .attr('fill', color);
        }});

        const g = svg.append('g');

        const zoom = d3.zoom()
            .scaleExtent([0.1, 4])
            .on('zoom', (event) => g.attr('transform', event.transform));

        svg.call(zoom);

        let simulation, link, linkLabels, node;

        function updateGraph(data) {{
            g.selectAll('*').remove();

            simulation = d3.forceSimulation(data.nodes)
                .force('link', d3.forceLink(data.edges).id(d => d.id).distance(d => d.type === 'contains' ? 80 : 120))
                .force('charge', d3.forceManyBody().strength(-200))
                .force('center', d3.forceCenter(width / 2, height / 2))
                .force('collision', d3.forceCollide().radius(d => (d.size || 10) + 15));

            link = g.append('g')
                .selectAll('path')
                .data(data.edges)
                .join('path')
                .attr('class', d => 'link' + (d.dashed ? ' dashed' : ''))
                .attr('stroke', d => d.color || '#475569')
                .attr('stroke-width', d => d.type === 'contains' ? 1 : 2)
                .attr('marker-end', d => {{
                    const colors = {{'#dc2626': 1, '#16a34a': 2, '#7c3aed': 3, '#f97316': 4, '#0284c7': 5}};
                    return `url(#arrowhead-${{colors[d.color] || 0}})`;
                }});

            linkLabels = g.append('g')
                .selectAll('text')
                .data(data.edges.filter(d => d.label && d.type !== 'contains'))
                .join('text')
                .attr('class', 'link-label')
                .text(d => d.label);

            node = g.append('g')
                .selectAll('g')
                .data(data.nodes)
                .join('g')
                .attr('class', d => 'node' + (d.type === 'gap' ? ' gap' : ''))
                .call(d3.drag()
                    .on('start', dragstarted)
                    .on('drag', dragged)
                    .on('end', dragended))
                .on('click', selectNode);

            node.append('circle')
                .attr('r', d => d.size || 10)
                .attr('fill', d => d.color || '#64748b');

            node.append('text')
                .attr('dy', d => (d.size || 10) + 12)
                .attr('text-anchor', 'middle')
                .text(d => d.label && d.label.length > 18 ? d.label.substring(0, 18) + '...' : d.label);

            simulation.on('tick', () => {{
                link.attr('d', d => `M${{d.source.x}},${{d.source.y}} L${{d.target.x}},${{d.target.y}}`);
                linkLabels
                    .attr('x', d => (d.source.x + d.target.x) / 2)
                    .attr('y', d => (d.source.y + d.target.y) / 2);
                node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
            }});
        }}

        updateGraph(graphData);

        function filterByType(type) {{
            if (type === 'all') {{
                filteredData = {{ nodes: [...graphData.nodes], edges: [...graphData.edges] }};
            }} else {{
                const nodeIds = new Set();
                const nodes = graphData.nodes.filter(n => {{
                    if (n.type === type || n.type === 'session') {{
                        nodeIds.add(n.id);
                        return true;
                    }}
                    return false;
                }});
                const edges = graphData.edges.filter(e => {{
                    const sourceId = e.source.id || e.source;
                    const targetId = e.target.id || e.target;
                    return nodeIds.has(sourceId) && nodeIds.has(targetId);
                }});
                filteredData = {{ nodes, edges }};
            }}
            updateGraph(filteredData);
        }}

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

            let attrsHtml = '';
            if (d.attributes && Object.keys(d.attributes).length > 0) {{
                attrsHtml = `
                    <div class="property-group">
                        <div class="property-label">Attributes</div>
                        <div class="property-value">
                            <div class="attr-list">
                                ${{Object.entries(d.attributes).map(([k, v]) =>
                                    `<div class="attr-item"><span class="attr-key">${{k}}</span><span class="attr-val">${{v}}</span></div>`
                                ).join('')}}
                            </div>
                        </div>
                    </div>
                `;
            }}

            let connectionsHtml = '';
            if (incoming.length > 0 || outgoing.length > 0) {{
                const incomingItems = incoming.slice(0, 5).map(e => {{
                    const sourceNode = graphData.nodes.find(n => n.id === (e.source.id || e.source));
                    return `<div class="connection-item"><span class="connection-label">${{e.label || 'connects'}} ←</span> ${{sourceNode?.label || 'unknown'}}</div>`;
                }}).join('');
                const outgoingItems = outgoing.slice(0, 5).map(e => {{
                    const targetNode = graphData.nodes.find(n => n.id === (e.target.id || e.target));
                    return `<div class="connection-item"><span class="connection-label">${{e.label || 'connects'}} →</span> ${{targetNode?.label || 'unknown'}}</div>`;
                }}).join('');
                connectionsHtml = `
                    <div class="property-group">
                        <div class="property-label">Connections (${{incoming.length}} in, ${{outgoing.length}} out)</div>
                        <div class="property-value">
                            ${{incomingItems}}${{outgoingItems}}
                            ${{(incoming.length + outgoing.length) > 10 ? '<div style="color:#64748b;font-size:0.8rem;margin-top:8px;">...and more</div>' : ''}}
                        </div>
                    </div>
                `;
            }}

            const panel = document.getElementById('properties-content');
            panel.innerHTML = `
                <div class="property-group">
                    <div class="property-label">Label</div>
                    <div class="property-value">${{d.label}}</div>
                </div>
                <div class="property-group">
                    <div class="property-label">Type</div>
                    <div class="property-value">
                        <span class="node-type" style="background: ${{d.color || '#64748b'}}">${{d.type}}</span>
                    </div>
                </div>
                <div class="property-group">
                    <div class="property-label">Description</div>
                    <div class="property-value">${{d.description || 'No description'}}</div>
                </div>
                ${{attrsHtml}}
                ${{connectionsHtml}}
                <div class="property-group">
                    <div class="property-label">ID</div>
                    <div class="property-value" style="font-family: monospace; font-size: 0.75rem;">${{d.id}}</div>
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

