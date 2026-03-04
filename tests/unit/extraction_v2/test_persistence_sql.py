"""Unit tests for V2 persistence SQL correctness (no DB required)."""

from __future__ import annotations

import re


class TestFactUpsertSQL:
    """Verify the delete-then-insert + ON CONFLICT DO UPDATE pattern in _persist_facts_in_tx.

    The pattern:
      1. DELETE WHERE doc_id = ... (cross-run idempotency)
      2. INSERT ... ON CONFLICT DO UPDATE (intra-run dedup: keep higher-confidence fact)
    """

    def _get_persist_sql(self) -> str:
        """Extract the raw source of V2PersistenceAdapter._persist_facts_in_tx."""
        # Import here so the module loads without a DB connection
        import inspect

        from src.extraction_v2.persistence import V2PersistenceAdapter

        source = inspect.getsource(V2PersistenceAdapter._persist_facts_in_tx)
        return source

    def test_on_conflict_do_update_used(self):
        """_persist_facts_in_tx must use ON CONFLICT DO UPDATE to handle intra-run duplicates."""
        source = self._get_persist_sql()

        assert "DO UPDATE SET" in source.upper(), (
            "_persist_facts_in_tx must use ON CONFLICT DO UPDATE SET to handle "
            "intra-run duplicate facts (keeping higher-confidence fact)"
        )

    def test_delete_before_insert(self):
        """DELETE FROM v2_metric_facts WHERE doc_id must precede INSERT (cross-run idempotency)."""
        source = self._get_persist_sql()

        assert "DELETE FROM v2_metric_facts WHERE doc_id" in source, (
            "_persist_facts_in_tx must DELETE existing facts before inserting fresh results"
        )

        # DELETE should appear before INSERT in the source
        delete_pos = source.index("DELETE FROM v2_metric_facts WHERE doc_id")
        insert_pos = source.index("INSERT INTO v2_metric_facts")
        assert delete_pos < insert_pos, "DELETE must precede INSERT in _persist_facts_in_tx"

    def test_review_status_in_insert_columns(self):
        """review_status must appear in the INSERT column list."""
        source = self._get_persist_sql()

        # Isolate the INSERT ... VALUES block
        insert_match = re.search(
            r"INSERT INTO v2_metric_facts\s*\((.*?)\)\s*VALUES",
            source,
            re.DOTALL | re.IGNORECASE,
        )
        assert insert_match, "Could not find INSERT column list in _persist_facts_in_tx SQL"

        insert_columns = insert_match.group(1)
        assert "review_status" in insert_columns, (
            "review_status must be in INSERT columns so initial inserts set the value"
        )

    def test_review_reason_in_insert_columns(self):
        """review_reason must appear in INSERT columns."""
        source = self._get_persist_sql()

        insert_match = re.search(
            r"INSERT INTO v2_metric_facts\s*\((.*?)\)\s*VALUES",
            source,
            re.DOTALL | re.IGNORECASE,
        )
        assert insert_match, "Could not find INSERT column list in _persist_facts_in_tx SQL"

        insert_columns = insert_match.group(1)
        assert "review_reason" in insert_columns, (
            "review_reason (machine-generated) must be included in INSERT columns"
        )

    def test_confidence_kept_on_conflict(self):
        """ON CONFLICT DO UPDATE must use GREATEST(confidence) to keep the higher-confidence fact."""
        source = self._get_persist_sql()

        assert "GREATEST(EXCLUDED.confidence, v2_metric_facts.confidence)" in source, (
            "ON CONFLICT DO UPDATE must use GREATEST(confidence) to retain the higher-confidence fact"
        )
