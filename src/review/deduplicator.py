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
       - P1.6: If prefer_same_sentence=True, prefer same-sentence matches
       - Sort by suggestion_confidence (descending, None last)
       - Secondary sort by respectively_confidence (L1 enhancement)
       - Keep the first (highest confidence) candidate
    3. Return deduplicated list and count of removed duplicates

L1 Enhancement (Respectively Patterns):
    When detecting "respectively" patterns (e.g., "for 2015, 2016 was 33%, 35%"),
    the deduplication key includes `detected_period` to preserve different
    period associations for the same value.

P1.6 Enhancement (Same-Sentence Preference):
    When prefer_same_sentence=True, candidates where the keyword and value
    are in the same sentence are preferred over cross-sentence matches,
    even if the cross-sentence match has slightly higher confidence.
"""

import logging
from typing import Dict, List, Tuple

from src.review.models import ReviewCandidate

logger = logging.getLogger(__name__)


def deduplicate_candidates(
    candidates: List[ReviewCandidate],
    prefer_same_sentence: bool = True,
) -> Tuple[List[ReviewCandidate], int]:
    """
    Remove duplicate candidates based on (parsed_value, suggested_metric_id, detected_period).

    When duplicates exist, keeps the one with highest suggestion_confidence.
    If confidence is equal or None, keeps the first occurrence.

    P1.6 Enhancement: When prefer_same_sentence=True, same-sentence candidates
    are preferred over cross-sentence candidates within each group.

    Args:
        candidates: List of candidates to deduplicate
        prefer_same_sentence: If True, prefer candidates where keyword and value
                             are in the same sentence (P1.6 enhancement)

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

        >>> # Same-sentence preference (P1.6)
        >>> # c1: same sentence, confidence=0.7
        >>> # c2: cross sentence, confidence=0.8
        >>> unique, count = deduplicate_candidates([c1, c2], prefer_same_sentence=True)
        >>> assert unique[0] == c1  # Same-sentence wins despite lower confidence
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
            # P1.6: Prefer same-sentence matches if enabled
            candidates_to_consider = group
            if prefer_same_sentence:
                same_sentence_candidates = [
                    c for c in group
                    if c.features and c.features.is_same_sentence
                ]
                # Only filter if we have same-sentence candidates
                # (fallback: if none are marked same-sentence, consider all)
                if same_sentence_candidates:
                    candidates_to_consider = same_sentence_candidates
                    if len(group) > len(same_sentence_candidates):
                        logger.debug(
                            f"P1.6: Preferring {len(same_sentence_candidates)} same-sentence "
                            f"candidates over {len(group) - len(same_sentence_candidates)} "
                            f"cross-sentence candidates"
                        )

            # Sort by confidence (descending), None values last
            # L1: Also consider respectively_confidence when available
            sorted_group = sorted(
                candidates_to_consider,
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
