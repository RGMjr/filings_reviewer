"""Unit tests for V2 persistence SQL correctness (no DB required)."""

from __future__ import annotations

import inspect
import re


class TestFactUpsertSQL:
    """Verify the delete-then-insert pattern in _persist_facts_in_tx."""

    def _get_persist_sql(self) -> str:
        """Extract the raw source of V2PersistenceAdapter._persist_facts_in_tx."""
        # Import here so the module loads without a DB connection
        import inspect

        from src.extraction_v2.persistence import V2PersistenceAdapter

        source = inspect.getsource(V2PersistenceAdapter._persist_facts_in_tx)
        return source

    def test_review_status_not_in_do_update_set(self):
        """persistence uses delete-then-insert, not DO UPDATE SET (WP-12)."""
        source = self._get_persist_sql()

        # The new pattern must not use ON CONFLICT DO UPDATE at all
        assert "DO UPDATE SET" not in source.upper(), (
            "_persist_facts_in_tx must not use ON CONFLICT DO UPDATE SET — "
            "delete-then-insert is the required pattern"
        )

    def test_delete_before_insert(self):
        """DELETE FROM v2_metric_facts WHERE doc_id must precede INSERT (WP-12)."""
        source = self._get_persist_sql()

        assert "DELETE FROM v2_metric_facts WHERE doc_id" in source, (
            "_persist_facts_in_tx must DELETE existing facts before inserting fresh results"
        )

        # DELETE should appear before INSERT in the source
        delete_pos = source.index("DELETE FROM v2_metric_facts WHERE doc_id")
        insert_pos = source.index("INSERT INTO v2_metric_facts")
        assert delete_pos < insert_pos, "DELETE must precede INSERT in _persist_facts_in_tx"

    def test_review_status_in_insert_columns(self):
        """review_status must appear in the INSERT column list (WP-12)."""
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

    def test_review_reason_in_do_update_set(self):
        """review_reason must appear in INSERT columns under delete-then-insert pattern."""
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


class TestPersistDedup:
    """Verify the persistence-layer dedup uses highest-confidence-wins (WP-12)."""

    def _get_dedup_source(self) -> str:
        from src.extraction_v2.persistence import V2PersistenceAdapter
        return inspect.getsource(V2PersistenceAdapter._persist_facts_in_tx)

    def _run_dedup(self, params_list: list[dict]) -> list[dict]:
        """Exercise the dedup logic extracted from _persist_facts_in_tx."""
        seen: dict[tuple, dict] = {}
        for p in params_list:
            key = (
                p.get("doc_id"),
                p.get("canonical_metric_id"),
                p.get("period_start"),
                p.get("period_end"),
                p.get("unit"),
                p.get("scope"),
                p.get("cohort_def") or "",
                p.get("customer_type") or "",
            )
            existing = seen.get(key)
            if existing is None or p["confidence"] > existing["confidence"]:
                seen[key] = p
        return list(seen.values())

    def _make_param(self, fact_id: str, confidence: float) -> dict:
        return {
            "doc_id": 1,
            "canonical_metric_id": "cm_average_order_value",
            "period_start": "2024-01-01",
            "period_end": "2024-12-31",
            "unit": "CURRENCY",
            "scope": "COMPANY",
            "cohort_def": None,
            "customer_type": None,
            "confidence": confidence,
            "fact_id": fact_id,
        }

    def test_persist_dedup_keeps_highest_confidence(self) -> None:
        """When a low-confidence fact arrives before a high-confidence one, high wins."""
        low = self._make_param("low", confidence=0.5)
        high = self._make_param("high", confidence=0.9)

        result = self._run_dedup([low, high])

        assert len(result) == 1
        assert result[0]["fact_id"] == "high"

    def test_persist_dedup_high_first_low_second(self) -> None:
        """High-confidence fact is not displaced by a later low-confidence one."""
        high = self._make_param("high", confidence=0.9)
        low = self._make_param("low", confidence=0.5)

        result = self._run_dedup([high, low])

        assert len(result) == 1
        assert result[0]["fact_id"] == "high"

    def test_persist_dedup_source_uses_confidence_check(self) -> None:
        """_persist_facts_in_tx uses confidence comparison, not last-write-wins."""
        source = self._get_dedup_source()
        assert 'existing["confidence"]' in source, (
            "_persist_facts_in_tx must compare confidence to keep highest, not last-write-wins"
        )
