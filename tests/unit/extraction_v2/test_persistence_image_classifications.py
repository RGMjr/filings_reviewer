"""Unit tests for V2PersistenceAdapter._persist_image_classifications_in_tx.

Uses a MagicMock cursor — no DB required. Verifies that the SQL shape + the
parameter dicts match the v2_image_classifications schema (sql/45).
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import MagicMock

from src.extraction_v2.models import ImageClassificationRecord
from src.extraction_v2.persistence import V2PersistenceAdapter


def _make_adapter() -> V2PersistenceAdapter:
    # DB arg is unused in these tests (we pass the cursor directly).
    return V2PersistenceAdapter(db=MagicMock())


def _record(**overrides) -> ImageClassificationRecord:
    defaults = {
        "img_id": "11111111-1111-1111-1111-111111111111",
        "predicted_metrics": [{"metric_id": "cm_revenue_by_cohort", "score": 0.8}],
        "confidence": 0.8,
        "rejection_reason": None,
        "reasoning": "cohort-bar shape",
        "provider": "gemini",
        "model": "gemini-2.5-flash-lite",
        "prompt_version": 1,
        "cost_usd": 0.00218,
        "latency_ms": 1590,
    }
    defaults.update(overrides)
    return ImageClassificationRecord(**defaults)


class TestPersistImageClassifications:
    def test_empty_list_is_noop(self):
        cur = MagicMock()
        count = _make_adapter()._persist_image_classifications_in_tx(cur, [])
        assert count == 0
        cur.executemany.assert_not_called()

    def test_inserts_one_record(self):
        cur = MagicMock()
        rec = _record()
        count = _make_adapter()._persist_image_classifications_in_tx(cur, [rec])

        assert count == 1
        cur.executemany.assert_called_once()
        sql_arg, params_arg = cur.executemany.call_args[0]

        # SQL references the target table + all key columns
        assert "INSERT INTO v2_image_classifications" in sql_arg
        for column in (
            "img_id",
            "predicted_metrics",
            "confidence",
            "rejection_reason",
            "reasoning",
            "provider",
            "model",
            "prompt_version",
            "cost_usd",
            "latency_ms",
        ):
            assert column in sql_arg, f"{column} missing from INSERT"

        # predicted_metrics is serialized as JSON for JSONB column
        assert len(params_arg) == 1
        row = params_arg[0]
        assert row["img_id"] == rec.img_id
        assert json.loads(row["predicted_metrics"]) == rec.predicted_metrics
        assert row["confidence"] == rec.confidence
        assert row["cost_usd"] == rec.cost_usd
        assert row["latency_ms"] == rec.latency_ms

    def test_multiple_records_batched(self):
        cur = MagicMock()
        recs = [_record(img_id=f"img-{i:03d}") for i in range(5)]

        count = _make_adapter()._persist_image_classifications_in_tx(cur, recs)

        assert count == 5
        cur.executemany.assert_called_once()
        _, params_arg = cur.executemany.call_args[0]
        assert len(params_arg) == 5
        assert [p["img_id"] for p in params_arg] == [f"img-{i:03d}" for i in range(5)]

    def test_rejection_reason_passed_through(self):
        cur = MagicMock()
        rec = _record(
            predicted_metrics=[],
            confidence=0.0,
            rejection_reason="table_handled_elsewhere",
        )
        _make_adapter()._persist_image_classifications_in_tx(cur, [rec])

        _, params_arg = cur.executemany.call_args[0]
        assert params_arg[0]["rejection_reason"] == "table_handled_elsewhere"

    def test_signature_does_not_leak_filing_id(self):
        # The table has no filing_id column — assert the signature doesn't
        # take one, so a caller passing it gets a TypeError early.
        sig = inspect.signature(V2PersistenceAdapter._persist_image_classifications_in_tx)
        assert "filing_id" not in sig.parameters
