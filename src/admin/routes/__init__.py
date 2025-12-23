"""
Admin routes package.

Provides the combined router with all admin endpoints.
"""

from fastapi import APIRouter

from src.admin.routes.dashboard import router as dashboard_router
from src.admin.routes.zep_sessions import router as zep_sessions_router
from src.admin.routes.knowledge_graph import router as knowledge_graph_router
from src.admin.routes.graph import router as graph_router
from src.admin.routes.api import router as api_router

# Create combined router
router = APIRouter(prefix="/admin", tags=["admin"])

# Include all sub-routers
router.include_router(dashboard_router)
router.include_router(zep_sessions_router)
router.include_router(knowledge_graph_router)
router.include_router(graph_router)
router.include_router(api_router)

__all__ = ["router"]
