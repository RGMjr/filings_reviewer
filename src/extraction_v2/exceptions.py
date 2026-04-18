"""Exception hierarchy for the V2 extraction pipeline."""

from __future__ import annotations


class V2PipelineError(Exception):
    """Base exception for all V2 pipeline errors."""


class V2StageError(V2PipelineError):
    """Stage-level pipeline failure with stage name attribution."""

    def __init__(self, message: str, stage_name: str) -> None:
        super().__init__(message)
        self.stage_name = stage_name

    def __str__(self) -> str:
        return f"[{self.stage_name}] {super().__str__()}"

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"{super().__str__()!r}, stage_name={self.stage_name!r})"
        )


class V2TransientError(V2StageError):
    """Retryable stage error (API timeouts, network failures)."""


class V2FatalError(V2StageError):
    """Non-retryable stage error (parse failures, schema violations)."""


class ReviewedFilingError(V2PipelineError):
    """Raised when persistence would purge existing human review decisions.

    The persistence layer refuses to re-persist facts for a filing that
    has rows in ``v2_review_decisions`` unless the caller explicitly passes
    ``force=True``. Callers that need to re-extract (e.g. after keyword or
    pipeline changes) must acknowledge the loss via the override.
    """

    def __init__(self, filing_id: int, decision_count: int, reviewer_count: int) -> None:
        self.filing_id = filing_id
        self.decision_count = decision_count
        self.reviewer_count = reviewer_count
        super().__init__(
            f"filing_id={filing_id} has {decision_count} human review decision(s) "
            f"from {reviewer_count} reviewer(s). Pass force=True (or "
            f"--force-reextract) to purge and re-extract."
        )
