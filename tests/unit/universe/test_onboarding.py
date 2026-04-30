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
    discover_candidates,
    load_industry_map,
    resolve_criteria,
    resolve_industry,
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


def test_resolve_criteria_empty_sic_industries_and_company_raises() -> None:
    with pytest.raises(ValueError, match="industry, SIC code, or company name"):
        resolve_criteria({"year": "2020"})


def test_resolve_criteria_company_name_only_allowed() -> None:
    """Company-name filter alone satisfies the narrowing requirement."""
    q = resolve_criteria({"year": "2020", "company_name_ilike": "Chewy"})
    assert q.sic_codes == []
    assert q.company_name_ilike == "Chewy"


def test_resolve_criteria_blank_company_name_does_not_satisfy() -> None:
    """Whitespace-only company_name_ilike does not satisfy the narrowing rule."""
    with pytest.raises(ValueError, match="industry, SIC code, or company name"):
        resolve_criteria({"year": "2020", "company_name_ilike": "   "})


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


def test_detects_gap_when_filings_exist_for_other_sic() -> None:
    """Filings for SIC 7389 should NOT count when querying SIC 5411."""
    # The fake DB returns no rows — simulating what the SQL would return
    # when a SIC filter excludes all present rows (filings are under 7389,
    # but the query filters to 5411).
    db = _FakeDB(rows=[])
    query = ResolvedQuery(
        sic_codes=["5411"],
        form_types=["S-1"],
        year_min=2023,
        year_max=2023,
    )
    gaps = detect_universe_gaps(db, query)
    # Gap should be reported because no matching rows returned
    assert gaps == [Gap(year=2023, form_type="S-1")]
    # Verify sic_codes were passed through to the DB query
    assert db.last_params is not None
    assert db.last_params["sic_codes"] == ["5411"]


def test_no_gap_when_matching_sic_present() -> None:
    """When the DB returns a row for the queried SIC, no gap is reported."""
    db = _FakeDB(rows=[{"yr": 2023, "form_type": "S-1"}])
    query = ResolvedQuery(
        sic_codes=["5411"],
        form_types=["S-1"],
        year_min=2023,
        year_max=2023,
    )
    gaps = detect_universe_gaps(db, query)
    assert gaps == []
    # Verify sic_codes were passed through to the DB query
    assert db.last_params is not None
    assert db.last_params["sic_codes"] == ["5411"]


def test_empty_sic_codes_omits_industry_clause() -> None:
    """Company-name-only criteria (empty sic_codes) skip the SIC SQL clause."""
    db = _FakeDB(rows=[])
    query = ResolvedQuery(
        sic_codes=[],
        form_types=["S-1"],
        year_min=2023,
        year_max=2023,
    )
    gaps = detect_universe_gaps(db, query)
    # Empty filings table → gap reported.
    assert gaps == [Gap(year=2023, form_type="S-1")]
    # sic_codes is NOT in params when the list is empty — the SQL clause is
    # omitted entirely, so a name-only criteria can still surface gaps.
    assert db.last_params is not None
    assert "sic_codes" not in db.last_params


def test_detect_universe_gaps_name_only_finds_gap_when_filings_present() -> None:
    """Even with rows present in the year, a non-matching form_type is a gap."""
    # Filings table has S-1 in 2023, but the query asks for 10-K in 2023.
    db = _FakeDB(rows=[{"yr": 2023, "form_type": "S-1"}])
    query = ResolvedQuery(
        sic_codes=[],  # company-name-only criteria
        form_types=["10-K"],
        year_min=2023,
        year_max=2023,
    )
    gaps = detect_universe_gaps(db, query)
    assert gaps == [Gap(year=2023, form_type="10-K")]
    assert db.last_params is not None
    assert "sic_codes" not in db.last_params


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


# ---------------------------------------------------------------------------
# discover_candidates — limit + DESC sort
# ---------------------------------------------------------------------------


def _candidate_row(filing_id: int, **overrides: Any) -> dict[str, Any]:
    """Build a fake row matching the DISCOVERY_SQL projection."""
    base = {
        "filing_id": filing_id,
        "cik": "0000000001",
        "ticker": None,
        "company_name": f"Co {filing_id}",
        "form_type": "S-1",
        "filing_date": "2024-01-01",
        "industry_code": "7372",
        "accession_number": f"0000000001-24-{filing_id:06d}",
        "primary_doc_url": "https://example.com/doc",
        "txt_url": None,
        "already_extracted": False,
        "extracted_at": None,
    }
    base.update(overrides)
    return base


def test_discover_candidates_omits_limit_clause_when_unset() -> None:
    """Without limit, SQL should not contain LIMIT and params should not include it."""
    db = _FakeDB(rows=[])
    discover_candidates(db, form_types=["S-1"], year_min=2024, year_max=2024, sic_codes=["7372"])
    assert db.last_sql is not None
    assert "LIMIT" not in db.last_sql
    assert db.last_params is not None
    assert "limit" not in db.last_params


def test_discover_candidates_appends_limit_clause_when_set() -> None:
    """With limit=N, SQL gets LIMIT %(limit)s and params include limit."""
    db = _FakeDB(rows=[])
    discover_candidates(
        db, form_types=["S-1"], year_min=2024, year_max=2024, sic_codes=["7372"], limit=10
    )
    assert db.last_sql is not None
    assert "LIMIT %(limit)s" in db.last_sql
    assert db.last_params is not None
    assert db.last_params["limit"] == 10


def test_discover_candidates_default_sort_is_filing_date_desc() -> None:
    """ORDER BY clause should sort filing_date DESC for 'most recent first'."""
    db = _FakeDB(rows=[])
    discover_candidates(db, form_types=["S-1"], year_min=2024, year_max=2024, sic_codes=["7372"])
    assert db.last_sql is not None
    assert "ORDER BY f.filing_date DESC, c.company_name ASC" in db.last_sql


# ---------------------------------------------------------------------------
# resolve_criteria — limit validation
# ---------------------------------------------------------------------------


def test_resolve_criteria_limit_none_when_unset() -> None:
    """limit defaults to None when not present in criteria dict."""
    q = resolve_criteria({"industries": ["software"], "year": "2023"})
    assert q.limit is None


def test_resolve_criteria_limit_empty_string_treated_as_unset() -> None:
    """Empty string means 'no limit' (avoids HTML-form-driven false positives)."""
    q = resolve_criteria({"industries": ["software"], "year": "2023", "limit": ""})
    assert q.limit is None


def test_resolve_criteria_limit_valid_integer_passes_through() -> None:
    q = resolve_criteria({"industries": ["software"], "year": "2023", "limit": 25})
    assert q.limit == 25


def test_resolve_criteria_limit_string_coerced_to_int() -> None:
    """HTML form input arrives as string; resolve_criteria must coerce."""
    q = resolve_criteria({"industries": ["software"], "year": "2023", "limit": "50"})
    assert q.limit == 50


def test_resolve_criteria_limit_zero_raises() -> None:
    with pytest.raises(ValueError, match="must be between 1 and 5000"):
        resolve_criteria({"industries": ["software"], "year": "2023", "limit": 0})


def test_resolve_criteria_limit_too_large_raises() -> None:
    with pytest.raises(ValueError, match="must be between 1 and 5000"):
        resolve_criteria({"industries": ["software"], "year": "2023", "limit": 5001})


def test_resolve_criteria_limit_non_numeric_raises() -> None:
    with pytest.raises(ValueError, match="must be a positive integer"):
        resolve_criteria({"industries": ["software"], "year": "2023", "limit": "abc"})


# ---------------------------------------------------------------------------
# Industry catalog expansion — Phase 1 added 20 new sectors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "industry, expected_codes",
    [
        ("biotech", {"2836", "8731"}),
        ("pharmaceuticals", {"2834", "2835"}),
        ("medical_devices", {"3841", "3842", "3845"}),
        ("commercial_banking", {"6020", "6021", "6022", "6029"}),
        ("investment_management", {"6282", "6726"}),
        ("apparel_retail", {"5621", "5651", "5661", "5699"}),
        ("home_improvement_retail", {"5211", "5251"}),
        ("auto_dealers", {"5511", "5521"}),
        ("restaurants", {"5812"}),
        ("oil_gas_exploration", {"1311", "1381"}),
        ("oil_gas_refining", {"2911"}),
        ("electric_utilities", {"4911", "4931"}),
        ("semiconductors", {"3674"}),
        ("computer_hardware", {"3576", "3577", "3672"}),
        ("telecom_equipment", {"3661", "3663"}),
        ("aerospace_defense", {"3721", "3728", "3812"}),
        ("media_publishing", {"2711", "2721", "2731"}),
        ("gaming_entertainment", {"7372", "7812", "7993"}),
        ("it_services_consulting", {"7371", "7389"}),
        ("homebuilding", {"1531"}),
    ],
)
def test_load_industry_map_includes_new_industries(industry: str, expected_codes: set[str]) -> None:
    m = load_industry_map()
    canon, codes = resolve_industry(industry, m)
    assert canon == industry
    assert set(codes) == expected_codes


@pytest.mark.parametrize(
    "alias, target",
    [
        ("bio", "biotech"),
        ("pharma", "pharmaceuticals"),
        ("medtech", "medical_devices"),
        ("banks", "commercial_banking"),
        ("wealth management", "investment_management"),
        ("oil", "oil_gas_exploration"),
        ("chips", "semiconductors"),
        ("defense", "aerospace_defense"),
        ("gaming", "gaming_entertainment"),
        ("homebuilders", "homebuilding"),
    ],
)
def test_load_industry_map_resolves_new_aliases(alias: str, target: str) -> None:
    m = load_industry_map()
    canon, _codes = resolve_industry(alias, m)
    assert canon == target
