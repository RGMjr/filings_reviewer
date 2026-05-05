"""Integration coverage for the conditional industry filter in discover_candidates.

The discovery SQL omits the ``AND c.industry_code = ANY(...)`` clause when
``sic_codes`` is empty so that company-name-only discovery returns rows. This
test seeds two companies with different SIC codes and asserts an empty-SIC
search sees both, while a constrained search still narrows.
"""

from __future__ import annotations

import pytest

from src.universe.onboarding import discover_candidates, query_universe_year_counts


def _seed(db, *, cik: str, name: str, sic: str, accession: str, form_type: str = "S-1"):
    company_id = db.upsert_company(
        cik=cik,
        company_name=name,
        ticker=None,
        industry_code=sic,
    )
    db.upsert_filing(
        company_id=company_id,
        cik=cik,
        accession_number=accession,
        form_type=form_type,
        filing_date="2015-06-01",
        sec_html_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/primary.htm",
        is_in_scope_phase1=True,
        is_first_time_issuer=True,
        is_spac=False,
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )


@pytest.mark.integration
def test_discover_candidates_empty_sic_returns_all_matching_form_types(clean_db):
    """Empty sic_codes list → industry filter is omitted; both rows return."""
    _seed(
        clean_db, cik="0000999101", name="Software Co", sic="7372", accession="0000999101-15-000001"
    )
    _seed(
        clean_db, cik="0000999102", name="Grocery Co", sic="5411", accession="0000999102-15-000001"
    )

    results = discover_candidates(
        clean_db,
        form_types=["S-1"],
        year_min=2015,
        year_max=2015,
        sic_codes=[],
    )

    names = {c.company_name for c in results}
    assert "Software Co" in names
    assert "Grocery Co" in names


@pytest.mark.integration
def test_discover_candidates_nonempty_sic_still_filters(clean_db):
    """Non-empty sic_codes retains the industry filter (regression)."""
    _seed(
        clean_db, cik="0000999201", name="Software Co", sic="7372", accession="0000999201-15-000001"
    )
    _seed(
        clean_db, cik="0000999202", name="Grocery Co", sic="5411", accession="0000999202-15-000001"
    )

    results = discover_candidates(
        clean_db,
        form_types=["S-1"],
        year_min=2015,
        year_max=2015,
        sic_codes=["7372"],
    )

    names = {c.company_name for c in results}
    assert "Software Co" in names
    assert "Grocery Co" not in names


@pytest.mark.integration
def test_discover_candidates_other_partition_reaches_null_and_unmapped(clean_db):
    """include_other=True surfaces filings with NULL or unmapped industry_code
    while still excluding mapped-only matches (the partition is the complement
    of mapped_sic_codes)."""
    # Seed three rows: mapped, unmapped (real but not in YAML), and NULL.
    _seed(
        clean_db,
        cik="0000999301",
        name="Mapped Software Co",
        sic="7372",
        accession="0000999301-15-000001",
    )
    _seed(
        clean_db,
        cik="0000999302",
        name="Unmapped Manufacturing Co",
        sic="3674",  # semiconductors - may or may not be in YAML; set mapped explicitly below
        accession="0000999302-15-000001",
    )
    _seed(
        clean_db,
        cik="0000999303",
        name="Null Industry Co",
        sic=None,  # type: ignore[arg-type]
        accession="0000999303-15-000001",
    )

    # Treat 7372 as the only "mapped" code; everything else is "Other".
    mapped = ["7372"]
    results = discover_candidates(
        clean_db,
        form_types=["S-1"],
        year_min=2015,
        year_max=2015,
        sic_codes=[],
        include_other=True,
        mapped_sic_codes=mapped,
    )

    names = {c.company_name for c in results}
    assert "Null Industry Co" in names
    assert "Unmapped Manufacturing Co" in names
    # The mapped-only row is NOT in the Other partition when sic_codes is empty.
    assert "Mapped Software Co" not in names


@pytest.mark.integration
def test_discover_candidates_sic_union_other_returns_all_three(clean_db):
    """Selecting a real industry alongside Other returns the union — every
    row whose industry is in sic_codes OR whose industry is NULL/unmapped."""
    _seed(
        clean_db,
        cik="0000999401",
        name="Mapped Software Co",
        sic="7372",
        accession="0000999401-15-000001",
    )
    _seed(
        clean_db,
        cik="0000999402",
        name="Unmapped Manufacturing Co",
        sic="3674",
        accession="0000999402-15-000001",
    )
    _seed(
        clean_db,
        cik="0000999403",
        name="Null Industry Co",
        sic=None,  # type: ignore[arg-type]
        accession="0000999403-15-000001",
    )

    results = discover_candidates(
        clean_db,
        form_types=["S-1"],
        year_min=2015,
        year_max=2015,
        sic_codes=["7372"],
        include_other=True,
        mapped_sic_codes=["7372"],
    )

    names = {c.company_name for c in results}
    assert names == {"Mapped Software Co", "Unmapped Manufacturing Co", "Null Industry Co"}


@pytest.mark.integration
def test_year_counts_other_only_excludes_mapped_sic(clean_db):
    """query_universe_year_counts with include_other=True and sic_codes=None
    returns year rows covering only the Other partition (NULL or unmapped
    industry_code), not the full universe.

    This is the cross-axis facet regression tested by gh-387: when the user
    selects __other__ as the only industry, the year-axis counts must be
    restricted to the Other partition instead of returning full-universe totals.
    """
    # Seed two companies: one with a mapped SIC, one with an unmapped SIC.
    _seed(
        clean_db,
        cik="0000999501",
        name="Mapped Tech Co",
        sic="7372",
        accession="0000999501-15-000001",
    )
    _seed(
        clean_db,
        cik="0000999502",
        name="Unmapped Other Co",
        sic="9999",  # not in mapped_sic_codes below
        accession="0000999502-15-000001",
    )

    # With include_other=True and mapped=["7372"], the year row should count
    # only the row with sic="9999" (Other partition). The mapped row is excluded.
    mapped = ["7372"]
    rows = query_universe_year_counts(
        clean_db,
        sic_codes=None,
        include_other=True,
        mapped_sic_codes=mapped,
    )

    assert len(rows) == 1, f"Expected 1 year row; got {rows}"
    assert rows[0].year == 2015
    # Only the unmapped company counts toward the Other partition.
    assert rows[0].total == 1, (
        f"Other partition year count should be 1 (unmapped only); got {rows[0].total}"
    )
