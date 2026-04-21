"""Unit tests for the _classify_path function in scripts/audit_filing_url_mismatch.py.

Uses importlib.util.spec_from_file_location so that scripts/__init__.py is not required.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

# Load the module by file path; avoids requiring scripts/__init__.py.
_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "audit_filing_url_mismatch.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("audit_filing_url_mismatch", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, (
        f"Could not load module from {_SCRIPT_PATH}"
    )
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules so relative imports inside the script can resolve.
    sys.modules["audit_filing_url_mismatch"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_mod = _load_module()
_classify_path = _mod._classify_path


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_row(**overrides: Any) -> dict:
    """Return a minimal row dict with all keys _classify_path reads.

    Default values represent a simple uber-contaminated filing with no
    downstream data — safe for Path B.
    """
    base: dict = {
        "html_content_is_uber": True,
        "v2_review_decisions_count": 0,
        "v2_image_review_decisions_count": 0,
        "in_gold_standard": False,
        "v2_metric_facts_count": 5,
        "accession_collides_in_scope": False,
        "html_storage_path_shared_with": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_not_uber_short_circuits_to_a() -> None:
    """Case 1: html_content_is_uber=False -> 'A' regardless of other fields."""
    row = _make_row(
        html_content_is_uber=False,
        v2_review_decisions_count=3,
        v2_metric_facts_count=10,
        accession_collides_in_scope=True,
        html_storage_path_shared_with=[999],
    )
    assert _classify_path(row) == "A"


def test_review_decisions_defers_to_c() -> None:
    """Case 2: v2_review_decisions_count > 0 -> 'C'."""
    row = _make_row(v2_review_decisions_count=1)
    assert _classify_path(row) == "C"


def test_image_review_decisions_defers_to_c() -> None:
    """Case 3: v2_image_review_decisions_count > 0 -> 'C'."""
    row = _make_row(v2_image_review_decisions_count=1)
    assert _classify_path(row) == "C"


def test_gold_standard_defers_to_c() -> None:
    """Case 4: in_gold_standard=True -> 'C'."""
    row = _make_row(in_gold_standard=True)
    assert _classify_path(row) == "C"


def test_facts_zero_with_collision_is_a() -> None:
    """Case 5: facts=0, collision present -> 'A' (Spectrum Brands pattern)."""
    row = _make_row(
        v2_metric_facts_count=0,
        accession_collides_in_scope=True,
        html_storage_path_shared_with=[123],
    )
    assert _classify_path(row) == "A"


def test_facts_nonzero_with_shared_storage_is_b_coordinated() -> None:
    """Case 6: facts>0, reviews=0, storage shared -> 'B_coordinated'."""
    row = _make_row(
        v2_metric_facts_count=5,
        html_storage_path_shared_with=[123],
    )
    assert _classify_path(row) == "B_coordinated"


def test_facts_nonzero_no_collision_is_b() -> None:
    """Case 7: facts>0, reviews=0, no collision/sharing -> 'B'."""
    row = _make_row(
        v2_metric_facts_count=5,
        accession_collides_in_scope=False,
        html_storage_path_shared_with=[],
    )
    assert _classify_path(row) == "B"
