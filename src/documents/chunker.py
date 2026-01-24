"""Document chunking for retrieval.

Splits documents into 300-800 token chunks with overlap.
Uses LangChain's RecursiveCharacterTextSplitter.

Anti-pattern avoided: Don't hand-roll text splitting.
LangChain handles paragraph boundaries properly.
"""
import logging
from typing import Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

# Constants
DEFAULT_CHUNK_SIZE = 500       # ~500 tokens (chars ≈ tokens * 4)
DEFAULT_CHUNK_OVERLAP = 50     # Overlap for context continuity
CHARS_PER_TOKEN = 4            # Rough estimate
MIN_CHUNK_SIZE = 100           # Don't create tiny chunks


def chunk_document(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict]:
    """Split document into chunks for retrieval.

    Args:
        text: Full document text.
        chunk_size: Target chunk size in tokens.
        chunk_overlap: Overlap between chunks in tokens.

    Returns:
        List of chunk dicts with:
        - chunk_index: Position in document (0-based)
        - chunk_text: The chunk content
        - token_count: Estimated tokens
        - start_char: Starting character position
        - end_char: Ending character position
    """
    if not text or len(text) < MIN_CHUNK_SIZE:
        # Document too small to chunk
        return [{
            "chunk_index": 0,
            "chunk_text": text,
            "token_count": len(text) // CHARS_PER_TOKEN,
            "start_char": 0,
            "end_char": len(text),
        }]

    # Convert token sizes to character sizes
    char_chunk_size = chunk_size * CHARS_PER_TOKEN
    char_overlap = chunk_overlap * CHARS_PER_TOKEN

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=char_chunk_size,
        chunk_overlap=char_overlap,
        separators=["\n\n", "\n", ". ", " "],
        length_function=len,
    )

    # Split text
    chunks = splitter.split_text(text)

    # Build result with metadata
    result = []
    current_pos = 0

    for i, chunk_text in enumerate(chunks):
        # Find actual position in original text
        start_char = text.find(chunk_text, current_pos)
        if start_char == -1:
            start_char = current_pos
        end_char = start_char + len(chunk_text)
        current_pos = start_char + 1  # Move past overlap

        result.append({
            "chunk_index": i,
            "chunk_text": chunk_text,
            "token_count": len(chunk_text) // CHARS_PER_TOKEN,
            "start_char": start_char,
            "end_char": end_char,
        })

    logger.info(f"Split document into {len(result)} chunks")
    return result


def get_chunk_context(
    chunks: list[dict],
    chunk_index: int,
    context_chunks: int = 1,
) -> str:
    """Get a chunk with surrounding context.

    Useful when showing a specific chunk but want nearby content.

    Args:
        chunks: All chunks from chunk_document().
        chunk_index: Target chunk index.
        context_chunks: Number of chunks before/after to include.

    Returns:
        Combined text of target chunk with context.
    """
    start_idx = max(0, chunk_index - context_chunks)
    end_idx = min(len(chunks), chunk_index + context_chunks + 1)

    context_texts = [
        chunks[i]["chunk_text"]
        for i in range(start_idx, end_idx)
    ]

    return "\n\n".join(context_texts)


def estimate_tokens(text: str) -> int:
    """Estimate token count for text.

    Args:
        text: Input text.

    Returns:
        Estimated token count.
    """
    return len(text) // CHARS_PER_TOKEN
