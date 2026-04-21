"""Unit tests for V2 persistence SQL correctness (no DB required)."""

from __future__ import annotations

import inspect
import re
from unittest.mock import MagicMock, patch


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
        """DELETE FROM v2_metric_facts scoped by doc_id must precede INSERT (WP-12)."""
        source = self._get_persist_sql()

        assert "DELETE FROM v2_metric_facts" in source, (
            "_persist_facts_in_tx must DELETE existing facts before inserting fresh results"
        )
        assert "doc_id = %(filing_id)s" in source, (
            "_persist_facts_in_tx DELETE must be scoped by doc_id so cross-filing data is not wiped"
        )

        # DELETE should appear before INSERT in the source
        delete_pos = source.index("DELETE FROM v2_metric_facts")
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
                p.get("source_type"),
            )
            existing = seen.get(key)
            if existing is None or p["confidence"] > existing["confidence"]:
                seen[key] = p
        return list(seen.values())

    def _make_param(
        self,
        fact_id: str,
        confidence: float,
        source_type: str = "text",
    ) -> dict:
        return {
            "doc_id": 1,
            "canonical_metric_id": "cm_average_order_value",
            "period_start": "2024-01-01",
            "period_end": "2024-12-31",
            "unit": "CURRENCY",
            "scope": "COMPANY",
            "cohort_def": None,
            "customer_type": None,
            "source_type": source_type,
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

    def test_persist_dedup_preserves_distinct_source_types(self) -> None:
        """Facts differing only in source_type must not collapse (matches DB 9-col identity index)."""
        text_fact = self._make_param("text", confidence=0.8, source_type="text")
        chart_fact = self._make_param("chart", confidence=0.8, source_type="chart")

        result = self._run_dedup([text_fact, chart_fact])

        assert len(result) == 2
        assert {p["fact_id"] for p in result} == {"text", "chart"}

    def test_persist_dedup_source_key_includes_source_type(self) -> None:
        """_persist_facts_in_tx dedup key must include source_type (9-col identity)."""
        source = self._get_dedup_source()
        assert 'p["source_type"]' in source, (
            "_persist_facts_in_tx dedup key must include source_type so CHART + TEXT "
            "facts on the same slot are not silently collapsed within a single run"
        )


def _make_image_asset():
    """Build a minimal ImageAsset fixture suitable for _persist_images_in_tx tests."""
    from src.extraction_v2.models import ImageAsset, ImageClassification

    return ImageAsset(
        img_id="test-img-id",
        filename="test_image.png",
        nearby_text="",
        ocr_text=None,
        classification=ImageClassification.UNKNOWN,
    )


def _make_adapter():
    """Build a V2PersistenceAdapter without requiring a DB connection."""
    from unittest.mock import MagicMock

    from src.extraction_v2.persistence import V2PersistenceAdapter

    adapter = V2PersistenceAdapter.__new__(V2PersistenceAdapter)
    adapter._db = MagicMock()
    return adapter


def _make_cursor(rows=None):
    """Build a mock cursor whose fetchall returns [] and fetchone returns a mock row."""
    cur = MagicMock()
    # Guard query (incoming_hidden_filenames check) returns no rows
    cur.fetchall.return_value = []
    # execute().fetchone() for the upsert RETURNING clause
    row_mock = MagicMock()
    row_mock.__getitem__ = lambda self, key: "test-img-id"
    row_mock.__iter__ = lambda self: iter(["test-img-id"])
    cur.fetchone.return_value = row_mock
    return cur


class TestImagePersistSQL:
    """Verify detected_keywords is wired through _persist_images_in_tx (sql/32)."""

    def test_detected_keywords_in_insert_columns(self) -> None:
        """detected_keywords must appear in the INSERT column list of the upsert SQL."""
        adapter = _make_adapter()
        cur = _make_cursor()
        image = _make_image_asset()

        with patch("src.extraction_v2.persistence.match_nearby_text", return_value=["keyword"]):
            adapter._persist_images_in_tx(cur, [image], filing_id=1)

        # Capture the SQL string from the first execute call (the upsert, not the guard)
        # The guard only fires when incoming_hidden_filenames is non-empty; with UNKNOWN
        # classification that branch is skipped, so execute call 0 is the upsert.
        sql_calls = [
            call
            for call in cur.execute.call_args_list
            if "INSERT INTO v2_image_assets" in str(call)
        ]
        assert sql_calls, "Expected at least one INSERT INTO v2_image_assets execute call"
        sql_text = sql_calls[0].args[0]

        insert_match = re.search(
            r"INSERT INTO v2_image_assets\s*\((.*?)\)\s*VALUES",
            sql_text,
            re.DOTALL | re.IGNORECASE,
        )
        assert insert_match, "Could not find INSERT column list in upsert SQL"
        assert "detected_keywords" in insert_match.group(1), (
            "detected_keywords must be in INSERT columns"
        )

    def test_detected_keywords_in_on_conflict_update(self) -> None:
        """detected_keywords must appear in the ON CONFLICT DO UPDATE SET clause."""
        adapter = _make_adapter()
        cur = _make_cursor()
        image = _make_image_asset()

        with patch("src.extraction_v2.persistence.match_nearby_text", return_value=["keyword"]):
            adapter._persist_images_in_tx(cur, [image], filing_id=1)

        sql_calls = [
            call
            for call in cur.execute.call_args_list
            if "INSERT INTO v2_image_assets" in str(call)
        ]
        assert sql_calls, "Expected at least one INSERT INTO v2_image_assets execute call"
        sql_text = sql_calls[0].args[0]

        assert "detected_keywords = EXCLUDED.detected_keywords" in sql_text, (
            "detected_keywords must be refreshed on ON CONFLICT DO UPDATE so re-extraction "
            "recomputes keywords against current YAML patterns"
        )

    def test_matcher_invoked_for_each_image(self) -> None:
        """match_nearby_text must be called once per ImageAsset."""
        from src.extraction_v2.models import ImageAsset, ImageClassification

        adapter = _make_adapter()
        cur = _make_cursor()

        images = [
            ImageAsset(
                img_id=f"img-{i}",
                filename=f"image_{i}.png",
                nearby_text=f"text {i}",
                ocr_text=None,
                classification=ImageClassification.UNKNOWN,
            )
            for i in range(3)
        ]

        with patch(
            "src.extraction_v2.persistence.match_nearby_text", return_value=["kw"]
        ) as mock_matcher:
            adapter._persist_images_in_tx(cur, images, filing_id=1)

        assert mock_matcher.call_count == 3, (
            f"Expected match_nearby_text called 3 times (once per image), got {mock_matcher.call_count}"
        )

    def test_empty_matches_persist_as_null(self) -> None:
        """When match_nearby_text returns [], detected_keywords param must be None (SQL NULL)."""
        adapter = _make_adapter()
        cur = _make_cursor()
        image = _make_image_asset()

        with patch("src.extraction_v2.persistence.match_nearby_text", return_value=[]):
            adapter._persist_images_in_tx(cur, [image], filing_id=1)

        # Find the upsert params (second positional arg to execute)
        sql_calls = [
            call
            for call in cur.execute.call_args_list
            if "INSERT INTO v2_image_assets" in str(call)
        ]
        assert sql_calls, "Expected at least one INSERT INTO v2_image_assets execute call"
        params = sql_calls[0].args[1]

        assert params["detected_keywords"] is None, (
            f"Empty matcher result must collapse to None (SQL NULL), got {params['detected_keywords']!r}"
        )
