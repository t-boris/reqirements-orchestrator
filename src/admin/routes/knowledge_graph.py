"""Knowledge graph visualization."""

from typing import Any, Optional
import json

import structlog
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from src.admin.routes.base import render_page

logger = structlog.get_logger()

router = APIRouter()


# Type colors for nodes
TYPE_COLORS = {
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
REL_COLORS = {
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
    "has_gap": "#f97316",
    "mentions": "#475569",
}


@router.get("/zep/knowledge-graph", response_class=HTMLResponse)
async def zep_knowledge_graph(session_id: Optional[str] = Query(None, description="Session ID to display")):
    """Interactive D3.js knowledge graph - single session view without session nodes."""
    from src.memory.zep_client import get_http_client
    from src.memory.entity_extractor import _knowledge_graphs

    nodes = []
    edges = []
    node_ids = {}  # name -> id mapping
    existing_node_ids = set()
    all_sessions = []

    # Get all available sessions from Zep
    try:
        client = await get_http_client()
        sessions_response = await client.get("/api/v1/sessions")
        if sessions_response.status_code == 200:
            sessions_data = sessions_response.json()
            sessions = sessions_data if isinstance(sessions_data, list) else sessions_data.get("sessions", [])
            all_sessions = [s.get("session_id", s.get("uuid")) for s in sessions if s.get("session_id") or s.get("uuid")]
    except Exception as e:
        logger.error("knowledge_graph_sessions_error", error=str(e))

    # Add in-memory sessions
    for sid in _knowledge_graphs.keys():
        if sid not in all_sessions:
            all_sessions.append(sid)

    # If no session specified, use first available
    if not session_id and all_sessions:
        session_id = all_sessions[0]

    # Build graph for selected session only
    if session_id:
        # 1. Get from in-memory knowledge graphs
        if session_id in _knowledge_graphs:
            kg = _knowledge_graphs[session_id]
            kg_data = kg.to_dict()

            for entity in kg_data.get("entities", []):
                entity_name = entity.get("name", "")
                entity_type = entity.get("type", "requirement")
                entity_id = f"{entity_type}_{entity_name.lower().replace(' ', '_')[:50]}"

                if entity_id not in existing_node_ids:
                    nodes.append({
                        "id": entity_id,
                        "label": entity_name[:30],
                        "type": entity_type,
                        "description": entity.get("description", entity_name),
                        "attributes": entity.get("attributes", {}),
                        "color": TYPE_COLORS.get(entity_type, "#64748b"),
                        "size": 10,
                    })
                    existing_node_ids.add(entity_id)
                    node_ids[entity_name] = entity_id

            for rel in kg_data.get("relationships", []):
                source_id = node_ids.get(rel.get("source"))
                target_id = node_ids.get(rel.get("target"))
                if source_id and target_id:
                    edges.append({
                        "source": source_id,
                        "target": target_id,
                        "type": rel.get("type", "affects"),
                        "label": rel.get("type", "affects").replace("_", " "),
                        "color": REL_COLORS.get(rel.get("type"), "#64748b"),
                    })

            # Add gaps connected to entities only
            for i, gap in enumerate(kg_data.get("knowledge_gaps", [])):
                gap_entity = gap.get("entity")
                if gap_entity and gap_entity in node_ids:
                    gap_id = f"gap_{i}"
                    if gap_id not in existing_node_ids:
                        nodes.append({
                            "id": gap_id,
                            "label": f"Gap: {gap.get('gap_type', '')[:15]}",
                            "type": "gap",
                            "description": gap.get("description", ""),
                            "color": TYPE_COLORS["gap"],
                            "size": 8,
                            "dashed": True,
                        })
                        existing_node_ids.add(gap_id)
                        edges.append({
                            "source": node_ids[gap_entity],
                            "target": gap_id,
                            "type": "has_gap",
                            "label": "has gap",
                            "color": REL_COLORS["has_gap"],
                            "dashed": True,
                        })

        # 2. Get from Zep memory
        try:
            client = await get_http_client()
            memory_response = await client.get(f"/api/v1/sessions/{session_id}/memory")
            if memory_response.status_code == 200:
                memory_data = memory_response.json()

                # Process facts as nodes
                for i, fact in enumerate(memory_data.get("facts", []) or []):
                    fact_text = fact if isinstance(fact, str) else fact.get("fact", str(fact))
                    fact_id = f"fact_{i}"

                    if fact_id not in existing_node_ids:
                        nodes.append({
                            "id": fact_id,
                            "label": fact_text[:40] + "..." if len(fact_text) > 40 else fact_text,
                            "type": "fact",
                            "description": fact_text,
                            "color": TYPE_COLORS["fact"],
                            "size": 10,
                        })
                        existing_node_ids.add(fact_id)

                # Process entities and relationships from messages
                for msg in memory_data.get("messages", []) or []:
                    metadata = msg.get("metadata", {}) or {}

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
                                "color": TYPE_COLORS.get(entity_type, "#64748b"),
                                "size": 10,
                            })
                            existing_node_ids.add(entity_id)
                            node_ids[entity_name] = entity_id

                    for rel in metadata.get("relationships", []) or []:
                        if not isinstance(rel, dict):
                            continue
                        source_id = node_ids.get(rel.get("source"))
                        target_id = node_ids.get(rel.get("target"))
                        if source_id and target_id:
                            edges.append({
                                "source": source_id,
                                "target": target_id,
                                "type": rel.get("type", "affects"),
                                "label": rel.get("type", "affects").replace("_", " "),
                                "color": REL_COLORS.get(rel.get("type"), "#64748b"),
                            })

                    for i, gap in enumerate(metadata.get("knowledge_gaps", []) or []):
                        if not isinstance(gap, dict):
                            continue
                        gap_entity = gap.get("entity")
                        if gap_entity and gap_entity in node_ids:
                            gap_id = f"msg_gap_{i}"
                            if gap_id not in existing_node_ids:
                                nodes.append({
                                    "id": gap_id,
                                    "label": f"Gap: {gap.get('gap_type', '')[:15]}",
                                    "type": "gap",
                                    "description": gap.get("description", ""),
                                    "color": TYPE_COLORS["gap"],
                                    "size": 8,
                                    "dashed": True,
                                })
                                existing_node_ids.add(gap_id)
                                edges.append({
                                    "source": node_ids[gap_entity],
                                    "target": gap_id,
                                    "type": "has_gap",
                                    "label": "has gap",
                                    "color": REL_COLORS["has_gap"],
                                    "dashed": True,
                                })
        except Exception as e:
            logger.error("knowledge_graph_memory_error", error=str(e))

    # Placeholder if no data
    if not nodes:
        nodes = [{"id": "no_data", "label": "No Data Yet", "type": "info", "description": "Start conversations to build knowledge", "color": "#64748b", "size": 15}]

    # Stats
    entity_counts = {}
    gap_count = 0
    for n in nodes:
        t = n.get("type", "unknown")
        if t == "gap":
            gap_count += 1
        elif t != "info":
            entity_counts[t] = entity_counts.get(t, 0) + 1

    # Session options for dropdown
    session_options = "".join(
        f'<option value="{s}" {"selected" if s == session_id else ""}>{s.replace("channel-", "")[:30]}</option>'
        for s in all_sessions
    )

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
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; overflow: hidden; }}
        .container {{ display: flex; height: 100vh; }}
        #graph-container {{ flex: 1; position: relative; }}
        #panel {{ width: 350px; background: #1e293b; border-left: 1px solid #334155; padding: 20px; overflow-y: auto; }}
        .panel-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
        .panel-title {{ color: #38bdf8; font-size: 1.1rem; font-weight: 600; }}
        .back-link {{ color: #64748b; text-decoration: none; font-size: 0.85rem; }}
        .back-link:hover {{ color: #94a3b8; }}
        .prop-group {{ margin-bottom: 15px; }}
        .prop-label {{ color: #64748b; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }}
        .prop-value {{ color: #e2e8f0; font-size: 0.85rem; padding: 8px 10px; background: #0f172a; border-radius: 6px; word-wrap: break-word; }}
        .node-type {{ display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 500; color: white; }}
        .conn-item {{ padding: 5px 8px; margin: 3px 0; background: #334155; border-radius: 4px; font-size: 0.8rem; }}
        .conn-label {{ color: #94a3b8; font-size: 0.7rem; }}
        .empty {{ color: #64748b; font-style: italic; text-align: center; padding: 30px; }}
        .controls {{ position: absolute; top: 15px; left: 15px; background: #1e293b; padding: 10px; border-radius: 8px; display: flex; gap: 8px; align-items: center; }}
        .controls button {{ background: #334155; color: #e2e8f0; border: none; padding: 6px 10px; border-radius: 4px; cursor: pointer; font-size: 0.8rem; }}
        .controls button:hover {{ background: #475569; }}
        .controls select {{ background: #334155; color: #e2e8f0; border: none; padding: 6px 8px; border-radius: 4px; font-size: 0.8rem; }}
        .stats {{ position: absolute; top: 15px; right: 370px; background: #1e293b; padding: 8px 12px; border-radius: 8px; font-size: 0.75rem; display: flex; gap: 15px; }}
        .stat {{ text-align: center; }}
        .stat-val {{ font-size: 1.1rem; font-weight: bold; color: #38bdf8; }}
        .stat-lbl {{ color: #64748b; font-size: 0.65rem; }}
        .legend {{ position: absolute; bottom: 15px; left: 15px; background: #1e293b; padding: 12px; border-radius: 8px; font-size: 0.7rem; max-height: 250px; overflow-y: auto; }}
        .legend h4 {{ color: #94a3b8; margin-bottom: 8px; font-size: 0.75rem; }}
        .legend-item {{ display: flex; align-items: center; margin-bottom: 3px; }}
        .legend-dot {{ width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; }}
        .legend-line {{ width: 16px; height: 2px; margin-right: 5px; }}
        svg {{ width: 100%; height: 100%; }}
        .link {{ stroke-opacity: 0.6; fill: none; }}
        .link.dashed {{ stroke-dasharray: 5,5; }}
        .link-label {{ fill: #64748b; font-size: 7px; }}
        .node circle {{ stroke: #1e293b; stroke-width: 2px; cursor: pointer; }}
        .node circle:hover {{ stroke: #38bdf8; stroke-width: 3px; }}
        .node.selected circle {{ stroke: #38bdf8; stroke-width: 4px; }}
        .node.gap circle {{ stroke-dasharray: 3,3; }}
        .node text {{ fill: #e2e8f0; font-size: 8px; pointer-events: none; }}
    </style>
</head>
<body>
    <div class="container">
        <div id="graph-container">
            <div class="controls">
                <button onclick="zoomIn()">+</button>
                <button onclick="zoomOut()">-</button>
                <button onclick="resetZoom()">Reset</button>
                <select id="session-select" onchange="changeSession(this.value)">
                    {session_options if session_options else '<option value="">No sessions</option>'}
                </select>
                <select id="filter-type" onchange="filterByType(this.value)">
                    <option value="all">All Types</option>
                    <option value="requirement">Requirements</option>
                    <option value="constraint">Constraints</option>
                    <option value="component">Components</option>
                    <option value="stakeholder">Stakeholders</option>
                    <option value="risk">Risks</option>
                    <option value="gap">Gaps</option>
                    <option value="fact">Facts</option>
                </select>
            </div>
            <div class="stats">
                <div class="stat"><div class="stat-val">{len(nodes)}</div><div class="stat-lbl">Nodes</div></div>
                <div class="stat"><div class="stat-val">{len(edges)}</div><div class="stat-lbl">Edges</div></div>
                <div class="stat"><div class="stat-val">{gap_count}</div><div class="stat-lbl">Gaps</div></div>
            </div>
            <svg id="graph"></svg>
            <div class="legend">
                <h4>Entity Types</h4>
                <div class="legend-item"><div class="legend-dot" style="background: #0284c7;"></div> Requirement/Fact</div>
                <div class="legend-item"><div class="legend-dot" style="background: #dc2626;"></div> Constraint</div>
                <div class="legend-item"><div class="legend-dot" style="background: #16a34a;"></div> Acceptance Criteria</div>
                <div class="legend-item"><div class="legend-dot" style="background: #ea580c;"></div> Risk</div>
                <div class="legend-item"><div class="legend-dot" style="background: #7c3aed;"></div> Dependency</div>
                <div class="legend-item"><div class="legend-dot" style="background: #0891b2;"></div> Stakeholder</div>
                <div class="legend-item"><div class="legend-dot" style="background: #4f46e5;"></div> Component</div>
                <div class="legend-item"><div class="legend-dot" style="background: #f97316;"></div> Gap</div>
                <h4 style="margin-top:10px;">Relationships</h4>
                <div class="legend-item"><div class="legend-line" style="background: #dc2626;"></div> requires</div>
                <div class="legend-item"><div class="legend-line" style="background: #7c3aed;"></div> depends on</div>
                <div class="legend-item"><div class="legend-line" style="background: #16a34a;"></div> implements</div>
                <div class="legend-item"><div class="legend-line" style="background: #f97316;"></div> has gap</div>
            </div>
        </div>
        <div id="panel">
            <div class="panel-header">
                <span class="panel-title">Knowledge Graph</span>
                <a href="/admin/dashboard" class="back-link">← Dashboard</a>
            </div>
            <div id="props">
                <p class="empty">Click a node to view details</p>
                <div class="prop-group" style="margin-top:20px;">
                    <div class="prop-label">Session</div>
                    <div class="prop-value">{session_id or 'None selected'}</div>
                </div>
                <div class="prop-group">
                    <div class="prop-label">Entity Types</div>
                    <div class="prop-value">{', '.join(f'{k}: {v}' for k, v in sorted(entity_counts.items())[:6]) or 'None'}</div>
                </div>
            </div>
        </div>
    </div>
    <script>
        const graphData = {graph_json};
        const width = document.getElementById('graph-container').clientWidth;
        const height = document.getElementById('graph-container').clientHeight;
        const svg = d3.select('#graph').attr('viewBox', [0, 0, width, height]);
        const defs = svg.append('defs');
        ['#475569','#dc2626','#16a34a','#7c3aed','#f97316','#0284c7'].forEach((c,i) => {{
            defs.append('marker').attr('id',`arr${{i}}`).attr('viewBox','-0 -5 10 10').attr('refX',18).attr('refY',0).attr('orient','auto').attr('markerWidth',5).attr('markerHeight',5).append('path').attr('d','M0,-5L10,0L0,5').attr('fill',c);
        }});
        const g = svg.append('g');
        const zoom = d3.zoom().scaleExtent([0.1,4]).on('zoom', e => g.attr('transform', e.transform));
        svg.call(zoom);
        let simulation, link, node;
        function updateGraph(data) {{
            g.selectAll('*').remove();
            simulation = d3.forceSimulation(data.nodes)
                .force('link', d3.forceLink(data.edges).id(d=>d.id).distance(100))
                .force('charge', d3.forceManyBody().strength(-250))
                .force('center', d3.forceCenter(width/2, height/2))
                .force('collision', d3.forceCollide().radius(d=>(d.size||10)+12));
            link = g.append('g').selectAll('path').data(data.edges).join('path')
                .attr('class', d => 'link'+(d.dashed?' dashed':''))
                .attr('stroke', d => d.color||'#475569')
                .attr('stroke-width', 2)
                .attr('marker-end', d => {{const m={{'#dc2626':1,'#16a34a':2,'#7c3aed':3,'#f97316':4,'#0284c7':5}};return `url(#arr${{m[d.color]||0}})`;}});
            g.append('g').selectAll('text').data(data.edges.filter(d=>d.label)).join('text')
                .attr('class','link-label').text(d=>d.label);
            node = g.append('g').selectAll('g').data(data.nodes).join('g')
                .attr('class', d => 'node'+(d.type==='gap'?' gap':''))
                .call(d3.drag().on('start',(e,d)=>{{if(!e.active)simulation.alphaTarget(0.3).restart();d.fx=d.x;d.fy=d.y;}}).on('drag',(e,d)=>{{d.fx=e.x;d.fy=e.y;}}).on('end',(e,d)=>{{if(!e.active)simulation.alphaTarget(0);d.fx=null;d.fy=null;}}))
                .on('click', selectNode);
            node.append('circle').attr('r', d=>d.size||10).attr('fill', d=>d.color||'#64748b');
            node.append('text').attr('dy', d=>(d.size||10)+10).attr('text-anchor','middle').text(d=>d.label&&d.label.length>15?d.label.slice(0,15)+'...':d.label);
            simulation.on('tick', () => {{
                link.attr('d', d => `M${{d.source.x}},${{d.source.y}}L${{d.target.x}},${{d.target.y}}`);
                node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
            }});
        }}
        updateGraph(graphData);
        function filterByType(t) {{
            if(t==='all') return updateGraph(graphData);
            const ids = new Set(graphData.nodes.filter(n=>n.type===t).map(n=>n.id));
            const nodes = graphData.nodes.filter(n=>ids.has(n.id));
            const edges = graphData.edges.filter(e=>ids.has(e.source.id||e.source)&&ids.has(e.target.id||e.target));
            updateGraph({{nodes,edges}});
        }}
        function selectNode(e, d) {{
            d3.selectAll('.node').classed('selected',false);
            d3.select(this).classed('selected',true);
            const inc = graphData.edges.filter(e=>(e.target.id||e.target)===d.id);
            const out = graphData.edges.filter(e=>(e.source.id||e.source)===d.id);
            let conn = '';
            if(inc.length||out.length) {{
                const items = [...inc.slice(0,3).map(e=>{{const n=graphData.nodes.find(n=>n.id===(e.source.id||e.source));return `<div class="conn-item"><span class="conn-label">${{e.label}} ←</span> ${{n?.label||'?'}}</div>`}}),
                    ...out.slice(0,3).map(e=>{{const n=graphData.nodes.find(n=>n.id===(e.target.id||e.target));return `<div class="conn-item"><span class="conn-label">${{e.label}} →</span> ${{n?.label||'?'}}</div>`}})].join('');
                conn = `<div class="prop-group"><div class="prop-label">Connections</div><div class="prop-value">${{items}}</div></div>`;
            }}
            document.getElementById('props').innerHTML = `
                <div class="prop-group"><div class="prop-label">Label</div><div class="prop-value">${{d.label}}</div></div>
                <div class="prop-group"><div class="prop-label">Type</div><div class="prop-value"><span class="node-type" style="background:${{d.color||'#64748b'}}">${{d.type}}</span></div></div>
                <div class="prop-group"><div class="prop-label">Description</div><div class="prop-value">${{d.description||'-'}}</div></div>
                ${{conn}}
                <div class="prop-group"><div class="prop-label">ID</div><div class="prop-value" style="font-family:monospace;font-size:0.7rem;">${{d.id}}</div></div>
            `;
        }}
        function changeSession(s) {{ window.location.href = '/admin/zep/knowledge-graph?session_id=' + encodeURIComponent(s); }}
        function zoomIn() {{ svg.transition().call(zoom.scaleBy, 1.3); }}
        function zoomOut() {{ svg.transition().call(zoom.scaleBy, 0.7); }}
        function resetZoom() {{ svg.transition().call(zoom.transform, d3.zoomIdentity); }}
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html)
