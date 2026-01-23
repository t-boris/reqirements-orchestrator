"""Approval validation for state-bound approvals.

Validates approval requests against:
1. State version (outdated approval detection)
2. Channel policy (two_person, only_admins, etc.)
3. Already-approved status (first-wins)

Phase 27.4 - State-Bound Approvals
"""
import logging
from typing import Optional, Tuple

from src.schemas.approval import ApprovalPolicy
from src.db import get_connection
from src.db.approval_policy_store import ApprovalPolicyStore

logger = logging.getLogger(__name__)


async def validate_approval(
    channel_id: str,
    user_id: str,
    creator_user_id: str,
    state_version: int,
    current_state_version: int,
    draft_hash: str,
    action_type: str = "jira_create",
) -> Tuple[bool, Optional[str]]:
    """Validate if user can approve this action.

    Checks:
    1. State version match (outdated approval detection)
    2. Channel policy requirements (two_person, only_admins)

    Args:
        channel_id: Slack channel ID
        user_id: User attempting to approve
        creator_user_id: User who created the draft
        state_version: State version from button payload
        current_state_version: Current state version in agent state
        draft_hash: Hash of draft content (for logging)
        action_type: Type of action being approved

    Returns:
        (is_valid, error_message) - If invalid, error_message explains why
    """
    # Check state version (outdated approval)
    if state_version != current_state_version:
        logger.warning(
            "Outdated approval attempt",
            extra={
                "channel_id": channel_id,
                "user_id": user_id,
                "button_state_version": state_version,
                "current_state_version": current_state_version,
                "draft_hash": draft_hash,
            },
        )
        return False, "This preview is outdated. Please review the updated version."

    # Get channel policy
    async with get_connection() as conn:
        store = ApprovalPolicyStore(conn)
        await store.ensure_table()
        policy = await store.get_effective_policy(channel_id, action_type)

    # Validate based on policy
    if policy == ApprovalPolicy.TWO_PERSON:
        if user_id == creator_user_id:
            logger.info(
                "Two-person rule blocked self-approval",
                extra={
                    "channel_id": channel_id,
                    "user_id": user_id,
                    "action_type": action_type,
                },
            )
            return False, "Two-person rule: You cannot approve your own work. Please ask another team member."

    if policy == ApprovalPolicy.ONLY_ADMINS:
        # Note: Full implementation would check Slack API for channel admin status
        # For now, this is a placeholder that allows all approvals
        # A future enhancement could integrate with Slack's conversations.info API
        logger.debug(
            "ONLY_ADMINS policy - admin check not implemented, allowing approval",
            extra={
                "channel_id": channel_id,
                "user_id": user_id,
            },
        )
        # TODO: Implement Slack admin check when needed
        pass

    logger.info(
        "Approval validation passed",
        extra={
            "channel_id": channel_id,
            "user_id": user_id,
            "policy": policy.value,
            "action_type": action_type,
        },
    )
    return True, None


async def check_already_approved(
    session_id: str,
    draft_hash: str,
) -> Tuple[bool, Optional[str]]:
    """Check if this draft was already approved.

    Used to implement first-wins semantics - only the first approval
    is accepted, subsequent clicks show "Already approved by @user".

    Args:
        session_id: Session ID for the draft
        draft_hash: Hash of draft content

    Returns:
        (already_approved, approver_display) - If approved, who approved it
    """
    from src.db.approval_store import ApprovalStore
    from src.db.user_metadata_store import UserMetadataStore

    async with get_connection() as conn:
        approval_store = ApprovalStore(conn)
        await approval_store.create_tables()
        existing = await approval_store.get_approval(session_id, draft_hash)

        if not existing:
            return False, None

        # Get approver display name
        user_store = UserMetadataStore(conn)
        await user_store.ensure_table()
        display_name = await user_store.get_display_name(
            existing.approved_by, default=f"<@{existing.approved_by}>"
        )

        logger.debug(
            "Draft already approved",
            extra={
                "session_id": session_id,
                "draft_hash": draft_hash,
                "approved_by": existing.approved_by,
                "display_name": display_name,
            },
        )

        return True, display_name


async def get_creator_user_id(state: dict) -> str:
    """Extract creator user ID from agent state.

    The creator is the user who initiated the draft creation.
    For two-person rule, this is the user who cannot approve.

    Args:
        state: Agent state dict

    Returns:
        User ID of the draft creator
    """
    # Primary: user_id in state (set when draft was created)
    creator = state.get("user_id")
    if creator:
        return creator

    # Fallback: check draft attribution if available
    draft = state.get("draft")
    if draft:
        # Check if draft has attribution (Phase 27.1)
        attribution = draft.get("title_attribution") if isinstance(draft, dict) else getattr(draft, "title_attribution", None)
        if attribution:
            user_id = attribution.get("user_id") if isinstance(attribution, dict) else getattr(attribution, "user_id", None)
            if user_id:
                return user_id

    # Final fallback: empty string (will not match any user)
    return ""
