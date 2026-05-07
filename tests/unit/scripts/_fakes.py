"""Signature-parity helpers for script test fakes (gh-546 / PR #535 incident).

PR #535 changed PresenceClassifierClient.classify_segment to return a 2-tuple
(classifications, token_counts). Two scripts crashed live because their test
fakes were not updated. This module provides an import-time assertion so any
future signature change is caught during test collection, not on a live run.
"""

import inspect


def assert_classify_segment_parity(fake_class: type) -> None:
    """Fail at import time if fake_class.classify_segment drifts from the real method.

    Checks: (1) required positional parameter count matches; (2) return annotation
    is a tuple type. Each assertion names the fake class and the offending field
    so CI failures are self-diagnosing.
    """
    from src.llm.presence_classifier_client import PresenceClassifierClient

    real_sig = inspect.signature(PresenceClassifierClient.classify_segment)
    fake_sig = inspect.signature(fake_class.classify_segment)

    def _required_params(sig: inspect.Signature) -> list[str]:
        return [
            name
            for name, param in sig.parameters.items()
            if name != "self"
            and param.default is inspect.Parameter.empty
            and param.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]

    real_required = _required_params(real_sig)
    fake_required = _required_params(fake_sig)
    assert len(fake_required) == len(real_required), (
        f"{fake_class.__name__}.classify_segment has {len(fake_required)} required "
        f"positional params {fake_required}; real PresenceClassifierClient.classify_segment "
        f"has {len(real_required)} {real_required}. Update the fake to match."
    )

    real_return = str(real_sig.return_annotation).replace(" ", "")
    fake_return = str(fake_sig.return_annotation).replace(" ", "")
    assert "tuple[" in fake_return, (
        f"{fake_class.__name__}.classify_segment return annotation {fake_return!r} "
        f"is not a tuple type; real method returns {real_return!r}. "
        f"Update the fake to return (classifications, token_counts)."
    )
