"""
Candidate Generator - Generate review candidates from filing segments.

This module scans source segments for numbers near metric keywords,
creating candidates for human review. It implements a high-recall
detection strategy to catch potential metrics.

Algorithm:
1. For each segment, find all numbers using regex
2. For each number, find metric keywords within 100 characters
3. Deduplicate by (number_position, metric_id)
4. Extract context (30-50 words each direction)
5. Create ReviewCandidate objects for bulk insert
"""

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

from src.review.models import ReviewCandidate

logger = logging.getLogger(__name__)


# =============================================================================
# Number Detection Patterns
# =============================================================================

# Pattern to match numbers with optional currency, commas, decimals, and suffixes
# Supports both comma-separated (1,234,567) and plain integers (1234567)
NUMBER_PATTERN = r"""
    (?P<currency>\$)?                           # Optional currency symbol
    \s*
    (?P<number>
        -?                                      # Optional negative sign
        (?:
            \d{1,3}(?:,\d{3})+                 # Comma-separated (1,234 or 1,234,567)
            |
            \d+                                 # Or plain integer (1234567)
        )
        (?:\.\d+)?                              # Optional decimal part
    )
    \s*
    (?P<suffix>million|billion|thousand|mn|bn|k|m|b|%|percent)?  # Optional suffix
"""

NUMBER_REGEX = re.compile(NUMBER_PATTERN, re.IGNORECASE | re.VERBOSE)


# =============================================================================
# Metric Keywords (imported from metric_classifier.py)
# =============================================================================

# These keywords trigger candidate detection when found near numbers
METRIC_KEYWORDS: Dict[str, List[str]] = {
    # Core Metrics
    "cm_new_customers_acquired": [
        r"\bnew\s+customers?\b",
        r"\bcustomers?\s+acquired\b",
        r"\bcustomer\s+acquisition[s]?\b",
        r"\bacquired\s+customers?\b",
        r"\bnewly\s+acquired\b",
        r"\bnet\s+new\s+customers?\b",
        r"\bcustomers?\s+added\b",
    ],
    "cm_customers_period_end_by_tenure": [
        r"\bcustomers?\s+by\s+tenure\b",
        r"\btenure\s+cohort\b",
        r"\bcustomers?\s+at\s+period\s+end\b",
    ],
    "cm_revenue_by_cohort": [
        r"\brevenue\s+by\s+cohort\b",
        r"\bcohort\s+revenue\b",
    ],
    "cm_transactions_by_cohort": [
        r"\btransactions?\s+by\s+cohort\b",
        r"\bcohort\s+transactions?\b",
    ],
    # Extended Metrics
    "cm_active_customers_total": [
        r"\bactive\s+customers?\b",
        r"\btotal\s+customers?\b",
        r"\bcustomer\s+base\b",
    ],
    "cm_revenue_per_customer": [
        r"\barpu\b",
        r"\baverage\s+revenue\s+per\s+user\b",
        r"\brevenue\s+per\s+customer\b",
        r"\brevenue\s+per\s+user\b",
    ],
    "cm_customer_acquisition_cost": [
        r"\bcac\b",
        r"\bcustomer\s+acquisition\s+cost\b",
        r"\bacquisition\s+cost\b",
    ],
    "cm_cac_payback_period": [
        r"\bcac\s+payback\b",
        r"\bpayback\s+period\b",
    ],
    "cm_customer_retention_rate": [
        r"\bretention\s+rate\b",
        r"\bcustomer\s+retention\b",
    ],
    "cm_customer_churn_rate": [
        r"\bchurn\s+rate\b",
        r"\bcustomer\s+churn\b",
        r"\battrition\s+rate\b",
    ],
    "cm_net_revenue_retention": [
        r"\bnrr\b",
        r"\bnet\s+revenue\s+retention\b",
        r"\bnet\s+retention\b",
        r"\bnet\s+dollar\s+retention\b",
        r"\bndr\b",
    ],
    "cm_gross_revenue_retention": [
        r"\bgrr\b",
        r"\bgross\s+revenue\s+retention\b",
    ],
    "cm_monthly_active_users": [
        r"\bmau\b",
        r"\bmonthly\s+active\s+users?\b",
    ],
    "cm_daily_active_users": [
        r"\bdau\b",
        r"\bdaily\s+active\s+users?\b",
    ],
    "cm_gross_margin_by_cohort": [
        r"\bgross\s+margin\b",
        r"\bgross\s+profit\b",
    ],
    "cm_expansion_revenue": [
        r"\bexpansion\s+revenue\b",
        r"\bcross[- ]sell\b",
        r"\bupsell\b",
    ],
    "cm_revenue_concentration": [
        r"\brevenue\s+concentration\b",
        r"\bcustomer\s+concentration\b",
        r"\btop\s+\d+\s+customers?\b",
        r"\blargest\s+customers?\b",
    ],
    "cm_lifetime_value_per_customer": [
        r"\bltv\b",
        r"\blifetime\s+value\b",
        r"\bcustomer\s+lifetime\s+value\b",
        r"\bclv\b",
    ],
    "cm_ltv_to_cac_ratio": [
        r"\bltv\s*[:/]\s*cac\b",
        r"\bltv\s+to\s+cac\b",
    ],
}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class NumberMatch:
    """A number found in text with position and parsed value."""

    start: int  # Character position in text
    end: int  # End position
    raw_text: str  # Original text (e.g., "$1,234.56 million")
    value: Optional[Decimal]  # Parsed numeric value
    unit: Optional[str]  # Detected unit ('count', '%', 'usd', etc.)


@dataclass
class KeywordMatch:
    """A keyword match found in text."""

    start: int  # Character position
    end: int  # End position
    keyword: str  # The matched text
    metric_id: str  # Associated metric ID
    pattern: str  # The regex pattern that matched


# =============================================================================
# CandidateGenerator Class
# =============================================================================


class CandidateGenerator:
    """
    Generates review candidates from source segments.

    The generator scans text for numbers near metric keywords and creates
    ReviewCandidate objects for human review. It uses a high-recall strategy
    to avoid missing potential metrics.
    """

    # Maximum character distance between number and keyword
    MAX_KEYWORD_DISTANCE = 100

    # Context extraction settings
    CONTEXT_WORDS = 40  # Words to extract each direction

    def __init__(
        self,
        max_keyword_distance: int = 100,
        context_words: int = 40,
    ):
        """
        Initialize the candidate generator.

        Args:
            max_keyword_distance: Maximum chars between number and keyword
            context_words: Words to extract for context each direction
        """
        self.max_keyword_distance = max_keyword_distance
        self.context_words = context_words

        # Compile keyword patterns for performance
        self._compiled_patterns: Dict[str, List[re.Pattern]] = {}
        for metric_id, patterns in METRIC_KEYWORDS.items():
            self._compiled_patterns[metric_id] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]

    def generate_for_filing(
        self,
        filing_id: int,
        company_id: int,
        segments: List[Dict[str, Any]],
    ) -> List[ReviewCandidate]:
        """
        Generate candidates from all segments of a filing.

        Args:
            filing_id: The filing ID
            company_id: The company ID
            segments: List of segment dicts from database

        Returns:
            List of ReviewCandidate objects (not yet saved to DB)
        """
        candidates = []

        for segment in segments:
            segment_candidates = self._process_segment(
                filing_id=filing_id,
                company_id=company_id,
                segment=segment,
            )
            candidates.extend(segment_candidates)

        logger.info(
            f"Generated {len(candidates)} candidates from "
            f"{len(segments)} segments for filing {filing_id}"
        )
        return candidates

    def _process_segment(
        self,
        filing_id: int,
        company_id: int,
        segment: Dict[str, Any],
    ) -> List[ReviewCandidate]:
        """
        Process a single segment to find candidates.

        Args:
            filing_id: The filing ID
            company_id: The company ID
            segment: Segment dict from database

        Returns:
            List of ReviewCandidate objects found in this segment
        """
        text = segment.get("raw_text", "")
        if not text:
            return []

        source_segment_id = segment.get("source_segment_id")
        candidates = []

        # Find all numbers in the segment
        numbers = self._find_numbers(text)
        if not numbers:
            return []

        # Track (number_position, metric_id) pairs to avoid duplicates
        seen: Set[Tuple[int, str]] = set()

        # For each number, find nearby keywords
        for num in numbers:
            keyword_matches = self._find_keywords_near_number(text, num)

            for kw in keyword_matches:
                # Deduplicate by (number_position, metric_id)
                key = (num.start, kw.metric_id)
                if key in seen:
                    continue
                seen.add(key)

                # Calculate distance and position
                distance = self._calculate_distance(num, kw)
                keyword_position = "before" if kw.start < num.start else "after"

                # Extract context
                context = self._extract_context(text, num.start)

                candidate = ReviewCandidate(
                    filing_id=filing_id,
                    company_id=company_id,
                    source_segment_id=source_segment_id,
                    char_position=num.start,
                    context_text=context,
                    raw_number_text=num.raw_text,
                    parsed_value=num.value,
                    parsed_unit=num.unit,
                    triggering_keyword=kw.keyword,
                    keyword_distance=distance,
                    keyword_position=keyword_position,
                    suggested_metric_id=kw.metric_id,
                    # Features will be added by feature_extractor (B2)
                    features=None,
                )
                candidates.append(candidate)

        return candidates

    def _find_numbers(self, text: str) -> List[NumberMatch]:
        """
        Find all numbers in text.

        Args:
            text: The text to search

        Returns:
            List of NumberMatch objects
        """
        matches = []

        for match in NUMBER_REGEX.finditer(text):
            raw_text = match.group(0).strip()

            # Skip very short matches (likely false positives)
            if len(raw_text) < 1:
                continue

            # Parse the value
            value, unit = self._parse_number(match)

            # Skip if we couldn't parse a meaningful value
            if value is None:
                continue

            matches.append(
                NumberMatch(
                    start=match.start(),
                    end=match.end(),
                    raw_text=raw_text,
                    value=value,
                    unit=unit,
                )
            )

        return matches

    def _parse_number(
        self, match: re.Match
    ) -> Tuple[Optional[Decimal], Optional[str]]:
        """
        Parse a number match into value and unit.

        Args:
            match: Regex match object

        Returns:
            Tuple of (parsed_value, unit)
        """
        groups = match.groupdict()
        currency = groups.get("currency")
        number_str = groups.get("number", "")
        suffix = groups.get("suffix", "")

        # Remove commas
        number_str = number_str.replace(",", "")

        try:
            value = Decimal(number_str)
        except (InvalidOperation, ValueError):
            return None, None

        # Apply suffix multiplier
        if suffix:
            suffix_lower = suffix.lower()
            if suffix_lower in ("million", "mn", "m"):
                value *= Decimal("1000000")
            elif suffix_lower in ("billion", "bn", "b"):
                value *= Decimal("1000000000")
            elif suffix_lower in ("thousand", "k"):
                value *= Decimal("1000")

        # Determine unit
        if suffix and suffix.lower() in ("%", "percent"):
            unit = "%"
        elif currency:
            unit = "usd"
        else:
            unit = "count"

        return value, unit

    def _find_keywords_near_number(
        self, text: str, number: NumberMatch
    ) -> List[KeywordMatch]:
        """
        Find metric keywords within max_keyword_distance of a number.

        Args:
            text: The full text
            number: The NumberMatch to search around

        Returns:
            List of KeywordMatch objects within range
        """
        matches = []

        # Define search window
        window_start = max(0, number.start - self.max_keyword_distance)
        window_end = min(len(text), number.end + self.max_keyword_distance)

        # Search for each metric's keywords
        for metric_id, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    # Check if match is within window
                    if match.start() >= window_start and match.end() <= window_end:
                        # Check actual distance (not just window)
                        dist = self._calculate_distance_from_positions(
                            number.start, number.end, match.start(), match.end()
                        )
                        if dist <= self.max_keyword_distance:
                            matches.append(
                                KeywordMatch(
                                    start=match.start(),
                                    end=match.end(),
                                    keyword=match.group(),
                                    metric_id=metric_id,
                                    pattern=pattern.pattern,
                                )
                            )
                            # Only take first match per metric to avoid duplicates
                            break

        return matches

    def _calculate_distance(self, number: NumberMatch, keyword: KeywordMatch) -> int:
        """
        Calculate character distance between number and keyword.

        Args:
            number: NumberMatch
            keyword: KeywordMatch

        Returns:
            Minimum distance in characters
        """
        return self._calculate_distance_from_positions(
            number.start, number.end, keyword.start, keyword.end
        )

    def _calculate_distance_from_positions(
        self, n_start: int, n_end: int, k_start: int, k_end: int
    ) -> int:
        """
        Calculate distance between two spans.

        If spans overlap, distance is 0.
        Otherwise, distance is the gap between them.
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

    def _extract_context(self, text: str, position: int) -> str:
        """
        Extract context words around a position.

        Args:
            text: The full text
            position: Character position to center on

        Returns:
            Context string with ~context_words words each direction
        """
        # Split into words with positions
        words = []
        for match in re.finditer(r"\S+", text):
            words.append((match.start(), match.end(), match.group()))

        if not words:
            return text[:500] if len(text) > 500 else text

        # Find the word containing or nearest to position
        center_idx = 0
        min_dist = float("inf")
        for i, (start, end, _) in enumerate(words):
            if start <= position < end:
                center_idx = i
                break
            dist = min(abs(start - position), abs(end - position))
            if dist < min_dist:
                min_dist = dist
                center_idx = i

        # Extract words around center
        start_idx = max(0, center_idx - self.context_words)
        end_idx = min(len(words), center_idx + self.context_words + 1)

        # Get text span
        context_start = words[start_idx][0]
        context_end = words[end_idx - 1][1]

        return text[context_start:context_end]


# =============================================================================
# Convenience Functions
# =============================================================================


def generate_candidates_for_filing(
    db,
    filing_id: int,
    generator: Optional[CandidateGenerator] = None,
) -> List[ReviewCandidate]:
    """
    Generate and optionally save candidates for a filing.

    Args:
        db: DatabaseAdapter instance
        filing_id: Filing ID to process
        generator: Optional CandidateGenerator instance (creates default if None)

    Returns:
        List of generated ReviewCandidate objects

    Raises:
        ValueError: If filing not found
    """
    # Get filing info
    filing = db.get_filing_with_company(filing_id)
    if not filing:
        raise ValueError(f"Filing not found: {filing_id}")

    company_id = filing["company_id"]

    # Get segments
    segments = db.get_source_segments_for_filing(filing_id)
    if not segments:
        logger.warning(f"No segments found for filing {filing_id}")
        return []

    # Generate candidates
    if generator is None:
        generator = CandidateGenerator()

    candidates = generator.generate_for_filing(
        filing_id=filing_id,
        company_id=company_id,
        segments=segments,
    )

    return candidates
