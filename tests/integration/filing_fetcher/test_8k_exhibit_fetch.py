"""
Tests for FilingFetcher 8-K exhibit 99.1 fetching.

Verifies:
- 8-K filings fetch exhibit 99.1 and concatenate it with the primary document
- 8-K/A is also covered (form_type.startswith("8-K"))
- S-1/F-1 filings are unaffected
- Idempotency: cached file with separator is a no-op on re-fetch
- Backfill: cached file without separator gets exhibit appended on re-fetch
- Missing exhibit does not fail the fetch

No database required — all HTTP is mocked.
"""

from __future__ import annotations

import pathlib
from unittest.mock import Mock, patch

import pytest

from src.filing_fetcher.filing_fetcher import _EXHIBIT_SEPARATOR, FilingFetcher
from src.infra.sec_client import FilingMetadata

# ---------------------------------------------------------------------------
# Shared HTML fixtures
# ---------------------------------------------------------------------------

# Small 8-K cover page (~2 KB) — deliberately below the 15 KB minimum size
# threshold to reproduce the Samsara 2025-08-21 shape.
_8K_PRIMARY_HTML = (
    "<html><head><title>Current Report on Form 8-K</title></head><body>"
    "<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>"
    "<p>WASHINGTON, D.C. 20549</p>"
    "<p>FORM 8-K</p>"
    "<p>CURRENT REPORT</p>"
    "<p>Pursuant to Section 13 or 15(d) of the Securities Exchange Act of 1934</p>"
    + " " * 2000
    + "</body></html>"
)

# Exhibit 99.1 — earnings press release with customer-metric language.
# Combined with primary HTML, this pushes total well above 15 KB.
_EXHIBIT_HTML = (
    "<html><head><title>Earnings Release Q3 2025</title></head><body>"
    "<h1>Samsara Inc. Reports Third Quarter Fiscal 2025 Results</h1>"
    "<p>Total revenue increased 36% year-over-year to $322 million.</p>"
    "<p>Annual Recurring Revenue (ARR) reached $1.36 billion.</p>"
    "<p>Net revenue retention rate was 115%.</p>"
    "<p>Customers with ARR over $100,000 grew to 1,848.</p>"
    + "X" * 18000
    + "</body></html>"
)

_EXHIBIT_URL = (
    "https://www.sec.gov/Archives/edgar/data/1642545/"
    "000164254525000123/exhibit991-2025x08x21.htm"
)

_CIK = "0001642545"
_ACCESSION = "0001642545-25-000123"
_PRIMARY_URL = (
    "https://www.sec.gov/Archives/edgar/data/1642545/"
    "000164254525000123/primary.htm"
)


def _make_metadata(form_type: str = "8-K") -> FilingMetadata:
    return FilingMetadata(
        cik=_CIK,
        company_name="Samsara Inc.",
        form_type=form_type,
        filing_date="2025-08-21",
        accession_number=_ACCESSION,
        primary_doc_url=_PRIMARY_URL,
        txt_url=None,
    )


def _mock_response(text: str) -> Mock:
    resp = Mock()
    resp.text = text
    resp.raise_for_status = Mock()
    return resp


@pytest.fixture
def fetcher(tmp_path: pathlib.Path) -> FilingFetcher:
    """FilingFetcher with mocked SECClient and temp storage root; no DB."""
    mock_sec_client = Mock()
    mock_sec_client.get_exhibit_99_1_url.return_value = _EXHIBIT_URL
    mock_sec_client.resolve_primary_document_url.return_value = None
    return FilingFetcher(
        storage_root=str(tmp_path / "filings"),
        sec_client=mock_sec_client,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEightKExhibitFetch:
    def test_exhibit_fetched_and_concatenated(self, fetcher: FilingFetcher) -> None:
        """Exhibit 99.1 is fetched and concatenated with separator into primary.htm."""
        md = _make_metadata("8-K")

        with patch.object(
            fetcher.session,
            "get",
            side_effect=[
                _mock_response(_8K_PRIMARY_HTML),
                _mock_response(_EXHIBIT_HTML),
            ],
        ):
            content = fetcher.fetch_filing(md, fetch_txt=False)

        assert content is not None
        html = pathlib.Path(content.html_path).read_text(encoding="utf-8")
        assert _EXHIBIT_SEPARATOR in html
        assert "total revenue" in html.lower()
        assert "arr" in html.lower()
        assert "net revenue retention" in html.lower()

    def test_8ka_also_fetches_exhibit(self, fetcher: FilingFetcher) -> None:
        """8-K/A also triggers exhibit fetch (form_type.startswith('8-K') covers it)."""
        md = _make_metadata("8-K/A")

        with patch.object(
            fetcher.session,
            "get",
            side_effect=[
                _mock_response(_8K_PRIMARY_HTML),
                _mock_response(_EXHIBIT_HTML),
            ],
        ):
            content = fetcher.fetch_filing(md, fetch_txt=False)

        assert content is not None
        assert _EXHIBIT_SEPARATOR in pathlib.Path(content.html_path).read_text(
            encoding="utf-8"
        )

    def test_exhibit_fetch_skipped_for_s1(self, fetcher: FilingFetcher) -> None:
        """S-1 filings do not trigger exhibit fetch; get_exhibit_99_1_url not called."""
        md = _make_metadata("S-1")
        s1_html = (
            "<html><head><title>S-1</title></head><body>"
            "<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>"
            "<p>FORM S-1</p>"
            + "X" * 20000
            + "</body></html>"
        )

        with patch.object(
            fetcher.session, "get", return_value=_mock_response(s1_html)
        ):
            content = fetcher.fetch_filing(md, fetch_txt=False)

        assert content is not None
        fetcher.sec_client.get_exhibit_99_1_url.assert_not_called()
        html = pathlib.Path(content.html_path).read_text(encoding="utf-8")
        assert _EXHIBIT_SEPARATOR not in html

    def test_missing_exhibit_does_not_fail(self, fetcher: FilingFetcher) -> None:
        """If index.json has no exhibit 99.1 match, fetch succeeds with primary only."""
        fetcher.sec_client.get_exhibit_99_1_url.return_value = None
        md = _make_metadata("8-K")
        large_primary = (
            "<html><head><title>8-K</title></head><body>"
            "<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>"
            "<p>FORM 8-K</p>"
            + "X" * 20000
            + "</body></html>"
        )

        with patch.object(
            fetcher.session, "get", return_value=_mock_response(large_primary)
        ):
            content = fetcher.fetch_filing(md, fetch_txt=False)

        assert content is not None
        html = pathlib.Path(content.html_path).read_text(encoding="utf-8")
        assert _EXHIBIT_SEPARATOR not in html

    def test_idempotency_cached_file_without_separator(
        self, fetcher: FilingFetcher
    ) -> None:
        """Cached primary.htm lacking separator gets exhibit appended on re-fetch."""
        md = _make_metadata("8-K")
        storage_dir = fetcher._get_storage_dir(md.cik, md.accession_number)
        storage_dir.mkdir(parents=True, exist_ok=True)
        (storage_dir / "primary.htm").write_text(_8K_PRIMARY_HTML, encoding="utf-8")

        with patch.object(
            fetcher.session,
            "get",
            return_value=_mock_response(_EXHIBIT_HTML),
        ):
            content = fetcher.fetch_filing(md, fetch_txt=False)

        assert content is not None
        html = pathlib.Path(content.html_path).read_text(encoding="utf-8")
        assert _EXHIBIT_SEPARATOR in html
        assert "total revenue" in html.lower()

    def test_idempotency_cached_file_with_separator(
        self, fetcher: FilingFetcher
    ) -> None:
        """Cached primary.htm with separator triggers no HTTP calls on re-fetch."""
        md = _make_metadata("8-K")
        already_combined = (
            _8K_PRIMARY_HTML + f"\n{_EXHIBIT_SEPARATOR}\n" + _EXHIBIT_HTML
        )
        storage_dir = fetcher._get_storage_dir(md.cik, md.accession_number)
        storage_dir.mkdir(parents=True, exist_ok=True)
        (storage_dir / "primary.htm").write_text(already_combined, encoding="utf-8")

        with patch.object(fetcher.session, "get") as mock_get:
            fetcher.fetch_filing(md, fetch_txt=False)

        mock_get.assert_not_called()
        fetcher.sec_client.get_exhibit_99_1_url.assert_not_called()
