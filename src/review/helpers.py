"""
Helper functions for candidate generation workflows.

Convenience wrappers that combine database operations
with candidate generation for common use cases.
"""

import logging
from typing import List, Optional

from src.infra.db import DatabaseAdapter
from src.review.candidate_generator import CandidateGenerator
from src.review.models import ReviewCandidate

logger = logging.getLogger(__name__)


def generate_candidates_for_filing(
    db: DatabaseAdapter,
    filing_id: int,
    generator: Optional[CandidateGenerator] = None,
    save: bool = False,
    batch_id: Optional[int] = None,
) -> List[ReviewCandidate]:
    """
    Generate and optionally save candidates for a filing.

    Args:
        db: DatabaseAdapter instance
        filing_id: Filing ID to process
        generator: Optional CandidateGenerator instance (creates default if None)
        save: If True, bulk insert candidates to database
        batch_id: Optional batch ID to assign to saved candidates

    Returns:
        List of generated ReviewCandidate objects (with candidate_id set if saved)

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
        db=db,
    )

    # Optionally save to database
    if save and candidates:
        # Convert to dicts for bulk insert
        candidate_dicts = []
        for c in candidates:
            d = c.to_dict()
            if batch_id is not None:
                d["review_batch_id"] = batch_id
            candidate_dicts.append(d)

        # Bulk insert and get IDs
        candidate_ids = db.bulk_insert_review_candidates(candidate_dicts)

        # Update candidate objects with their IDs
        for candidate, cid in zip(candidates, candidate_ids):
            candidate.candidate_id = cid

        logger.info(
            f"Saved {len(candidate_ids)} candidates for filing {filing_id}"
        )

    return candidates
