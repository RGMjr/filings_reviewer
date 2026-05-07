"""Integration tests for ``scripts/run_phase1_eval.py``.

Covers:
  - ``--dry-run`` end-to-end: corpus selection, label construction, CSV
    header writing, summary skeleton — no API calls, no DB writes.
  - Corpus-selection logic picks gold filings that satisfy the
    required-metric coverage rule.
  - Smoke-test criteria computation: hand-build EvalRow sets and
    confirm pass/fail logic fires for each branch.
  - Stratified-30-sample sampler is deterministic with a fixed seed.

The Anthropic client is never instantiated in these tests; ``--dry-run``
bypasses live execution. The classify-direct path is exercised in
unit tests with a mock client (kept under ``tests/unit/`` per project
convention).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_phase1_eval.py"


def _load_script_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "run_phase1_eval_integration"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_script_module()


# ---------------------------------------------------------------------------
# Dry-run end-to-end
# ---------------------------------------------------------------------------


def test_dry_run_gold_only_writes_csv_and_summary(cli, tmp_path, monkeypatch):
    """--dry-run --gold-only produces a header-only CSV and an empty-rollup summary."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    exit_code, summary = cli.run_eval(
        run_id="testrun",
        out_dir=tmp_path,
        path_mode="direct",
        gold_only=True,
        reviewed_only=False,
        limit=5,
        dry_run=True,
    )
    assert exit_code == 0, summary

    csv_path = tmp_path / "phase1_10filing_testrun.csv"
    summary_path = tmp_path / "phase1_10filing_testrun_summary.json"
    assert csv_path.exists()
    assert summary_path.exists()

    csv_text = csv_path.read_text()
    # Header present, no data rows.
    assert csv_text.startswith("run_id,run_started_at,run_finished_at,corpus")
    assert csv_text.count("\n") == 1

    summary_loaded = json.loads(summary_path.read_text())
    assert summary_loaded["dry_run"] is True
    assert summary_loaded["run_id"] == "testrun"
    assert summary_loaded["per_metric"] == {"gold": {}, "reviewed": {}}
    assert summary_loaded["smoke"]["pass_prompt_errors"] is True
    assert summary_loaded["smoke"]["pass_catastrophic_regression"] is True
    # Gold corpus selection ran — at least one filing chosen.
    assert len(summary_loaded["selected_gold_filings"]) >= 1


def test_path_pipeline_returns_precondition_failure(cli, tmp_path):
    """Selecting --path pipeline returns exit code 2 with a clear message."""
    exit_code, summary = cli.run_eval(
        run_id="testrun_pipeline",
        out_dir=tmp_path,
        path_mode="pipeline",
        gold_only=True,
        reviewed_only=False,
        limit=5,
        dry_run=True,
    )
    assert exit_code == 2
    assert "not implemented" in summary["error"].lower()


def test_dry_run_reviewed_corpus_requires_database_url(cli, tmp_path, monkeypatch):
    """Without --gold-only and no DATABASE_URL, dry-run exits 2."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    exit_code, summary = cli.run_eval(
        run_id="testrun_no_db",
        out_dir=tmp_path,
        path_mode="direct",
        gold_only=False,
        reviewed_only=False,
        limit=5,
        dry_run=True,
    )
    assert exit_code == 2
    assert "DATABASE_URL" in summary["error"]


# ---------------------------------------------------------------------------
# Corpus-selection logic
# ---------------------------------------------------------------------------


def test_gold_corpus_covers_required_metrics(cli):
    """The selector must satisfy every required metric or return missing."""
    enrolled, _ = cli._load_recall_augmentation()
    scoreable, _skipped = cli.discover_required_gold_metrics(enrolled)
    splits = cli._load_splits()
    eligible = splits.test_urls | splits.calibration_urls
    metrics_per_filing = cli._gold_metrics_per_filing(cli.GOLD_CSV, eligible)

    selections, missing = cli.select_gold_corpus(splits, metrics_per_filing, scoreable, limit=5)
    assert len(selections) <= 5
    assert all(s.corpus == "gold" for s in selections)
    # Either coverage was achieved (missing == []) or the selector returned
    # the unmet set so the caller can fail loudly.
    if missing:
        # With a frozen split it shouldn't drift, but if it does the message
        # is the actionable signal.
        pytest.fail(
            f"Gold split no longer covers required metrics: {missing}. "
            f"Update split_v1.json or PLAN_REQUIRED_GOLD_METRICS."
        )
    # Confirm every required metric is covered by the union of chosen filings.
    chosen_urls = {s.filing_url for s in selections}
    union: set[str] = set()
    for url in chosen_urls:
        union |= metrics_per_filing.get(url, set())
    for metric in scoreable:
        assert metric in union, f"required metric {metric} not covered"


def test_gold_corpus_selection_is_deterministic(cli):
    """Running the selector twice with the same inputs returns the same filings."""
    enrolled, _ = cli._load_recall_augmentation()
    scoreable, _ = cli.discover_required_gold_metrics(enrolled)
    splits = cli._load_splits()
    eligible = splits.test_urls | splits.calibration_urls
    metrics_per_filing = cli._gold_metrics_per_filing(cli.GOLD_CSV, eligible)

    s1, _ = cli.select_gold_corpus(splits, metrics_per_filing, scoreable, limit=5)
    s2, _ = cli.select_gold_corpus(splits, metrics_per_filing, scoreable, limit=5)
    assert [f.filing_url for f in s1] == [f.filing_url for f in s2]


# ---------------------------------------------------------------------------
# Smoke-test criteria
# ---------------------------------------------------------------------------


def _make_row(
    cli,
    *,
    corpus="gold",
    filing_url="https://example.com/f1.htm",
    metric_id="cm_net_revenue_retention",
    ground_truth=True,
    classifier_present=True,
    keyword_present=None,
    classifier_score=0.9,
):
    return cli.EvalRow(
        run_id="r",
        run_started_at="t0",
        run_finished_at="t1",
        corpus=corpus,
        filing_url=filing_url,
        filing_id=None,
        issuer_key="iss",
        metric_id=metric_id,
        ground_truth=ground_truth,
        classifier_present=classifier_present,
        classifier_score=classifier_score,
        classifier_model="claude-haiku-4-5",
        classifier_sonnet_fallback=False,
        keyword_present=keyword_present,
        agreement=(
            "agree"
            if ground_truth == classifier_present
            else ("disagree" if ground_truth is not None else "n/a")
        ),
        classification=(
            "TP"
            if ground_truth and classifier_present
            else "FN"
            if ground_truth and not classifier_present
            else "FP"
            if not ground_truth and classifier_present
            else "TN"
        ),
        prompt_version="1.0",
        section_type=None,
        notes="",
    )


def test_smoke_criterion_1_prompt_errors_fail_run(cli):
    rows = [_make_row(cli)]
    errors = [
        {
            "filing_url": "https://example.com/f1.htm",
            "metric_id": None,
            "exception": "Classifier response was not valid JSON: ...",
            "stage": "classify_segment",
        }
    ]
    smoke = cli.compute_smoke_criteria(rows, errors)
    assert smoke.pass_prompt_errors is False
    assert smoke.has_hard_failure is True


def test_smoke_criterion_3_catastrophic_regression(cli):
    """Build a metric with classifier recall 0.0 and keyword baseline 1.0."""
    rows = []
    # 3 positives where keyword fired but classifier didn't.
    for i in range(3):
        rows.append(
            _make_row(
                cli,
                filing_url=f"https://example.com/f{i}.htm",
                ground_truth=True,
                classifier_present=False,
                keyword_present=True,
            )
        )
    smoke = cli.compute_smoke_criteria(rows, [])
    assert smoke.pass_catastrophic_regression is False
    assert smoke.has_hard_failure is True
    assert smoke.catastrophic_metrics
    breach = smoke.catastrophic_metrics[0]
    assert breach["metric_id"] == "cm_net_revenue_retention"
    assert breach["classifier_recall"] == 0.0
    assert breach["keyword_baseline_recall"] == 1.0


def test_smoke_criterion_3_passes_when_below_min_filings(cli):
    """Two filings is below the catastrophic-check threshold; should pass."""
    rows = [
        _make_row(
            cli,
            filing_url="https://example.com/f1.htm",
            ground_truth=True,
            classifier_present=False,
            keyword_present=True,
        ),
        _make_row(
            cli,
            filing_url="https://example.com/f2.htm",
            ground_truth=True,
            classifier_present=False,
            keyword_present=True,
        ),
    ]
    smoke = cli.compute_smoke_criteria(rows, [])
    assert smoke.pass_catastrophic_regression is True


def test_smoke_criterion_2_disagreement_sample_at_threshold(cli):
    """>30 disagreements yields a 30-row stratified sample."""
    rows = []
    metrics = ["cm_net_revenue_retention", "cm_revenue_concentration", "cm_revenue_by_cohort"]
    # 35 disagreements distributed across 3 metrics (12+12+11).
    for i in range(35):
        rows.append(
            _make_row(
                cli,
                filing_url=f"https://example.com/f{i}.htm",
                metric_id=metrics[i % 3],
                ground_truth=True,
                classifier_present=False,
            )
        )
    smoke = cli.compute_smoke_criteria(rows, [])
    assert smoke.disagreements_total == 35
    assert smoke.pass_disagreement_count is False
    assert len(smoke.stratified_30_sample) == 30
    # Stratification: every metric represented.
    sampled_metrics = {row["metric_id"] for row in smoke.stratified_30_sample}
    assert sampled_metrics == set(metrics)


def test_smoke_criterion_2_does_not_fail_run(cli):
    """Disagreement-count breach is informational; does not set has_hard_failure."""
    rows = [
        _make_row(
            cli,
            filing_url=f"https://example.com/f{i}.htm",
            metric_id="cm_net_revenue_retention",
            ground_truth=True,
            classifier_present=False,
            keyword_present=False,  # avoid catastrophic-regression fail
        )
        for i in range(35)
    ]
    smoke = cli.compute_smoke_criteria(rows, [])
    assert smoke.pass_disagreement_count is False
    # Catastrophic check passes (keyword recall == classifier recall == 0.0).
    assert smoke.pass_catastrophic_regression is True
    assert smoke.has_hard_failure is False


def test_stratified_sample_deterministic(cli):
    rows = []
    for i in range(60):
        rows.append(
            _make_row(
                cli,
                filing_url=f"https://example.com/f{i}.htm",
                metric_id=f"metric_{i % 4}",
                ground_truth=True,
                classifier_present=False,
            )
        )
    s1 = cli._stratified_disagreement_sample(rows, sample_size=30, seed=42)
    s2 = cli._stratified_disagreement_sample(rows, sample_size=30, seed=42)
    assert s1 == s2
    s3 = cli._stratified_disagreement_sample(rows, sample_size=30, seed=99)
    assert s1 != s3
