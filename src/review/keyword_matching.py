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
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from src.extraction.metric_classifier import MetricClassifier
from src.review.number_parsing import NumberMatch

if TYPE_CHECKING:
    from src.review.boundary_detection import TextBoundary

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
    direction: Optional[str] = None  # 'before' | 'after' | 'at' (relative to number, L3 enhancement)


# =============================================================================
# KeywordMatcher Class
# =============================================================================


class KeywordMatcher:
    """
    Matcher for finding metric keywords in text.

    Handles finding all keyword matches in text and filtering them by
    distance from numbers. Uses pre-compiled regex patterns for efficiency.

    P1 Enhancements:
    - Sort by distance first (closest keyword), then length (longest)
    - Boundary-aware matching (prefer keywords in same boundary as number)
    - Ambiguity logging when multiple keywords are equally close

    P1.5 Enhancements:
    - Sentence-aware matching (filter keywords from different sentences)

    L4 Enhancement:
    - Post-value distance multiplier (prefer keywords before values)
    - Context-dependent multipliers (Option C: different preferences by context)
    """

    def __init__(
        self,
        max_keyword_distance: int = 100,
        prefer_closest_keyword: bool = True,
        respect_bullet_boundaries: bool = True,
        respect_sentence_boundaries: bool = True,
        log_ambiguous_matches: bool = True,
        ambiguity_threshold: int = 10,
        post_value_distance_multiplier: float = 0.9,
        use_context_dependent_multipliers: bool = True,
        multiplier_bullet_points: float = 0.9,
        multiplier_parenthetical: float = 1.15,
        multiplier_tables: float = 0.85,
        multiplier_copula_verb: float = 0.9,
        multiplier_preposition: float = 1.1,
        multiplier_default: float = 0.9,
    ):
        """
        Initialize the keyword matcher.

        Args:
            max_keyword_distance: Maximum character distance between number
                                 and keyword for a match
            prefer_closest_keyword: Sort by distance first, then length (P1 enhancement)
            respect_bullet_boundaries: Prefer keywords in same boundary as number (P1 enhancement)
            respect_sentence_boundaries: Filter keywords from different sentences (P1.5 enhancement)
            log_ambiguous_matches: Log when multiple keywords are equally close (P1 enhancement)
            ambiguity_threshold: Characters to consider "equally close" (default: 10)
            post_value_distance_multiplier: Base multiplier for post-value keyword distances (L4 enhancement)
            use_context_dependent_multipliers: Enable context-dependent multiplier logic (L4 Option C)
            multiplier_bullet_points: Multiplier for bullet point contexts (L4 Option C)
            multiplier_parenthetical: Multiplier for parenthetical text (L4 Option C)
            multiplier_tables: Multiplier for table contexts (L4 Option C)
            multiplier_copula_verb: Multiplier for copula verb contexts (L4 Option C)
            multiplier_preposition: Multiplier for prepositional phrases (L4 Option C)
            multiplier_default: Default multiplier when no context detected (L4 Option C)
        """
        self.max_keyword_distance = max_keyword_distance
        self.prefer_closest_keyword = prefer_closest_keyword
        self.respect_bullet_boundaries = respect_bullet_boundaries
        self.respect_sentence_boundaries = respect_sentence_boundaries
        self.log_ambiguous_matches = log_ambiguous_matches
        self.ambiguity_threshold = ambiguity_threshold
        self.post_value_distance_multiplier = post_value_distance_multiplier

        # L4 Option C: Context-dependent multipliers
        self.use_context_dependent_multipliers = use_context_dependent_multipliers
        self.multiplier_bullet_points = multiplier_bullet_points
        self.multiplier_parenthetical = multiplier_parenthetical
        self.multiplier_tables = multiplier_tables
        self.multiplier_copula_verb = multiplier_copula_verb
        self.multiplier_preposition = multiplier_preposition
        self.multiplier_default = multiplier_default

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
        boundaries: Optional[List["TextBoundary"]] = None,
        sentence_boundaries: Optional[List["TextBoundary"]] = None,
        text: str = "",
        segment_type: Optional[str] = None,
    ) -> List[KeywordMatch]:
        """
        Find metric keywords within max_keyword_distance of a number.

        Uses pre-computed keyword matches for efficiency. Returns at most
        one keyword per metric ID (the closest one). Filters out keywords
        that are substrings of other matched keywords at overlapping positions
        (e.g., if "LTV/CAC" is matched, don't also match "LTV" and "CAC").

        P1 Enhancements:
        - Sorts by distance first (closest), then length (longest)
        - Applies boundary constraints if boundaries provided
        - Logs ambiguous matches when multiple keywords are equally close

        P1.5 Enhancements:
        - Applies sentence boundary constraints if sentence_boundaries provided
        - Filters keywords from different sentences than the number

        L4 Option C Enhancement:
        - Context-dependent multipliers for post-value keywords
        - Different preferences based on textual context (tables, bullets, parentheticals)

        Args:
            number: The NumberMatch to search around
            all_keywords: Pre-computed list of all keyword matches in text
            boundaries: Optional list of TextBoundary objects for boundary-aware matching
            sentence_boundaries: Optional list of sentence boundaries for P1.5 filtering
            text: Optional full text for context detection (L4 Option C)
            segment_type: Optional segment type for context detection (L4 Option C)

        Returns:
            List of KeywordMatch objects within range (one per metric,
            prioritizing closest, then longest keywords)
        """
        # Phase 1: Collect all keywords within distance with their distances and directions
        # Store as (keyword, raw_distance, direction) for L4 multiplier application
        candidates_with_distance: List[Tuple[KeywordMatch, int]] = []
        for kw in all_keywords:
            dist = self.calculate_distance_from_positions(
                number.start, number.end, kw.start, kw.end
            )
            if dist <= self.max_keyword_distance:
                candidates_with_distance.append((kw, dist))

        if not candidates_with_distance:
            return []

        # Phase 2: Apply boundary constraints (P1 enhancement)
        if boundaries and self.respect_bullet_boundaries:
            # Find the boundary containing the number
            number_boundary = self._get_boundary_at_position(number.start, boundaries)

            if number_boundary is not None:
                # Separate candidates into same-boundary vs cross-boundary
                same_boundary = [
                    (kw, dist)
                    for kw, dist in candidates_with_distance
                    if self._is_in_same_boundary(kw.start, number_boundary, boundaries)
                ]

                # Prefer same-boundary candidates if any exist
                if same_boundary:
                    logger.debug(
                        f"Boundary filtering: {len(same_boundary)}/{len(candidates_with_distance)} "
                        f"keywords in same boundary as number at position {number.start}"
                    )
                    candidates_with_distance = same_boundary

        # Phase 2.5: Apply sentence boundary constraints (P1.5 enhancement)
        if sentence_boundaries and self.respect_sentence_boundaries:
            # Find the sentence containing the number
            number_sentence = self._get_boundary_at_position(
                number.start, sentence_boundaries
            )

            if number_sentence is not None:
                # Filter to keywords in the same sentence as the number
                same_sentence = [
                    (kw, dist)
                    for kw, dist in candidates_with_distance
                    if self._is_in_same_boundary(
                        kw.start, number_sentence, sentence_boundaries
                    )
                ]

                # Only filter if we have same-sentence candidates
                # (fallback: if no same-sentence keywords, keep all)
                if same_sentence:
                    if len(same_sentence) < len(candidates_with_distance):
                        logger.debug(
                            f"Sentence filtering: {len(same_sentence)}/{len(candidates_with_distance)} "
                            f"keywords in same sentence as number '{number.raw_text}'"
                        )
                    candidates_with_distance = same_sentence
                else:
                    # No same-sentence keywords found - keep all candidates (fallback)
                    logger.debug(
                        f"Sentence filtering fallback: no keywords in same sentence "
                        f"as number '{number.raw_text}'; keeping all {len(candidates_with_distance)} candidates"
                    )

        # Phase 3: Sort by distance first, then length (P1 enhancement + L4 multiplier + L4 Option C)
        if self.prefer_closest_keyword:
            # L4 Option C: Compute effective distance using context-dependent multipliers
            candidates_with_effective_distance: List[Tuple[KeywordMatch, int, float]] = []

            for kw, raw_distance in candidates_with_distance:
                # Compute direction to determine if multiplier applies
                direction = self.calculate_keyword_direction(kw.start, number.start)

                # Get context-appropriate multiplier (L4 Option C)
                multiplier = self.get_context_multiplier(
                    text=text,
                    number_position=number.start,
                    keyword_position=kw.start,
                    keyword_direction=direction,
                    boundaries=boundaries,
                    segment_type=segment_type,
                )

                # Apply multiplier to post-value keywords by dividing
                # Example: distance=100, multiplier=0.9 → effective=111.11 (less favorable)
                # Example: distance=100, multiplier=1.15 → effective=86.96 (more favorable)
                effective_distance = (
                    raw_distance / multiplier if direction == "after" else float(raw_distance)
                )

                candidates_with_effective_distance.append(
                    (kw, raw_distance, effective_distance)
                )

            # Sort by (effective_distance, -length): closest first, then longest
            candidates_with_effective_distance.sort(
                key=lambda x: (x[2], -len(x[0].keyword))
            )
        else:
            # Original behavior: sort by length only (longest first)
            # Still need to create tuples with effective distance for consistency
            candidates_with_effective_distance = [
                (kw, dist, float(dist)) for kw, dist in candidates_with_distance
            ]
            candidates_with_effective_distance.sort(key=lambda x: -len(x[0].keyword))

        # Phase 4: Detect and log ambiguous matches (P1 enhancement, B1 fix)
        # B1 Fix: Use EFFECTIVE distance for ambiguity detection, not raw distance
        if self.log_ambiguous_matches and len(candidates_with_effective_distance) > 1:
            min_effective_distance = candidates_with_effective_distance[0][2]
            ambiguous_keywords = [
                kw.keyword
                for kw, raw_dist, eff_dist in candidates_with_effective_distance
                if abs(eff_dist - min_effective_distance) <= self.ambiguity_threshold
            ]

            if len(ambiguous_keywords) > 1:
                logger.info(
                    f"Ambiguous match: {len(ambiguous_keywords)} keywords equally close "
                    f"(effective distance) to number '{number.raw_text}' "
                    f"at ~{min_effective_distance:.1f} chars: "
                    f"{', '.join(repr(k) for k in ambiguous_keywords[:5])}"
                )

        # Phase 5: Filter substring duplicates, deduplicate by metric, and add direction (L3)
        matches: list[KeywordMatch] = []
        seen_metrics: Set[str] = set()

        for kw, raw_dist, eff_dist in candidates_with_effective_distance:
            # Skip if we already have a match for this metric
            if kw.metric_id in seen_metrics:
                continue

            # Check if this keyword is a substring of any already-accepted keyword
            # at an overlapping position (only within the same metric)
            is_substring_duplicate = False
            for accepted in matches:
                if (
                    kw.metric_id == accepted.metric_id
                    and self._keywords_overlap(kw, accepted)
                    and self._is_substring_match(kw, accepted)
                ):
                    logger.debug(
                        f"Filtered substring duplicate: '{kw.keyword}' "
                        f"(substring of '{accepted.keyword}')"
                    )
                    is_substring_duplicate = True
                    break

            if not is_substring_duplicate:
                # L3: Compute direction relative to number
                direction = self.calculate_keyword_direction(kw.start, number.start)

                # Create new KeywordMatch with direction set
                match_with_direction = KeywordMatch(
                    start=kw.start,
                    end=kw.end,
                    keyword=kw.keyword,
                    metric_id=kw.metric_id,
                    pattern=kw.pattern,
                    direction=direction,
                )

                matches.append(match_with_direction)
                seen_metrics.add(kw.metric_id)

        return matches

    def _keywords_overlap(self, kw1: KeywordMatch, kw2: KeywordMatch) -> bool:
        """
        Check if two keyword matches overlap in position.

        Args:
            kw1: First keyword match
            kw2: Second keyword match

        Returns:
            True if keywords overlap, False otherwise
        """
        return not (kw1.end <= kw2.start or kw2.end <= kw1.start)

    def _is_substring_match(self, kw1: KeywordMatch, kw2: KeywordMatch) -> bool:
        """
        Check if kw1's keyword is a substring of kw2's keyword.

        Args:
            kw1: First keyword match
            kw2: Second keyword match

        Returns:
            True if kw1.keyword is a substring of kw2.keyword (case-insensitive)
        """
        kw1_lower = kw1.keyword.lower()
        kw2_lower = kw2.keyword.lower()
        return kw1_lower in kw2_lower or kw2_lower in kw1_lower

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

    def calculate_keyword_direction(
        self, keyword_start: int, number_start: int
    ) -> str:
        """
        Calculate whether keyword appears before or after the number.

        Args:
            keyword_start: Keyword start position
            number_start: Number start position

        Returns:
            'before' if keyword appears before number,
            'after' if keyword appears after number,
            'at' if they start at the same position (edge case)
        """
        if keyword_start < number_start:
            return "before"
        elif keyword_start > number_start:
            return "after"
        else:
            return "at"

    def get_context_type(
        self,
        text: str,
        number_position: int,
        keyword_position: int,
        keyword_direction: str,
        boundaries: Optional[List["TextBoundary"]] = None,
        segment_type: Optional[str] = None,
    ) -> str:
        """
        Determine which context type applies to this keyword-number pair.

        This is used for E1 multiplier optimization to track which context
        triggered the multiplier selection.

        Args:
            text: Full text containing both keyword and number
            number_position: Character position of the number
            keyword_position: Character position of the keyword
            keyword_direction: 'before' or 'after' (from calculate_keyword_direction)
            boundaries: Optional list of TextBoundary objects
            segment_type: Optional segment type ('table', 'paragraph', etc.)

        Returns:
            Context type: 'table', 'parenthetical', 'bullet', 'copula', 'preposition', or 'default'
        """
        # For pre-value keywords, context doesn't affect multiplier (always 1.0)
        # But still track context for analysis

        # Priority 1: Table context (strongest signal)
        if segment_type == "table" or self._is_in_table(number_position, boundaries):
            return 'table'

        # Priority 2: Parenthetical text (strong signal for clarifications)
        if self._is_in_parentheses(number_position, text):
            return 'parenthetical'

        # Priority 3: Bullet points (strong signal for structured lists)
        if self._is_in_bullet_point(number_position, boundaries):
            return 'bullet'

        # Priority 4: Copula verb pattern (moderate signal)
        if self._has_copula_verb_between(
            text, min(keyword_position, number_position), max(keyword_position, number_position)
        ):
            return 'copula'

        # Priority 5: Prepositional phrase (moderate signal)
        if keyword_direction == "after" and self._has_preposition_after(text, number_position, keyword_position):
            return 'preposition'

        # Default: no special context
        return 'default'

    def get_context_multiplier(
        self,
        text: str,
        number_position: int,
        keyword_position: int,
        keyword_direction: str,
        boundaries: Optional[List["TextBoundary"]] = None,
        segment_type: Optional[str] = None,
    ) -> float:
        """
        Determine the appropriate multiplier based on textual context.

        This implements L4 Option C: context-dependent multipliers for post-value keywords.
        Different contexts have different patterns for where metrics appear relative to values.

        Args:
            text: Full text containing both keyword and number
            number_position: Character position of the number
            keyword_position: Character position of the keyword
            keyword_direction: 'before' or 'after' (from calculate_keyword_direction)
            boundaries: Optional list of TextBoundary objects
            segment_type: Optional segment type ('table', 'paragraph', etc.)

        Returns:
            Multiplier to apply to the effective distance (only for 'after' direction)
            - < 1.0: Penalize post-value keywords (prefer pre-value)
            - 1.0: No preference
            - > 1.0: Boost post-value keywords (prefer post-value)
        """
        # If context-dependent multipliers disabled, use base multiplier
        if not self.use_context_dependent_multipliers:
            return self.post_value_distance_multiplier

        # Only apply multiplier for post-value keywords
        if keyword_direction != "after":
            return 1.0  # No adjustment for pre-value keywords

        # Get context type and map to multiplier
        context_type = self.get_context_type(
            text, number_position, keyword_position, keyword_direction, boundaries, segment_type
        )

        # Map context type to multiplier
        context_multipliers = {
            'table': self.multiplier_tables,
            'parenthetical': self.multiplier_parenthetical,
            'bullet': self.multiplier_bullet_points,
            'copula': self.multiplier_copula_verb,
            'preposition': self.multiplier_preposition,
            'default': self.multiplier_default,
        }

        return context_multipliers.get(context_type, self.multiplier_default)

    def _is_in_parentheses(self, position: int, text: str) -> bool:
        """
        Check if a position is inside parentheses.

        Args:
            position: Character position to check
            text: Full text

        Returns:
            True if position is inside (...), False otherwise
        """
        # Count open parentheses before position
        text_before = text[:position]
        open_count = text_before.count("(") - text_before.count(")")

        # If more open than close, we're inside parentheses
        return open_count > 0

    def _is_in_table(
        self, position: int, boundaries: Optional[List["TextBoundary"]]
    ) -> bool:
        """
        Check if a position is in a table boundary.

        Args:
            position: Character position to check
            boundaries: Optional list of boundaries

        Returns:
            True if position is in a table boundary, False otherwise
        """
        if boundaries is None:
            return False

        boundary = self._get_boundary_at_position(position, boundaries)
        if boundary is None:
            return False

        # Check if boundary type indicates table
        # Note: boundary_type might be "table" or have other indicators
        return getattr(boundary, "boundary_type", None) == "table"

    def _is_in_bullet_point(
        self, position: int, boundaries: Optional[List["TextBoundary"]]
    ) -> bool:
        """
        Check if a position is in a bullet point boundary.

        Args:
            position: Character position to check
            boundaries: Optional list of boundaries

        Returns:
            True if position is in a bullet boundary, False otherwise
        """
        if boundaries is None:
            return False

        boundary = self._get_boundary_at_position(position, boundaries)
        if boundary is None:
            return False

        # Check if boundary type indicates bullet/list
        boundary_type = getattr(boundary, "boundary_type", None)
        return boundary_type in ("bullet", "numbered_list", "lettered_list")

    def _has_copula_verb_between(self, text: str, start: int, end: int) -> bool:
        """
        Check if there's a copula verb (is/was/were/are) between two positions.

        Copula verbs suggest subject-verb structure: "Gross margin was 33%"

        Args:
            text: Full text
            start: Start position
            end: End position

        Returns:
            True if copula verb found between positions, False otherwise
        """
        snippet = text[start:end].lower()
        # Match copula verbs with word boundaries
        copula_pattern = r"\b(is|was|were|are)\b"
        return bool(re.search(copula_pattern, snippet))

    def _has_preposition_after(
        self, text: str, number_position: int, keyword_position: int
    ) -> bool:
        """
        Check if there's a preposition (of/for/in) between number and keyword.

        Prepositions suggest the keyword is the object: "33% of revenue", "33% for margin"

        Args:
            text: Full text
            number_position: Number start position
            keyword_position: Keyword start position (must be after number)

        Returns:
            True if preposition found between number and keyword, False otherwise
        """
        if keyword_position <= number_position:
            return False

        # Check the gap between number and keyword (up to 50 chars)
        gap_start = number_position
        gap_end = min(number_position + 50, keyword_position + 10)
        snippet = text[gap_start:gap_end].lower()

        # Match common prepositions with word boundaries
        preposition_pattern = r"\b(of|for|in|from)\b"
        return bool(re.search(preposition_pattern, snippet))

    def _get_boundary_at_position(
        self, pos: int, boundaries: List["TextBoundary"]
    ) -> Optional["TextBoundary"]:
        """
        Find the boundary containing a position.

        Args:
            pos: Character position
            boundaries: List of TextBoundary objects

        Returns:
            The boundary containing the position, or None if not found
        """
        for boundary in boundaries:
            if boundary.contains_position(pos):
                return boundary
        return None

    def _is_in_same_boundary(
        self, pos: int, target_boundary: "TextBoundary", boundaries: List["TextBoundary"]
    ) -> bool:
        """
        Check if a position is in the same boundary as a target boundary.

        Args:
            pos: Character position to check
            target_boundary: The target boundary
            boundaries: List of all boundaries

        Returns:
            True if position is in the same boundary, False otherwise
        """
        boundary = self._get_boundary_at_position(pos, boundaries)
        return boundary is not None and boundary == target_boundary
