"""
Boundary detection for semantic text segmentation.

This module provides utilities for detecting semantic boundaries in text,
particularly bullet points, numbered lists, and sentences. These boundaries
are used to constrain keyword matching in candidate generation, preventing
incorrect associations when keywords cross semantic boundaries.

Key Features:
- Detects bullet points (Unicode bullets, asterisks, hyphens)
- Detects numbered lists (1. 2. 3. or (1) (2) (3))
- Detects lettered lists (a. b. c.)
- Handles multi-line bullets (indented continuations)
- Detects sentence boundaries (P1.5 enhancement)
- Provides position-based boundary lookup

Usage:
    detector = BoundaryDetector()
    boundaries = detector.find_boundaries(text)
    boundary = detector.get_boundary_at_position(100, boundaries)

    # P1.5: Sentence boundary detection
    sentences = detector.find_sentence_boundaries(text)
    sentence = detector.get_boundary_at_position(50, sentences)
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class TextBoundary:
    """
    Represents a semantic boundary in text.

    A boundary is a contiguous region of text that forms a semantic unit,
    such as a bullet point, numbered list item, or paragraph.

    Attributes:
        start: Character position where the boundary starts (inclusive)
        end: Character position where the boundary ends (exclusive)
        boundary_type: Type of boundary ('bullet', 'numbered_list', 'lettered_list', 'paragraph')
        marker: The marker text that started this boundary (e.g., '•', '1.', 'a.')
    """

    start: int
    end: int
    boundary_type: str
    marker: str

    def contains_position(self, pos: int) -> bool:
        """Check if a character position falls within this boundary."""
        return self.start <= pos < self.end

    def __repr__(self) -> str:
        return f"TextBoundary(type={self.boundary_type}, start={self.start}, end={self.end}, marker='{self.marker}')"


# =============================================================================
# Boundary Detection
# =============================================================================


class BoundaryDetector:
    """
    Detects semantic boundaries in text for improved keyword matching.

    This class identifies bullet points, numbered lists, and other semantic
    boundaries that should constrain keyword-to-number associations during
    candidate generation.
    """

    # Bullet point patterns (must match at start of line)
    # Uses raw strings to avoid escaping backslashes
    BULLET_PATTERNS = [
        (r"^\s*[•●○■□▪▫◦‣⁃]\s+", "bullet"),  # Unicode bullets
        (r"^\s*[-*]\s+", "bullet"),  # Hyphen and asterisk bullets
        (r"^\s*\d+\.\s+", "numbered_list"),  # Numbered: 1. 2. 3.
        (r"^\s*[a-z]\.\s+", "lettered_list"),  # Lettered: a. b. c.
        (r"^\s*\(\d+\)\s+", "numbered_list"),  # Parenthetical: (1) (2) (3)
        (r"^\s*\([a-z]\)\s+", "lettered_list"),  # Parenthetical: (a) (b) (c)
    ]

    # Compile patterns once for performance
    _compiled_patterns = [(re.compile(pattern), btype) for pattern, btype in BULLET_PATTERNS]

    # Minimum indentation (spaces) to consider a line as a continuation
    # Lines with less indentation are considered new boundaries
    MIN_CONTINUATION_INDENT = 2

    # ==========================================================================
    # P1.5: Sentence Detection Constants
    # ==========================================================================

    # Common abbreviations that should NOT end sentences
    # These are checked case-insensitively
    ABBREVIATIONS: set[str] = {
        # Titles
        "mr",
        "ms",
        "mrs",
        "dr",
        "jr",
        "sr",
        "prof",
        # Corporate suffixes
        "inc",
        "corp",
        "ltd",
        "co",
        "llc",
        "llp",
        "plc",
        # Country codes
        "u.s",
        "u.k",
        "e.u",
        # Latin abbreviations
        "e.g",
        "i.e",
        "vs",
        "etc",
        "al",  # et al.
        "approx",
        # Other common
        "no",  # No. 1
        "vol",
        "fig",
        "sec",  # Section
        "pp",  # pages
    }

    def __init__(self) -> None:
        """Initialize the boundary detector."""
        pass

    def find_boundaries(self, text: str) -> List[TextBoundary]:
        """
        Find all semantic boundaries in the given text.

        This method splits text into lines and identifies bullet points,
        numbered lists, and other semantic boundaries. Multi-line bullets
        (continuations) are grouped into single boundaries.

        Args:
            text: The text to analyze

        Returns:
            List of TextBoundary objects in document order

        Algorithm:
            1. Split text into lines
            2. For each line, check if it starts a new boundary (matches BULLET_PATTERNS)
            3. Group consecutive lines into boundaries
            4. Handle multi-line bullets using indentation heuristics
            5. Create TextBoundary objects with start/end positions
        """
        if not text:
            return []

        lines = text.split("\n")
        boundaries: List[TextBoundary] = []
        current_boundary_start: Optional[int] = None
        current_boundary_type: Optional[str] = None
        current_boundary_marker: Optional[str] = None
        current_pos = 0

        for i, line in enumerate(lines):
            line_start = current_pos
            line_end = current_pos + len(line)

            # Check if this line starts a new boundary
            marker, boundary_type = self._get_line_boundary_type(line)

            if marker is not None:
                # This line starts a new boundary

                # Close previous boundary if exists
                if current_boundary_start is not None:
                    boundaries.append(
                        TextBoundary(
                            start=current_boundary_start,
                            end=line_start,  # End at start of new boundary
                            boundary_type=current_boundary_type or "paragraph",
                            marker=current_boundary_marker or "",
                        )
                    )

                # Start new boundary
                current_boundary_start = line_start
                current_boundary_type = boundary_type
                current_boundary_marker = marker

            elif current_boundary_start is not None:
                # This line might be a continuation of the current boundary
                # Check indentation to determine if it's a continuation
                is_continuation = self._is_continuation_line(line, lines, i)

                if not is_continuation and line.strip() and current_boundary_type != "paragraph":
                    # Non-empty, non-indented line after a bullet/numbered list - close current boundary
                    boundaries.append(
                        TextBoundary(
                            start=current_boundary_start,
                            end=line_start,
                            boundary_type=current_boundary_type or "paragraph",
                            marker=current_boundary_marker or "",
                        )
                    )
                    # This line starts a new implicit paragraph boundary
                    current_boundary_start = line_start
                    current_boundary_type = "paragraph"
                    current_boundary_marker = ""
                # else: continuation - keep accumulating (including for plain paragraphs)

            else:
                # No current boundary, start implicit paragraph
                if line.strip():  # Only for non-empty lines
                    current_boundary_start = line_start
                    current_boundary_type = "paragraph"
                    current_boundary_marker = ""

            # Move position to next line (including newline)
            current_pos = line_end + 1  # +1 for the newline character

        # Close final boundary
        if current_boundary_start is not None:
            boundaries.append(
                TextBoundary(
                    start=current_boundary_start,
                    end=len(text),  # End at end of text
                    boundary_type=current_boundary_type or "paragraph",
                    marker=current_boundary_marker or "",
                )
            )

        return boundaries

    def get_boundary_at_position(
        self, pos: int, boundaries: List[TextBoundary]
    ) -> Optional[TextBoundary]:
        """
        Find the boundary that contains the given character position.

        Args:
            pos: Character position to look up
            boundaries: List of boundaries to search

        Returns:
            The TextBoundary containing the position, or None if not found
        """
        for boundary in boundaries:
            if boundary.contains_position(pos):
                return boundary
        return None

    # ==========================================================================
    # P1.5: Sentence Boundary Detection
    # ==========================================================================

    def find_sentence_boundaries(
        self, text: str, segment_type: Optional[str] = None
    ) -> List[TextBoundary]:
        """
        Find sentence boundaries within text.

        This method detects sentence-ending punctuation (.!?) and returns
        boundaries for each sentence. It handles abbreviations (Mr., Inc., U.S.)
        and decimals (52.3%) to avoid false sentence breaks.

        P1.5 Enhancement: Used to constrain keyword matching within sentences,
        preventing cross-sentence false positives.

        Args:
            text: The text to analyze
            segment_type: Optional segment type ('table', 'paragraph', etc.)
                          If 'table', returns single boundary covering all text
                          to prevent false negatives in tabular data.

        Returns:
            List of TextBoundary objects with boundary_type='sentence'

        Example:
            >>> detector = BoundaryDetector()
            >>> text = "Revenue grew 25%. Margin improved to 52.3%."
            >>> sentences = detector.find_sentence_boundaries(text)
            >>> len(sentences)
            2
            >>> sentences[0].boundary_type
            'sentence'
        """
        if not text or not text.strip():
            return []

        # For table segments, return single boundary to prevent false negatives
        # Table cells may not form grammatical sentences
        if segment_type == "table":
            return [
                TextBoundary(
                    start=0,
                    end=len(text),
                    boundary_type="sentence",
                    marker="[table]",
                )
            ]

        boundaries: List[TextBoundary] = []
        current_start = 0

        # Find potential sentence endings
        # Pattern: sentence-ending punctuation followed by whitespace or end
        sentence_end_pattern = re.compile(r"[.!?](?=\s|$)")

        for match in sentence_end_pattern.finditer(text):
            end_pos = match.end()
            punct_pos = match.start()

            # Check if this is a false positive (abbreviation or decimal)
            if self._is_false_sentence_end(text, punct_pos):
                continue

            # Check if followed by capital letter (strong sentence boundary signal)
            # or end of text
            if not self._is_likely_sentence_end(text, end_pos):
                continue

            # Found a sentence boundary
            boundaries.append(
                TextBoundary(
                    start=current_start,
                    end=end_pos,
                    boundary_type="sentence",
                    marker=text[punct_pos],  # The punctuation mark
                )
            )

            # Find next sentence start (skip whitespace)
            current_start = end_pos
            while current_start < len(text) and text[current_start].isspace():
                current_start += 1

        # Handle final sentence (may not end with punctuation)
        if current_start < len(text):
            remaining = text[current_start:].strip()
            if remaining:
                boundaries.append(
                    TextBoundary(
                        start=current_start,
                        end=len(text),
                        boundary_type="sentence",
                        marker="",  # No terminator
                    )
                )

        return boundaries

    def _is_false_sentence_end(self, text: str, punct_pos: int) -> bool:
        """
        Check if a period at the given position is NOT a sentence end.

        Returns True if the period is likely:
        - Part of an abbreviation (Mr., Inc., U.S.)
        - Part of a decimal number (52.3)
        - Part of an ellipsis (...)

        Args:
            text: The full text
            punct_pos: Position of the punctuation mark

        Returns:
            True if this is a false sentence end, False if it's a real end
        """
        # Check if part of ellipsis
        if punct_pos >= 2 and text[punct_pos - 2 : punct_pos + 1] == "...":
            return True
        if punct_pos + 2 < len(text) and text[punct_pos : punct_pos + 3] == "...":
            return True

        # Only check abbreviations for periods (not ! or ?)
        if text[punct_pos] != ".":
            return False

        # Check if this is a decimal number (digit.digit pattern like 52.3)
        # Only treat as decimal if there's a digit BOTH before AND after the period
        if punct_pos > 0 and text[punct_pos - 1].isdigit():
            if punct_pos + 1 < len(text) and text[punct_pos + 1].isdigit():
                return True
            # If digit before but not after, this is likely end of sentence
            # e.g., "in 2023." or "grew 25%."

        # Extract the word before the period
        word_start = punct_pos - 1
        while word_start > 0 and (text[word_start - 1].isalpha() or text[word_start - 1] == "."):
            word_start -= 1

        word = text[word_start:punct_pos].lower()

        # Handle multi-part abbreviations (U.S., e.g., i.e.)
        # Strip internal periods for comparison
        word_normalized = word.replace(".", "")

        # Check against abbreviations
        if word_normalized in self.ABBREVIATIONS or word in self.ABBREVIATIONS:
            return True

        # Single letter followed by period is often an initial (J. Smith)
        if len(word) == 1 and word.isalpha():
            return True

        return False

    def _is_likely_sentence_end(self, text: str, pos_after_punct: int) -> bool:
        """
        Check if position after punctuation indicates a real sentence end.

        A real sentence end is typically followed by:
        - End of text
        - Whitespace then capital letter
        - Multiple whitespace characters (paragraph break)

        Args:
            text: The full text
            pos_after_punct: Position immediately after the punctuation

        Returns:
            True if this looks like a real sentence end
        """
        # End of text is always a sentence end
        if pos_after_punct >= len(text):
            return True

        # Skip whitespace to find next non-whitespace character
        next_pos = pos_after_punct
        while next_pos < len(text) and text[next_pos].isspace():
            next_pos += 1

        # No more text after whitespace
        if next_pos >= len(text):
            return True

        # Check if next character is uppercase (strong signal)
        next_char = text[next_pos]
        if next_char.isupper():
            return True

        # Check if next character is a quote or parenthesis followed by uppercase
        if next_char in '"\'([':
            if next_pos + 1 < len(text) and text[next_pos + 1].isupper():
                return True

        # Not followed by uppercase - probably not a sentence end
        return False

    def _get_line_boundary_type(self, line: str) -> tuple[Optional[str], Optional[str]]:
        """
        Check if a line starts a semantic boundary and return its type.

        Args:
            line: The line to check

        Returns:
            Tuple of (marker, boundary_type) if line starts a boundary,
            (None, None) otherwise
        """
        for pattern, boundary_type in self._compiled_patterns:
            match = pattern.match(line)
            if match:
                marker = match.group(0).strip()
                return marker, boundary_type
        return None, None

    def _is_continuation_line(self, line: str, all_lines: List[str], line_index: int) -> bool:
        """
        Determine if a line is a continuation of the previous boundary.

        A line is considered a continuation if:
        1. It's indented more than the boundary marker line, OR
        2. It's blank (allows for spacing within boundaries)

        Args:
            line: The line to check
            all_lines: All lines in the text
            line_index: Index of the current line

        Returns:
            True if line is a continuation, False otherwise
        """
        # Blank lines are continuations
        if not line.strip():
            return True

        # Find the indentation of the current line
        current_indent = len(line) - len(line.lstrip())

        # Look back to find the boundary marker line
        # (the most recent line that started a boundary)
        for i in range(line_index - 1, -1, -1):
            prev_line = all_lines[i]
            marker, _ = self._get_line_boundary_type(prev_line)
            if marker is not None:
                # Found the boundary marker line
                # Calculate where the text starts (after the marker)
                marker_match = None
                for pattern, _ in self._compiled_patterns:
                    marker_match = pattern.match(prev_line)
                    if marker_match:
                        break

                if marker_match:
                    # Indentation of text after marker
                    marker_end = marker_match.end()
                    # Current line is continuation if indented at least as much as marker text
                    # or if it has some minimum indentation
                    return current_indent >= self.MIN_CONTINUATION_INDENT
                break

        # Default: not a continuation
        return False


# =============================================================================
# Helper Functions
# =============================================================================


def in_same_boundary(pos1: int, pos2: int, boundaries: List[TextBoundary]) -> bool:
    """
    Check if two positions are in the same semantic boundary.

    Args:
        pos1: First character position
        pos2: Second character position
        boundaries: List of boundaries to check

    Returns:
        True if both positions are in the same boundary, False otherwise
    """
    detector = BoundaryDetector()
    boundary1 = detector.get_boundary_at_position(pos1, boundaries)
    boundary2 = detector.get_boundary_at_position(pos2, boundaries)

    if boundary1 is None or boundary2 is None:
        return False

    return boundary1 == boundary2
