"""
Candidate deduplication utilities for the review module.

Provides functions to remove duplicate candidates based on
(value, metric_id, period) tuples, keeping the highest-confidence
candidate from each group.

Basic Usage:
    >>> from src.review.deduplicator import deduplicate_candidates
    >>> from src.review.models import ReviewCandidate
    >>>
    >>> # Deduplicate a list of candidates
    >>> unique, removed_count = deduplicate_candidates(candidates)
    >>> print(f"Removed {removed_count} duplicates, kept {len(unique)}")

Algorithm:
    1. Group candidates by (parsed_value, suggested_metric_id, detected_period)
    2. For each group with multiple candidates:
       - Sort by suggestion_confidence (descending, None last)
       - Secondary sort by respectively_confidence (L1 enhancement)
       - Keep the first (highest confidence) candidate
    3. Return deduplicated list and count of removed duplicates

L1 Enhancement (Respectively Patterns):
    When detecting "respectively" patterns (e.g., "for 2015, 2016 was 33%, 35%"),
    the deduplication key includes `detected_period` to preserve different
    period associations for the same value.
"""

import logging
from typing import Dict, List, Tuple

from src.review.models import ReviewCandidate

logger = logging.getLogger(__name__)


def deduplicate_candidates(
    candidates: List[ReviewCandidate],
) -> Tuple[List[ReviewCandidate], int]:
    """
    Remove duplicate candidates based on (parsed_value, suggested_metric_id, detected_period).

    When duplicates exist, keeps the one with highest suggestion_confidence.
    If confidence is equal or None, keeps the first occurrence.

    Args:
        candidates: List of candidates to deduplicate

    Returns:
        Tuple of (deduplicated_candidates, duplicates_removed_count)

    Examples:
        >>> # Basic deduplication
        >>> candidates = [c1, c2, c3]  # c1 and c2 are duplicates
        >>> unique, count = deduplicate_candidates(candidates)
        >>> assert len(unique) == 2
        >>> assert count == 1

        >>> # Empty list handling
        >>> unique, count = deduplicate_candidates([])
        >>> assert unique == []
        >>> assert count == 0
    """
    if not candidates:
        return [], 0

    # Group candidates by (parsed_value, suggested_metric_id, detected_period)
    # Use string representation of Decimal to handle None values
    groups: Dict[Tuple[str, str, str], List[ReviewCandidate]] = {}

    for candidate in candidates:
        # Create key - convert Decimal to string for hashing
        value_key = (
            str(candidate.parsed_value)
            if candidate.parsed_value is not None
            else "None"
        )
        metric_key = candidate.suggested_metric_id or "none"

        # L1: Include period in key to preserve different periods
        period_key = (
            candidate.features.detected_period
            if candidate.features and candidate.features.detected_period
            else "none"
        )

        key = (value_key, metric_key, period_key)

        if key not in groups:
            groups[key] = []
        groups[key].append(candidate)

    # Select best candidate from each group
    deduplicated = []
    for group in groups.values():
        if len(group) == 1:
            deduplicated.append(group[0])
        else:
            # Sort by confidence (descending), None values last
            # L1: Also consider respectively_confidence when available
            sorted_group = sorted(
                group,
                key=lambda c: (
                    c.suggestion_confidence is not None,
                    c.suggestion_confidence or 0,
                    (c.features.respectively_confidence or 0)
                    if c.features
                    else 0,
                ),
                reverse=True,
            )
            deduplicated.append(sorted_group[0])

    duplicates_removed = len(candidates) - len(deduplicated)

    if duplicates_removed > 0:
        logger.debug(
            f"Deduplication removed {duplicates_removed} candidates "
            f"({len(candidates)} -> {len(deduplicated)})"
        )

    return deduplicated, duplicates_removed
