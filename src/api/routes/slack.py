"""Slack events endpoint.

Ref: RESEARCH.md - Complete AsyncApp Setup with FastAPI
"""

from fastapi import APIRouter, Request
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

from src.slack.app import get_bolt_app

router = APIRouter(prefix="/slack", tags=["slack"])

# Create handler lazily to avoid import-time app creation
_handler: AsyncSlackRequestHandler | None = None


def get_handler() -> AsyncSlackRequestHandler:
    """Get or create the Slack request handler."""
    global _handler
    if _handler is None:
        _handler = AsyncSlackRequestHandler(get_bolt_app())
    return _handler


@router.post("/events")
async def slack_events(req: Request):
    """Handle all Slack events (messages, actions, commands).

    Slack sends all events to this single endpoint.
    The Bolt handler routes to appropriate listeners.
    """
    return await get_handler().handle(req)
