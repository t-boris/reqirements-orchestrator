"""jira_create skill - creates Jira tickets with strict approval validation.

This is the most dangerous skill - it creates real Jira tickets.
Every guard must pass before create:
1. Validate approval exists
2. Check draft_hash matches (no drift)
3. Check idempotency (first wins)
4. Create Jira issue
5. Audit trail in jira_operations table

All-or-nothing: Jira failure doesn't advance session state.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from psycopg import AsyncConnection

from src.config.settings import Settings, get_settings
from src.db.approval_store import ApprovalStore
from src.db.jira_operations import JiraOperationStore
from src.jira.client import JiraService, JiraAPIError
from src.jira.types import JiraCreateRequest, JiraIssueType, JiraPriority
from src.schemas.draft import TicketDraft
from src.skills.preview_ticket import compute_draft_hash

logger = logging.getLogger(__name__)


@dataclass
class JiraCreateResult:
    """Result of jira_create operation."""

    success: bool
    jira_key: Optional[str] = None
    jira_url: Optional[str] = None
    error: Optional[str] = None
    was_duplicate: bool = False  # True if already created (idempotent return)


def _format_description(draft: TicketDraft) -> str:
    """Format draft into Jira description.

    Builds a structured description with:
    - Problem statement
    - Proposed solution (if present)
    - Acceptance criteria
    - Constraints (if present)
    - Risks (if present)
    """
    sections = []

    # Problem
    if draft.problem:
        sections.append(f"h3. Problem\n{draft.problem}")

    # Proposed Solution
    if draft.proposed_solution:
        sections.append(f"h3. Proposed Solution\n{draft.proposed_solution}")

    # Acceptance Criteria
    if draft.acceptance_criteria:
        ac_text = "\n".join(f"* {ac}" for ac in draft.acceptance_criteria)
        sections.append(f"h3. Acceptance Criteria\n{ac_text}")

    # Constraints
    if draft.constraints:
        constraints_text = "\n".join(
            f"* {c.key}: {c.value}" for c in draft.constraints if c.status.value != "deprecated"
        )
        if constraints_text:
            sections.append(f"h3. Constraints\n{constraints_text}")

    # Risks
    if draft.risks:
        risks_text = "\n".join(f"* {risk}" for risk in draft.risks)
        sections.append(f"h3. Risks\n{risks_text}")

    # Dependencies
    if draft.dependencies:
        deps_text = "\n".join(f"* {dep}" for dep in draft.dependencies)
        sections.append(f"h3. Dependencies\n{deps_text}")

    return "\n\n".join(sections)


def _map_priority(draft: TicketDraft) -> JiraPriority:
    """Map draft priority to JiraPriority enum.

    Currently defaults to MEDIUM as TicketDraft doesn't have priority field.
    Can be extended to derive priority from risk level or constraints.
    """
    # Future: Could derive from risks or constraints
    # For now, default to MEDIUM
    return JiraPriority.MEDIUM


async def jira_create(
    session_id: str,
    draft: TicketDraft,
    approved_by: str,
    jira_service: JiraService,
    conn: AsyncConnection,
    settings: Optional[Settings] = None,
) -> JiraCreateResult:
    """Create a Jira issue with strict approval validation.

    Pipeline (all-or-nothing):
    1. Validate approval exists
    2. Check draft_hash matches (no drift since approval)
    3. Check idempotency (first wins)
    4. Create Jira issue
    5. Record in audit trail

    Args:
        session_id: Session ID for this operation
        draft: Ticket draft to create
        approved_by: User ID who triggered this (should match approver)
        jira_service: JiraService instance for API calls
        conn: Database connection for approval/operation stores
        settings: Optional settings override (defaults to get_settings())

    Returns:
        JiraCreateResult with success/error status and Jira details
    """
    if settings is None:
        settings = get_settings()

    # Compute current draft hash
    current_hash = compute_draft_hash(draft)

    logger.info(
        "jira_create started",
        extra={
            "session_id": session_id,
            "draft_hash": current_hash,
            "approved_by": approved_by,
        },
    )

    # --- Step 1: Validate approval exists ---
    approval_store = ApprovalStore(conn)
    approval = await approval_store.get_approval(session_id, current_hash)

    if not approval:
        logger.warning(
            "No approval record found",
            extra={"session_id": session_id, "draft_hash": current_hash},
        )
        return JiraCreateResult(
            success=False,
            error="No approval record found. Please approve the draft first.",
        )

    # --- Step 2: Check draft_hash matches ---
    # The approval was for this exact hash, so if we got here, they match
    # Additional validation: ensure the approval status is correct
    if approval.status != "approved":
        logger.warning(
            "Approval status not 'approved'",
            extra={
                "session_id": session_id,
                "draft_hash": current_hash,
                "status": approval.status,
            },
        )
        return JiraCreateResult(
            success=False,
            error=f"Draft status is '{approval.status}', not 'approved'. Please re-approve.",
        )

    # --- Step 3: Check idempotency (first wins) ---
    op_store = JiraOperationStore(conn)
    await op_store.create_tables()  # Ensure table exists

    # Check if already created successfully
    if await op_store.was_already_created(session_id, current_hash):
        existing = await op_store.get_operation(session_id, current_hash, "jira_create")
        if existing and existing.jira_key:
            logger.info(
                "Returning existing Jira issue (idempotent)",
                extra={
                    "session_id": session_id,
                    "draft_hash": current_hash,
                    "jira_key": existing.jira_key,
                },
            )
            return JiraCreateResult(
                success=True,
                jira_key=existing.jira_key,
                jira_url=f"{settings.jira_url.rstrip('/')}/browse/{existing.jira_key}",
                was_duplicate=True,
            )

    # Try to claim this operation (first wins)
    is_new = await op_store.record_operation_start(
        session_id=session_id,
        draft_hash=current_hash,
        operation="jira_create",
        created_by=approved_by,
        approved_by=approval.approved_by,
    )

    if not is_new:
        # Race condition - another process already claimed it
        # Check if it succeeded
        existing = await op_store.get_operation(session_id, current_hash, "jira_create")
        if existing:
            if existing.status == "success" and existing.jira_key:
                # Another process completed successfully
                return JiraCreateResult(
                    success=True,
                    jira_key=existing.jira_key,
                    jira_url=f"{settings.jira_url.rstrip('/')}/browse/{existing.jira_key}",
                    was_duplicate=True,
                )
            elif existing.status == "pending":
                # Another process is still working on it
                return JiraCreateResult(
                    success=False,
                    error="Operation already in progress. Please wait.",
                )
            elif existing.status == "failed":
                # Previous attempt failed - could retry, but for safety, require re-approval
                return JiraCreateResult(
                    success=False,
                    error=f"Previous creation failed: {existing.error_message}. Please try again.",
                )

        return JiraCreateResult(
            success=False,
            error="Operation already in progress",
        )

    # --- Step 4: Create Jira issue ---
    try:
        # Build request
        project_key = settings.jira_default_project
        if not project_key:
            await op_store.mark_failed(
                session_id, current_hash, "jira_create",
                "JIRA_DEFAULT_PROJECT not configured",
            )
            return JiraCreateResult(
                success=False,
                error="Jira project not configured. Please contact administrator.",
            )

        request = JiraCreateRequest(
            project_key=project_key,
            summary=draft.title or "Untitled Ticket",
            description=_format_description(draft),
            issue_type=JiraIssueType.STORY,
            priority=_map_priority(draft),
            epic_key=draft.epic_id,  # Link to Epic if set
        )

        logger.info(
            "Creating Jira issue",
            extra={
                "session_id": session_id,
                "project_key": project_key,
                "summary": draft.title,
            },
        )

        issue = await jira_service.create_issue(request)

        # --- Step 5: Record success in audit trail ---
        await op_store.mark_success(session_id, current_hash, "jira_create", issue.key)

        logger.info(
            "Jira issue created successfully",
            extra={
                "session_id": session_id,
                "jira_key": issue.key,
                "jira_url": issue.url,
            },
        )

        return JiraCreateResult(
            success=True,
            jira_key=issue.key,
            jira_url=issue.url,
        )

    except JiraAPIError as e:
        # Record failure in audit trail
        await op_store.mark_failed(
            session_id, current_hash, "jira_create",
            f"Jira API error {e.status_code}: {e.message}",
        )

        logger.error(
            "Jira API error during creation",
            extra={
                "session_id": session_id,
                "status_code": e.status_code,
                "message": e.message,
            },
            exc_info=True,
        )

        return JiraCreateResult(
            success=False,
            error=f"Jira API error: {e.message}",
        )

    except Exception as e:
        # Record unexpected failure
        await op_store.mark_failed(
            session_id, current_hash, "jira_create",
            f"Unexpected error: {str(e)}",
        )

        logger.error(
            "Unexpected error during Jira creation",
            extra={"session_id": session_id, "error": str(e)},
            exc_info=True,
        )

        return JiraCreateResult(
            success=False,
            error=f"Unexpected error: {str(e)}",
        )
