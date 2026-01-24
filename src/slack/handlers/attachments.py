"""Attachment event handlers.

Handles file_shared events and files in messages.
Registers attachments for extraction pipeline.

Flow:
1. Detect file (file_shared event OR message with files array)
2. Filter to supported MIME types
3. Create Attachment record (status=pending)
4. Trigger immediate extraction (fire-and-forget)
"""
import asyncio
import logging
from typing import Callable, Optional
from uuid import UUID

from slack_sdk.web.async_client import AsyncWebClient

from src.db.attachment_store import AttachmentStore
from src.db.connection import get_connection
from src.documents.slack import SUPPORTED_TYPES
from src.schemas.attachment import AttachmentStatus

logger = logging.getLogger(__name__)


async def handle_file_shared(
    client: AsyncWebClient,
    event: dict,
) -> None:
    """Handle file_shared event from Slack.

    Called when a file is uploaded to a channel.
    Creates Attachment record for supported file types.

    Args:
        client: Slack client for API calls.
        event: file_shared event payload.
    """
    file_id = event.get("file_id")
    channel_id = event.get("channel_id")
    user_id = event.get("user_id")

    if not all([file_id, channel_id, user_id]):
        logger.warning(f"Incomplete file_shared event: {event}")
        return

    # Get file info from Slack
    try:
        result = await client.files_info(file=file_id)
        file_info = result.get("file", {})
    except Exception as e:
        logger.error(f"Failed to get file info for {file_id}: {e}")
        return

    attachment_result = await _register_attachment(
        file_info=file_info,
        channel_id=channel_id,
        thread_ts=None,  # file_shared doesn't include thread
        uploaded_by=user_id,
    )

    # Trigger immediate processing (fire-and-forget)
    if attachment_result:
        await _trigger_processing(client, UUID(attachment_result["id"]))


async def handle_message_files(
    event: dict,
    files: list[dict],
) -> list[str]:
    """Handle files array in message event.

    Called when a message contains file attachments.
    Returns list of registered file IDs.

    Args:
        event: Message event payload.
        files: List of file objects from event["files"].

    Returns:
        List of file IDs that were registered.
    """
    channel_id = event.get("channel")
    thread_ts = event.get("thread_ts")
    user_id = event.get("user")

    if not channel_id or not user_id:
        logger.warning(f"Incomplete message event for files: {event}")
        return []

    registered = []
    for file_info in files:
        attachment = await _register_attachment(
            file_info=file_info,
            channel_id=channel_id,
            thread_ts=thread_ts,
            uploaded_by=user_id,
        )
        if attachment:
            registered.append(file_info.get("id"))

    return registered


async def _register_attachment(
    file_info: dict,
    channel_id: str,
    thread_ts: Optional[str],
    uploaded_by: str,
) -> Optional[dict]:
    """Register a file as an Attachment if supported.

    Args:
        file_info: Slack file object with id, name, mimetype, size.
        channel_id: Channel where file was uploaded.
        thread_ts: Thread timestamp if in thread.
        uploaded_by: User who uploaded the file.

    Returns:
        Attachment dict if registered, None if unsupported.
    """
    file_id = file_info.get("id")
    filename = file_info.get("name", "unknown")
    mimetype = file_info.get("mimetype", "")
    size_bytes = file_info.get("size")

    # Filter to supported types
    if mimetype not in SUPPORTED_TYPES:
        logger.debug(
            f"Skipping unsupported file type: {filename} ({mimetype})"
        )
        return None

    # Check size limit (10MB)
    max_size = 10 * 1024 * 1024
    if size_bytes and size_bytes > max_size:
        logger.info(
            f"File too large: {filename} ({size_bytes} bytes)"
        )
        # Still register, but mark as too_large
        async with get_connection() as conn:
            store = AttachmentStore(conn)
            attachment = await store.create(
                file_id=file_id,
                filename=filename,
                mimetype=mimetype,
                channel_id=channel_id,
                thread_ts=thread_ts,
                uploaded_by=uploaded_by,
                size_bytes=size_bytes,
            )
            await store.update_status(
                attachment.id,
                AttachmentStatus.TOO_LARGE,
                error_message=f"File size {size_bytes} exceeds limit {max_size}",
            )
        return None

    # Register attachment
    async with get_connection() as conn:
        store = AttachmentStore(conn)
        attachment = await store.create(
            file_id=file_id,
            filename=filename,
            mimetype=mimetype,
            channel_id=channel_id,
            thread_ts=thread_ts,
            uploaded_by=uploaded_by,
            size_bytes=size_bytes,
        )

    logger.info(
        f"Registered attachment: {filename} ({file_id}) "
        f"in {channel_id}/{thread_ts or 'channel'}"
    )

    return {
        "id": str(attachment.id),
        "file_id": file_id,
        "filename": filename,
        "status": attachment.status.value,
    }


def is_supported_file(file_info: dict) -> bool:
    """Check if a file is supported for extraction.

    Args:
        file_info: Slack file object.

    Returns:
        True if file can be extracted.
    """
    mimetype = file_info.get("mimetype", "")
    return mimetype in SUPPORTED_TYPES


def on_file_shared(event: dict, client) -> None:
    """Synchronous wrapper for file_shared event handler.

    Bolt calls event handlers from a sync context. This wraps the
    async handler and runs it in the background.

    Args:
        event: file_shared event payload from Slack.
        client: Slack WebClient.
    """
    from src.slack.handlers.core import _run_async

    _run_async(_handle_file_shared_async(event, client))


async def _handle_file_shared_async(event: dict, client) -> None:
    """Async implementation for file_shared event handling."""
    file_id = event.get("file_id")
    channel_id = event.get("channel_id")
    user_id = event.get("user_id")

    if not all([file_id, channel_id, user_id]):
        logger.warning(f"Incomplete file_shared event: {event}")
        return

    # Get file info from Slack (sync client)
    try:
        result = client.files_info(file=file_id)
        file_info = result.get("file", {})
    except Exception as e:
        logger.error(f"Failed to get file info for {file_id}: {e}")
        return

    await _register_attachment(
        file_info=file_info,
        channel_id=channel_id,
        thread_ts=None,  # file_shared doesn't include thread
        uploaded_by=user_id,
    )


async def _trigger_processing(
    client: AsyncWebClient,
    attachment_id: UUID,
) -> None:
    """Trigger processing for a newly registered attachment.

    Fire-and-forget: errors logged but don't block registration.

    Args:
        client: Slack async client for file download.
        attachment_id: ID of the attachment to process.
    """
    try:
        from src.services.attachment_processor import AttachmentProcessor

        processor = AttachmentProcessor(client)
        async with get_connection() as conn:
            store = AttachmentStore(conn)
            attachment = await store.get(attachment_id)

        if attachment:
            # Fire-and-forget: create task but don't await
            asyncio.create_task(processor._do_process(attachment))
            logger.debug(f"Triggered processing for attachment {attachment_id}")
    except Exception as e:
        logger.warning(f"Failed to trigger processing: {e}")


async def handle_attachment_pin(
    client: AsyncWebClient,
    body: dict,
    respond: Callable,
) -> None:
    """Handle pin button click.

    Pins attachment to context for BUILD/THINK modes.

    Args:
        client: Slack client.
        body: Button action payload.
        respond: Response function for ephemeral message.
    """
    user_id = body.get("user", {}).get("id")
    action = body.get("actions", [{}])[0]
    attachment_id = action.get("value")

    if not attachment_id:
        await respond(text="Error: No attachment ID")
        return

    async with get_connection() as conn:
        store = AttachmentStore(conn)
        attachment = await store.get(UUID(attachment_id))

        if not attachment:
            await respond(text="Attachment not found")
            return

        success = await store.pin(UUID(attachment_id), user_id)

    if success:
        # Fetch updated attachment for notification
        async with get_connection() as conn:
            store = AttachmentStore(conn)
            attachment = await store.get(UUID(attachment_id))

        # Post notification
        from src.slack.blocks.attachments import build_attachment_notification
        blocks = build_attachment_notification(attachment, "pinned")

        await respond(
            text=f":pushpin: Pinned: {attachment.filename}",
            blocks=blocks,
        )

        logger.info(
            f"Attachment pinned: {attachment.filename} "
            f"by {user_id}"
        )
    else:
        await respond(text="Failed to pin attachment")


async def handle_attachment_unpin(
    client: AsyncWebClient,
    body: dict,
    respond: Callable,
) -> None:
    """Handle unpin button click.

    Removes attachment from context.

    Args:
        client: Slack client.
        body: Button action payload.
        respond: Response function for ephemeral message.
    """
    action = body.get("actions", [{}])[0]
    attachment_id = action.get("value")

    if not attachment_id:
        await respond(text="Error: No attachment ID")
        return

    async with get_connection() as conn:
        store = AttachmentStore(conn)
        attachment = await store.get(UUID(attachment_id))

        if not attachment:
            await respond(text="Attachment not found")
            return

        success = await store.unpin(UUID(attachment_id))

    if success:
        # Fetch updated attachment
        async with get_connection() as conn:
            store = AttachmentStore(conn)
            attachment = await store.get(UUID(attachment_id))

        from src.slack.blocks.attachments import build_attachment_notification
        blocks = build_attachment_notification(attachment, "unpinned")

        await respond(
            text=f":paperclip: Unpinned: {attachment.filename}",
            blocks=blocks,
        )

        logger.info(f"Attachment unpinned: {attachment.filename}")
    else:
        await respond(text="Failed to unpin attachment")


def register_attachment_handlers(app) -> None:
    """Register attachment button handlers with Slack app.

    Call from router.py during app setup.

    Args:
        app: Slack Bolt app instance.
    """
    from src.slack.handlers.core import _run_async

    @app.action("attachment_pin")
    def on_pin(ack, body, client, respond):
        ack()
        _run_async(handle_attachment_pin(client, body, respond))

    @app.action("attachment_unpin")
    def on_unpin(ack, body, client, respond):
        ack()
        _run_async(handle_attachment_unpin(client, body, respond))
