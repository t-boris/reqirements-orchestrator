"""Slack file download utilities."""

import logging
from typing import Optional

from slack_sdk.web import WebClient

from src.documents.extractor import ExtractionError, extract_from_file, normalize_for_llm

logger = logging.getLogger(__name__)

# Supported MIME types
SUPPORTED_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/markdown": ".md",
}


async def download_and_extract(
    client: WebClient,
    file_info: dict,
    max_length: int = 10000,
) -> Optional[str]:
    """Download Slack file and extract text content.

    Args:
        client: Slack WebClient with bot token
        file_info: File object from Slack event
        max_length: Max characters for extracted text

    Returns:
        Extracted and normalized text, or None if unsupported/failed
    """
    file_id = file_info.get("id")
    filename = file_info.get("name", "unknown")
    mimetype = file_info.get("mimetype", "")
    url_private = file_info.get("url_private")

    # Check if supported
    if mimetype not in SUPPORTED_TYPES:
        logger.debug(f"Unsupported file type: {mimetype} ({filename})")
        return None

    if not url_private:
        logger.warning(f"No download URL for file: {filename}")
        return None

    try:
        # Download file content
        response = client.files_info(file=file_id)
        file_content = client.http_client.fetch(
            url_private,
            headers={"Authorization": f"Bearer {client.token}"},
        )

        # Extract text
        text = extract_from_file(file_content.body, filename)
        normalized = normalize_for_llm(text, max_length)

        logger.info(
            f"Extracted document",
            extra={
                "filename": filename,
                "mimetype": mimetype,
                "chars": len(normalized),
            },
        )

        return normalized

    except ExtractionError as e:
        logger.warning(f"Extraction failed for {filename}: {e}")
        return None
    except Exception as e:
        logger.error(f"Download failed for {filename}: {e}")
        return None


def get_extractable_files(files: list[dict]) -> list[dict]:
    """Filter files to only extractable types.

    Args:
        files: List of file objects from Slack event

    Returns:
        Filtered list of extractable files
    """
    return [f for f in files if f.get("mimetype") in SUPPORTED_TYPES]
