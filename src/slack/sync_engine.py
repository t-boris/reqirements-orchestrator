"""Smart sync engine for bidirectional Jira synchronization.

Detects changes between Slack channel decisions and Jira state,
categorizes them for auto-apply or review, and handles conflict resolution.

Usage:
    engine = SyncEngine(jira_service, jira_base_url)
    plan = await engine.detect_changes(channel_id, conn)
    results = await engine.apply_changes(plan.auto_apply, conn)
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg import AsyncConnection
    from src.jira.client import JiraService

logger = logging.getLogger(__name__)


@dataclass
class ChangeDetection:
    """A detected change between Slack and Jira.

    Attributes:
        issue_key: Jira issue key (e.g., "SCRUM-123")
        field: Field that changed (status, priority, summary, description, etc.)
        slack_value: What the channel decided (if any)
        jira_value: Current Jira state
        change_type: Classification of the change
        confidence: How confident we are (0.0-1.0)
        source: Where we detected the slack_value (e.g., "decision:ts123", "command:ts456")
        source_ts: Timestamp of the source message (for linking)
    """

    issue_key: str
    field: str
    slack_value: Optional[str]
    jira_value: Optional[str]
    change_type: Literal["slack_ahead", "jira_ahead", "conflict", "in_sync"]
    confidence: float
    source: str
    source_ts: Optional[str] = None


@dataclass
class SyncPlan:
    """Categorized plan for syncing changes.

    Attributes:
        auto_apply: High confidence changes to apply automatically
        needs_review: Conflicts or low confidence changes requiring user decision
        in_sync: Issue keys already synchronized
    """

    auto_apply: list[ChangeDetection] = field(default_factory=list)
    needs_review: list[ChangeDetection] = field(default_factory=list)
    in_sync: list[str] = field(default_factory=list)


@dataclass
class SyncResult:
    """Result of applying a single change.

    Attributes:
        issue_key: Jira issue key
        field: Field that was updated
        success: Whether the update succeeded
        error: Error message if failed
    """

    issue_key: str
    field: str
    success: bool
    error: Optional[str] = None


class SyncEngine:
    """Engine for detecting and applying Slack-Jira synchronization.

    Compares channel decisions against Jira state and produces a categorized
    sync plan. High-confidence, obvious changes can be auto-applied; conflicts
    require user review.

    Usage:
        engine = SyncEngine(jira_service, jira_base_url)
        plan = await engine.detect_changes(channel_id, conn)

        # Auto-apply obvious changes
        results = await engine.apply_changes(plan.auto_apply, channel_id, conn)

        # Present conflicts to user for resolution
        for change in plan.needs_review:
            # Show side-by-side comparison UI
            ...
    """

    # Confidence threshold for auto-apply
    AUTO_APPLY_THRESHOLD = 0.8

    def __init__(
        self,
        jira_service: "JiraService",
        jira_base_url: str = "",
    ):
        """Initialize sync engine.

        Args:
            jira_service: JiraService instance for Jira API calls
            jira_base_url: Base URL for Jira links
        """
        self._jira = jira_service
        self._jira_base_url = jira_base_url.rstrip("/")

    async def detect_changes(
        self,
        channel_id: str,
        conn: "AsyncConnection",
    ) -> SyncPlan:
        """Detect changes between Slack decisions and Jira state.

        Steps:
        1. Get all tracked issues from ChannelIssueTracker
        2. Fetch current state from Jira for each
        3. Query ChannelDecision for unsynced decisions
        4. Compare and categorize changes

        Args:
            channel_id: Slack channel ID
            conn: Database connection

        Returns:
            SyncPlan with categorized changes
        """
        from src.slack.channel_tracker import ChannelIssueTracker

        plan = SyncPlan()
        tracker = ChannelIssueTracker(conn)

        # 1. Get tracked issues
        tracked_issues = await tracker.get_tracked_issues(channel_id)

        if not tracked_issues:
            logger.info(
                "No tracked issues for sync",
                extra={"channel_id": channel_id},
            )
            return plan

        logger.info(
            "Detecting changes for tracked issues",
            extra={
                "channel_id": channel_id,
                "tracked_count": len(tracked_issues),
            },
        )

        # 2. Fetch current Jira state and compare
        for tracked in tracked_issues:
            try:
                # Get current Jira issue
                jira_issue = await self._jira.get_issue(tracked.issue_key)

                # Check for Jira-side changes (Jira ahead of our last sync)
                jira_changes = self._detect_jira_changes(tracked, jira_issue)
                for change in jira_changes:
                    if change.change_type == "in_sync":
                        if change.issue_key not in plan.in_sync:
                            plan.in_sync.append(change.issue_key)
                    elif change.confidence >= self.AUTO_APPLY_THRESHOLD:
                        plan.auto_apply.append(change)
                    else:
                        plan.needs_review.append(change)

            except Exception as e:
                logger.warning(
                    f"Failed to fetch Jira issue {tracked.issue_key}: {e}",
                    extra={"issue_key": tracked.issue_key},
                )

        # 3. Query unsynced decisions
        decision_changes = await self._detect_decision_changes(channel_id, conn)
        for change in decision_changes:
            if change.confidence >= self.AUTO_APPLY_THRESHOLD:
                plan.auto_apply.append(change)
            else:
                plan.needs_review.append(change)

        logger.info(
            "Sync plan generated",
            extra={
                "channel_id": channel_id,
                "auto_apply": len(plan.auto_apply),
                "needs_review": len(plan.needs_review),
                "in_sync": len(plan.in_sync),
            },
        )

        return plan

    def _detect_jira_changes(
        self,
        tracked,
        jira_issue,
    ) -> list[ChangeDetection]:
        """Detect changes between tracked state and current Jira state.

        Args:
            tracked: TrackedIssue from database
            jira_issue: Current JiraIssue from API

        Returns:
            List of detected changes
        """
        changes = []

        # Check status
        if tracked.last_jira_status and tracked.last_jira_status != jira_issue.status:
            changes.append(ChangeDetection(
                issue_key=tracked.issue_key,
                field="status",
                slack_value=tracked.last_jira_status,
                jira_value=jira_issue.status,
                change_type="jira_ahead",
                confidence=0.9,  # High confidence - Jira is authoritative for status
                source="jira_update",
            ))
        elif tracked.last_jira_status == jira_issue.status:
            changes.append(ChangeDetection(
                issue_key=tracked.issue_key,
                field="status",
                slack_value=tracked.last_jira_status,
                jira_value=jira_issue.status,
                change_type="in_sync",
                confidence=1.0,
                source="tracker",
            ))

        # Check summary
        if tracked.last_jira_summary and tracked.last_jira_summary != jira_issue.summary:
            changes.append(ChangeDetection(
                issue_key=tracked.issue_key,
                field="summary",
                slack_value=tracked.last_jira_summary,
                jira_value=jira_issue.summary,
                change_type="jira_ahead",
                confidence=0.7,  # Medium confidence - might be intentional update
                source="jira_update",
            ))

        return changes

    async def _detect_decision_changes(
        self,
        channel_id: str,
        conn: "AsyncConnection",
    ) -> list[ChangeDetection]:
        """Detect unsynced decisions that should update Jira.

        Args:
            channel_id: Slack channel ID
            conn: Database connection

        Returns:
            List of changes from unsynced decisions
        """
        changes = []

        try:
            # Query unsynced decisions
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT decision_ts, topic, decision_text, related_issues
                    FROM channel_decisions
                    WHERE channel_id = %s AND synced_to_jira = FALSE
                    ORDER BY created_at DESC
                    """,
                    (channel_id,),
                )
                rows = await cur.fetchall()

            for row in rows:
                decision_ts, topic, decision_text, related_issues = row

                # related_issues is stored as JSON array
                if not related_issues:
                    continue

                issues = related_issues if isinstance(related_issues, list) else []

                for issue_key in issues:
                    changes.append(ChangeDetection(
                        issue_key=issue_key,
                        field="description",
                        slack_value=f"[Decision] {topic}: {decision_text}",
                        jira_value=None,  # We'll append, not replace
                        change_type="slack_ahead",
                        confidence=0.85,  # High confidence - explicit decision
                        source=f"decision:{decision_ts}",
                        source_ts=decision_ts,
                    ))

        except Exception as e:
            # Table might not exist yet
            logger.debug(f"Could not query decisions: {e}")

        return changes

    async def apply_changes(
        self,
        changes: list[ChangeDetection],
        channel_id: str,
        conn: "AsyncConnection",
    ) -> list[SyncResult]:
        """Apply a list of changes to Jira.

        Args:
            changes: List of changes to apply
            channel_id: Channel ID for tracker updates
            conn: Database connection

        Returns:
            List of results for each change
        """
        from src.slack.channel_tracker import ChannelIssueTracker

        results = []
        tracker = ChannelIssueTracker(conn)

        for change in changes:
            result = await self._apply_single_change(change)
            results.append(result)

            if result.success:
                # Update tracker with new values
                if change.change_type == "slack_ahead":
                    # We pushed Slack value to Jira
                    await tracker.update_sync_status(
                        channel_id,
                        change.issue_key,
                        status=change.slack_value if change.field == "status" else None,
                        summary=change.slack_value if change.field == "summary" else None,
                    )
                elif change.change_type == "jira_ahead":
                    # We're accepting Jira value
                    await tracker.update_sync_status(
                        channel_id,
                        change.issue_key,
                        status=change.jira_value if change.field == "status" else None,
                        summary=change.jira_value if change.field == "summary" else None,
                    )

                # Mark decision as synced if from decision
                if change.source.startswith("decision:"):
                    await self._mark_decision_synced(change.source_ts, conn)

        logger.info(
            "Changes applied",
            extra={
                "channel_id": channel_id,
                "total": len(results),
                "successful": sum(1 for r in results if r.success),
            },
        )

        return results

    async def _apply_single_change(self, change: ChangeDetection) -> SyncResult:
        """Apply a single change to Jira.

        Args:
            change: The change to apply

        Returns:
            SyncResult indicating success or failure
        """
        try:
            if change.change_type == "slack_ahead":
                # Push Slack value to Jira
                if change.field == "description" and change.slack_value:
                    # Append decision to description as comment
                    await self._jira.add_comment(
                        change.issue_key,
                        change.slack_value,
                    )
                elif change.field == "status" and change.slack_value:
                    # Transition issue
                    await self._transition_to_status(change.issue_key, change.slack_value)
                elif change.field in ("summary", "priority"):
                    # Direct field update
                    updates = {change.field: change.slack_value}
                    if change.field == "priority":
                        updates = {"priority": {"name": change.slack_value}}
                    await self._jira.update_issue(change.issue_key, updates)

            elif change.change_type == "jira_ahead":
                # Accept Jira value - just update tracker (done in apply_changes)
                pass

            return SyncResult(
                issue_key=change.issue_key,
                field=change.field,
                success=True,
            )

        except Exception as e:
            logger.error(
                f"Failed to apply change: {e}",
                extra={
                    "issue_key": change.issue_key,
                    "field": change.field,
                    "change_type": change.change_type,
                },
            )
            return SyncResult(
                issue_key=change.issue_key,
                field=change.field,
                success=False,
                error=str(e),
            )

    async def _transition_to_status(self, issue_key: str, target_status: str) -> None:
        """Transition an issue to a new status.

        Args:
            issue_key: Jira issue key
            target_status: Target status name
        """
        # Get available transitions
        response = await self._jira._request(
            "GET",
            f"/rest/api/3/issue/{issue_key}/transitions",
        )

        transitions = response.get("transitions", [])
        target_lower = target_status.lower().replace(" ", "")

        # Find matching transition
        transition_id = None
        for t in transitions:
            name = t.get("name", "")
            to_status = t.get("to", {}).get("name", "")

            if (
                name.lower().replace(" ", "") == target_lower
                or to_status.lower().replace(" ", "") == target_lower
            ):
                transition_id = t.get("id")
                break

        if not transition_id:
            available = [t.get("to", {}).get("name", "") for t in transitions]
            raise ValueError(
                f"Status '{target_status}' not available. "
                f"Available: {', '.join(available)}"
            )

        # Execute transition
        await self._jira._request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/transitions",
            json_data={"transition": {"id": transition_id}},
        )

    async def _mark_decision_synced(
        self,
        decision_ts: Optional[str],
        conn: "AsyncConnection",
    ) -> None:
        """Mark a decision as synced to Jira.

        Args:
            decision_ts: Decision timestamp
            conn: Database connection
        """
        if not decision_ts:
            return

        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE channel_decisions
                    SET synced_to_jira = TRUE, synced_at = %s
                    WHERE decision_ts = %s
                    """,
                    (datetime.now(timezone.utc), decision_ts),
                )
                await conn.commit()
        except Exception as e:
            logger.debug(f"Could not mark decision synced: {e}")


def extract_issue_keys(text: str) -> list[str]:
    """Extract Jira issue keys from text.

    Args:
        text: Text that may contain issue keys

    Returns:
        List of unique issue keys found (uppercase)
    """
    pattern = r'\b([A-Z][A-Z0-9]+-\d+)\b'
    matches = re.findall(pattern, text, re.IGNORECASE)
    # Deduplicate and uppercase
    seen = set()
    result = []
    for key in matches:
        key_upper = key.upper()
        if key_upper not in seen:
            seen.add(key_upper)
            result.append(key_upper)
    return result
