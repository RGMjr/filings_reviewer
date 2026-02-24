"""Unit tests for V2 persistence SQL correctness (no DB required)."""

from __future__ import annotations

import re

import pytest


class TestFactUpsertSQL:
    """Verify the DO UPDATE SET clause in _upsert_facts does not include review_status."""

    def _get_upsert_sql(self) -> str:
        """Extract the raw SQL string from V2PersistenceAdapter._persist_facts_in_tx."""
        # Import here so the module loads without a DB connection
        import inspect

        from src.extraction_v2.persistence import V2PersistenceAdapter

        source = inspect.getsource(V2PersistenceAdapter._persist_facts_in_tx)
        return source

    def test_review_status_not_in_do_update_set(self):
        """review_status must NOT appear in the DO UPDATE SET clause (WP-12)."""
        source = self._get_upsert_sql()

        # Isolate the DO UPDATE SET block
        do_update_match = re.search(
            r"DO UPDATE SET\s*(.*?)(?=\"\"\"|''')",
            source,
            re.DOTALL | re.IGNORECASE,
        )
        assert do_update_match, "Could not find DO UPDATE SET block in _upsert_facts SQL"

        do_update_block = do_update_match.group(1)
        assert "review_status" not in do_update_block, (
            "review_status must NOT be in DO UPDATE SET — it would overwrite reviewer decisions"
        )

    def test_review_status_in_insert_columns(self):
        """review_status must appear in the INSERT column list (WP-12)."""
        source = self._get_upsert_sql()

        # Isolate the INSERT ... VALUES block (before ON CONFLICT)
        insert_match = re.search(
            r"INSERT INTO v2_metric_facts\s*\((.*?)\)\s*VALUES",
            source,
            re.DOTALL | re.IGNORECASE,
        )
        assert insert_match, "Could not find INSERT column list in _upsert_facts SQL"

        insert_columns = insert_match.group(1)
        assert "review_status" in insert_columns, (
            "review_status must be in INSERT columns so initial inserts set the value"
        )

    def test_review_reason_in_do_update_set(self):
        """review_reason (machine-generated) should remain in DO UPDATE SET."""
        source = self._get_upsert_sql()

        do_update_match = re.search(
            r"DO UPDATE SET\s*(.*?)(?=\"\"\"|''')",
            source,
            re.DOTALL | re.IGNORECASE,
        )
        assert do_update_match, "Could not find DO UPDATE SET block in _upsert_facts SQL"

        do_update_block = do_update_match.group(1)
        assert "review_reason" in do_update_block, (
            "review_reason (machine-generated) should be updated on re-extraction"
        )
