"""Document text extraction for various formats."""

import io
import logging
from pathlib import Path
from typing import Optional

import pypdf
from docx import Document

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Error during document extraction."""

    pass


def extract_pdf(content: bytes) -> str:
    """Extract text from PDF bytes.

    Args:
        content: PDF file content as bytes

    Returns:
        Extracted text, pages separated by newlines
    """
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
        return "\n\n".join(pages)
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        raise ExtractionError(f"Failed to extract PDF: {e}")


def extract_docx(content: bytes) -> str:
    """Extract text from DOCX bytes.

    Args:
        content: DOCX file content as bytes

    Returns:
        Extracted text, paragraphs separated by newlines
    """
    try:
        doc = Document(io.BytesIO(content))
        paragraphs = []
        for para in doc.paragraphs:
            if para.text.strip():
                paragraphs.append(para.text.strip())
        return "\n\n".join(paragraphs)
    except Exception as e:
        logger.error(f"DOCX extraction failed: {e}")
        raise ExtractionError(f"Failed to extract DOCX: {e}")


def extract_text(content: bytes, encoding: str = "utf-8") -> str:
    """Extract text from plain text file (TXT, MD).

    Args:
        content: File content as bytes
        encoding: Text encoding (default utf-8)

    Returns:
        Decoded text content
    """
    try:
        return content.decode(encoding).strip()
    except UnicodeDecodeError:
        # Try latin-1 as fallback
        try:
            return content.decode("latin-1").strip()
        except Exception as e:
            raise ExtractionError(f"Failed to decode text: {e}")


def extract_from_file(content: bytes, filename: str) -> str:
    """Extract text based on file extension.

    Args:
        content: File content as bytes
        filename: Original filename (for extension detection)

    Returns:
        Extracted text content

    Raises:
        ExtractionError: If extraction fails or format unsupported
    """
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        return extract_pdf(content)
    elif ext == ".docx":
        return extract_docx(content)
    elif ext in (".txt", ".md", ".markdown"):
        return extract_text(content)
    else:
        raise ExtractionError(f"Unsupported file type: {ext}")


def normalize_for_llm(text: str, max_length: int = 10000) -> str:
    """Normalize extracted text for LLM consumption.

    - Removes excessive whitespace
    - Truncates if too long
    - Adds truncation marker if needed

    Args:
        text: Extracted text
        max_length: Maximum character length

    Returns:
        Normalized text
    """
    # Normalize whitespace
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = " ".join(line.split())  # Normalize internal whitespace
        if stripped:
            cleaned.append(stripped)

    normalized = "\n".join(cleaned)

    # Truncate if needed
    if len(normalized) > max_length:
        normalized = normalized[: max_length - 50] + "\n\n[Document truncated...]"

    return normalized
