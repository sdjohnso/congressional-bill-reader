"""
utils.py
Shared helpers for the Congressional Bill Reader pipeline.
"""

import hashlib
import re


def hash_text(text: str) -> str:
    """Return a short SHA256 hash of a string. Used to detect version changes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def chunk_text(text: str, max_words: int = 15000, overlap_words: int = 200) -> list[str]:
    """
    Split a long text into overlapping chunks for API processing.
    Tries to split on section boundaries first, falls back to word count.

    Args:
        text:          Full bill text
        max_words:     Maximum words per chunk
        overlap_words: Words of overlap between chunks to preserve context

    Returns:
        List of text chunks
    """
    # Try to split on obvious section headers first
    section_pattern = re.compile(
        r'\n(?=SEC\.|SECTION|Title [IVXLC]+|DIVISION [A-Z])', re.IGNORECASE
    )
    parts = section_pattern.split(text)

    chunks = []
    current_chunk_words = []
    current_word_count = 0

    for part in parts:
        part_words = part.split()
        part_word_count = len(part_words)

        # If adding this part would exceed the limit, flush and start new chunk
        if current_word_count + part_word_count > max_words and current_chunk_words:
            chunks.append(" ".join(current_chunk_words))
            # Keep overlap from end of current chunk
            overlap = current_chunk_words[-overlap_words:] if len(current_chunk_words) > overlap_words else current_chunk_words
            current_chunk_words = overlap + part_words
            current_word_count = len(current_chunk_words)
        else:
            current_chunk_words.extend(part_words)
            current_word_count += part_word_count

    if current_chunk_words:
        chunks.append(" ".join(current_chunk_words))

    return chunks if chunks else [text]


def compute_offsets(sections: list[dict]) -> list[dict]:
    """
    Walk through a list of section dicts and add word_offset and char_offset
    to each one. This is what enables deep linking and TTS timestamp sharing
    later without reprocessing.

    Args:
        sections: List of dicts, each with at least a 'text' key

    Returns:
        Same list with word_offset and char_offset populated
    """
    word_pos = 0
    char_pos = 0
    for section in sections:
        section["word_offset"] = word_pos
        section["char_offset"] = char_pos
        words_in_section = len(section["text"].split())
        chars_in_section = len(section["text"])
        word_pos += words_in_section
        char_pos += chars_in_section + 1  # +1 for the newline between sections
    return sections


def slugify(text: str) -> str:
    """Convert a section title to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = re.sub(r'^-+|-+$', '', text)
    return text


def bill_folder_name(congress: int, bill_type: str, bill_number: str) -> str:
    """
    Return a consistent folder name for a bill.
    Example: congress=119, bill_type='s', bill_number='1247' -> '119-s-1247'
    """
    return f"{congress}-{bill_type.lower()}-{bill_number}"
