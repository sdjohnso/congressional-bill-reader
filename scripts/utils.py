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


# Status progression - ordered from earliest to latest in legislative process
STATUS_PROGRESSION = [
    "introduced",
    "referred_to_committee",
    "committee_reported",
    "passed_house",
    "passed_senate",
    "resolving_differences",
    "to_president",
    "signed_into_law",
    "vetoed",
]


def derive_bill_status(actions: list[dict]) -> dict:
    """
    Analyze bill actions to determine current status and key dates.
    Returns dict with current_status, status_date, and milestone flags.
    """
    status_info = {
        "current_status": "introduced",
        "status_date": "",
        "last_action_date": "",
        "last_action_text": "",
        "passed_house": False,
        "passed_house_date": "",
        "passed_senate": False,
        "passed_senate_date": "",
        "became_law": False,
        "became_law_date": "",
        "vetoed": False,
        "vetoed_date": "",
    }

    if not actions:
        return status_info

    latest_action = actions[0] if actions else {}
    status_info["last_action_date"] = latest_action.get("actionDate", "")
    status_info["last_action_text"] = latest_action.get("text", "")[:200]

    best_status = "introduced"
    best_status_date = ""

    for action in actions:
        text = action.get("text", "").lower()
        action_type = action.get("type", "")
        action_date = action.get("actionDate", "")

        if "referred to" in text and "committee" in text:
            if STATUS_PROGRESSION.index("referred_to_committee") > STATUS_PROGRESSION.index(best_status):
                best_status = "referred_to_committee"
                best_status_date = action_date

        if any(kw in text for kw in ["reported by", "ordered to be reported", "reported (amended)"]):
            if STATUS_PROGRESSION.index("committee_reported") > STATUS_PROGRESSION.index(best_status):
                best_status = "committee_reported"
                best_status_date = action_date

        if "passed house" in text or "passed the house" in text:
            status_info["passed_house"] = True
            status_info["passed_house_date"] = action_date
            if STATUS_PROGRESSION.index("passed_house") > STATUS_PROGRESSION.index(best_status):
                best_status = "passed_house"
                best_status_date = action_date

        if "passed senate" in text or "passed the senate" in text:
            status_info["passed_senate"] = True
            status_info["passed_senate_date"] = action_date
            if STATUS_PROGRESSION.index("passed_senate") > STATUS_PROGRESSION.index(best_status):
                best_status = "passed_senate"
                best_status_date = action_date

        if action_type == "ResolvingDifferences" or "conference report" in text:
            if STATUS_PROGRESSION.index("resolving_differences") > STATUS_PROGRESSION.index(best_status):
                best_status = "resolving_differences"
                best_status_date = action_date

        if "presented to president" in text or "sent to president" in text:
            if STATUS_PROGRESSION.index("to_president") > STATUS_PROGRESSION.index(best_status):
                best_status = "to_president"
                best_status_date = action_date

        if action_type == "BecameLaw" or "became public law" in text or "signed by president" in text:
            status_info["became_law"] = True
            status_info["became_law_date"] = action_date
            best_status = "signed_into_law"
            best_status_date = action_date

        if action_type == "Veto" or "vetoed" in text:
            status_info["vetoed"] = True
            status_info["vetoed_date"] = action_date
            best_status = "vetoed"
            best_status_date = action_date

    status_info["current_status"] = best_status
    status_info["status_date"] = best_status_date

    return status_info


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
