"""Jira service factory - creates configured service instances."""

import logging
from functools import lru_cache

from src.config import get_settings
from src.jira.client import JiraClient
from src.jira.preflight import PreflightService
from src.jira.reconciliation import ReconciliationService
from src.jira.sync_service import JiraSyncService

logger = logging.getLogger(__name__)


@lru_cache
def get_jira_client() -> JiraClient:
    """Get cached Jira client instance."""
    settings = get_settings()
    return JiraClient(
        url=settings.jira_url,
        email=settings.jira_user,
        token=settings.jira_api_token,
    )


def get_sync_service() -> JiraSyncService:
    """Create a JiraSyncService with configured dependencies."""
    client = get_jira_client()
    preflight = PreflightService(client)
    return JiraSyncService(client, preflight)


def get_reconciliation_service() -> ReconciliationService:
    """Create a ReconciliationService with configured dependencies."""
    sync_service = get_sync_service()
    return ReconciliationService(sync_service)
