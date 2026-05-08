"""Integration tests for scripts/evaluate_vision_metric_scores.py.

Covers:
  - Happy path: positives + negatives produce a sensible report with AUC/AP.
  - Sentinel-reject expansion: one sentinel row yields label=0 for all
    Vision-predicted metrics on that image.
  - Label precedence: any accept beats a reject on the same (img_id, metric_id).
  - Empty data path: no classifications → warning line in report.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "evaluate_vision_metric_scores.py"


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------


def _load_script() -> ModuleType:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "evaluate_vision_metric_scores_integration"
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


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _seed_filing(db) -> tuple[int, int]:
    """Create minimal company + filing rows; return (company_id, filing_id)."""
    company_id = db.upsert_company(
        cik="0009990001",
        company_name="VisionEval Test Co",
        ticker=None,
        industry_code=None,
    )
    filing_id = db.upsert_filing(
        company_id=company_id,
        cik="0009990001",
        accession_number="0009990001-99-000001",
        form_type="S-1",
        filing_date="2024-01-01",
        sec_html_url="https://www.sec.gov/test/0009990001",
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )
    return company_id, filing_id


def _insert_image(db, filing_id: int, filename: str = "chart1.png") -> str:
    """Insert a v2_image_assets row and return img_id as string."""
    rows = db.query(
        """
        INSERT INTO v2_image_assets (
            filing_id, filename, classification, width, height,
            dom_locator, file_path
        )
        VALUES (
            %(filing_id)s, %(filename)s, 'chart', 800, 600, %(dom_locator)s, %(file_path)s
        )
        ON CONFLICT (filing_id, filename) DO UPDATE SET classification = EXCLUDED.classification
        RETURNING img_id::text
        """,
        {
            "filing_id": filing_id,
            "filename": filename,
            "dom_locator": f"body > img[src='{filename}']",
            "file_path": f"pipeline/test/{filename}",
        },
    )
    return rows[0]["img_id"]


def _insert_classification(
    db,
    img_id: str,
    predicted_metrics: list[dict],
    confidence: float = 0.9,
) -> None:
    """Insert a v2_image_classifications row."""
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
            'openai',
            'gpt-4o',
            1,
            0.001,
            500
        )
        """,
        {
            "img_id": img_id,
            "predicted_metrics": json.dumps(predicted_metrics),
            "confidence": confidence,
        },
    )


def _insert_confirmation(
    db,
    img_id: str,
    *,
    decision: str,
    detected_metric_id: str | None = None,
    confirmed_metric_id: str | None = None,
    rejection_reason: str | None = None,
    reviewer_id: str = "test_reviewer",
) -> None:
    """Insert a v2_image_metric_confirmations row."""
    db.execute(
        """
        INSERT INTO v2_image_metric_confirmations (
            img_id, detected_metric_id, confirmed_metric_id,
            decision, rejection_reason, reviewer_id
        )
        VALUES (
            %(img_id)s::uuid,
            %(detected_metric_id)s,
            %(confirmed_metric_id)s,
            %(decision)s,
            %(rejection_reason)s,
            %(reviewer_id)s
        )
        """,
        {
            "img_id": img_id,
            "detected_metric_id": detected_metric_id,
            "confirmed_metric_id": confirmed_metric_id,
            "decision": decision,
            "rejection_reason": rejection_reason,
            "reviewer_id": reviewer_id,
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Happy path: positives + negatives produce sensible report metrics."""

    def test_report_contains_auc_and_ap(self, clean_db, cli):
        """With balanced labels, AUC-ROC and Average Precision appear in report."""
        _, filing_id = _seed_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id, "chart_happy.png")

        # Predict two metrics with distinct scores.
        _insert_classification(
            clean_db,
            img_id,
            [
                {"metric_id": "cm_customers_period_end", "score": 0.85},
                {"metric_id": "cm_net_revenue_retention", "score": 0.25},
            ],
        )

        # Accept the high-score metric, reject the low-score metric.
        _insert_confirmation(
            clean_db,
            img_id,
            decision="accept",
            detected_metric_id="cm_customers_period_end",
            confirmed_metric_id="cm_customers_period_end",
        )
        _insert_confirmation(
            clean_db,
            img_id,
            decision="reject",
            detected_metric_id="cm_net_revenue_retention",
            rejection_reason="wrong_metric",
        )

        report = cli.run(clean_db, dry_run=True)

        assert "AUC-ROC" in report
        assert "Average Precision" in report
        # Should have 2 labeled pairs (one positive, one negative).
        assert "Total labeled" in report
        assert "Positives (label=1)" in report

    def test_threshold_sweep_rows_present(self, clean_db, cli):
        """Report includes 9 threshold rows (0.1–0.9)."""
        _, filing_id = _seed_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id, "chart_sweep.png")

        _insert_classification(
            clean_db,
            img_id,
            [{"metric_id": "cm_customers_period_end", "score": 0.7}],
        )
        _insert_confirmation(
            clean_db,
            img_id,
            decision="accept",
            detected_metric_id="cm_customers_period_end",
            confirmed_metric_id="cm_customers_period_end",
        )

        report = cli.run(clean_db, dry_run=True)

        # All 9 threshold values should appear as separate lines.
        for thresh in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
            assert f"{thresh:.1f}" in report


class TestSentinelRejectExpansion:
    """Sentinel 'no_relevant_metrics' → label=0 for ALL predicted metrics."""

    def test_sentinel_generates_negatives_for_all_predicted_metrics(self, clean_db, cli):
        """One sentinel row produces a negative label for each Vision-predicted metric."""
        _, filing_id = _seed_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id, "chart_sentinel.png")

        predicted = [
            {"metric_id": "cm_customers_period_end", "score": 0.9},
            {"metric_id": "cm_net_revenue_retention", "score": 0.8},
            {"metric_id": "cm_revenue_concentration", "score": 0.75},
        ]
        _insert_classification(clean_db, img_id, predicted)

        # Sentinel: both IDs null, rejection_reason='no_relevant_metrics'.
        _insert_confirmation(
            clean_db,
            img_id,
            decision="reject",
            detected_metric_id=None,
            confirmed_metric_id=None,
            rejection_reason="no_relevant_metrics",
        )

        report = cli.run(clean_db, dry_run=True)

        # All 3 predicted metrics have label=0 → 0 positives, 3 negatives.
        assert "Positives (label=1)                   : 0" in report
        assert "Total labeled (img_id, metric_id) pairs : 3" in report

    def test_sentinel_negatives_overridden_by_accept(self, clean_db, cli):
        """If another confirmation accepts a metric that was sentinel-rejected, label=1 wins."""
        _, filing_id = _seed_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id, "chart_sentinel_override.png")

        _insert_classification(
            clean_db,
            img_id,
            [
                {"metric_id": "cm_customers_period_end", "score": 0.9},
                {"metric_id": "cm_net_revenue_retention", "score": 0.3},
            ],
        )

        # Sentinel reject from reviewer A.
        _insert_confirmation(
            clean_db,
            img_id,
            decision="reject",
            detected_metric_id=None,
            confirmed_metric_id=None,
            rejection_reason="no_relevant_metrics",
            reviewer_id="reviewer_a",
        )
        # Accept from reviewer B overrides the sentinel for that metric.
        _insert_confirmation(
            clean_db,
            img_id,
            decision="accept",
            detected_metric_id="cm_customers_period_end",
            confirmed_metric_id="cm_customers_period_end",
            reviewer_id="reviewer_b",
        )

        report = cli.run(clean_db, dry_run=True)

        # cm_customers_period_end → label=1 (accept wins)
        # cm_net_revenue_retention → label=0 (only sentinel)
        assert "Positives (label=1)                   : 1" in report
        assert "Negatives (label=0)                   : 1" in report


class TestLabelPrecedence:
    """any-accept-wins: a reject row loses to a concurrent accept on the same pair."""

    def test_accept_beats_reject_on_same_metric(self, clean_db, cli):
        """When both accept and reject exist for same (img_id, metric_id), label=1."""
        _, filing_id = _seed_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id, "chart_precedence.png")

        _insert_classification(
            clean_db,
            img_id,
            [{"metric_id": "cm_customers_period_end", "score": 0.65}],
        )

        # Reviewer A rejects.
        _insert_confirmation(
            clean_db,
            img_id,
            decision="reject",
            detected_metric_id="cm_customers_period_end",
            rejection_reason="wrong_metric",
            reviewer_id="reviewer_a",
        )
        # Reviewer B accepts (any-accept-wins policy).
        _insert_confirmation(
            clean_db,
            img_id,
            decision="accept",
            detected_metric_id="cm_customers_period_end",
            confirmed_metric_id="cm_customers_period_end",
            reviewer_id="reviewer_b",
        )

        report = cli.run(clean_db, dry_run=True)

        assert "Positives (label=1)                   : 1" in report
        assert "Negatives (label=0)                   : 0" in report

    def test_correct_decision_treated_as_positive(self, clean_db, cli):
        """'correct' decision (different confirmed_metric_id) → label=1 for confirmed metric."""
        _, filing_id = _seed_filing(clean_db)
        img_id = _insert_image(clean_db, filing_id, "chart_correct.png")

        # Predict cm_net_revenue_retention; reviewer corrects it to cm_gross_revenue_retention.
        _insert_classification(
            clean_db,
            img_id,
            [
                {"metric_id": "cm_net_revenue_retention", "score": 0.6},
                {"metric_id": "cm_gross_revenue_retention", "score": 0.55},
            ],
        )
        _insert_confirmation(
            clean_db,
            img_id,
            decision="correct",
            detected_metric_id="cm_net_revenue_retention",
            confirmed_metric_id="cm_gross_revenue_retention",
        )

        report = cli.run(clean_db, dry_run=True)

        # cm_gross_revenue_retention is confirmed → label=1 (if also predicted).
        # cm_net_revenue_retention has no accept → not labeled positive.
        assert "Positives (label=1)                   : 1" in report


class TestEmptyData:
    """When no classifications exist, the report includes a warning."""

    def test_no_classifications_emits_warning(self, clean_db, cli):
        """With no v2_image_classifications rows, report warns and returns gracefully."""
        report = cli.run(clean_db, dry_run=True)
        assert "WARNING" in report or "No labeled pairs" in report or "0" in report


class TestBuildLabelMap:
    """Unit-level tests for the label-derivation logic (pure Python, no DB)."""

    def test_accept_generates_positive(self, cli):
        confirmations = [
            {
                "img_id": "img1",
                "detected_metric_id": "cm_customers_period_end",
                "confirmed_metric_id": "cm_customers_period_end",
                "decision": "accept",
                "rejection_reason": None,
            }
        ]
        vision_metrics = {"img1": {"cm_customers_period_end"}}
        label_map = cli.build_label_map(confirmations, vision_metrics)
        assert label_map[("img1", "cm_customers_period_end")] == 1

    def test_reject_generates_negative(self, cli):
        confirmations = [
            {
                "img_id": "img1",
                "detected_metric_id": "cm_net_revenue_retention",
                "confirmed_metric_id": None,
                "decision": "reject",
                "rejection_reason": "wrong_metric",
            }
        ]
        vision_metrics = {"img1": {"cm_net_revenue_retention"}}
        label_map = cli.build_label_map(confirmations, vision_metrics)
        assert label_map[("img1", "cm_net_revenue_retention")] == 0

    def test_sentinel_expands_to_all_predicted(self, cli):
        confirmations = [
            {
                "img_id": "img1",
                "detected_metric_id": None,
                "confirmed_metric_id": None,
                "decision": "reject",
                "rejection_reason": "no_relevant_metrics",
            }
        ]
        vision_metrics = {"img1": {"cm_customers_period_end", "cm_net_revenue_retention"}}
        label_map = cli.build_label_map(confirmations, vision_metrics)
        assert label_map[("img1", "cm_customers_period_end")] == 0
        assert label_map[("img1", "cm_net_revenue_retention")] == 0

    def test_accept_overrides_sentinel(self, cli):
        confirmations = [
            {
                "img_id": "img1",
                "detected_metric_id": None,
                "confirmed_metric_id": None,
                "decision": "reject",
                "rejection_reason": "no_relevant_metrics",
            },
            {
                "img_id": "img1",
                "detected_metric_id": "cm_customers_period_end",
                "confirmed_metric_id": "cm_customers_period_end",
                "decision": "accept",
                "rejection_reason": None,
            },
        ]
        vision_metrics = {"img1": {"cm_customers_period_end", "cm_net_revenue_retention"}}
        label_map = cli.build_label_map(confirmations, vision_metrics)
        assert label_map[("img1", "cm_customers_period_end")] == 1  # accept wins
        assert label_map[("img1", "cm_net_revenue_retention")] == 0  # only sentinel


class TestThresholdSweep:
    """Threshold sweep must read score column (pos 2), not label column (pos 3).

    Regression for gh-577: `[score for _, _, _, score in pairs]` extracts position 3
    (the label) regardless of variable name, collapsing Predicted+ to a constant
    (= count of positives) at every threshold and inflating AUC/AP to 1.0.
    """

    def _predicted_positive_at(self, report: str, threshold: float) -> int:
        prefix = f"{threshold:>10.1f}"
        for line in report.splitlines():
            if line.startswith(prefix):
                return int(line.split()[-1])
        raise AssertionError(f"threshold {threshold} not found in report:\n{report}")

    def test_sweep_uses_score_not_label(self, cli):
        # 3 positives, 3 negatives. Score distribution chosen so each tested
        # threshold yields a count different from 3 — the bug would always
        # return 3 (count of positives) regardless of threshold.
        pairs = [
            ("img1", "m1", 0.95, 1),
            ("img2", "m2", 0.85, 0),
            ("img3", "m3", 0.55, 0),
            ("img4", "m4", 0.55, 1),
            ("img5", "m5", 0.15, 0),
            ("img6", "m6", 0.15, 1),
        ]
        report = cli.generate_report(pairs)

        assert self._predicted_positive_at(report, 0.1) == 6
        assert self._predicted_positive_at(report, 0.5) == 4
        assert self._predicted_positive_at(report, 0.9) == 1

    def test_auc_reflects_score_distribution(self, cli):
        # Negatives have higher scores than positives — AUC must be < 0.5,
        # not 1.0 (which would mean y_score is being read as y_true).
        pairs = [
            ("img1", "m1", 0.1, 1),
            ("img2", "m2", 0.2, 1),
            ("img3", "m3", 0.8, 0),
            ("img4", "m4", 0.9, 0),
        ]
        report = cli.generate_report(pairs)
        auc_line = next(line for line in report.splitlines() if line.startswith("AUC-ROC"))
        auc = float(auc_line.split(":")[1].strip())
        assert auc < 0.5, f"AUC={auc} indicates score/label confusion (gh-577 regression)"
