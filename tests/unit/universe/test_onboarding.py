"""Unit tests for src/universe/onboarding.py.

All tests are DB-free — DatabaseAdapter is mocked with a lightweight stub.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.universe.onboarding import (
    Gap,
    ResolvedQuery,
    VolumeBand,
    classify_volume,
    count_reviewer_work,
    detect_universe_gaps,
    resolve_criteria,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeDB:
    """Minimal DatabaseAdapter stand-in."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []
        self.last_sql: str | None = None
        self.last_params: dict[str, Any] | None = None

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.last_sql = sql
        self.last_params = params
        return self._rows


# ---------------------------------------------------------------------------
# classify_volume — all 5 bands + boundary values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "count, expected",
    [
        (0, VolumeBand.OK),
        (1, VolumeBand.OK),
        (49, VolumeBand.OK),
        (50, VolumeBand.SOFT_WARN),
        (51, VolumeBand.SOFT_WARN),
        (199, VolumeBand.SOFT_WARN),
        (200, VolumeBand.HARD_WARN),
        (201, VolumeBand.HARD_WARN),
        (499, VolumeBand.HARD_WARN),
        (500, VolumeBand.REFINE),
        (501, VolumeBand.REFINE),
        (999, VolumeBand.REFINE),
        (1000, VolumeBand.BLOCK),
        (1001, VolumeBand.BLOCK),
        (9999, VolumeBand.BLOCK),
    ],
)
def test_classify_volume(count: int, expected: VolumeBand) -> None:
    assert classify_volume(count) == expected


# ---------------------------------------------------------------------------
# resolve_criteria — basic cases
# ---------------------------------------------------------------------------


def test_resolve_criteria_single_industry() -> None:
    q = resolve_criteria({"industries": ["software"], "year": "2020"})
    assert isinstance(q, ResolvedQuery)
    assert "7372" in q.sic_codes
    assert q.year_min == 2020
    assert q.year_max == 2020
    # Default form types = s1f1 bundle
    assert "S-1" in q.form_types
    assert "F-1" in q.form_types
    assert q.include_amendments is True
    assert q.company_name_ilike is None


def test_resolve_criteria_year_range() -> None:
    q = resolve_criteria({"industries": ["software"], "year": "2018-2021"})
    assert q.year_min == 2018
    assert q.year_max == 2021


def test_resolve_criteria_direct_sic_string() -> None:
    """Comma-separated SIC string should be accepted and validated."""
    q = resolve_criteria({"sic_codes": "5411,7389", "year": "2020"})
    assert "5411" in q.sic_codes
    assert "7389" in q.sic_codes


def test_resolve_criteria_direct_sic_list() -> None:
    q = resolve_criteria({"sic_codes": ["5411", "7389"], "year": "2020"})
    assert "5411" in q.sic_codes
    assert "7389" in q.sic_codes


def test_resolve_criteria_industry_and_sic_union() -> None:
    """When both industries and sic_codes are supplied, the SIC sets are unioned."""
    q = resolve_criteria(
        {
            "industries": ["software"],
            "sic_codes": "5411",
            "year": "2020",
        }
    )
    # software codes
    assert "7372" in q.sic_codes
    # direct SIC
    assert "5411" in q.sic_codes


def test_resolve_criteria_invalid_sic_raises() -> None:
    with pytest.raises(ValueError, match="Invalid SIC code"):
        resolve_criteria({"sic_codes": "73AB", "year": "2020"})


def test_resolve_criteria_three_digit_sic_raises() -> None:
    with pytest.raises(ValueError, match="Invalid SIC code"):
        resolve_criteria({"sic_codes": "737", "year": "2020"})


def test_resolve_criteria_unknown_industry_raises() -> None:
    with pytest.raises(ValueError, match="Unknown industry"):
        resolve_criteria({"industries": ["quantum_widgets"], "year": "2020"})


def test_resolve_criteria_missing_year_raises() -> None:
    with pytest.raises(ValueError, match="year"):
        resolve_criteria({"industries": ["software"]})


def test_resolve_criteria_empty_sic_and_industries_raises() -> None:
    with pytest.raises(ValueError, match="At least one industry or SIC code"):
        resolve_criteria({"year": "2020"})


def test_resolve_criteria_exclude_amendments() -> None:
    q = resolve_criteria(
        {
            "industries": ["software"],
            "year": "2020",
            "form_types": ["s1f1"],
            "include_amendments": False,
        }
    )
    for ft in q.form_types:
        assert not ft.endswith("/A"), f"Amendment form {ft!r} should have been removed"
    assert "S-1" in q.form_types
    assert "F-1" in q.form_types


def test_resolve_criteria_8k_bundle() -> None:
    q = resolve_criteria(
        {
            "industries": ["software"],
            "year": "2020",
            "form_types": ["8k"],
        }
    )
    assert "8-K" in q.form_types
    assert "8-K/A" in q.form_types


def test_resolve_criteria_company_name_ilike() -> None:
    q = resolve_criteria(
        {
            "industries": ["software"],
            "year": "2020",
            "company_name_ilike": "Acme%",
        }
    )
    assert q.company_name_ilike == "Acme%"


def test_resolve_criteria_form_types_deduped() -> None:
    """Supplying overlapping bundles should not duplicate form types."""
    q = resolve_criteria(
        {
            "industries": ["software"],
            "year": "2020",
            "form_types": ["s1f1", "S-1"],  # S-1 already in s1f1
        }
    )
    assert q.form_types.count("S-1") == 1


def test_resolve_criteria_grocery_retail() -> None:
    q = resolve_criteria({"industries": ["grocery_retail"], "year": "2020"})
    assert "5411" in q.sic_codes


def test_resolve_criteria_grocery_alias() -> None:
    q = resolve_criteria({"industries": ["grocery"], "year": "2020"})
    assert "5411" in q.sic_codes


def test_resolve_criteria_industrial_services() -> None:
    q = resolve_criteria({"industries": ["industrial_services"], "year": "2020"})
    assert "7389" in q.sic_codes


# ---------------------------------------------------------------------------
# detect_universe_gaps
# ---------------------------------------------------------------------------


def _make_query(
    form_types: list[str] | None = None,
    year_min: int = 2019,
    year_max: int = 2020,
) -> ResolvedQuery:
    return ResolvedQuery(
        sic_codes=["7372"],
        form_types=form_types or ["S-1", "10-K"],
        year_min=year_min,
        year_max=year_max,
    )


def test_detect_gaps_empty_filings_table() -> None:
    """Zero rows in filings → every (year, form_type) is a gap."""
    db = _FakeDB(rows=[])
    query = _make_query(form_types=["S-1", "10-K"], year_min=2019, year_max=2020)
    gaps = detect_universe_gaps(db, query)
    # 2 years × 2 form_types = 4 gaps
    assert len(gaps) == 4
    gap_tuples = {(g.year, g.form_type) for g in gaps}
    assert (2019, "S-1") in gap_tuples
    assert (2020, "10-K") in gap_tuples


def test_detect_gaps_partial_coverage() -> None:
    """Only some (year, form_type) combos present → others are gaps."""
    db = _FakeDB(
        rows=[
            {"yr": 2019, "form_type": "S-1"},
            {"yr": 2020, "form_type": "S-1"},
        ]
    )
    query = _make_query(form_types=["S-1", "10-K"], year_min=2019, year_max=2020)
    gaps = detect_universe_gaps(db, query)
    gap_tuples = {(g.year, g.form_type) for g in gaps}
    # 10-K not present for either year
    assert (2019, "10-K") in gap_tuples
    assert (2020, "10-K") in gap_tuples
    # S-1 fully covered
    assert (2019, "S-1") not in gap_tuples
    assert (2020, "S-1") not in gap_tuples


def test_detect_gaps_full_coverage() -> None:
    """All (year, form_type) combos present → no gaps."""
    db = _FakeDB(
        rows=[
            {"yr": 2019, "form_type": "S-1"},
            {"yr": 2019, "form_type": "10-K"},
            {"yr": 2020, "form_type": "S-1"},
            {"yr": 2020, "form_type": "10-K"},
        ]
    )
    query = _make_query(form_types=["S-1", "10-K"], year_min=2019, year_max=2020)
    gaps = detect_universe_gaps(db, query)
    assert gaps == []


def test_detect_gaps_single_year() -> None:
    db = _FakeDB(rows=[])
    query = _make_query(form_types=["8-K"], year_min=2022, year_max=2022)
    gaps = detect_universe_gaps(db, query)
    assert len(gaps) == 1
    assert gaps[0] == Gap(year=2022, form_type="8-K")


# ---------------------------------------------------------------------------
# count_reviewer_work
# ---------------------------------------------------------------------------


def test_count_reviewer_work_empty_list() -> None:
    db = _FakeDB()
    result = count_reviewer_work(db, [])
    assert result == {}
    # Must NOT issue a DB query for empty input
    assert db.last_sql is None


def test_count_reviewer_work_single_filing_no_decisions() -> None:
    db = _FakeDB(rows=[])
    result = count_reviewer_work(db, [42])
    assert result == {42: (0, 0)}


def test_count_reviewer_work_single_filing_with_decisions() -> None:
    db = _FakeDB(rows=[{"filing_id": 42, "decision_count": 5, "reviewer_count": 2}])
    result = count_reviewer_work(db, [42])
    assert result == {42: (5, 2)}


def test_count_reviewer_work_multi_filing() -> None:
    db = _FakeDB(
        rows=[
            {"filing_id": 1, "decision_count": 3, "reviewer_count": 1},
            {"filing_id": 2, "decision_count": 0, "reviewer_count": 0},
        ]
    )
    result = count_reviewer_work(db, [1, 2, 3])
    # Filing 3 not in DB rows — defaults to (0, 0)
    assert result[1] == (3, 1)
    assert result[2] == (0, 0)
    assert result[3] == (0, 0)


def test_count_reviewer_work_null_counts() -> None:
    """Postgres COUNT() never returns NULL, but defensive None handling tested."""
    db = _FakeDB(rows=[{"filing_id": 99, "decision_count": None, "reviewer_count": None}])
    result = count_reviewer_work(db, [99])
    assert result == {99: (0, 0)}


def test_count_reviewer_work_issues_single_query() -> None:
    """The batch function must use ONE query regardless of how many filing IDs."""
    call_count = 0

    class _CountingDB:
        def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            return []

    count_reviewer_work(_CountingDB(), [1, 2, 3, 4, 5])
    assert call_count == 1, "count_reviewer_work must use a single batched DB query"
