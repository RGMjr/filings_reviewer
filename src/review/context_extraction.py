"""
Context Extraction - Extract text context around positions in documents.

This module provides functionality to extract context words around specific
positions in text. It handles:
- Parsing text into words with character positions
- Extracting N words before and after a target position
- Optimized caching for repeated extractions from the same text

Extracted from candidate_generator.py as part of P1.3 module splitting
for improved maintainability and testability.

Basic Usage:
    >>> from src.review.context_extraction import ContextExtractor
    >>>
    >>> # Initialize extractor
    >>> extractor = ContextExtractor(context_words=40)
    >>>
    >>> # Extract context around a position
    >>> text = "We had 50,000 active customers as of December 31, 2023."
    >>> context = extractor.extract_context(text, position=10, context_words=20)
    >>> print(context)  # Returns ~20 words each direction from position 10

Automatic Usage (via CandidateGenerator):
    >>> from src.review import CandidateGenerator
    >>>
    >>> # Context extraction happens automatically during candidate generation
    >>> generator = CandidateGenerator()
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>> # Each candidate has context_text field (default: 40 words each direction)
    >>> print(candidates[0].context_text)

Customizing Context Window Size:
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> # Adjust context window size
    >>> config = CandidateGenerationConfig(
    ...     context_words=60,  # Larger context (60 words each direction)
    ... )
    >>> generator = CandidateGenerator(config=config)
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )

Performance Optimization (P1.2):
    >>> # For multiple extractions from same text, pre-compute word positions
    >>> extractor = ContextExtractor()
    >>> text = "Large text with multiple numbers to process..."
    >>>
    >>> # Parse words once
    >>> words = extractor.parse_text_into_words(text)
    >>>
    >>> # Extract context multiple times efficiently (using cached words)
    >>> context1 = extractor.extract_context(text, position=100, word_positions=words)
    >>> context2 = extractor.extract_context(text, position=500, word_positions=words)
    >>> context3 = extractor.extract_context(text, position=900, word_positions=words)
    >>> # ~10-20x faster than re-parsing each time

See Also:
    - candidate_generator.py: Uses ContextExtractor internally
    - config.py: Configure context_words parameter
"""

import logging
import re

from src.review.config import DEFAULT_CONFIG, DEFAULT_CONTEXT_WORDS

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Default number of words to extract each direction from target position
# (imported from config.py for centralized configuration)
DEFAULT_CONTEXT_WORDS = DEFAULT_CONTEXT_WORDS


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

    def __init__(self, context_words: int = DEFAULT_CONFIG.context_words):
        """
        Initialize the context extractor.

        Args:
            context_words: Number of words to extract each direction (default from config)
        """
        self.context_words = context_words

    def parse_text_into_words(self, text: str) -> list[tuple[int, int, str]]:
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
        cached_words: list[tuple[int, int, str]] | None = None,
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
