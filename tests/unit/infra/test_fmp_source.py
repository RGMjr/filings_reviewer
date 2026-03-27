"""
Unit tests for src/infra/fmp_source.py.

Tests cover:
- Protocol compliance (DocumentSource)
- Source ID format (_build_source_id)
- Cache freshness (_is_cache_fresh)
- Metadata roundtrip (_metadata_to_dict / _dict_to_metadata)
- list_available with ticker filtering
- fetch cache hit (no HTTP call)
- fetch cache miss (mocked HTTP)
- Error handling (missing API key, invalid source_id)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.infra.document_source import DocumentMetadata, DocumentSource
from src.infra.fmp_source import (
    _CACHE_TTL_DAYS,
    SOURCE_PREFIX,
    FMPTranscriptSource,
    _build_source_id,
    _is_cache_fresh,
)

# ============================================================================
# Module-level helpers
# ============================================================================


def _make_source(tmp_path: Path) -> FMPTranscriptSource:
    """Create a source with a temporary cache dir and dummy API key."""
    return FMPTranscriptSource(api_key="test-key-123", cache_dir=tmp_path / "fmp_cache")


def _make_meta(**kwargs) -> DocumentMetadata:
    """Build a minimal DocumentMetadata."""
    defaults = dict(
        source_id="fmp:CRM_2025-02-26_Q4",
        source="fmp:financialmodelingprep.com",
        ticker="CRM",
        company_name="Salesforce",
        document_type="earnings_call",
        document_date=date(2025, 2, 26),
        title="CRM Earnings Call Q4 2024",
        fiscal_year=2024,
        fiscal_period="Q4",
        form_type="earnings_call",
    )
    defaults.update(kwargs)
    return DocumentMetadata(**defaults)


# ============================================================================
# _build_source_id Tests
# ============================================================================


class TestBuildSourceId:
    def test_basic_format(self):
        """Source ID follows fmp:{TICKER}_{DATE}_{QUARTER} format."""
        sid = _build_source_id("CRM", "2025-02-26", "Q4")
        assert sid == "fmp:CRM_2025-02-26_Q4"

    def test_ticker_uppercased(self):
        """Ticker is uppercased in source ID."""
        sid = _build_source_id("crm", "2025-02-26", "Q4")
        assert sid.startswith("fmp:CRM_")

    def test_date_truncated_to_10_chars(self):
        """Only the date portion (YYYY-MM-DD) is used, not time."""
        sid = _build_source_id("CRM", "2025-02-26T10:30:00", "Q4")
        assert "2025-02-26" in sid
        assert "T10:30:00" not in sid

    def test_empty_date_uses_unknown(self):
        """Empty date string falls back to 'unknown'."""
        sid = _build_source_id("CRM", "", "Q4")
        assert "unknown" in sid

    def test_quarter_spaces_removed(self):
        """Spaces in quarter string are stripped."""
        sid = _build_source_id("CRM", "2025-02-26", "Q4 2025")
        assert " " not in sid

    def test_prefix_is_fmp(self):
        """Source ID always starts with 'fmp:'."""
        sid = _build_source_id("MSFT", "2025-01-01", "Q1")
        assert sid.startswith(f"{SOURCE_PREFIX}:")


# ============================================================================
# _is_cache_fresh Tests
# ============================================================================


class TestIsCacheFresh:
    def test_nonexistent_file_is_not_fresh(self, tmp_path):
        """Missing file returns False."""
        assert _is_cache_fresh(tmp_path / "missing.html") is False

    def test_fresh_file_returns_true(self, tmp_path):
        """File modified just now is fresh."""
        cache_file = tmp_path / "fresh.html"
        cache_file.write_text("content")
        assert _is_cache_fresh(cache_file) is True

    def test_stale_file_returns_false(self, tmp_path):
        """File older than TTL returns False."""
        cache_file = tmp_path / "stale.html"
        cache_file.write_text("content")

        # Mock datetime.utcnow to simulate file being old
        stale_time = datetime.utcnow() + timedelta(days=_CACHE_TTL_DAYS + 1)
        with patch("src.infra.fmp_source.datetime") as mock_dt:
            mock_dt.utcnow.return_value = stale_time
            mock_dt.utcfromtimestamp.side_effect = datetime.utcfromtimestamp
            assert _is_cache_fresh(cache_file) is False


# ============================================================================
# FMPTranscriptSource Protocol Compliance
# ============================================================================


class TestFMPSourceProtocol:
    def test_is_document_source(self, tmp_path):
        """FMPTranscriptSource satisfies DocumentSource protocol."""
        source = _make_source(tmp_path)
        assert isinstance(source, DocumentSource)

    def test_missing_api_key_raises(self, tmp_path, monkeypatch):
        """ValueError raised when no API key is available."""
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        with pytest.raises(ValueError, match="FMP_API_KEY"):
            FMPTranscriptSource(api_key=None, cache_dir=tmp_path)

    def test_api_key_from_env(self, tmp_path, monkeypatch):
        """API key is read from FMP_API_KEY environment variable."""
        monkeypatch.setenv("FMP_API_KEY", "env-key-xyz")
        source = FMPTranscriptSource(cache_dir=tmp_path / "cache")
        assert source._api_key == "env-key-xyz"

    def test_cache_dirs_created(self, tmp_path):
        """Init creates html and index subdirectories."""
        source = _make_source(tmp_path)
        assert source._html_dir.exists()
        assert source._index_dir.exists()


# ============================================================================
# Metadata Serialization Tests
# ============================================================================


class TestMetadataSerialization:
    def test_roundtrip_with_date(self):
        """Full metadata roundtrip preserves all fields including date."""
        original = _make_meta()
        serialized = FMPTranscriptSource._metadata_to_dict(original)
        deserialized = FMPTranscriptSource._dict_to_metadata(serialized)

        assert deserialized.source_id == original.source_id
        assert deserialized.ticker == original.ticker
        assert deserialized.document_date == original.document_date
        assert deserialized.fiscal_year == original.fiscal_year
        assert deserialized.fiscal_period == original.fiscal_period
        assert deserialized.company_name == original.company_name

    def test_roundtrip_none_date(self):
        """None document_date is preserved through serialization."""
        original = _make_meta(document_date=None)
        serialized = FMPTranscriptSource._metadata_to_dict(original)
        assert serialized["document_date"] is None
        deserialized = FMPTranscriptSource._dict_to_metadata(serialized)
        assert deserialized.document_date is None

    def test_dict_with_invalid_date_returns_none(self):
        """Malformed date string in dict yields None document_date."""
        d = {"source_id": "x", "source": "y", "document_date": "not-a-date"}
        meta = FMPTranscriptSource._dict_to_metadata(d)
        assert meta.document_date is None

    def test_metadata_to_dict_date_format(self):
        """document_date is serialized as ISO format string."""
        original = _make_meta(document_date=date(2025, 2, 26))
        serialized = FMPTranscriptSource._metadata_to_dict(original)
        assert serialized["document_date"] == "2025-02-26"


# ============================================================================
# list_available Tests
# ============================================================================


class TestListAvailable:
    def test_requires_ticker(self, tmp_path):
        """ValueError raised when ticker is not provided."""
        source = _make_source(tmp_path)
        with pytest.raises(ValueError, match="ticker"):
            source.list_available(ticker=None)

    def test_uses_cached_index(self, tmp_path):
        """list_available reads cached index without API call."""
        source = _make_source(tmp_path)
        index_data = [
            {
                "source_id": "fmp:CRM_2025-02-26_Q4",
                "symbol": "CRM",
                "date": "2025-02-26",
                "quarter": 4,
                "year": 2024,
                "content": "Transcript text",
            }
        ]
        cache_path = source._index_dir / "CRM.json"
        cache_path.write_text(json.dumps(index_data))

        results = source.list_available(ticker="CRM")
        assert len(results) == 1
        assert results[0].ticker == "CRM"

    def test_respects_limit(self, tmp_path):
        """list_available respects the limit parameter."""
        source = _make_source(tmp_path)
        index_data = [
            {
                "source_id": f"fmp:CRM_2025-0{i}-01_Q{i}",
                "symbol": "CRM",
                "date": f"2025-0{i}-01",
                "quarter": i,
                "year": 2025,
            }
            for i in range(1, 6)
        ]
        cache_path = source._index_dir / "CRM.json"
        cache_path.write_text(json.dumps(index_data))

        results = source.list_available(ticker="CRM", limit=2)
        assert len(results) == 2


# ============================================================================
# fetch Tests
# ============================================================================


class TestFetch:
    def test_invalid_source_id_prefix_raises(self, tmp_path):
        """ValueError raised for source_id not starting with 'fmp:'."""
        source = _make_source(tmp_path)
        with pytest.raises(ValueError, match="Invalid FMP source_id"):
            source.fetch("huggingface:CRM_2025-02-26_Q4")

    def test_cache_hit_returns_cached_content(self, tmp_path):
        """fetch returns cached HTML without HTTP call when cache is fresh."""
        source = _make_source(tmp_path)
        source_id = "fmp:CRM_2025-02-26_Q4"
        html_content = "<html><body>Cached earnings call</body></html>"
        meta_dict = {
            "source_id": source_id,
            "source": "fmp:financialmodelingprep.com",
            "ticker": "CRM",
            "company_name": "Salesforce",
            "document_type": "earnings_call",
            "document_date": "2025-02-26",
            "title": "CRM Earnings Call Q4 2024",
            "fiscal_year": 2024,
            "fiscal_period": "Q4",
            "form_type": "earnings_call",
        }

        # Pre-populate cache
        cache_html = source._html_dir / f"{source_id.replace(':', '_')}.html"
        cache_meta = source._html_dir / f"{source_id.replace(':', '_')}.meta.json"
        cache_html.write_text(html_content, encoding="utf-8")
        cache_meta.write_text(json.dumps(meta_dict))

        # fetch should not make any HTTP calls
        with patch("src.infra.fmp_source.FMPTranscriptSource._call_api_list") as mock_api:
            html, metadata = source.fetch(source_id)

        mock_api.assert_not_called()
        assert html == html_content
        assert metadata.source_id == source_id
        assert metadata.ticker == "CRM"
        assert metadata.document_date == date(2025, 2, 26)

    def test_cache_miss_fetches_from_index(self, tmp_path):
        """fetch on cache miss resolves ticker from index."""
        source = _make_source(tmp_path)
        source_id = "fmp:CRM_2025-02-26_Q4"

        index_entry = {
            "source_id": source_id,
            "symbol": "CRM",
            "date": "2025-02-26",
            "quarter": 4,
            "year": 2024,
            "content": "Good morning. Our Q4 results were strong.",
        }

        # Patch _fetch_index to return our test entry
        with patch.object(source, "_fetch_index", return_value=[index_entry]):
            html, metadata = source.fetch(source_id)

        assert "<html" in html.lower()
        assert metadata.ticker == "CRM"
        assert metadata.fiscal_period == "Q4"

    def test_cache_miss_source_id_not_in_index_raises(self, tmp_path):
        """FileNotFoundError raised when source_id not found in index."""
        source = _make_source(tmp_path)
        source_id = "fmp:CRM_2025-02-26_Q4"

        with patch.object(source, "_fetch_index", return_value=[]):
            with pytest.raises(FileNotFoundError):
                source.fetch(source_id)
