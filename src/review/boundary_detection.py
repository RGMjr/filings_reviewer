"""
Boundary detection for semantic text segmentation.

This module provides utilities for detecting semantic boundaries in text,
particularly bullet points and numbered lists. These boundaries are used
to constrain keyword matching in candidate generation, preventing incorrect
associations when keywords cross semantic boundaries.

Key Features:
- Detects bullet points (Unicode bullets, asterisks, hyphens)
- Detects numbered lists (1. 2. 3. or (1) (2) (3))
- Detects lettered lists (a. b. c.)
- Handles multi-line bullets (indented continuations)
- Provides position-based boundary lookup

Usage:
    detector = BoundaryDetector()
    boundaries = detector.find_boundaries(text)
    boundary = detector.get_boundary_at_position(100, boundaries)
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
