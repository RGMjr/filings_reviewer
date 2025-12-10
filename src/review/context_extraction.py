"""
Context Extraction - Extract text context around positions in documents.

This module provides functionality to extract context words around specific
positions in text. It handles:
- Parsing text into words with character positions
- Extracting N words before and after a target position
- Optimized caching for repeated extractions from the same text

Extracted from candidate_generator.py as part of P1.3 module splitting
for improved maintainability and testability.
"""

import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Default number of words to extract each direction from target position
DEFAULT_CONTEXT_WORDS = 40


# =============================================================================
# ContextExtractor Class
# =============================================================================


class ContextExtractor:
    """
    Extractor for text context around positions.

    Handles extracting context words around specific character positions
    in text. Supports caching of word positions for efficiency when
    extracting multiple contexts from the same text.
    """

    def __init__(self, context_words: int = DEFAULT_CONTEXT_WORDS):
        """
        Initialize the context extractor.

        Args:
            context_words: Number of words to extract each direction
        """
        self.context_words = context_words

    def parse_text_into_words(self, text: str) -> List[Tuple[int, int, str]]:
        """
        Parse text into words with their character positions.

        This helper method allows pre-computing word positions once,
        rather than re-parsing for every extraction.

        Args:
            text: The text to parse

        Returns:
            List of (start_pos, end_pos, word_text) tuples
        """
        words = []
        for match in re.finditer(r"\S+", text):
            words.append((match.start(), match.end(), match.group()))
        return words

    def extract_context(
        self,
        text: str,
        position: int,
        cached_words: Optional[List[Tuple[int, int, str]]] = None,
    ) -> str:
        """
        Extract context words around a position.

        Can use pre-computed word positions (cached_words) for efficiency,
        otherwise will parse the text. The cache should be populated by
        calling parse_text_into_words() once per text.

        Args:
            text: The full text
            position: Character position to center on
            cached_words: Optional pre-computed word positions from parse_text_into_words()

        Returns:
            Context string with ~context_words words each direction
        """
        # Use cached word positions if available
        if cached_words is not None:
            words = cached_words
        else:
            # Fallback: parse words if not cached
            words = self.parse_text_into_words(text)

        if not words:
            # No words found - return truncated text
            return text[:500] if len(text) > 500 else text

        # Find the word containing or nearest to position
        center_idx = 0
        min_dist = float("inf")
        for i, (start, end, _) in enumerate(words):
            if start <= position < end:
                # Position is inside this word
                center_idx = i
                break
            # Position is outside - calculate distance
            dist = min(abs(start - position), abs(end - position))
            if dist < min_dist:
                min_dist = dist
                center_idx = i

        # Extract words around center
        start_idx = max(0, center_idx - self.context_words)
        end_idx = min(len(words), center_idx + self.context_words + 1)

        # Get text span from first word start to last word end
        context_start = words[start_idx][0]
        context_end = words[end_idx - 1][1]

        return text[context_start:context_end]
