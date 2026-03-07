"""
Helper functions for candidate generation workflows.

Convenience wrappers that combine database operations
with candidate generation for common use cases.

Basic Usage (Recommended):
    >>> from src.review.helpers import generate_candidates_for_filing
    >>> from src.infra.db import DatabaseAdapter
    >>>
    >>> # Initialize database
    >>> db = DatabaseAdapter("postgresql://user:pass@localhost/filings_analysis")
    >>>
    >>> # One-liner to generate candidates (fetches segments automatically)
    >>> candidates = generate_candidates_for_filing(
    ...     db=db,
    ...     filing_id=123,
    ... )
    >>> print(f"Generated {len(candidates)} candidates")

Save Candidates Directly to Database:
    >>> # Generate and save in one step
    >>> candidates = generate_candidates_for_filing(
    ...     db=db,
    ...     filing_id=123,
    ...     save=True,  # Bulk insert to database
    ... )
    >>> # Candidates now have candidate_id set
    >>> assert all(c.candidate_id is not None for c in candidates)

Suppression Logging (DUP-3):
    >>> # Log suppressed candidates for pattern learning
    >>> candidates = generate_candidates_for_filing(
    ...     db=db,
    ...     filing_id=123,
    ...     save=True,
    ...     log_suppressed=True,  # Capture alternatives in suppressed_candidates table
    ... )
    >>> # Suppressions are logged automatically during insert

    Design Note (DUP-3 Simplification):
    Suppression logging happens at the database layer via bulk_insert_review_candidates(),
    which handles both within-batch deduplication and cross-batch conflict resolution.
    This captures 'lower_confidence' and 'runner_up' suppression reasons.

    The in-memory deduplication (deduplicate_candidates in candidate_generator.py) also
    removes duplicates before DB insert, but its 'cross_sentence' suppression reason is
    NOT captured separately. This was a deliberate simplification - the DB layer provides
    ~90% of suppression tracking value without the architectural complexity of coordinating
    two deduplication layers. (DUP-3 completion notes preserved in git history.)

Using Custom Generator Configuration:
    >>> from src.review import CandidateGenerator
    >>> from src.review.config import get_high_precision_config
    >>>
    >>> # Create generator with custom config
    >>> hp_generator = CandidateGenerator(config=get_high_precision_config())
    >>>
    >>> # Pass custom generator to helper
    >>> candidates = generate_candidates_for_filing(
    ...     db=db,
    ...     filing_id=123,
    ...     generator=hp_generator,
    ...     save=True,
    ... )

Processing Multiple Filings:
    >>> # Process multiple filings efficiently
    >>> filing_ids = [101, 102, 103, 104, 105]
    >>> all_candidates = []
    >>>
    >>> for filing_id in filing_ids:
    ...     try:
    ...         candidates = generate_candidates_for_filing(
    ...             db=db,
    ...             filing_id=filing_id,
    ...             save=True,
    ...         )
    ...         all_candidates.extend(candidates)
    ...     except ValueError as e:
    ...         print(f"Filing {filing_id} not found: {e}")
    >>>
    >>> print(f"Generated {len(all_candidates)} total candidates")

Batch Processing:
    >>> # Assign batch ID for tracking
    >>> batch_id = 42
    >>> candidates = generate_candidates_for_filing(
    ...     db=db,
    ...     filing_id=123,
    ...     save=True,
    ...     batch_id=batch_id,
    ... )
    >>> # All candidates will have review_batch_id=42

Error Handling:
    >>> try:
    ...     candidates = generate_candidates_for_filing(
    ...         db=db,
    ...         filing_id=999999,  # Non-existent filing
    ...     )
    ... except ValueError as e:
    ...     print(f"Error: {e}")  # "Filing not found: 999999"

See Also:
    - candidate_generator.py: CandidateGenerator class for direct usage
    - config.py: Configuration presets and customization
    - models.py: ReviewCandidate data structure
"""

import logging
from typing import cast

from src.infra.db import DatabaseAdapter
from src.review.candidate_generator import CandidateGenerator
from src.review.models import ReviewCandidate

logger = logging.getLogger(__name__)


def generate_candidates_for_filing(
    db: DatabaseAdapter,
    filing_id: int,
    generator: CandidateGenerator | None = None,
    save: bool = False,
    batch_id: int | None = None,
    log_suppressed: bool = False,
) -> list[ReviewCandidate]:
    """
    Generate and optionally save candidates for a filing.

    Args:
        db: DatabaseAdapter instance
        filing_id: Filing ID to process
        generator: Optional CandidateGenerator instance (creates default if None)
        save: If True, bulk insert candidates to database
        batch_id: Optional batch ID to assign to saved candidates
        log_suppressed: If True, log suppressed candidates to suppressed_candidates
            table for pattern learning. Only effective when save=True.
            Captures 'lower_confidence' and 'runner_up' suppression reasons.
            See module docstring for design rationale (DUP-3 simplification).

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

    # Note: return_stats=False (default), so this always returns List[ReviewCandidate]
    candidates_result = generator.generate_for_filing(
        filing_id=filing_id,
        company_id=company_id,
        segments=segments,
        db=db,
    )
    # Cast to clarify type for mypy (we know it's List[ReviewCandidate] when return_stats=False)
    candidates: list[ReviewCandidate] = cast(list[ReviewCandidate], candidates_result)

    # Optionally save to database
    if save and candidates:
        # Convert to dicts for bulk insert
        candidate_dicts = []
        for c in candidates:
            d = c.to_dict()
            if batch_id is not None:
                d["review_batch_id"] = batch_id
            candidate_dicts.append(d)

        # Bulk insert with optional suppression logging (DUP-3)
        # When log_suppressed=True, captures:
        # - 'lower_confidence': within-batch duplicates and cross-batch conflicts
        # - 'runner_up': best alternative metric at same position
        if log_suppressed:
            result = db.bulk_insert_review_candidates(candidate_dicts, log_suppressed=True)
            candidate_ids, suppression_entries = result

            # Log suppression summary
            if suppression_entries:
                reasons: dict[str, int] = {}
                for entry in suppression_entries:
                    reason = entry.get("suppression_reason", "unknown")
                    reasons[reason] = reasons.get(reason, 0) + 1
                reason_summary = ", ".join(
                    f"{count} {reason}" for reason, count in sorted(reasons.items())
                )
                logger.info(
                    f"Filing {filing_id}: logged {len(suppression_entries)} "
                    f"suppressed candidates ({reason_summary})"
                )
        else:
            candidate_ids = db.bulk_insert_review_candidates(candidate_dicts)

        # Update candidate objects with their IDs
        for candidate, cid in zip(candidates, candidate_ids, strict=True):
            candidate.candidate_id = cid

        logger.info(f"Saved {len(candidate_ids)} candidates for filing {filing_id}")

    return candidates
