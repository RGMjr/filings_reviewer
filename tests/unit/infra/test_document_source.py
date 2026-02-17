"""
Unit tests for DocumentSource protocol and HuggingFaceTranscriptSource.

Tests cover:
- DocumentMetadata dataclass
- DocumentSource protocol compliance
- HuggingFaceTranscriptSource caching
- Metadata serialization/deserialization
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.infra.document_source import DocumentMetadata, DocumentSource
from src.infra.huggingface_source import HuggingFaceTranscriptSource


# ============================================================================
# DocumentMetadata Tests
# ============================================================================


class TestDocumentMetadata:
    def test_create_with_defaults(self):
        meta = DocumentMetadata(source_id="test-1", source="test")
        assert meta.source_id == "test-1"
        assert meta.document_type == "sec_filing"
        assert meta.ticker is None

    def test_create_with_all_fields(self):
        meta = DocumentMetadata(
            source_id="abc123",
            source="huggingface:test",
            company_name="Snowflake Inc.",
            ticker="SNOW",
            cik="0001640147",
            document_type="earnings_call",
            document_date=date(2025, 11, 20),
            title="Q3 2025 Earnings Call",
            fiscal_year=2025,
            fiscal_period="Q3",
            form_type="earnings_call",
            url="https://example.com",
        )
        assert meta.ticker == "SNOW"
        assert meta.fiscal_period == "Q3"
        assert meta.document_date == date(2025, 11, 20)


# ============================================================================
# DocumentSource Protocol Tests
# ============================================================================


class TestDocumentSourceProtocol:
    def test_huggingface_source_is_document_source(self, tmp_path):
        """HuggingFaceTranscriptSource satisfies DocumentSource protocol."""
        source = HuggingFaceTranscriptSource(cache_dir=tmp_path / "cache")
        assert isinstance(source, DocumentSource)

    def test_mock_source_satisfies_protocol(self):
        """A mock with fetch() and list_available() satisfies protocol."""

        class MockSource:
            def fetch(self, source_id: str) -> tuple[str, DocumentMetadata]:
                return "<html></html>", DocumentMetadata(source_id=source_id, source="mock")

            def list_available(
                self, ticker=None, company_name=None, limit=100
            ) -> list[DocumentMetadata]:
                return []

        assert isinstance(MockSource(), DocumentSource)


# ============================================================================
# HuggingFaceTranscriptSource Tests
# ============================================================================


class TestHuggingFaceTranscriptSource:
    @pytest.fixture
    def source(self, tmp_path) -> HuggingFaceTranscriptSource:
        """Create a source with temporary cache directory."""
        return HuggingFaceTranscriptSource(
            dataset_name="test/dataset",
            cache_dir=tmp_path / "cache",
        )

    def test_init_creates_cache_dirs(self, source):
        """Init creates cache and html directories."""
        assert source.cache_dir.exists()
        assert source._html_dir.exists()

    def test_source_name_format(self, source):
        """Source name follows 'huggingface:dataset_name' format."""
        assert source.source_name == "huggingface:test/dataset"

    def test_list_available_with_empty_index(self, source):
        """list_available returns empty list when no index exists and datasets unavailable."""
        # Patch load_dataset to raise ImportError (datasets not installed)
        with patch.dict("sys.modules", {"datasets": None}):
            source._index = []
            result = source.list_available()
            assert result == []

    def test_list_available_filters_by_ticker(self, source):
        """list_available filters by ticker."""
        source._index = [
            {"source_id": "1", "ticker": "SNOW", "company_name": "Snowflake"},
            {"source_id": "2", "ticker": "META", "company_name": "Meta"},
            {"source_id": "3", "ticker": "SNOW", "company_name": "Snowflake"},
        ]
        results = source.list_available(ticker="SNOW")
        assert len(results) == 2
        assert all(r.ticker == "SNOW" for r in results)

    def test_list_available_filters_by_company_name(self, source):
        """list_available filters by company name (case-insensitive substring)."""
        source._index = [
            {"source_id": "1", "ticker": "SNOW", "company_name": "Snowflake Inc."},
            {"source_id": "2", "ticker": "META", "company_name": "Meta Platforms"},
        ]
        results = source.list_available(company_name="snowflake")
        assert len(results) == 1
        assert results[0].company_name == "Snowflake Inc."

    def test_list_available_respects_limit(self, source):
        """list_available respects the limit parameter."""
        source._index = [
            {"source_id": str(i), "ticker": "TEST"} for i in range(10)
        ]
        results = source.list_available(limit=3)
        assert len(results) == 3

    def test_fetch_uses_cache(self, source, tmp_path):
        """fetch returns cached HTML without re-downloading."""
        # Pre-populate cache
        html_content = "<html><body>Cached transcript</body></html>"
        meta_dict = {
            "source_id": "cached-1",
            "source": source.source_name,
            "ticker": "TEST",
            "document_type": "earnings_call",
        }

        cache_html = source._html_dir / "cached-1.html"
        cache_meta = source._html_dir / "cached-1.meta.json"
        cache_html.write_text(html_content)

        import json
        cache_meta.write_text(json.dumps(meta_dict))

        html, metadata = source.fetch("cached-1")
        assert html == html_content
        assert metadata.source_id == "cached-1"
        assert metadata.ticker == "TEST"

    def test_fetch_not_found_raises(self, source):
        """fetch raises FileNotFoundError for unknown source_id."""
        source._index = []
        with pytest.raises(FileNotFoundError):
            source.fetch("nonexistent")

    def test_metadata_serialization_roundtrip(self):
        """Metadata serialization and deserialization is lossless."""
        original = DocumentMetadata(
            source_id="test-1",
            source="huggingface:test",
            company_name="Snowflake",
            ticker="SNOW",
            document_type="earnings_call",
            document_date=date(2025, 11, 20),
            title="Q3 Earnings",
            fiscal_year=2025,
            fiscal_period="Q3",
            form_type="earnings_call",
        )

        serialized = HuggingFaceTranscriptSource._metadata_to_dict(original)
        deserialized = HuggingFaceTranscriptSource._dict_to_metadata(serialized)

        assert deserialized.source_id == original.source_id
        assert deserialized.ticker == original.ticker
        assert deserialized.document_date == original.document_date
        assert deserialized.fiscal_year == original.fiscal_year
        assert deserialized.fiscal_period == original.fiscal_period

    def test_metadata_serialization_handles_none_date(self):
        """Metadata serialization handles None document_date."""
        meta = DocumentMetadata(source_id="test", source="test")
        serialized = HuggingFaceTranscriptSource._metadata_to_dict(meta)
        assert serialized["document_date"] is None

        deserialized = HuggingFaceTranscriptSource._dict_to_metadata(serialized)
        assert deserialized.document_date is None

    def test_entry_to_metadata_parses_date(self, source):
        """_entry_to_metadata correctly parses date strings."""
        entry = {
            "source_id": "test",
            "ticker": "SNOW",
            "company_name": "Snowflake",
            "date": "2025-11-20",
            "year": "2025",
            "quarter": "Q3",
        }
        meta = source._entry_to_metadata(entry)
        assert meta.document_date == date(2025, 11, 20)
        assert meta.fiscal_year == 2025
        assert meta.fiscal_period == "Q3"
        assert meta.document_type == "earnings_call"

    def test_entry_to_metadata_handles_missing_date(self, source):
        """_entry_to_metadata handles missing/invalid date gracefully."""
        entry = {"source_id": "test", "ticker": "TEST", "date": "", "year": ""}
        meta = source._entry_to_metadata(entry)
        assert meta.document_date is None
        assert meta.fiscal_year is None

    def test_index_cache_reuse(self, source, tmp_path):
        """Index is loaded from cache on second call."""
        import json

        # Pre-populate index cache
        index_data = [{"source_id": "1", "ticker": "TEST", "company_name": "Test Corp"}]
        source._index_path.write_text(json.dumps(index_data))

        # Should load from cache without calling load_dataset
        index = source._ensure_index()
        assert len(index) == 1
        assert index[0]["ticker"] == "TEST"
