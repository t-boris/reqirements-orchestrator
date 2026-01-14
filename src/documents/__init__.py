"""Document processing for Slack attachments."""

from src.documents.extractor import (
    ExtractionError,
    extract_docx,
    extract_from_file,
    extract_pdf,
    extract_text,
    normalize_for_llm,
)
from src.documents.slack import (
    SUPPORTED_TYPES,
    download_and_extract,
    get_extractable_files,
)

__all__ = [
    "extract_from_file",
    "extract_pdf",
    "extract_docx",
    "extract_text",
    "normalize_for_llm",
    "ExtractionError",
    "download_and_extract",
    "get_extractable_files",
    "SUPPORTED_TYPES",
]
