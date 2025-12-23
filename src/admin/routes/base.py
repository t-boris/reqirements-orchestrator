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

