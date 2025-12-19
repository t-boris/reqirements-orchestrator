"""
Health check endpoints.

Provides liveness and readiness probes for container orchestration.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    """
    Basic health check.

    Returns:
        Health status.
    """
    return {"status": "healthy"}


@router.get("/ready")
async def readiness_check() -> dict:
    """
    Readiness check.

    Verifies all dependencies are available.

    Returns:
        Readiness status.
    """
    # TODO: Add database and Redis connectivity checks
    return {"status": "ready"}
