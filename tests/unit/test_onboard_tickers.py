"""Unit tests for scripts/onboard_tickers.py.

Covers: industry-map loading & resolution, year/form-type arg parsing,
SIC-code validation, and the already-extracted interactive guard state machine.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "onboard_tickers.py"


def _load_script_module():
    """Import the CLI script as a module for in-process testing."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "onboard_tickers_cli"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module  # required so @dataclass can resolve cls.__module__
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_script_module()


# ---------------------------------------------------------------------------
# Industry map
# ---------------------------------------------------------------------------


def test_shipped_yaml_loads_and_validates(cli):
    """The shipped config/industry_sic_codes.yaml must parse and every SIC must be 4-digit."""
    im = cli.load_industry_map()
    assert "software" in im["industries"]
    software_codes = im["industries"]["software"]["sic_codes"]
    assert software_codes, "software must declare at least one SIC code"
    for code in software_codes:
        assert isinstance(code, str) and len(code) == 4 and code.isdigit(), code


def test_resolve_known_industry(cli):
    im = cli.load_industry_map()
    canonical, codes = cli.resolve_industry("software", im)
    assert canonical == "software"
    assert "7372" in codes


def test_resolve_alias(cli):
    im = cli.load_industry_map()
    canonical, codes = cli.resolve_industry("saas", im)
    assert canonical == "software"
    assert "7372" in codes


def test_resolve_unknown_industry_raises(cli):
    im = cli.load_industry_map()
    with pytest.raises(ValueError, match="Unknown industry"):
        cli.resolve_industry("quantum_widgets", im)


def test_yaml_rejects_non_numeric_sic(cli, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"industries": {"x": {"sic_codes": ["73AB"]}}}))
    with pytest.raises(ValueError, match="Invalid SIC code"):
        cli.load_industry_map(bad)


def test_yaml_rejects_three_digit_sic(cli, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"industries": {"x": {"sic_codes": ["737"]}}}))
    with pytest.raises(ValueError, match="Invalid SIC code"):
        cli.load_industry_map(bad)


# ---------------------------------------------------------------------------
# Year and form-type parsing
# ---------------------------------------------------------------------------


def test_parse_year_single(cli):
    assert cli.parse_year_arg("2015") == (2015, 2015)


def test_parse_year_range(cli):
    assert cli.parse_year_arg("2014-2016") == (2014, 2016)


def test_parse_year_inverted_raises(cli):
    import argparse as _ap

    with pytest.raises(_ap.ArgumentTypeError):
        cli.parse_year_arg("2016-2014")


def test_resolve_form_types_bundle(cli):
    assert cli.resolve_form_types("s1f1") == ["S-1", "S-1/A", "F-1", "F-1/A"]


def test_resolve_form_types_single(cli):
    assert cli.resolve_form_types("S-1") == ["S-1"]


def test_resolve_form_types_unknown_raises(cli):
    import argparse as _ap

    with pytest.raises(_ap.ArgumentTypeError):
        cli.resolve_form_types("10-Q")


# ---------------------------------------------------------------------------
# Guard state machine — prompt_already_extracted
# ---------------------------------------------------------------------------


def _make_candidate(cli, filing_id: int):
    return cli.Candidate(
        filing_id=filing_id,
        cik=f"{filing_id:010d}",
        ticker=None,
        company_name=f"Co {filing_id}",
        form_type="S-1",
        filing_date="2015-06-01",
        industry_code="7372",
        accession_number=f"acc-{filing_id}",
        primary_doc_url="http://x",
        txt_url=None,
        already_extracted=True,
        extracted_at="2026-03-01",
    )


def test_guard_empty_list(cli):
    assert cli.prompt_already_extracted([], auto_yes=False) == {}


def test_guard_auto_yes_applies_to_all(cli):
    cands = [_make_candidate(cli, i) for i in (1, 2, 3)]
    result = cli.prompt_already_extracted(cands, auto_yes=True)
    assert result == {1: True, 2: True, 3: True}


def test_guard_default_no_skips_all(cli):
    cands = [_make_candidate(cli, i) for i in (1, 2, 3)]
    with patch("builtins.input", side_effect=["", "", ""]):
        result = cli.prompt_already_extracted(cands, auto_yes=False)
    assert result == {1: False, 2: False, 3: False}


def test_guard_y_reextract_only_that_one(cli):
    cands = [_make_candidate(cli, i) for i in (1, 2, 3)]
    with patch("builtins.input", side_effect=["y", "", "N"]):
        result = cli.prompt_already_extracted(cands, auto_yes=False)
    assert result == {1: True, 2: False, 3: False}


def test_guard_a_applies_to_remaining(cli):
    cands = [_make_candidate(cli, i) for i in (1, 2, 3, 4)]
    with patch("builtins.input", side_effect=["N", "a"]):
        result = cli.prompt_already_extracted(cands, auto_yes=False)
    # First: N (skip). Second: a (apply yes to remaining). 3 and 4 get True
    # without further prompts.
    assert result == {1: False, 2: True, 3: True, 4: True}


def test_guard_q_aborts(cli):
    cands = [_make_candidate(cli, i) for i in (1, 2)]
    with patch("builtins.input", side_effect=["q"]):
        with pytest.raises(SystemExit) as exc_info:
            cli.prompt_already_extracted(cands, auto_yes=False)
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Discovery SQL: parameter construction (does not hit DB)
# ---------------------------------------------------------------------------


class _RecordingDB:
    """Stand-in DatabaseAdapter: records query params, returns no rows."""

    def __init__(self) -> None:
        self.last_sql: str | None = None
        self.last_params: dict | None = None

    def query(self, sql, params=None):
        self.last_sql = sql
        self.last_params = params
        return []


def test_discovery_query_params(cli):
    db = _RecordingDB()
    out = cli.discover_candidates(
        db,
        form_types=["S-1", "S-1/A"],
        year_min=2015,
        year_max=2015,
        sic_codes=["7372", "7371"],
    )
    assert out == []
    assert db.last_params == {
        "form_types": ["S-1", "S-1/A"],
        "year_min": 2015,
        "year_max": 2015,
        "sic_codes": ["7372", "7371"],
    }
    assert "industry_code = ANY" in db.last_sql
    assert "is_in_scope_phase1 = TRUE" in db.last_sql
    assert "LEFT JOIN v2_documents" in db.last_sql


# ---------------------------------------------------------------------------
# Form-type bundles sanity
# ---------------------------------------------------------------------------


def test_form_type_bundles_include_s1f1(cli):
    assert set(cli.FORM_TYPE_BUNDLES["s1f1"]) == {"S-1", "S-1/A", "F-1", "F-1/A"}


# ---------------------------------------------------------------------------
# --year required (B1)
# ---------------------------------------------------------------------------


def test_year_required_on_discover(cli, capsys):
    import pytest as _pytest

    parser = cli.build_parser()
    with _pytest.raises(SystemExit):
        parser.parse_args(["discover", "--industry", "software"])
    err = capsys.readouterr().err
    assert "--year" in err


def test_year_required_on_onboard(cli, capsys):
    import pytest as _pytest

    parser = cli.build_parser()
    with _pytest.raises(SystemExit):
        parser.parse_args(["onboard", "--industry", "software"])
    err = capsys.readouterr().err
    assert "--year" in err


def test_year_not_required_on_populate(cli):
    # populate requires --year but NOT --industry; regression sanity
    parser = cli.build_parser()
    args = parser.parse_args(["populate", "--year", "2015"])
    assert args.year == "2015"
    assert args.command == "populate"


# ---------------------------------------------------------------------------
# Reviewed-filing second guard (B2)
# ---------------------------------------------------------------------------


def test_count_review_decisions_empty(cli):
    class _EmptyDB:
        def query(self, sql, params=None):
            return [{"decision_count": 0, "reviewer_count": 0}]

    assert cli.count_review_decisions(_EmptyDB(), 123) == (0, 0)


def test_count_review_decisions_with_rows(cli):
    class _DB:
        def query(self, sql, params=None):
            return [{"decision_count": 5, "reviewer_count": 2}]

    assert cli.count_review_decisions(_DB(), 123) == (5, 2)


def test_count_review_decisions_null_counts(cli):
    """Postgres COUNT() never returns NULL, but defensive None handling kept for safety."""

    class _DB:
        def query(self, sql, params=None):
            return [{"decision_count": None, "reviewer_count": None}]

    assert cli.count_review_decisions(_DB(), 123) == (0, 0)


def _reviewed_candidate(cli):
    return cli.Candidate(
        filing_id=42,
        cik="0000000042",
        ticker="FOO",
        company_name="Reviewed Co",
        form_type="S-1",
        filing_date="2015-01-09",
        industry_code="7372",
        accession_number="acc-42",
        primary_doc_url="http://x",
        txt_url=None,
        already_extracted=True,
        extracted_at="2026-03-01",
    )


def test_prompt_reviewed_filing_yes(cli):
    with patch("builtins.input", return_value="y"):
        assert cli.prompt_reviewed_filing(_reviewed_candidate(cli), 3, 2) is True


def test_prompt_reviewed_filing_default_no(cli):
    with patch("builtins.input", return_value=""):
        assert cli.prompt_reviewed_filing(_reviewed_candidate(cli), 3, 2) is False


def test_prompt_reviewed_filing_explicit_N(cli):
    with patch("builtins.input", return_value="N"):
        assert cli.prompt_reviewed_filing(_reviewed_candidate(cli), 3, 2) is False


def test_prompt_reviewed_filing_other_input_is_no(cli):
    """Only literal 'y' proceeds; anything else is a skip."""
    with patch("builtins.input", return_value="yes"):  # not 'y'
        assert cli.prompt_reviewed_filing(_reviewed_candidate(cli), 3, 2) is False


# ---------------------------------------------------------------------------
# --exclude-amendments (C1)
# ---------------------------------------------------------------------------


def test_exclude_amendments_filters_slash_a_forms(cli):
    """With --exclude-amendments, s1f1 bundle narrows to S-1 + F-1 only."""
    parser = cli.build_parser()
    args = parser.parse_args(
        ["discover", "--industry", "software", "--year", "2015",
         "--form-type", "s1f1", "--exclude-amendments"]
    )
    assert args.exclude_amendments is True

    form_types = cli.resolve_form_types(args.form_type)
    if args.exclude_amendments:
        form_types = [ft for ft in form_types if not ft.endswith("/A")]
    assert set(form_types) == {"S-1", "F-1"}


def test_exclude_amendments_default_false(cli):
    parser = cli.build_parser()
    args = parser.parse_args(
        ["discover", "--industry", "software", "--year", "2015"]
    )
    assert args.exclude_amendments is False


# ---------------------------------------------------------------------------
# 10-K bundle + conditional Phase-1 filter (Issue #7)
# ---------------------------------------------------------------------------


def test_10k_bundle_resolves(cli):
    assert cli.resolve_form_types("10k") == ["10-K", "10-K/A"]


def test_10k_single_form_bundle(cli):
    assert cli.resolve_form_types("10-K") == ["10-K"]


def test_populate_accepts_form_type_flag(cli):
    parser = cli.build_parser()
    args = parser.parse_args(["populate", "--year", "2020", "--form-type", "10k"])
    assert args.form_type == "10k"


def test_populate_default_form_type_s1f1(cli):
    parser = cli.build_parser()
    args = parser.parse_args(["populate", "--year", "2020"])
    assert args.form_type == "s1f1"


def test_build_discovery_sql_includes_phase1_for_s1f1(cli):
    """S-1/F-1 requests retain the is_in_scope_phase1 = TRUE filter."""
    sql = cli._build_discovery_sql(["S-1", "S-1/A", "F-1", "F-1/A"])
    assert "is_in_scope_phase1 = TRUE" in sql


def test_build_discovery_sql_drops_phase1_for_10k(cli):
    """10-K requests omit the Phase-1 gate (10-K is not Phase 1 by design)."""
    sql = cli._build_discovery_sql(["10-K", "10-K/A"])
    assert "is_in_scope_phase1" not in sql


def test_build_discovery_sql_keeps_phase1_for_mixed_bundle(cli):
    """A bundle that includes any S-1/F-1 form keeps the Phase-1 filter.

    Rationale: the filter is conservative — only drop it when the operator
    is explicitly asking for non-Phase-1 forms only.
    """
    sql = cli._build_discovery_sql(["S-1", "10-K"])
    assert "is_in_scope_phase1 = TRUE" in sql


# ---------------------------------------------------------------------------
# document_date threading — regression test for A1 (was silently dropping
# chart-fact-bridge for every onboarded filing)
# ---------------------------------------------------------------------------


def test_cmd_onboard_threads_document_date_to_process_filing(cli, tmp_path):
    """`cmd_onboard` must pass `document_date` (derived from filing_date) to `process_filing`.

    Regression: without this, `ChartFactBridgeStage` silently skips chart-fact
    emission — losing cohort facts from any filing with charts.
    """
    from datetime import date as _date
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    # Seed a single NEW candidate; discover returns it unchanged.
    candidate = cli.Candidate(
        filing_id=9999,
        cik="0000000001",
        ticker=None,
        company_name="Test Co",
        form_type="S-1",
        filing_date="2015-01-09",
        industry_code="7372",
        accession_number="acc-test",
        primary_doc_url="http://example/primary.htm",
        txt_url=None,
        already_extracted=False,
        extracted_at=None,
    )

    fake_html = tmp_path / "primary.htm"
    fake_html.write_text("<html></html>")

    # Minimal FilingContent-shaped object
    fake_content = SimpleNamespace(html_path=fake_html)

    mock_fetcher = MagicMock()
    mock_fetcher.fetch_filing.return_value = fake_content

    mock_result = MagicMock()
    mock_result.fact_count = 0

    mock_persistence = MagicMock()

    with (
        patch.object(cli, "discover_candidates", return_value=[candidate]),
        patch.object(cli, "FilingFetcher", return_value=mock_fetcher),
        patch.object(cli, "SECClient"),
        patch.object(cli, "V2PersistenceAdapter", return_value=mock_persistence),
        patch.object(cli, "process_filing", return_value=mock_result) as mock_proc,
    ):
        args = SimpleNamespace(
            industry="software",
            year="2015",
            form_type="S-1",
            limit=None,
            storage_root=str(tmp_path),
            skip_txt=False,
            include_already_extracted=False,
            yes=False,
            dry_run=False,
            user_agent="test/1.0",
        )
        rc = cli.cmd_onboard(args, db=MagicMock())

    assert rc == 0
    assert mock_proc.called, "process_filing must be invoked"
    _, kwargs = mock_proc.call_args
    assert kwargs["document_date"] == _date(2015, 1, 9), (
        "document_date must be the filing_date parsed from the candidate"
    )
    # Sanity: also propagated to persistence
    _, persist_kwargs = mock_persistence.persist_pipeline_result.call_args
    assert persist_kwargs["document_date"] == _date(2015, 1, 9)
