"""
Admin routes - Re-exports from routes/ package.

This file is kept for backward compatibility.
All route implementations have been moved to src/admin/routes/ package.
"""

# Re-export the combined router
from src.admin.routes import router

__all__ = ["router"]
