"""Integration test for scripts/onboard_tickers.py end-to-end.

Covers the `cmd_onboard` orchestration glue: DB discovery query →
FilingFetcher cache-hit → process_filing → persist_pipeline_result.
process_filing and persist_pipeline_result are mocked to avoid exercising
the full V2 pipeline (which has its own integration coverage).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "onboard_tickers.py"


def _load_script_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "onboard_tickers_cli_integration"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_script_module()


def _seed_filing(db, cik="0000999001", accession="0000999001-15-000001"):
    """Seed a test company + filing with SIC 7372 (software) and 2015 date."""
    company_id = db.upsert_company(
        cik=cik,
        company_name="Seeded Software Co",
        ticker=None,
        industry_code="7372",
    )
    filing_id = db.upsert_filing(
        company_id=company_id,
        cik=cik,
        accession_number=accession,
        form_type="S-1",
        filing_date="2015-06-01",
        sec_html_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/primary.htm",
        is_in_scope_phase1=True,
        is_first_time_issuer=True,
        is_spac=False,
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )
    return company_id, filing_id, cik, accession


def _prewrite_cached_html(storage_root: Path, cik: str, accession: str) -> Path:
    """Write a minimal HTML into the FilingFetcher cache path so fetch_filing
    hits the cached branch and never issues a network call."""
    accession_clean = accession.replace("-", "")
    filing_dir = storage_root / cik / accession_clean
    filing_dir.mkdir(parents=True, exist_ok=True)
    html_path = filing_dir / "primary.htm"
    html_path.write_text("<html><body><p>stub</p></body></html>")
    return html_path


def test_cmd_onboard_end_to_end_new_filing(clean_db, tmp_path, cli):
    """Happy path: seed a NEW filing, onboard it, assert DB write occurred."""
    _, filing_id, cik, accession = _seed_filing(clean_db)
    html_path = _prewrite_cached_html(tmp_path, cik, accession)

    # Mock the V2 pipeline + persistence so we don't depend on actual extraction.
    # The point of this test is the orchestration glue, not the pipeline.
    mock_pipeline_result = MagicMock()
    mock_pipeline_result.fact_count = 0

    with (
        patch.object(cli, "process_filing", return_value=mock_pipeline_result) as mock_proc,
        patch.object(cli, "V2PersistenceAdapter") as mock_persist_cls,
        patch.object(cli, "SECClient"),
    ):
        mock_persist = MagicMock()
        mock_persist_cls.return_value = mock_persist

        args = SimpleNamespace(
            industry="software",
            year="2015",
            form_type="S-1",
            limit=None,
            storage_root=str(tmp_path),
            skip_txt=True,
            include_already_extracted=False,
            yes=False,
            dry_run=False,
            user_agent="integration-test/1.0",
        )
        rc = cli.cmd_onboard(args, clean_db)

    assert rc == 0
    # process_filing invoked exactly once with the seeded filing_id
    assert mock_proc.call_count == 1
    _, kwargs = mock_proc.call_args
    assert kwargs["filing_id"] == filing_id
    assert kwargs["cik"] == cik
    assert kwargs["accession_number"] == accession
    # document_date threaded (regression guard for the A1 bug)
    from datetime import date

    assert kwargs["document_date"] == date(2015, 6, 1)
    # html_path points at the pre-cached file
    assert Path(kwargs["html_path"]) == html_path

    # persist_pipeline_result invoked with force=False (default path, not re-extract)
    assert mock_persist.persist_pipeline_result.call_count == 1
    _, persist_kwargs = mock_persist.persist_pipeline_result.call_args
    assert persist_kwargs["force"] is False
    assert persist_kwargs["document_date"] == date(2015, 6, 1)


def test_cmd_onboard_idempotent_default_skips_already_extracted(clean_db, tmp_path, cli):
    """With a v2_documents row present, default onboard must skip (no process_filing call)."""
    _, filing_id, cik, accession = _seed_filing(
        clean_db, cik="0000999002", accession="0000999002-15-000002"
    )
    _prewrite_cached_html(tmp_path, cik, accession)

    # Simulate the filing is already extracted by inserting a v2_documents row.
    with clean_db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO v2_documents (filing_id, document_type, status, fact_count, created_at, updated_at)
                VALUES (%s, 'sec_filing', 'complete', 0, now(), now())
                """,
                (filing_id,),
            )
        conn.commit()

    with (
        patch.object(cli, "process_filing") as mock_proc,
        patch.object(cli, "V2PersistenceAdapter") as mock_persist_cls,
        patch.object(cli, "SECClient"),
    ):
        mock_persist_cls.return_value = MagicMock()

        args = SimpleNamespace(
            industry="software",
            year="2015",
            form_type="S-1",
            limit=None,
            storage_root=str(tmp_path),
            skip_txt=True,
            include_already_extracted=False,
            yes=False,
            dry_run=False,
            user_agent="integration-test/1.0",
        )
        rc = cli.cmd_onboard(args, clean_db)

    assert rc == 0
    # Default path: already-extracted row is listed but NOT re-processed
    assert mock_proc.call_count == 0, (
        "cmd_onboard must not call process_filing on already-extracted filings "
        "without --include-already-extracted"
    )
