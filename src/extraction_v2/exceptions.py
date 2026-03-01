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
