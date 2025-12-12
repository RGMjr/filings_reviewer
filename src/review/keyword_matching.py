"""
Keyword Matching - Find metric keywords in text and match them to numbers.

This module provides functionality to find metric keywords in text and
determine which keywords are near which numbers. It handles:
- Finding all keyword matches in text
- Filtering keywords by distance from numbers
- Calculating distances between text spans

Extracted from candidate_generator.py as part of P1.3 module splitting
for improved maintainability and testability.

Automatic Usage (via CandidateGenerator):
    >>> from src.review import CandidateGenerator
    >>>
    >>> # Keyword matching happens automatically
    >>> generator = CandidateGenerator()
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>> # Each candidate has triggering_keyword field
    >>> print(candidates[0].triggering_keyword)  # e.g., "active customers"

Direct Usage (advanced):
    >>> from src.review.keyword_matching import KeywordMatcher
    >>> from src.review.number_parsing import NumberMatch
    >>> from decimal import Decimal
    >>>
    >>> # Initialize matcher
    >>> matcher = KeywordMatcher(max_keyword_distance=100)
    >>>
    >>> # Find all keywords in text
    >>> text = "We have 50,000 active customers and $100M in revenue."
    >>> keywords = matcher.find_all_keywords(text)
    >>> print(f"Found {len(keywords)} keyword matches")
    >>>
    >>> # Find keywords near a specific number
    >>> number = NumberMatch(
    ...     start=8, end=14, raw_text="50,000", value=Decimal("50000"), unit="count"
    ... )
    >>> nearby = matcher.find_keywords_near_number(number, keywords)
    >>> for kw in nearby:
    ...     print(f"{kw.keyword} (metric: {kw.metric_id}, distance: {kw.distance})")

Adjusting Proximity Threshold:
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> # Stricter proximity (high precision)
    >>> config = CandidateGenerationConfig(
    ...     max_keyword_distance=50,  # Only match if within 50 chars
    ... )
    >>> generator = CandidateGenerator(config=config)
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>>
    >>> # Looser proximity (high recall)
    >>> config = CandidateGenerationConfig(
    ...     max_keyword_distance=150,  # Match within 150 chars
    ... )
    >>> generator = CandidateGenerator(config=config)

Understanding Distance Calculation:
    >>> # Distance is character distance between spans
    >>> # If keyword ends at position 50 and number starts at 60:
    >>> # distance = 60 - 50 = 10 characters
    >>> # Whitespace counts toward distance
    >>>
    >>> # Example: "active customers 50,000"
    >>> # Keyword: "active customers" (positions 0-16)
    >>> # Number: "50,000" (positions 17-23)
    >>> # Distance: 17 - 16 = 1 character

See Also:
    - candidate_generator.py: Uses KeywordMatcher internally
    - config.py: Configure max_keyword_distance
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from src.extraction.metric_classifier import MetricClassifier
from src.review.number_parsing import NumberMatch

logger = logging.getLogger(__name__)


# =============================================================================
# Metric Keywords
# =============================================================================

# Import keywords from the authoritative source to ensure consistency
# between candidate generation and metric classification
METRIC_KEYWORDS: Dict[str, List[str]] = MetricClassifier.METRIC_KEYWORDS


# =============================================================================
# Specific Keyword Patterns
# =============================================================================

# Keywords that are more specific (multi-word) get a bonus
# Single-word keywords like "customers" are ambiguous
SPECIFIC_KEYWORD_PATTERNS = [
    r"active\s+customers?",
    r"enterprise\s+customers?",
    r"paying\s+customers?",
    r"total\s+customers?",
    r"net\s+revenue\s+retention",
    r"gross\s+revenue\s+retention",
    r"net\s+dollar\s+retention",
    r"customer\s+acquisition\s+cost",
    r"lifetime\s+value",
    r"average\s+revenue\s+per",
    r"annual\s+recurring\s+revenue",
    r"monthly\s+recurring\s+revenue",
    r"daily\s+active\s+users?",
    r"monthly\s+active\s+users?",
]


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class KeywordMatch:
    """A keyword match found in text."""

    start: int  # Character position
    end: int  # End position
    keyword: str  # The matched text
    metric_id: str  # Associated metric ID
    pattern: str  # The regex pattern that matched


# =============================================================================
# KeywordMatcher Class
# =============================================================================


class KeywordMatcher:
    """
    Matcher for finding metric keywords in text.

    Handles finding all keyword matches in text and filtering them by
    distance from numbers. Uses pre-compiled regex patterns for efficiency.
    """

    def __init__(self, max_keyword_distance: int = 100):
        """
        Initialize the keyword matcher.

        Args:
            max_keyword_distance: Maximum character distance between number
                                 and keyword for a match
        """
        self.max_keyword_distance = max_keyword_distance

        # Pre-compile all keyword patterns for reuse
        self._compiled_patterns: Dict[str, List[Tuple[re.Pattern[str], str]]] = {}
        for metric_id, patterns in METRIC_KEYWORDS.items():
            self._compiled_patterns[metric_id] = [
                (re.compile(pattern, re.IGNORECASE), pattern) for pattern in patterns
            ]

    def find_all_keywords(self, text: str) -> List[KeywordMatch]:
        """
        Find all metric keywords in text.

        Searches text for all metric keyword patterns. Uses pre-compiled
        patterns for efficiency, but searches each pattern individually.
        This approach is faster than combining patterns due to regex engine
        behavior with large alternations.

        Args:
            text: The full text to search

        Returns:
            List of all KeywordMatch objects found, sorted by position
        """
        all_matches = []

        # Search with each compiled pattern (faster than combined pattern due to early exits)
        for metric_id, compiled_patterns in self._compiled_patterns.items():
            for compiled_pattern, pattern_str in compiled_patterns:
                for match in compiled_pattern.finditer(text):
                    all_matches.append(
                        KeywordMatch(
                            start=match.start(),
                            end=match.end(),
                            keyword=match.group(),
                            metric_id=metric_id,
                            pattern=pattern_str,
                        )
                    )

        # Sort by position
        all_matches.sort(key=lambda m: m.start)
        return all_matches

    def find_keywords_near_number(
        self,
        number: NumberMatch,
        all_keywords: List[KeywordMatch],
    ) -> List[KeywordMatch]:
        """
        Find metric keywords within max_keyword_distance of a number.

        Uses pre-computed keyword matches for efficiency. Returns at most
        one keyword per metric ID (the closest one).

        Args:
            number: The NumberMatch to search around
            all_keywords: Pre-computed list of all keyword matches in text

        Returns:
            List of KeywordMatch objects within range (one per metric)
        """
        matches = []
        seen_metrics: Set[str] = set()

        for kw in all_keywords:
            # Skip if we already have a match for this metric
            if kw.metric_id in seen_metrics:
                continue

            # Calculate distance
            dist = self.calculate_distance_from_positions(
                number.start, number.end, kw.start, kw.end
            )

            if dist <= self.max_keyword_distance:
                matches.append(kw)
                seen_metrics.add(kw.metric_id)

        return matches

    def calculate_distance(self, number: NumberMatch, keyword: KeywordMatch) -> int:
        """
        Calculate character distance between number and keyword.

        Args:
            number: NumberMatch
            keyword: KeywordMatch

        Returns:
            Minimum distance in characters
        """
        return self.calculate_distance_from_positions(
            number.start, number.end, keyword.start, keyword.end
        )

    def calculate_distance_from_positions(
        self, n_start: int, n_end: int, k_start: int, k_end: int
    ) -> int:
        """
        Calculate distance between two spans.

        If spans overlap, distance is 0.
        Otherwise, distance is the gap between them.

        Args:
            n_start: Number start position
            n_end: Number end position
            k_start: Keyword start position
            k_end: Keyword end position

        Returns:
            Distance in characters
        """
        if n_end <= k_start:
            # Number is before keyword
            return k_start - n_end
        elif k_end <= n_start:
            # Keyword is before number
            return n_start - k_end
        else:
            # Overlapping
            return 0
