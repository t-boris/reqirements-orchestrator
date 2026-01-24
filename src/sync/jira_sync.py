"""JiraSyncService for syncing channel registry with Jira.

Provides comprehensive sync functionality for Phase 29:
- Fetch current state from Jira for all tracked issues
- Compare with local registry cache
- Detect changes, missing issues, and deleted issues
- Generate reconciliation report with action items

Philosophy from CONTEXT.md:
- Registry = what channel consciously chose to track
- Missing locally -> offer to track, don't auto-add
- Local only -> show, don't auto-remove
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.db.jira_registry import JiraIssueLink, JiraRegistryStore
    from src.jira.client import JiraService

logger = logging.getLogger(__name__)


@dataclass
class SyncChange:
    """A detected change for a single ticket."""

    jira_key: str
    field: str  # summary, status, assignee, etc.
    old_value: Optional[str]  # Local cached value (None if not tracked)
    new_value: str  # Current Jira value


@dataclass
class SyncIssue:
    """An issue in the sync report."""

    jira_key: str
    summary: str
    status: str
    issue_type: str
    changes: list[SyncChange] = field(default_factory=list)


@dataclass
class SyncResult:
    """Result of channel sync operation."""

    channel_id: str
    synced_at: datetime

    # Report sections (from CONTEXT.md)
    changed: list[SyncIssue]  # Jira differs from local cache
    in_sync: list[SyncIssue]  # Matching
    missing_locally: list[SyncIssue]  # In Jira (children) but not tracked
    local_only: list[SyncIssue]  # Tracked but deleted in Jira

    # Stats
    total_checked: int
    errors: list[str] = field(default_factory=list)


class JiraSyncService:
    """Service for syncing channel registry with Jira.

    Philosophy from CONTEXT.md:
    - Registry = what channel consciously chose to track
    - Missing locally -> offer to track, don't auto-add
    - Local only -> show, don't auto-remove
    """

    def __init__(
        self,
        jira_service: "JiraService",
        registry: "JiraRegistryStore",
    ):
        """Initialize sync service.

        Args:
            jira_service: Jira API client
            registry: JiraRegistryStore for channel issue tracking
        """
        self._jira = jira_service
        self._registry = registry

    async def sync_channel(self, channel_id: str) -> SyncResult:
        """Sync all tracked tickets in channel with Jira.

        Steps:
        1. Get all registered issues for channel
        2. For each issue, fetch from Jira API
        3. Compare fields and detect changes
        4. Update registry with fresh data
        5. Find child issues not tracked (missing_locally)
        6. Return comprehensive report

        Args:
            channel_id: Slack channel ID to sync

        Returns:
            SyncResult with full reconciliation report
        """
        synced_at = datetime.now(timezone.utc)
        changed: list[SyncIssue] = []
        in_sync: list[SyncIssue] = []
        missing_locally: list[SyncIssue] = []
        local_only: list[SyncIssue] = []
        errors: list[str] = []

        # Get all registered issues for this channel
        registered_issues = await self._registry.get_channel_issues(channel_id)

        if not registered_issues:
            logger.info(
                "No issues registered for channel",
                extra={"channel_id": channel_id},
            )
            return SyncResult(
                channel_id=channel_id,
                synced_at=synced_at,
                changed=[],
                in_sync=[],
                missing_locally=[],
                local_only=[],
                total_checked=0,
                errors=[],
            )

        # Track which keys we've seen from Jira (for detecting deleted)
        tracked_keys = {link.jira_key for link in registered_issues}
        epic_keys: set[str] = set()

        # Sync each registered issue
        for link in registered_issues:
            sync_issue, issue_errors = await self._sync_single_issue(
                channel_id,
                link,
            )

            if issue_errors:
                errors.extend(issue_errors)

            if sync_issue is None:
                # Issue deleted in Jira
                local_only.append(
                    SyncIssue(
                        jira_key=link.jira_key,
                        summary=link.summary or "(deleted)",
                        status="DELETED_EXTERNALLY",
                        issue_type=link.issue_type or "unknown",
                    )
                )
                # Mark as deleted in registry
                await self._registry.mark_deleted(channel_id, link.jira_key)
            elif sync_issue.changes:
                changed.append(sync_issue)
            else:
                in_sync.append(sync_issue)

            # Track epics for child discovery
            if link.issue_type and link.issue_type.lower() == "epic":
                epic_keys.add(link.jira_key)

        # Find missing children (issues under tracked epics but not in registry)
        if epic_keys:
            missing = await self._find_missing_children(
                channel_id,
                tracked_keys,
                epic_keys,
            )
            missing_locally.extend(missing)

        logger.info(
            "Channel sync complete",
            extra={
                "channel_id": channel_id,
                "total_checked": len(registered_issues),
                "changed": len(changed),
                "in_sync": len(in_sync),
                "missing_locally": len(missing_locally),
                "local_only": len(local_only),
                "errors": len(errors),
            },
        )

        return SyncResult(
            channel_id=channel_id,
            synced_at=synced_at,
            changed=changed,
            in_sync=in_sync,
            missing_locally=missing_locally,
            local_only=local_only,
            total_checked=len(registered_issues),
            errors=errors,
        )

    async def _sync_single_issue(
        self,
        channel_id: str,
        link: "JiraIssueLink",
    ) -> tuple[Optional[SyncIssue], list[str]]:
        """Sync single issue, return SyncIssue and any errors.

        Args:
            channel_id: Slack channel ID
            link: JiraIssueLink from registry

        Returns:
            Tuple of (SyncIssue or None if deleted, list of error messages)
        """
        errors: list[str] = []

        try:
            # Fetch current state from Jira
            jira_issue = await self._jira.get_issue(link.jira_key)

            # Detect changes by comparing fields
            changes: list[SyncChange] = []

            # Check summary
            if link.summary and jira_issue.summary != link.summary:
                changes.append(
                    SyncChange(
                        jira_key=link.jira_key,
                        field="summary",
                        old_value=link.summary,
                        new_value=jira_issue.summary,
                    )
                )

            # Check status
            if link.status and jira_issue.status != link.status:
                changes.append(
                    SyncChange(
                        jira_key=link.jira_key,
                        field="status",
                        old_value=link.status,
                        new_value=jira_issue.status,
                    )
                )

            # Check assignee
            if link.assignee is not None and jira_issue.assignee != link.assignee:
                changes.append(
                    SyncChange(
                        jira_key=link.jira_key,
                        field="assignee",
                        old_value=link.assignee or "(unassigned)",
                        new_value=jira_issue.assignee or "(unassigned)",
                    )
                )

            # Update registry with fresh data
            # Parse updated timestamp from Jira response if available
            jira_updated = datetime.now(timezone.utc)  # Default to now

            await self._registry.update_from_jira(
                channel_id=channel_id,
                jira_key=link.jira_key,
                summary=jira_issue.summary,
                status=jira_issue.status,
                assignee=jira_issue.assignee,
                issue_type=link.issue_type or "unknown",
                jira_updated=jira_updated,
            )

            return (
                SyncIssue(
                    jira_key=link.jira_key,
                    summary=jira_issue.summary,
                    status=jira_issue.status,
                    issue_type=link.issue_type or "unknown",
                    changes=changes,
                ),
                errors,
            )

        except Exception as e:
            error_str = str(e)

            # Check if issue was deleted (404)
            if "404" in error_str or "not found" in error_str.lower():
                logger.warning(
                    "Issue not found in Jira (deleted)",
                    extra={
                        "channel_id": channel_id,
                        "jira_key": link.jira_key,
                    },
                )
                return (None, [])  # No error, just deleted

            # Log other errors
            logger.error(
                f"Failed to sync issue: {e}",
                exc_info=True,
                extra={
                    "channel_id": channel_id,
                    "jira_key": link.jira_key,
                },
            )
            errors.append(f"{link.jira_key}: {error_str}")

            # Return a placeholder with current cached data
            return (
                SyncIssue(
                    jira_key=link.jira_key,
                    summary=link.summary or "(sync error)",
                    status=link.status or "Unknown",
                    issue_type=link.issue_type or "unknown",
                ),
                errors,
            )

    async def _find_missing_children(
        self,
        channel_id: str,
        tracked_keys: set[str],
        epic_keys: set[str],
    ) -> list[SyncIssue]:
        """Find child issues of tracked epics not in registry.

        Uses JQL: parent in (tracked_epic_keys) AND key not in (tracked_keys)

        Args:
            channel_id: Slack channel ID
            tracked_keys: Set of already tracked issue keys
            epic_keys: Set of epic keys to search children for

        Returns:
            List of SyncIssue for untracked children
        """
        if not epic_keys:
            return []

        missing: list[SyncIssue] = []

        try:
            # Build JQL to find children of tracked epics
            epic_list = ", ".join(f'"{key}"' for key in epic_keys)
            jql = f"parent in ({epic_list})"

            # Add exclusion for already tracked keys
            if tracked_keys:
                tracked_list = ", ".join(f'"{key}"' for key in tracked_keys)
                jql += f" AND key not in ({tracked_list})"

            jql += " ORDER BY created DESC"

            # Search Jira for untracked children
            children = await self._jira.search_issues(jql, limit=50)

            for child in children:
                # Double-check not already tracked (in case JQL missed something)
                if child.key not in tracked_keys:
                    missing.append(
                        SyncIssue(
                            jira_key=child.key,
                            summary=child.summary,
                            status=child.status,
                            issue_type="story",  # Children are typically stories/tasks
                        )
                    )

            logger.info(
                "Found missing children",
                extra={
                    "channel_id": channel_id,
                    "epic_count": len(epic_keys),
                    "missing_count": len(missing),
                },
            )

        except Exception as e:
            logger.warning(
                f"Failed to find missing children: {e}",
                extra={
                    "channel_id": channel_id,
                    "epic_keys": list(epic_keys),
                },
            )

        return missing
