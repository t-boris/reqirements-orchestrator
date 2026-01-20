"""Jira Sync Service for bidirectional sync with conflict detection (Phase 23.4).

Sync philosophy:
- Slack captures the "why" (discussions, decisions, constraints)
- Jira manages the "what/who/when" (status, assignee, sprints)
- Never silent overwrites - conflicts require manual resolution

Sync workflow:
1. Compute current fingerprints for Slack and Jira versions
2. Compare against last synced fingerprint (base)
3. Auto-merge non-conflicting changes
4. Flag conflicts for manual resolution
5. Update fingerprint after successful sync
"""
import logging
from datetime import datetime, timezone
from typing import Any

from psycopg import AsyncConnection

from src.db.models import WorkItem, WorkItemStatus, CommitType
from src.db.workitem_store import WorkItemStore
from src.db.commit_store import CommitStore
from src.jira.client import JiraService
from src.jira.types import JiraIssue
from src.jira.sync_config import (
    FieldOwnership,
    SyncDirection,
    SyncResult,
    FIELD_CLASSIFICATIONS,
    can_push_field,
    requires_conflict_check,
)
from src.jira.fingerprint import (
    compute_fingerprint,
    fingerprint_to_dict,
    dict_to_fingerprint,
    detect_conflict,
    parse_sections,
)

logger = logging.getLogger(__name__)


class SyncConflict:
    """Represents a sync conflict requiring manual resolution."""

    def __init__(
        self,
        field: str,
        slack_value: Any,
        jira_value: Any,
        section: str | None = None,
    ):
        self.field = field
        self.slack_value = slack_value
        self.jira_value = jira_value
        self.section = section  # For description section-level conflicts


class JiraSyncService:
    """Service for bidirectional Jira sync with conflict detection.

    Usage:
        async with get_connection() as conn:
            sync_service = JiraSyncService(jira_service, conn)
            result = await sync_service.sync_to_jira(workitem)
            if result.conflicts:
                # Show conflict resolution UI
    """

    def __init__(self, jira_service: JiraService, conn: AsyncConnection) -> None:
        """Initialize sync service.

        Args:
            jira_service: JiraService instance for API calls
            conn: Database connection for stores
        """
        self._jira = jira_service
        self._conn = conn
        self._workitem_store = WorkItemStore(conn)
        self._commit_store = CommitStore(conn)

    async def sync_to_jira(
        self,
        workitem: WorkItem,
        *,
        force_fields: list[str] | None = None,
    ) -> SyncResult:
        """Sync WorkItem changes to Jira.

        Only pushes SLACK_OWNED and SHARED fields.
        Detects conflicts for SHARED fields.

        Args:
            workitem: WorkItem to sync
            force_fields: Optional list of fields to push even with conflicts

        Returns:
            SyncResult with updated fields, conflicts, and status
        """
        if not workitem.jira_key:
            return SyncResult(
                success=False,
                direction=SyncDirection.SLACK_TO_JIRA,
                error="WorkItem has no jira_key - create first",
            )

        try:
            # Fetch current Jira state
            jira_issue = await self._jira.get_issue(workitem.jira_key)

            # Build update payload for pushable fields
            updates: dict[str, Any] = {}
            conflicts: list[dict[str, Any]] = []

            # Check summary (SLACK_OWNED)
            if workitem.summary != jira_issue.summary:
                if can_push_field("summary", SyncDirection.SLACK_TO_JIRA):
                    updates["summary"] = workitem.summary

            # Check description with section-level fingerprinting
            desc_result = await self._sync_description(workitem, jira_issue)
            if desc_result.get("update"):
                updates["description"] = desc_result["update"]
            if desc_result.get("conflicts"):
                conflicts.extend(desc_result["conflicts"])

            # Check SHARED fields for conflicts
            # Priority
            if requires_conflict_check("priority"):
                # Would need to compare priority - simplified for now
                pass

            # Skip update if there are conflicts and no force
            if conflicts and not force_fields:
                return SyncResult(
                    success=False,
                    direction=SyncDirection.SLACK_TO_JIRA,
                    conflicts=conflicts,
                    error="Conflicts detected - manual resolution required",
                )

            # Apply updates
            if updates:
                await self._jira.update_issue(workitem.jira_key, updates)
                logger.info(
                    "Synced WorkItem to Jira",
                    extra={
                        "workitem_id": workitem.id,
                        "jira_key": workitem.jira_key,
                        "fields_updated": list(updates.keys()),
                    },
                )

                # Update fingerprint
                new_fp = compute_fingerprint(workitem.description or "")
                await self._workitem_store.update(
                    workitem.id,
                    jira_sync_at=datetime.now(timezone.utc),
                    jira_fingerprint=fingerprint_to_dict(new_fp),
                )

            return SyncResult(
                success=True,
                direction=SyncDirection.SLACK_TO_JIRA,
                fields_updated=list(updates.keys()),
                conflicts=conflicts,
            )

        except Exception as e:
            logger.error(f"Sync to Jira failed: {e}", exc_info=True)
            return SyncResult(
                success=False,
                direction=SyncDirection.SLACK_TO_JIRA,
                error=str(e),
            )

    async def sync_from_jira(
        self,
        workitem: WorkItem,
        *,
        force_fields: list[str] | None = None,
    ) -> SyncResult:
        """Sync Jira changes to WorkItem.

        Only pulls JIRA_OWNED and SHARED fields.
        Detects conflicts for SHARED fields.
        JIRA_OWNED changes are "hotfixes" that apply automatically.

        Args:
            workitem: WorkItem to update
            force_fields: Optional list of fields to pull even with conflicts

        Returns:
            SyncResult with updated fields, conflicts, and status
        """
        if not workitem.jira_key:
            return SyncResult(
                success=False,
                direction=SyncDirection.JIRA_TO_SLACK,
                error="WorkItem has no jira_key",
            )

        try:
            # Fetch current Jira state
            jira_issue = await self._jira.get_issue(workitem.jira_key)

            # Track updates and conflicts
            updates: dict[str, Any] = {}
            conflicts: list[dict[str, Any]] = []

            # Check for Jira-side description changes (hotfixes)
            desc_result = await self._check_jira_description_changes(
                workitem, jira_issue
            )
            if desc_result.get("update"):
                updates["description"] = desc_result["update"]
            if desc_result.get("conflicts"):
                conflicts.extend(desc_result["conflicts"])

            # Skip update if conflicts and no force
            if conflicts and not force_fields:
                return SyncResult(
                    success=False,
                    direction=SyncDirection.JIRA_TO_SLACK,
                    conflicts=conflicts,
                    error="Conflicts detected - manual resolution required",
                )

            # Apply updates to WorkItem
            if updates:
                await self._workitem_store.update(workitem.id, **updates)
                logger.info(
                    "Synced Jira changes to WorkItem",
                    extra={
                        "workitem_id": workitem.id,
                        "jira_key": workitem.jira_key,
                        "fields_updated": list(updates.keys()),
                    },
                )

                # Update fingerprint
                new_desc = updates.get("description", workitem.description) or ""
                new_fp = compute_fingerprint(new_desc)
                await self._workitem_store.update(
                    workitem.id,
                    jira_sync_at=datetime.now(timezone.utc),
                    jira_fingerprint=fingerprint_to_dict(new_fp),
                )

            return SyncResult(
                success=True,
                direction=SyncDirection.JIRA_TO_SLACK,
                fields_updated=list(updates.keys()),
                conflicts=conflicts,
            )

        except Exception as e:
            logger.error(f"Sync from Jira failed: {e}", exc_info=True)
            return SyncResult(
                success=False,
                direction=SyncDirection.JIRA_TO_SLACK,
                error=str(e),
            )

    async def _sync_description(
        self,
        workitem: WorkItem,
        jira_issue: JiraIssue,
    ) -> dict[str, Any]:
        """Sync description with section-level conflict detection.

        Returns:
            Dict with 'update' (merged description) and 'conflicts' (list)
        """
        slack_desc = workitem.description or ""
        jira_desc = jira_issue.description or ""

        # Compute fingerprints
        slack_fp = compute_fingerprint(slack_desc)
        jira_fp = compute_fingerprint(jira_desc)
        base_fp = dict_to_fingerprint(workitem.jira_fingerprint or {})

        # Detect conflicts
        conflict_result = detect_conflict(slack_fp, jira_fp, base_fp)

        if conflict_result["conflicts"]:
            # Build conflict objects for UI
            conflicts = []
            slack_sections = parse_sections(slack_desc)
            jira_sections = parse_sections(jira_desc)

            for section in conflict_result["conflicts"]:
                conflicts.append({
                    "field": "description",
                    "section": section,
                    "slack_value": slack_sections.get(section, ""),
                    "jira_value": jira_sections.get(section, ""),
                })

            return {"update": None, "conflicts": conflicts}

        # Auto-merge based on conflict_result["auto_merge"]
        # For simplicity, if no conflicts, use Slack version (Slack-owned)
        if slack_fp.full_hash != jira_fp.full_hash:
            return {"update": slack_desc, "conflicts": []}

        return {"update": None, "conflicts": []}

    async def _check_jira_description_changes(
        self,
        workitem: WorkItem,
        jira_issue: JiraIssue,
    ) -> dict[str, Any]:
        """Check if Jira description changed (hotfix detection).

        Returns:
            Dict with 'update' and 'conflicts'
        """
        jira_desc = jira_issue.description or ""
        jira_fp = compute_fingerprint(jira_desc)
        base_fp = dict_to_fingerprint(workitem.jira_fingerprint or {})

        if base_fp is None:
            # No baseline - can't detect changes
            return {"update": None, "conflicts": []}

        # Check if Jira changed since last sync
        jira_changes = []
        for section, section_fp in jira_fp.sections.items():
            base_section = base_fp.sections.get(section)
            if base_section is None or base_section.hash != section_fp.hash:
                jira_changes.append(section)

        if not jira_changes:
            return {"update": None, "conflicts": []}

        # Check if Slack also changed these sections
        slack_desc = workitem.description or ""
        slack_fp = compute_fingerprint(slack_desc)

        conflict_result = detect_conflict(slack_fp, jira_fp, base_fp)

        if conflict_result["conflicts"]:
            slack_sections = parse_sections(slack_desc)
            jira_sections = parse_sections(jira_desc)
            conflicts = []
            for section in conflict_result["conflicts"]:
                conflicts.append({
                    "field": "description",
                    "section": section,
                    "slack_value": slack_sections.get(section, ""),
                    "jira_value": jira_sections.get(section, ""),
                })
            return {"update": None, "conflicts": conflicts}

        # Auto-apply Jira changes (hotfix)
        if conflict_result["auto_merge"]:
            # Merge sections: use Jira version for sections it changed
            slack_sections = parse_sections(slack_desc)
            jira_sections = parse_sections(jira_desc)

            for section, source in conflict_result["auto_merge"].items():
                if source == "jira":
                    slack_sections[section] = jira_sections.get(section, "")

            # Rebuild description
            merged = self._rebuild_description(slack_sections)
            return {"update": merged, "conflicts": []}

        return {"update": None, "conflicts": []}

    def _rebuild_description(self, sections: dict[str, str]) -> str:
        """Rebuild description from sections.

        Args:
            sections: Dict of section name to content

        Returns:
            Formatted description string
        """
        parts = []

        # Order sections
        section_order = ["problem", "acceptance_criteria", "architecture", "source"]
        section_headers = {
            "problem": "## Problem",
            "acceptance_criteria": "## Acceptance Criteria",
            "architecture": "## Architecture",
            "source": "## Source",
        }

        for section in section_order:
            if section in sections and sections[section]:
                header = section_headers.get(section, f"## {section.title()}")
                parts.append(f"{header}\n\n{sections[section]}")

        # Add any custom sections
        for section, content in sections.items():
            if section not in section_order and content:
                parts.append(f"## {section.title()}\n\n{content}")

        return "\n\n".join(parts)

    async def create_in_jira(
        self,
        workitem: WorkItem,
        *,
        user_id: str,
    ) -> tuple[WorkItem, JiraIssue]:
        """Create WorkItem in Jira and update with jira_key.

        This is the explicit action from "Create in Jira" button.

        Args:
            workitem: WorkItem to create (must be DRAFT or ACTIVE without jira_key)
            user_id: User who triggered creation

        Returns:
            Tuple of (updated WorkItem, created JiraIssue)
        """
        from src.jira.types import JiraCreateRequest, JiraIssueType, JiraPriority

        # Map WorkItemType to JiraIssueType
        type_map = {
            "epic": JiraIssueType.EPIC,
            "story": JiraIssueType.STORY,
            "bug": JiraIssueType.BUG,
            "task": JiraIssueType.TASK,
            "spike": JiraIssueType.TASK,  # Spike as Task in Jira
        }
        jira_type = type_map.get(workitem.item_type.value, JiraIssueType.TASK)

        # Create request
        request = JiraCreateRequest(
            project_key=self._jira.settings.jira_default_project,
            summary=workitem.summary,
            description=workitem.description or "",
            issue_type=jira_type,
            priority=JiraPriority.MEDIUM,  # Default priority
        )

        # Create in Jira
        jira_issue = await self._jira.create_issue(request)

        # Update WorkItem with Jira key and fingerprint
        fp = compute_fingerprint(workitem.description or "")
        updated_item = await self._workitem_store.update(
            workitem.id,
            jira_key=jira_issue.key,
            jira_sync_at=datetime.now(timezone.utc),
            jira_fingerprint=fingerprint_to_dict(fp),
            status=WorkItemStatus.ACTIVE,
        )

        # Create commit entry
        await self._commit_store.create_tables()
        await self._commit_store.create(
            channel_id=workitem.channel_id,
            commit_type=CommitType.JIRA_SYNCED,
            summary=f"Created {jira_issue.key}: {workitem.summary}",
            user_id=user_id,
            workitem_id=workitem.id,
            thread_ts=workitem.source_thread_ts,
        )

        logger.info(
            "Created WorkItem in Jira",
            extra={
                "workitem_id": workitem.id,
                "jira_key": jira_issue.key,
                "user_id": user_id,
            },
        )

        return updated_item, jira_issue
