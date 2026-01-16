"""DecisionLinker service for connecting decisions to Jira issues.

Links approved architecture decisions to relevant Jira tickets,
enabling automatic tracking of decisions in the project management system.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from src.config.settings import get_settings
from src.jira.client import JiraService

logger = logging.getLogger(__name__)

# Pattern to match Jira issue keys (PROJECT-123)
JIRA_KEY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


class DecisionLinker:
    """Service that connects approved decisions to Jira issues.

    Finds related Jira issues and updates them with decision information.

    Usage:
        linker = DecisionLinker()
        issues = await linker.find_related_issues("API design", "...", "C123")
        if issues:
            success = await linker.apply_decision_to_issue(
                issues[0],
                linker.format_decision_for_jira(...),
            )
    """

    def __init__(self, jira_service: Optional[JiraService] = None):
        """Initialize DecisionLinker.

        Args:
            jira_service: Optional JiraService instance. If not provided,
                         creates one from settings.
        """
        self._jira_service = jira_service
        self._owns_jira_service = jira_service is None

    async def _get_jira_service(self) -> JiraService:
        """Get or create JiraService instance."""
        if self._jira_service is None:
            settings = get_settings()
            self._jira_service = JiraService(settings)
        return self._jira_service

    async def close(self) -> None:
        """Close resources if we own them."""
        if self._owns_jira_service and self._jira_service is not None:
            await self._jira_service.close()
            self._jira_service = None

    async def find_related_issues(
        self,
        decision_topic: str,
        decision_text: str,
        channel_id: str,
        thread_binding: Optional[str] = None,
    ) -> list[str]:
        """Find Jira issues related to a decision.

        Ranking strategy:
        1. Explicit Jira keys in decision text (highest confidence)
        2. Thread binding if decision was in a bound thread
        3. Tracked issues with keyword matches (lower confidence)

        Args:
            decision_topic: The decision topic (1 line summary)
            decision_text: Full decision text
            channel_id: Slack channel ID for context
            thread_binding: Optional Jira key if thread is already bound

        Returns:
            Ranked list of likely related issue keys (most likely first)
        """
        related_issues: list[str] = []

        # 1. Extract explicit Jira keys from decision text
        explicit_keys = self._extract_jira_keys(decision_text)
        explicit_keys.extend(self._extract_jira_keys(decision_topic))
        # Deduplicate while preserving order
        for key in explicit_keys:
            if key not in related_issues:
                related_issues.append(key)

        logger.debug(
            "Extracted explicit keys from decision",
            extra={
                "explicit_keys": related_issues,
                "topic": decision_topic,
            }
        )

        # 2. Check thread binding (highest confidence if present)
        if thread_binding and thread_binding not in related_issues:
            # Insert at front - bound thread is highest confidence
            related_issues.insert(0, thread_binding)
            logger.debug(f"Added thread binding: {thread_binding}")

        # 3. Search tracked issues by keyword match
        keyword_matches = await self._find_keyword_matches(
            decision_topic,
            channel_id,
            exclude=related_issues,
        )
        related_issues.extend(keyword_matches)

        logger.info(
            "Found related issues for decision",
            extra={
                "channel_id": channel_id,
                "topic": decision_topic,
                "related_count": len(related_issues),
                "related_issues": related_issues[:5],  # Log first 5
            }
        )

        return related_issues

    def _extract_jira_keys(self, text: str) -> list[str]:
        """Extract Jira issue keys from text.

        Args:
            text: Text that may contain Jira keys

        Returns:
            List of unique Jira keys found
        """
        if not text:
            return []

        matches = JIRA_KEY_PATTERN.findall(text)
        # Normalize to uppercase and deduplicate
        seen = set()
        unique = []
        for key in matches:
            key_upper = key.upper()
            if key_upper not in seen:
                seen.add(key_upper)
                unique.append(key_upper)
        return unique

    async def _find_keyword_matches(
        self,
        topic: str,
        channel_id: str,
        exclude: list[str],
    ) -> list[str]:
        """Find tracked issues matching topic keywords.

        Args:
            topic: Decision topic to match
            channel_id: Channel ID to search tracked issues
            exclude: Keys to exclude (already found)

        Returns:
            List of matching issue keys
        """
        try:
            from src.db import get_connection
            from src.slack.channel_tracker import ChannelIssueTracker

            async with get_connection() as conn:
                tracker = ChannelIssueTracker(conn)
                tracked = await tracker.get_tracked_issues(channel_id)

            if not tracked:
                return []

            # Extract keywords from topic (words 3+ chars, lowercase)
            keywords = [
                w.lower() for w in re.findall(r"\b\w{3,}\b", topic)
                if w.lower() not in {"the", "and", "for", "this", "that", "with"}
            ]

            if not keywords:
                return []

            # Score each tracked issue
            matches = []
            for issue in tracked:
                if issue.issue_key in exclude:
                    continue

                summary = (issue.last_jira_summary or "").lower()
                # Count keyword matches in summary
                score = sum(1 for kw in keywords if kw in summary)

                if score > 0:
                    matches.append((score, issue.issue_key))

            # Sort by score descending
            matches.sort(reverse=True, key=lambda x: x[0])

            return [key for _, key in matches[:5]]  # Top 5 matches

        except Exception as e:
            logger.warning(f"Failed to find keyword matches: {e}")
            return []

    def format_decision_for_jira(
        self,
        topic: str,
        decision: str,
        approver: str,
        timestamp: str,
        slack_link: Optional[str] = None,
    ) -> str:
        """Format decision for Jira comment.

        Uses Jira wiki markup format (compatible with most Jira versions).

        Args:
            topic: Decision topic
            decision: Full decision text
            approver: Name or ID of person who approved
            timestamp: ISO timestamp of approval
            slack_link: Optional link to Slack thread

        Returns:
            Formatted Jira comment text
        """
        # Format timestamp for display
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            date_str = timestamp

        # Build formatted comment
        lines = [
            "h3. Architecture Decision",
            "",
            f"*Topic:* {topic}",
            "",
            f"{decision}",
            "",
            "----",
            f"_Approved by {approver} on {date_str}_",
        ]

        if slack_link:
            lines.append(f"_[View in Slack|{slack_link}]_")

        return "\n".join(lines)

    async def apply_decision_to_issue(
        self,
        issue_key: str,
        decision_content: str,
        mode: str = "add_comment",
        add_label: bool = True,
        channel_id: Optional[str] = None,
        decision_ts: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> bool:
        """Apply decision to a Jira issue.

        Args:
            issue_key: Jira issue key (e.g., "SCRUM-123")
            decision_content: Formatted decision content
            mode: How to apply:
                - "add_comment": Add as comment (default, safest)
                - "append_description": Append to description
            add_label: Whether to add "decision" label
            channel_id: Optional channel ID for sync tracking
            decision_ts: Optional decision timestamp for sync tracking
            topic: Optional decision topic for sync tracking

        Returns:
            True if successful, False otherwise
        """
        try:
            jira = await self._get_jira_service()

            if mode == "add_comment":
                await jira.add_comment(issue_key, decision_content)
                logger.info(f"Added decision comment to {issue_key}")

            elif mode == "append_description":
                # Get current description and append
                issue = await jira.get_issue(issue_key)
                current_desc = issue.description or ""
                separator = "\n\n---\n\n" if current_desc else ""
                new_desc = current_desc + separator + decision_content

                await jira.update_issue(issue_key, {"description": new_desc})
                logger.info(f"Appended decision to {issue_key} description")

            else:
                logger.warning(f"Unknown mode: {mode}, defaulting to add_comment")
                await jira.add_comment(issue_key, decision_content)

            # Add "decision" label if requested
            if add_label:
                await self.add_label_if_not_exists(issue_key, "decision")

            # Record for sync tracking (non-blocking)
            if channel_id and decision_ts:
                await self.record_decision_sync(
                    channel_id=channel_id,
                    decision_ts=decision_ts,
                    topic=topic or "",
                    decision_text=decision_content,
                    related_issues=[issue_key],
                    synced_to_jira=True,  # We just synced it
                )

            return True

        except Exception as e:
            logger.error(
                f"Failed to apply decision to {issue_key}: {e}",
                exc_info=True,
            )
            return False

    async def add_label_if_not_exists(
        self,
        issue_key: str,
        label: str,
    ) -> bool:
        """Add a label to issue if not already present.

        Args:
            issue_key: Jira issue key
            label: Label to add

        Returns:
            True if label was added or already existed
        """
        try:
            jira = await self._get_jira_service()

            # Get current labels via search
            issues = await jira.search_issues(
                f'key = "{issue_key}"',
                limit=1,
            )

            # The search API doesn't return labels, so we use the update endpoint
            # with the "add" operation which won't duplicate labels
            await jira._request(
                "PUT",
                f"/rest/api/3/issue/{issue_key}",
                json_data={
                    "update": {
                        "labels": [{"add": label}]
                    }
                }
            )

            logger.info(f"Added label '{label}' to {issue_key}")
            return True

        except Exception as e:
            # Label operations are non-critical, log but don't fail
            logger.warning(f"Failed to add label to {issue_key}: {e}")
            return False

    async def record_decision_sync(
        self,
        channel_id: str,
        decision_ts: str,
        topic: str,
        decision_text: str,
        related_issues: list[str],
        synced_to_jira: bool = True,
    ) -> bool:
        """Record decision in database for sync tracking.

        Creates entry in channel_decisions table used by sync engine.

        Args:
            channel_id: Slack channel ID
            decision_ts: Decision message timestamp
            topic: Decision topic
            decision_text: Full decision text
            related_issues: List of linked Jira issue keys
            synced_to_jira: Whether already synced (True if we just applied it)

        Returns:
            True if recorded successfully
        """
        try:
            from src.db import get_connection

            async with get_connection() as conn:
                async with conn.cursor() as cur:
                    # Create table if not exists
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS channel_decisions (
                            channel_id TEXT NOT NULL,
                            decision_ts TEXT NOT NULL,
                            topic TEXT NOT NULL,
                            decision_text TEXT NOT NULL,
                            related_issues JSONB DEFAULT '[]',
                            synced_to_jira BOOLEAN DEFAULT FALSE,
                            synced_at TIMESTAMPTZ,
                            created_at TIMESTAMPTZ DEFAULT NOW(),
                            PRIMARY KEY (channel_id, decision_ts)
                        )
                    """)

                    # UPSERT decision
                    await cur.execute(
                        """
                        INSERT INTO channel_decisions (
                            channel_id, decision_ts, topic, decision_text,
                            related_issues, synced_to_jira, synced_at
                        )
                        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                        ON CONFLICT (channel_id, decision_ts) DO UPDATE SET
                            topic = EXCLUDED.topic,
                            decision_text = EXCLUDED.decision_text,
                            related_issues = EXCLUDED.related_issues,
                            synced_to_jira = EXCLUDED.synced_to_jira,
                            synced_at = EXCLUDED.synced_at
                        """,
                        (
                            channel_id,
                            decision_ts,
                            topic,
                            decision_text,
                            str(related_issues).replace("'", '"'),  # Convert to JSON array
                            synced_to_jira,
                            datetime.now(timezone.utc) if synced_to_jira else None,
                        ),
                    )
                    await conn.commit()

            logger.info(
                "Decision recorded for sync tracking",
                extra={
                    "channel_id": channel_id,
                    "decision_ts": decision_ts,
                    "related_issues": related_issues,
                    "synced": synced_to_jira,
                },
            )
            return True

        except Exception as e:
            logger.warning(f"Failed to record decision: {e}")
            return False
