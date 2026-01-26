"""Draft approval handlers.

Handles the ticket draft lifecycle: approval to Jira.

Phase 28.4: Lifecycle transition enforcement for StructuredDraft.
- Reject approvals if lifecycle is COMMITTED (terminal state)
- Advance lifecycle to APPROVED/COMMITTED on successful operations
"""

import json
import logging

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner
from src.slack.handlers.core import _run_async
from src.slack.handlers.draft_blocks import (
    post_error_actions,
    update_preview_to_created,
)
from src.db.audit_store import AuditStore, AuditActionType

logger = logging.getLogger(__name__)


def handle_approve_draft(ack, body, client: WebClient, action):
    """Synchronous wrapper for draft approval.

    Bolt calls handlers from a sync context. This wraps the async handler.
    """
    ack()
    _run_async(_handle_approve_draft_async(body, client, action))


async def _handle_approve_draft_async(body, client: WebClient, action):
    """Handle 'Approve & Create' button click on draft preview.

    Implements version-checked approval with progress visibility:
    1. Check in-memory dedup (handles Slack retries)
    2. Parse session_id:draft_hash from button value
    3. Check if already approved in DB (duplicate click)
    4. Compute current draft hash and compare
    5. Record approval if valid
    6. Show progress during Jira creation (with retry visibility)
    7. Update preview message to show approved state
    """
    from src.slack.progress import ProgressTracker
    from src.slack.handlers.draft.create import (
        check_preflight_for_create,
        build_create_preflight_blocks,
        build_ticket_announcement_blocks,
    )

    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    message_ts = body["message"]["ts"]  # Preview message to update
    team_id = body["team"]["id"]
    user_id = body["user"]["id"]

    # Parse button payload (Phase 27.4: JSON format with state_version)
    button_value = action.get("value", "")
    action_id = action.get("action_id", "approve_draft")

    # In-memory dedup for Slack retries and rage-clicks
    from src.slack.dedup import try_process_button
    if not try_process_button(action_id, user_id, button_value):
        # Duplicate click - silently ignore (already processing)
        logger.debug(f"Ignoring duplicate approve click: {button_value}")
        return

    # Parse button payload (supports JSON and legacy formats)
    button_state_version = 0
    button_ui_version = 0
    try:
        # Phase 27.4: New JSON format
        payload = json.loads(button_value)
        session_id = payload.get("session_id", "")
        button_hash = payload.get("draft_hash", "")
        button_state_version = payload.get("state_version", 0)
        button_ui_version = payload.get("ui_version", 0)
    except json.JSONDecodeError:
        # Legacy format: session_id:draft_hash
        if ":" in button_value:
            session_id, button_hash = button_value.rsplit(":", 1)
        else:
            session_id = button_value
            button_hash = ""

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    logger.info(
        "Draft approval requested",
        extra={
            "session_id": session_id,
            "button_hash": button_hash,
            "user_id": user_id,
        }
    )

    # Import dependencies
    from src.db import ApprovalStore, get_connection
    from src.skills.preview_ticket import compute_draft_hash
    from src.skills.jira_create import jira_create
    from src.jira.client import JiraService
    from src.config.settings import get_settings

    # Get current draft from runner state (need this early for validation)
    runner = get_runner(identity)
    state = await runner._get_current_state()
    draft = state.get("draft")
    structured_draft = state.get("structured_draft")

    if not draft and not structured_draft:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Error: Could not find draft. Please start a new session.",
        )
        return

    # Phase 28.4: Check lifecycle state for StructuredDraft
    if structured_draft:
        from src.schemas.structured_draft import DraftLifecycle

        if structured_draft.lifecycle == DraftLifecycle.COMMITTED:
            # COMMITTED is terminal - reject approval
            logger.warning(
                "Attempted approval on COMMITTED draft",
                extra={
                    "session_id": session_id,
                    "lifecycle": structured_draft.lifecycle.value,
                }
            )
            client.chat_postEphemeral(
                channel=channel,
                user=user_id,
                text="This draft has already been committed to Jira. No further approvals are needed.",
            )
            return

    # Compute current draft hash
    current_hash = compute_draft_hash(draft)

    # Version check - compare button hash with current draft
    if button_hash and button_hash != current_hash:
        # Draft changed since preview was posted - require re-review
        logger.warning(
            "Draft version mismatch",
            extra={
                "button_hash": button_hash,
                "current_hash": current_hash,
                "session_id": session_id,
            }
        )

        # Post new preview with updated content (Phase 27.4: include state versions)
        from src.slack.blocks import build_draft_preview_blocks_with_hash
        new_blocks = build_draft_preview_blocks_with_hash(
            draft=draft,
            session_id=session_id,
            draft_hash=current_hash,
            state_version=state.get("state_version", 0),
            ui_version=state.get("ui_version", 0),
        )

        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="The draft has changed since you saw this preview. Please review the updated version:",
            blocks=new_blocks,
        )
        return

    # Phase 27.4: Validate approval against policy and state version
    from src.slack.approval_validator import validate_approval, get_creator_user_id

    current_state_version = state.get("state_version", 0)
    creator_user_id = await get_creator_user_id(state)
    hash_to_check = current_hash if current_hash else "no-hash"

    is_valid, error = await validate_approval(
        channel_id=channel,
        user_id=user_id,
        creator_user_id=creator_user_id,
        state_version=button_state_version,
        current_state_version=current_state_version,
        draft_hash=hash_to_check,
    )

    if not is_valid:
        client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text=error,
        )
        return

    # Create progress tracker for Jira creation status
    tracker = ProgressTracker(client, channel, thread_ts)

    # Check for existing approval and record new one
    async with get_connection() as conn:
        approval_store = ApprovalStore(conn)
        await approval_store.create_tables()  # Ensure table exists

        # Check if already approved for this hash
        hash_to_record = current_hash if current_hash else "no-hash"
        existing = await approval_store.get_approval(session_id, hash_to_record)
        if existing:
            # Already approved - check if Jira ticket was created
            from src.db.jira_operations import JiraOperationStore
            op_store = JiraOperationStore(conn)
            await op_store.create_tables()

            if await op_store.was_already_created(session_id, hash_to_record):
                # Ticket already created - notify with link
                existing_op = await op_store.get_operation(session_id, hash_to_record, "jira_create")
                if existing_op and existing_op.jira_key:
                    settings = get_settings()
                    jira_url = f"{settings.jira_url.rstrip('/')}/browse/{existing_op.jira_key}"
                    client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        text=f"Ticket was already created: <{jira_url}|{existing_op.jira_key}>",
                    )
                    return

            # Already approved but not created - notify
            approver = existing.approved_by
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"This draft was already approved by <@{approver}>.",
            )
            return

        # Record approval (first wins) - Phase 27.4: include state binding
        is_new = await approval_store.record_approval(
            session_id=session_id,
            draft_hash=hash_to_record,
            approved_by=user_id,
            status="approved",
            state_version=current_state_version,
            ui_version=state.get("ui_version", 0),
        )

        if not is_new:
            # Race condition - another approval just happened
            approver = await approval_store.get_approver(session_id, hash_to_record)
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"This draft was just approved by <@{approver}>.",
            )
            return

        # Log approval action (Phase 27.5)
        try:
            audit_store = AuditStore(conn)
            await audit_store.ensure_table()
            await audit_store.log(
                channel_id=channel,
                action_type=AuditActionType.DRAFT_APPROVE,
                actor_user_id=user_id,
                target_type="draft",
                target_id=session_id,
                outcome="success",
                thread_ts=thread_ts,
                metadata={
                    "draft_hash": hash_to_record,
                    "state_version": current_state_version,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to log approval audit entry: {e}")

        # Approval recorded - now create Jira ticket with progress visibility
        settings = get_settings()
        jira_service = JiraService(settings)

        # Phase 29.4: Preflight check for duplicates before creation
        try:
            from src.db.jira_registry import JiraRegistryStore
            registry = JiraRegistryStore(conn)
            await registry.create_tables()

            draft_title = draft.title if draft else None
            draft_problem = draft.problem if draft and hasattr(draft, 'problem') else None

            preflight_result = await check_preflight_for_create(
                jira_service=jira_service,
                registry=registry,
                channel_id=channel,
                draft_title=draft_title,
                draft_problem=draft_problem,
            )

            if preflight_result:
                # Duplicate detected - show preflight UI
                conflict_type = preflight_result["conflict_type"]
                existing_key = preflight_result["existing_key"]
                message = preflight_result["message"]

                logger.info(
                    "Preflight duplicate detected",
                    extra={
                        "session_id": session_id,
                        "conflict_type": conflict_type,
                        "existing_key": existing_key,
                    }
                )

                # Build preflight blocks for create
                blocks = build_create_preflight_blocks(
                    preflight_result=preflight_result,
                    session_id=session_id,
                    draft_hash=hash_to_record,
                    channel_id=channel,
                    thread_ts=thread_ts,
                )

                client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    blocks=blocks,
                    text=message,
                )

                await jira_service.close()
                return

        except Exception as e:
            logger.warning(f"Preflight check failed, proceeding with create: {e}")
            # Non-blocking - if preflight fails, proceed with creation

        # Get Slack permalink for Jira description
        slack_permalink = ""
        try:
            from src.context.jira_linker import JiraLinker
            linker = JiraLinker(client, jira_service)
            slack_permalink = linker.get_thread_permalink(channel, thread_ts)
        except Exception as e:
            logger.warning(f"Failed to get Slack permalink: {e}")

        try:
            # Start progress tracking
            await tracker.start("Creating ticket...")

            # Create callback for Jira retry visibility
            async def on_jira_retry(error_type: str, attempt: int, max_attempts: int):
                await tracker.set_error(error_type, "Jira", attempt, max_attempts)

            create_result = await jira_create(
                session_id=session_id,
                draft=draft,
                approved_by=user_id,
                jira_service=jira_service,
                conn=conn,
                settings=settings,
                slack_permalink=slack_permalink,
                progress_callback=on_jira_retry,
                channel_id=channel,
                thread_ts=thread_ts,
            )
        except Exception as e:
            # Unexpected error during creation
            await tracker.set_failure("Jira", str(e))
            await post_error_actions(client, channel, thread_ts, session_id, button_hash, str(e))
            return
        finally:
            await jira_service.close()
            await tracker.complete()

    # Handle Jira creation result
    if create_result.success:
        if create_result.was_duplicate:
            # Already created (idempotent return) - just notify
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"Ticket was already created: <{create_result.jira_url}|{create_result.jira_key}>",
            )
        else:
            # New creation - update session state
            await runner.handle_approval(approved=True)

            # Phase 28.4: Advance StructuredDraft lifecycle to COMMITTED
            if structured_draft:
                from src.schemas.structured_draft import DraftLifecycle, DraftItemStatus
                from src.graph.nodes.validation import transition_lifecycle

                # Mark all items as COMMITTED
                for item in structured_draft.items:
                    item.status = DraftItemStatus.COMMITTED
                    if create_result.jira_key:
                        item.jira_key = create_result.jira_key

                # Transition lifecycle to COMMITTED
                if structured_draft.lifecycle != DraftLifecycle.COMMITTED:
                    # First transition to APPROVED if needed
                    if structured_draft.lifecycle not in (DraftLifecycle.APPROVED, DraftLifecycle.COMMITTED):
                        transition_lifecycle(structured_draft, DraftLifecycle.APPROVED, user_id)
                    # Then transition to COMMITTED
                    transition_lifecycle(structured_draft, DraftLifecycle.COMMITTED, user_id)

                logger.info(
                    "StructuredDraft lifecycle advanced to COMMITTED",
                    extra={
                        "session_id": session_id,
                        "jira_key": create_result.jira_key,
                        "lifecycle": structured_draft.lifecycle.value,
                    }
                )

            # Bind thread to the created ticket for contextual references
            try:
                from src.slack.thread_bindings import get_binding_store

                binding_store = get_binding_store()
                await binding_store.bind(
                    channel_id=channel,
                    thread_ts=thread_ts,
                    issue_key=create_result.jira_key,
                    bound_by="system",  # Auto-bound on ticket creation
                )
            except Exception as e:
                logger.warning(f"Failed to bind thread to ticket: {e}")
                # Non-blocking

            # Register in channel Jira registry (Rule 8)
            try:
                from src.db.jira_registry import JiraRegistryStore

                # Get summary and issue_type from draft
                draft_title = draft.title if draft else None
                draft_issue_type = None
                if draft and hasattr(draft, 'issue_type') and draft.issue_type:
                    draft_issue_type = draft.issue_type.value if hasattr(draft.issue_type, 'value') else str(draft.issue_type)

                async with get_connection() as conn:
                    registry = JiraRegistryStore(conn)
                    await registry.create_tables()
                    await registry.register(
                        channel_id=channel,
                        jira_key=create_result.jira_key,
                        link_type="owned",
                        linked_by=user_id,
                        summary=draft_title,
                        issue_type=draft_issue_type,
                    )
                logger.info(
                    "Registered created ticket in channel registry",
                    extra={
                        "jira_key": create_result.jira_key,
                        "channel": channel,
                        "summary": draft_title[:50] if draft_title else None,
                        "issue_type": draft_issue_type,
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to register ticket in registry: {e}")
                # Non-blocking - ticket creation succeeded

            # Update thread pin with ticket link
            try:
                from src.context.jira_linker import JiraLinker
                from src.jira.client import JiraService
                from src.config.settings import get_settings

                settings = get_settings()
                jira = JiraService(settings)

                linker = JiraLinker(client, jira)
                await linker.on_ticket_created(
                    channel_id=channel,
                    thread_ts=thread_ts,
                    ticket_key=create_result.jira_key,
                    ticket_url=create_result.jira_url,
                    existing_pin_ts=None,  # Could track from epic binding if available
                )

                await jira.close()
            except Exception as e:
                logger.warning(f"Failed to update ticket pin: {e}")
                # Non-blocking

            # Update preview message to show created state
            update_preview_to_created(
                client=client,
                channel=channel,
                message_ts=message_ts,
                draft=draft,
                jira_key=create_result.jira_key,
                jira_url=create_result.jira_url,
                created_by=user_id,
            )

            # Notify in thread with Jira link
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"Ticket created: <{create_result.jira_url}|{create_result.jira_key}>",
            )

            # Post announcement card in MAIN channel (not thread)
            try:
                # Build announcement blocks
                announcement_blocks = build_ticket_announcement_blocks(
                    draft=draft,
                    jira_key=create_result.jira_key,
                    jira_url=create_result.jira_url,
                    created_by=user_id,
                    thread_ts=thread_ts,
                    channel=channel,
                    client=client,
                )
                client.chat_postMessage(
                    channel=channel,
                    # No thread_ts - posts to main channel
                    text=f"Ticket created: {create_result.jira_key} - {draft.title}",
                    blocks=announcement_blocks,
                )
                logger.info(
                    "Posted ticket announcement to main channel",
                    extra={"jira_key": create_result.jira_key, "channel": channel},
                )
            except Exception as e:
                logger.warning(f"Failed to post main channel announcement: {e}")
                # Non-blocking - thread notification already sent

            # Auto-track the created ticket in the channel (Phase 21)
            try:
                from src.slack.channel_tracker import ChannelIssueTracker

                async with get_connection() as conn:
                    tracker = ChannelIssueTracker(conn)
                    await tracker.create_tables()
                    await tracker.track(channel, create_result.jira_key, user_id)
                    # Update sync status with current info
                    await tracker.update_sync_status(
                        channel,
                        create_result.jira_key,
                        status=draft.issue_type or "Task",
                        summary=draft.title,
                    )
                logger.info(
                    "Auto-tracked created ticket",
                    extra={"issue_key": create_result.jira_key, "channel": channel},
                )
            except Exception as e:
                logger.warning(f"Failed to auto-track ticket: {e}")
                # Non-blocking - ticket creation succeeded
    else:
        # Creation failed after retries - show error with action buttons
        await post_error_actions(client, channel, thread_ts, session_id, button_hash, create_result.error)


def handle_approve_structure(ack, body, client: WebClient, action):
    """Synchronous wrapper for structure approval.

    Bolt calls handlers from a sync context. This wraps the async handler.
    """
    ack()
    _run_async(_handle_approve_structure_async(body, client, action))


async def _handle_approve_structure_async(body, client: WebClient, action):
    """Handle approve_structure button click on structure preview.

    R9: Rejects if draft.version != payload.version (stale button).
    Posts ephemeral message for stale approvals.

    Phase 28.6: Structure Feedback UI
    """
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    team_id = body["team"]["id"]
    user_id = body["user"]["id"]

    # Parse button payload with version
    button_value = action.get("value", "{}")
    try:
        payload = json.loads(button_value)
        expected_version = payload.get("version", 0)
        draft_id = payload.get("draft_id")
    except json.JSONDecodeError:
        expected_version = 0
        draft_id = None

    # In-memory dedup for Slack retries
    from src.slack.dedup import try_process_button
    action_id = action.get("action_id", "approve_structure")
    if not try_process_button(action_id, user_id, button_value):
        logger.debug(f"Ignoring duplicate approve_structure click: {button_value}")
        return

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    logger.info(
        "Structure approval requested",
        extra={
            "draft_id": draft_id,
            "expected_version": expected_version,
            "user_id": user_id,
        }
    )

    # Get current structured draft from runner state
    runner = get_runner(identity)
    state = await runner._get_current_state()
    structured_draft = state.get("structured_draft")

    if not structured_draft:
        client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text="Could not find draft. Please start a new session.",
        )
        return

    # R9: Version check - stale button detection
    if structured_draft.version != expected_version:
        # T4: Old approve button -> "Outdated, please review new structure"
        logger.warning(
            "Stale structure approval detected",
            extra={
                "expected_version": expected_version,
                "current_version": structured_draft.version,
                "draft_id": draft_id,
            }
        )
        client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text=f"This structure preview is outdated. The draft has been modified "
                 f"(version {expected_version} -> {structured_draft.version}). "
                 f"Please review the new structure.",
        )
        return

    # Phase 28.4: Check lifecycle state
    from src.schemas.structured_draft import DraftLifecycle, DraftItemStatus

    if structured_draft.lifecycle == DraftLifecycle.COMMITTED:
        client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text="This draft has already been committed to Jira. No further approvals are needed.",
        )
        return

    # Approve all items in the structure
    for item in structured_draft.items:
        if item.status == DraftItemStatus.PROPOSED:
            item.status = DraftItemStatus.APPROVED

    # Transition lifecycle to APPROVED
    from src.graph.nodes.validation import transition_lifecycle

    if structured_draft.lifecycle not in (DraftLifecycle.APPROVED, DraftLifecycle.COMMITTED):
        transition_lifecycle(structured_draft, DraftLifecycle.APPROVED, user_id)

    # Log the approval
    structured_draft.log_change(
        action="structure_approved",
        user_id=user_id,
        details={
            "approved_items": len(structured_draft.items),
        },
    )

    # Update state
    state["structured_draft"] = structured_draft
    await runner.update_state(state)

    # Log audit entry
    try:
        from src.db import get_connection
        async with get_connection() as conn:
            audit_store = AuditStore(conn)
            await audit_store.ensure_table()
            await audit_store.log(
                channel_id=channel,
                action_type=AuditActionType.DRAFT_APPROVE,
                actor_user_id=user_id,
                target_type="structured_draft",
                target_id=structured_draft.id,
                outcome="success",
                thread_ts=thread_ts,
                metadata={
                    "version": structured_draft.version,
                    "items_approved": len(structured_draft.items),
                },
            )
    except Exception as e:
        logger.warning(f"Failed to log structure approval audit: {e}")

    # Notify in thread
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Structure approved by <@{user_id}>. "
             f"{len(structured_draft.items)} items are ready for Jira creation.",
    )

    logger.info(
        "Structure approved",
        extra={
            "draft_id": structured_draft.id,
            "version": structured_draft.version,
            "items_approved": len(structured_draft.items),
            "user_id": user_id,
        }
    )
