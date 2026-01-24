"""Token types for invariant proof - Phase 32 Product Invariants.

Tokens provide proof that invariant checks passed.

Pattern:
1. Check runs (preflight, managed section parse, etc.)
2. If passes, check returns Token
3. Write API requires Token to proceed
4. Cannot construct Token without passing check

This is Layer 2 of the 4-layer protection:
- Layer 0: Types (invariants.py) - make wrong path hard
- Layer 1: Boundaries (gateways) - one door, one key
- Layer 2: Tokens (this file) - prove checks passed
- Layer 3: CI gates - make wrong path unshippable
- Layer 4: Runtime guardrails - make failures survivable
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4


@dataclass(frozen=True)
class PreflightToken:
    """Proof that preflight check passed.

    INVARIANT: Cannot construct without running preflight.
    Write APIs require this token to proceed.

    The token binds:
    - Which Jira key was checked
    - What conflict type was detected (IDEMPOTENT, SAFE_DRIFT, etc.)
    - When the check was performed
    - When the check expires

    Usage:
        # PreflightService.check() returns token if preflight passes
        token = await preflight_service.check(jira_key, operation)
        if not token:
            # Conflict detected, user action required
            return ConflictUI(...)

        # Token proves preflight passed - safe to proceed
        await jira_service.update(jira_key, patch, preflight_token=token)

    Attributes:
        id: Unique identifier for this token.
        jira_key: The Jira issue key that was checked.
        conflict_type: Result of preflight (IDEMPOTENT, SAFE_DRIFT, REAL_CONFLICT, STRUCTURAL).
        checked_at: When the preflight check was performed.
        expires_at: When this token expires (default 5 minutes).
    """

    id: str
    jira_key: str
    conflict_type: str
    checked_at: datetime
    expires_at: datetime

    def is_valid(self) -> bool:
        """Check if token is still valid (not expired).

        Returns:
            True if current time is before expiry.
        """
        return datetime.utcnow() < self.expires_at

    @classmethod
    def create(
        cls,
        jira_key: str,
        conflict_type: str,
        ttl_seconds: int = 300,
    ) -> "PreflightToken":
        """Create token after preflight check.

        IMPORTANT: ONLY PreflightService should call this method.
        Calling this directly without running actual preflight
        bypasses the invariant check.

        Args:
            jira_key: The Jira issue key that was checked.
            conflict_type: Result type (IDEMPOTENT, SAFE_DRIFT, etc.)
            ttl_seconds: Token time-to-live in seconds (default 5 minutes).

        Returns:
            A new PreflightToken proving the check passed.
        """
        now = datetime.utcnow()
        return cls(
            id=str(uuid4()),
            jira_key=jira_key,
            conflict_type=conflict_type,
            checked_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )


@dataclass(frozen=True)
class OverrideToken:
    """Emergency bypass token.

    ARCHITECTURE:
    - Bypass goes THROUGH the system, not around it
    - Must feel like pulling a fire alarm
    - Visible, audited, time-limited

    REQUIRED:
    - Role: admin/owner/ops-role only
    - Reason: mandatory text explanation
    - TTL: expires in 10 minutes or single action
    - Audit: logged to channel + audit log

    Escape hatch philosophy (from CONTEXT.md):
    - Not for convenience - for resilience
    - Production emergencies happen
    - Full block makes system brittle

    If override becomes a habit button, invariants are dead.

    Usage:
        # Admin grants override for emergency
        override = await override_service.grant(
            user_id=admin_id,
            reason="production incident - jira sync broken",
            scope="jira_update",
            jira_key="SCRUM-123",
        )

        # Post visibility message to channel
        await slack.post_override_notification(override)

        # Operation can now proceed with override
        await jira_service.update(jira_key, patch, override_token=override)

        # Audit log captures the bypass
        await audit.log_override_used(override, operation)

    Attributes:
        id: Unique identifier for this override.
        granted_by: User ID who granted the override (must be admin/owner).
        reason: Mandatory explanation for the bypass.
        scope: What operation this allows (e.g., "jira_update", "all").
        jira_key: Specific Jira key this covers, or None for any.
        expires_at: When this override expires.
        created_at: When the override was granted.
    """

    id: str
    granted_by: str
    reason: str
    scope: str
    jira_key: Optional[str]
    expires_at: datetime
    created_at: datetime

    def is_valid(self) -> bool:
        """Check if override is still valid (not expired).

        Returns:
            True if current time is before expiry.
        """
        return datetime.utcnow() < self.expires_at

    def covers(self, operation: str, jira_key: Optional[str]) -> bool:
        """Check if this override covers a specific operation.

        Args:
            operation: The operation being attempted (e.g., "jira_update").
            jira_key: The Jira key involved, if any.

        Returns:
            True if override is valid and covers this operation.
        """
        if not self.is_valid():
            return False
        if self.scope != "all" and self.scope != operation:
            return False
        if self.jira_key and self.jira_key != jira_key:
            return False
        return True

    @classmethod
    def create(
        cls,
        granted_by: str,
        reason: str,
        scope: str,
        jira_key: Optional[str] = None,
        ttl_seconds: int = 600,
    ) -> "OverrideToken":
        """Create override token.

        IMPORTANT: ONLY OverrideService should call this method.
        The service must verify:
        - User has admin/owner/ops role
        - Reason is non-empty
        - Override is logged to audit trail

        Args:
            granted_by: User ID of the admin granting override.
            reason: Mandatory explanation for the bypass.
            scope: Operation scope ("jira_update", "managed_section", "all").
            jira_key: Specific Jira key, or None for any key.
            ttl_seconds: Token time-to-live (default 10 minutes).

        Returns:
            A new OverrideToken for emergency bypass.
        """
        now = datetime.utcnow()
        return cls(
            id=str(uuid4()),
            granted_by=granted_by,
            reason=reason,
            scope=scope,
            jira_key=jira_key,
            expires_at=now + timedelta(seconds=ttl_seconds),
            created_at=now,
        )


# =============================================================================
# Export all token types for easy import
# =============================================================================

__all__ = [
    "PreflightToken",
    "OverrideToken",
]
