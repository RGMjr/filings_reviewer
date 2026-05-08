"""Integration tests for scripts/backfill_image_classifications.py.

Covers:
  - Happy path: 3 eligible images get classified, 3 rows in v2_image_classifications.
  - Idempotency: running twice does not double-insert (already-classified images excluded).
  - --limit 1 processes exactly 1 image.
  - --dry-run makes no DB writes and no Vision calls.
  - --max-spend-usd aborts early when each call costs more than the budget.
  - Images with classification='unknown' are NOT eligible.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "backfill_image_classifications.py"


def _load_script() -> ModuleType:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "backfill_image_classifications_integration"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    return _load_script()


# ---------------------------------------------------------------------------
# DB seeding helpers
# ---------------------------------------------------------------------------


def _seed_filing(db) -> tuple[int, int]:
    company_id = db.upsert_company(
        cik="0009880001",
        company_name="BackfillClassify Test Co",
        ticker=None,
        industry_code=None,
    )
    filing_id = db.upsert_filing(
        company_id=company_id,
        cik="0009880001",
        accession_number="0009880001-99-000001",
        form_type="S-1",
        filing_date="2024-01-01",
        sec_html_url="https://www.sec.gov/test/0009880001",
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )
    return company_id, filing_id


def _insert_image(
    db,
    filing_id: int,
    filename: str = "chart1.png",
    classification: str = "chart",
    file_path: str | None = None,
) -> str:
    fp = file_path or f"pipeline/test/{filename}"
    rows = db.query(
        """
        INSERT INTO v2_image_assets (
            filing_id, filename, classification, width, height,
            dom_locator, file_path
        )
        VALUES (
            %(filing_id)s, %(filename)s, %(classification)s, 800, 600,
            %(dom_locator)s, %(file_path)s
        )
        ON CONFLICT (filing_id, filename)
            DO UPDATE SET classification = EXCLUDED.classification,
                          file_path      = EXCLUDED.file_path
        RETURNING img_id::text
        """,
        {
            "filing_id": filing_id,
            "filename": filename,
            "classification": classification,
            "dom_locator": f"body > img[src='{filename}']",
            "file_path": fp,
        },
    )
    return rows[0]["img_id"]


def _insert_confirmation(db, img_id: str, metric_id: str = "cm_customers_period_end") -> None:
    db.execute(
        """
        INSERT INTO v2_image_metric_confirmations (
            img_id, detected_metric_id, confirmed_metric_id, decision, reviewer_id
        )
        VALUES (
            %(img_id)s::uuid,
            %(metric_id)s,
            %(metric_id)s,
            'accept',
            'test_reviewer'
        )
        """,
        {"img_id": img_id, "metric_id": metric_id},
    )


def _insert_classification_row(
    db, img_id: str, predicted_metrics: list[dict], confidence: float = 0.9
) -> None:
    db.execute(
        """
        INSERT INTO v2_image_classifications (
            img_id, predicted_metrics, confidence, provider, model,
            prompt_version, cost_usd, latency_ms
        )
        VALUES (
            %(img_id)s::uuid,
            %(predicted_metrics)s::jsonb,
            %(confidence)s,
            'gemini',
            'gemini-2.5-flash-lite',
            1,
            0.001,
            300
        )
        """,
        {
            "img_id": img_id,
            "predicted_metrics": json.dumps(predicted_metrics),
            "confidence": confidence,
        },
    )


def _count_classifications(db, img_id: str) -> int:
    rows = db.query(
        "SELECT COUNT(*) AS n FROM v2_image_classifications WHERE img_id = %(img_id)s::uuid",
        {"img_id": img_id},
    )
    return rows[0]["n"]


# ---------------------------------------------------------------------------
# Fake vision response factory
# ---------------------------------------------------------------------------

FAKE_VISION_RESPONSE = {
    "predicted_metrics": ["cm_customers_period_end"],
    "confidence": 0.85,
    "rejection_reason": None,
    "reasoning": "Chart shows customer count over time.",
    "_cost_usd": 0.001,
}


def _make_mock_client(response=None, side_effect=None):
    client = MagicMock()
    if side_effect is not None:
        client.analyze_image_for_metric_classification.side_effect = side_effect
    else:
        r = dict(response or FAKE_VISION_RESPONSE)
        client.analyze_image_for_metric_classification.return_value = r
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_three_eligible_images_classified(self, clean_db, cli):
        _, filing_id = _seed_filing(clean_db)
        img_ids = []
        for i in range(3):
            img_id = _insert_image(clean_db, filing_id, f"chart{i}.png")
            _insert_confirmation(clean_db, img_id)
            img_ids.append(img_id)

        mock_client = _make_mock_client()
        mock_storage = MagicMock()
        mock_storage.get_bytes.return_value = b"fake_image_bytes"

        with (
            patch.object(cli, "_build_vision_client", return_value=mock_client),
            patch.object(cli, "get_image_storage", return_value=mock_storage),
        ):
            stats = cli.run(
                clean_db,
                provider="gemini",
                model="gemini-2.5-flash-lite",
                limit=None,
                dry_run=False,
                max_spend_usd=None,
                batch_size=25,
            )

        assert stats["successes"] == 3
        assert stats["api_errors"] == 0
        assert stats["parse_failures"] == 0

        for img_id in img_ids:
            rows = clean_db.query(
                """
                SELECT predicted_metrics, confidence, cost_usd
                FROM v2_image_classifications
                WHERE img_id = %(img_id)s::uuid
                """,
                {"img_id": img_id},
            )
            assert len(rows) == 1
            pms = rows[0]["predicted_metrics"]
            assert isinstance(pms, list)
            assert len(pms) == 1
            assert pms[0]["metric_id"] == "cm_customers_period_end"
            assert float(rows[0]["confidence"]) == pytest.approx(0.85)


class TestIdempotency:
    def test_second_run_skips_already_classified(self, clean_db, cli):
        _, filing_id = _seed_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id, "chart_idem.png")
        _insert_confirmation(clean_db, img_id)

        _insert_classification_row(
            clean_db,
            img_id,
            [{"metric_id": "cm_customers_period_end", "score": 0.85}],
        )

        mock_client = _make_mock_client()
        mock_storage = MagicMock()
        mock_storage.get_bytes.return_value = b"fake_image_bytes"

        with (
            patch.object(cli, "_build_vision_client", return_value=mock_client),
            patch.object(cli, "get_image_storage", return_value=mock_storage),
        ):
            stats = cli.run(
                clean_db,
                provider="gemini",
                model="gemini-2.5-flash-lite",
                limit=None,
                dry_run=False,
                max_spend_usd=None,
                batch_size=25,
            )

        assert stats["successes"] == 0
        assert _count_classifications(clean_db, img_id) == 1


class TestLimit:
    def test_limit_one_processes_one_image(self, clean_db, cli):
        _, filing_id = _seed_filing(clean_db)
        for i in range(3):
            img_id = _insert_image(clean_db, filing_id, f"chart_lim{i}.png")
            _insert_confirmation(clean_db, img_id)

        mock_client = _make_mock_client()
        mock_storage = MagicMock()
        mock_storage.get_bytes.return_value = b"fake_image_bytes"

        with (
            patch.object(cli, "_build_vision_client", return_value=mock_client),
            patch.object(cli, "get_image_storage", return_value=mock_storage),
        ):
            stats = cli.run(
                clean_db,
                provider="gemini",
                model="gemini-2.5-flash-lite",
                limit=1,
                dry_run=False,
                max_spend_usd=None,
                batch_size=25,
            )

        assert stats["processed"] == 1
        assert stats["successes"] == 1


class TestDryRun:
    def test_dry_run_no_writes_no_api_calls(self, clean_db, cli):
        _, filing_id = _seed_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id, "chart_dry.png")
        _insert_confirmation(clean_db, img_id)

        mock_client = _make_mock_client()
        mock_storage = MagicMock()

        with (
            patch.object(cli, "_build_vision_client", return_value=mock_client),
            patch.object(cli, "get_image_storage", return_value=mock_storage),
        ):
            stats = cli.run(
                clean_db,
                provider="gemini",
                model="gemini-2.5-flash-lite",
                limit=None,
                dry_run=True,
                max_spend_usd=None,
                batch_size=25,
            )

        assert stats["processed"] == 0
        assert stats["successes"] == 0
        mock_client.analyze_image_for_metric_classification.assert_not_called()
        mock_storage.get_bytes.assert_not_called()
        assert _count_classifications(clean_db, img_id) == 0


class TestMaxSpend:
    def test_aborts_when_spend_exceeded(self, clean_db, cli):
        _, filing_id = _seed_filing(clean_db)
        for i in range(5):
            img_id = _insert_image(clean_db, filing_id, f"chart_spend{i}.png")
            _insert_confirmation(clean_db, img_id)

        mock_client = _make_mock_client(
            {
                "predicted_metrics": ["cm_customers_period_end"],
                "confidence": 0.85,
                "rejection_reason": None,
                "reasoning": "Test",
                "_cost_usd": 0.001,
            }
        )
        mock_storage = MagicMock()
        mock_storage.get_bytes.return_value = b"fake_image_bytes"

        with (
            patch.object(cli, "_build_vision_client", return_value=mock_client),
            patch.object(cli, "get_image_storage", return_value=mock_storage),
        ):
            stats = cli.run(
                clean_db,
                provider="gemini",
                model="gemini-2.5-flash-lite",
                limit=None,
                dry_run=False,
                max_spend_usd=0.0001,
                batch_size=25,
            )

        assert stats["successes"] == 0
        assert stats["processed"] == 0


class TestIneligibleClassification:
    def test_unknown_classification_not_eligible(self, clean_db, cli):
        _, filing_id = _seed_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id, "unknown_img.png", classification="unknown")
        _insert_confirmation(clean_db, img_id)

        mock_client = _make_mock_client()
        mock_storage = MagicMock()
        mock_storage.get_bytes.return_value = b"fake_image_bytes"

        with (
            patch.object(cli, "_build_vision_client", return_value=mock_client),
            patch.object(cli, "get_image_storage", return_value=mock_storage),
        ):
            stats = cli.run(
                clean_db,
                provider="gemini",
                model="gemini-2.5-flash-lite",
                limit=None,
                dry_run=False,
                max_spend_usd=None,
                batch_size=25,
            )

        assert stats["successes"] == 0
        mock_client.analyze_image_for_metric_classification.assert_not_called()
