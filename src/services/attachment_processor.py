"""Attachment processor service.

Processes pending attachments asynchronously.
Can be run as background task or triggered on-demand.

Flow:
1. Query pending attachments from store
2. For each: download -> extract -> summarize -> update
3. Mark as ready or failed

Usage:
    processor = AttachmentProcessor(slack_client)
    await processor.process_pending(limit=10)
"""
import asyncio
import logging
from typing import Optional

from slack_sdk.web.async_client import AsyncWebClient

from src.db.attachment_chunk_store import AttachmentChunkStore
from src.db.attachment_store import AttachmentStore
from src.db.connection import get_connection
from src.documents.chunker import chunk_document
from src.documents.pipeline import extract_attachment, generate_summary
from src.schemas.attachment import Attachment, AttachmentStatus

logger = logging.getLogger(__name__)


class AttachmentProcessor:
    """Processes pending attachments.

    Attributes:
        client: Slack client for file downloads.
        max_concurrent: Maximum concurrent extractions.
    """

    def __init__(
        self,
        client: AsyncWebClient,
        max_concurrent: int = 3,
    ) -> None:
        self.client = client
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def process_pending(self, limit: int = 10) -> dict:
        """Process pending attachments.

        Args:
            limit: Maximum attachments to process.

        Returns:
            Dict with processed, failed, skipped counts.
        """
        async with get_connection() as conn:
            store = AttachmentStore(conn)
            pending = await store.get_pending(limit=limit)

        if not pending:
            logger.debug("No pending attachments to process")
            return {"processed": 0, "failed": 0, "skipped": 0}

        logger.info(f"Processing {len(pending)} pending attachments")

        # Process concurrently with semaphore
        tasks = [
            self._process_one(attachment)
            for attachment in pending
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count results
        processed = sum(1 for r in results if r == "ready")
        failed = sum(1 for r in results if r == "failed")
        skipped = sum(1 for r in results if r == "skipped")

        logger.info(
            f"Attachment processing complete: "
            f"{processed} ready, {failed} failed, {skipped} skipped"
        )

        return {
            "processed": processed,
            "failed": failed,
            "skipped": skipped,
        }

    async def _process_one(self, attachment: Attachment) -> str:
        """Process a single attachment.

        Returns:
            Status string: "ready", "failed", or "skipped".
        """
        async with self._semaphore:
            try:
                return await self._do_process(attachment)
            except Exception as e:
                logger.error(
                    f"Unexpected error processing {attachment.filename}: {e}"
                )
                await self._mark_failed(attachment.id, str(e))
                return "failed"

    async def _do_process(self, attachment: Attachment) -> str:
        """Internal processing logic."""
        # Mark as extracting
        await self._update_status(attachment.id, AttachmentStatus.EXTRACTING)

        # Extract content
        result = await extract_attachment(self.client, attachment)

        if result["error"]:
            await self._mark_failed(attachment.id, result["error"])
            return "failed"

        extracted_text = result["extracted_text"]
        token_count = result["token_count"]

        # Generate summary
        summary = await generate_summary(extracted_text, attachment.filename)

        # Update attachment with extracted content
        async with get_connection() as conn:
            store = AttachmentStore(conn)
            success = await store.set_extracted_content(
                attachment.id,
                extracted_text=extracted_text,
                summary=summary,
                token_count=token_count,
            )

        # Chunk the document for retrieval
        if extracted_text and len(extracted_text) > 500:
            chunks = chunk_document(extracted_text)
            async with get_connection() as conn:
                chunk_store = AttachmentChunkStore(conn)
                num_chunks = await chunk_store.store_chunks(
                    attachment.id,
                    chunks,
                )
            logger.info(f"Stored {num_chunks} chunks for {attachment.filename}")

        if success:
            logger.info(f"Attachment ready: {attachment.filename}")
            return "ready"
        else:
            logger.error(f"Failed to save extracted content: {attachment.filename}")
            return "failed"

    async def _update_status(
        self,
        attachment_id,
        status: AttachmentStatus,
    ) -> None:
        """Update attachment status."""
        async with get_connection() as conn:
            store = AttachmentStore(conn)
            await store.update_status(attachment_id, status)

    async def _mark_failed(
        self,
        attachment_id,
        error_message: str,
    ) -> None:
        """Mark attachment as failed."""
        async with get_connection() as conn:
            store = AttachmentStore(conn)
            await store.update_status(
                attachment_id,
                AttachmentStatus.FAILED,
                error_message=error_message,
            )

    async def process_single(self, file_id: str) -> Optional[Attachment]:
        """Process a specific attachment by file ID.

        Use for on-demand processing when user explicitly requests.

        Args:
            file_id: Slack file ID.

        Returns:
            Updated Attachment or None if not found.
        """
        async with get_connection() as conn:
            store = AttachmentStore(conn)
            attachment = await store.get_by_file_id(file_id)

        if not attachment:
            logger.warning(f"Attachment not found: {file_id}")
            return None

        if attachment.status == AttachmentStatus.READY:
            logger.debug(f"Attachment already ready: {file_id}")
            return attachment

        await self._do_process(attachment)

        # Return updated attachment
        async with get_connection() as conn:
            store = AttachmentStore(conn)
            return await store.get_by_file_id(file_id)
