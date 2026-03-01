"""
V2 Extraction Pipeline — Shared Text Utilities

Standalone helper functions shared across multiple pipeline stages.
Import directly; do not import via the stages package.
"""

from __future__ import annotations

import re


def find_sentence_bounds(text: str, position: int) -> tuple[int, int]:
    """
    Find sentence boundaries around a given character position.

    Uses a heuristic boundary pattern: [.!?] followed by whitespace and a
    capital letter, or the start/end of the text.

    Args:
        text: Full text to search.
        position: Character position to find sentence bounds around.

    Returns:
        Tuple of (sentence_start, sentence_end) positions.
    """
    boundary_pattern = re.compile(r"[.!?]\s+[A-Z]")

    # Find sentence start (look backwards from position)
    sentence_start = 0
    text_before = text[:position]
    boundaries_before = list(boundary_pattern.finditer(text_before))
    if boundaries_before:
        last_boundary = boundaries_before[-1]
        sentence_start = last_boundary.end() - 1  # -1 to include the capital letter

    # Find sentence end (look forwards from position)
    sentence_end = len(text)
    text_after = text[position:]
    boundary_match = boundary_pattern.search(text_after)
    if boundary_match:
        sentence_end = position + boundary_match.start() + 1  # +1 to include punctuation

    return (sentence_start, sentence_end)


def normalize_text(text: str) -> str:
    """
    Normalize text by collapsing all whitespace (including newlines) to a
    single space and stripping leading/trailing whitespace.

    Args:
        text: Raw text content.

    Returns:
        Normalized text.
    """
    return re.sub(r"\s+", " ", text).strip()
