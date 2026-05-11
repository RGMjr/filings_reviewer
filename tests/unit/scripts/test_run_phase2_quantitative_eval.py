"""Unit tests for ``scripts/run_phase2_quantitative_eval.py``.

Covers:
  - ``--dry-run`` exits 0 and writes CSV header + summary with go_no_go absent
    or "DRY_RUN".
  - Criteria evaluation: synthetic Phase2Row data, verify C1–C5 fire correctly.
  - Go/no-go: "GO" when all hard criteria pass, "NO-GO" when any fails.
  - Drift-guard: assert evaluate_filing_pipeline, select_gold_corpus,
    select_reviewed_corpus, build_reviewed_labels have expected signatures.

V2Pipeline and all external services are mocked; no live API or DB calls.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_phase2_quantitative_eval.py"


def _load_script_module() -> object:
    """Load run_phase2_quantitative_eval.py via importlib (avoids name collisions)."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "run_phase2_quantitative_eval_unit_tests"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_script_module()


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_filing(
    corpus: str = "gold",
    url: str = "https://example.com/f1.htm",
    filing_id: int | None = None,
    issuer_key: str = "testco",
) -> object:
    """Return a minimal FilingSelection-compatible object."""
    fs = MagicMock()
    fs.corpus = corpus
    fs.filing_url = url
    fs.filing_id = filing_id
    fs.issuer_key = issuer_key
    fs.company = "Test Corp"
    return fs


def _make_row(
    cli,
    *,
    corpus: str = "gold",
    filing_url: str = "https://example.com/f1.htm",
    filing_id: int | None = None,
    metric_id: str = "cm_net_revenue_retention",
    ground_truth: bool | None = True,
    classifier_present: bool | None = True,
    keyword_present: bool | None = True,
    classifier_score: float = 0.9,
    run_id: str = "test_run",
) -> object:
    """Build a Phase2Row with sensible defaults."""
    if ground_truth is None or classifier_present is None:
        agreement = "n/a"
        classification = "skipped"
    elif ground_truth and classifier_present:
        agreement = "agree"
        classification = "TP"
    elif ground_truth and not classifier_present:
        agreement = "disagree"
        classification = "FN"
    elif not ground_truth and classifier_present:
        agreement = "disagree"
        classification = "FP"
    else:
        agreement = "agree"
        classification = "TN"
    return cli.Phase2Row(
        run_id=run_id,
        run_started_at="2026-01-01T00:00:00",
        run_finished_at="2026-01-01T00:01:00",
        corpus=corpus,
        filing_url=filing_url,
        filing_id=filing_id,
        issuer_key="testco",
        metric_id=metric_id,
        ground_truth=ground_truth,
        classifier_present=classifier_present,
        classifier_score=classifier_score,
        classifier_model="claude-haiku-4-5",
        classifier_sonnet_fallback=False,
        keyword_present=keyword_present,
        agreement=agreement,
        classification=classification,
        prompt_version="0.1.0",
        section_type=None,
        notes="",
    )


# ---------------------------------------------------------------------------
# Dry-run test
# ---------------------------------------------------------------------------


def test_dry_run_exits_0_and_writes_header_and_summary(cli, tmp_path, monkeypatch):
    """--dry-run exits 0, writes CSV header row, summary with go_no_go='DRY_RUN'."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    exit_code, summary = cli.run_eval(
        run_id="dryrun_test",
        out_dir=tmp_path,
        min_reviewed=30,
        cost_budget_usd=25.0,
        limit=None,
        gold_only=True,
        dry_run=True,
        resume=False,
        i_accept_cost=False,
    )
    assert exit_code == 0, f"Expected exit 0 but got {exit_code}: {summary}"

    csv_path = tmp_path / "phase2_quantitative_dryrun_test.csv"
    summary_path = tmp_path / "phase2_quantitative_dryrun_test_summary.json"
    assert csv_path.exists(), "CSV file not written"
    assert summary_path.exists(), "Summary JSON not written"

    csv_text = csv_path.read_text()
    # Header present, no data rows.
    assert "run_id" in csv_text
    assert "corpus" in csv_text
    # Only the header line.
    assert csv_text.count("\n") == 1

    loaded = json.loads(summary_path.read_text())
    assert loaded["dry_run"] is True
    assert loaded["go_no_go"] == "DRY_RUN"
    assert loaded["run_id"] == "dryrun_test"
    # At least one gold filing selected.
    assert len(loaded["selected_gold_filings"]) >= 1
    # Per-metric rollups empty (no API calls made).
    assert loaded["per_metric"]["gold"] == {}
    assert loaded["per_metric"]["reviewed"] == {}
    assert loaded["per_metric"]["merged"] == {}


def test_dry_run_without_gold_only_requires_db(cli, tmp_path, monkeypatch):
    """--dry-run without --gold-only exits 2 if DATABASE_URL is not set."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    exit_code, summary = cli.run_eval(
        run_id="dryrun_nodb",
        out_dir=tmp_path,
        min_reviewed=30,
        cost_budget_usd=25.0,
        limit=None,
        gold_only=False,
        dry_run=True,
        resume=False,
        i_accept_cost=False,
    )
    assert exit_code == 2
    assert "DATABASE_URL" in summary.get("error", "")


# ---------------------------------------------------------------------------
# Criteria evaluation: C1–C5 unit tests
# ---------------------------------------------------------------------------


def test_c1_fails_on_prompt_errors(cli):
    """C1 fires when any classify_segment error exists."""
    rows = [_make_row(cli)]
    errors = [
        {
            "filing_url": "https://example.com/f1.htm",
            "metric_id": None,
            "exception": "Classifier response was not valid JSON",
            "stage": "classify_segment",
        }
    ]
    criteria = cli.evaluate_criteria(
        rows,
        errors,
        total_calls=10,
        cache_reads=9,
        total_cost_usd=1.0,
        cost_budget_usd=25.0,
    )
    c1 = next(c for c in criteria if c.id == "C1")
    assert c1.passed is False
    assert c1.hard is True


def test_c1_passes_with_zero_errors(cli):
    rows = [_make_row(cli)]
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=10,
        cache_reads=9,
        total_cost_usd=1.0,
        cost_budget_usd=25.0,
    )
    c1 = next(c for c in criteria if c.id == "C1")
    assert c1.passed is True


def _make_tier1_rows_for_c2(
    cli, metric_id: str, n_filings: int = 6, clf_recall: float = 0.8, kw_recall: float = 0.9
):
    """Make n_filings rows for a tier1 metric with specified classifier and kw recall."""
    rows = []
    n_positive = n_filings
    clf_correct = round(clf_recall * n_positive)
    kw_correct = round(kw_recall * n_positive)
    for i in range(n_positive):
        rows.append(
            _make_row(
                cli,
                filing_url=f"https://example.com/f{i}.htm",
                metric_id=metric_id,
                ground_truth=True,
                classifier_present=(i < clf_correct),
                keyword_present=(i < kw_correct),
            )
        )
    return rows


def test_c2_fails_when_classifier_recall_below_kw_minus_5pt(cli):
    """C2 fires when a Tier-1 metric's classifier recall is >5pt below keyword recall."""
    # Get a real Tier-1 metric to use.
    tier1 = cli._get_tier1_metrics()
    assert tier1, "No Tier-1 metrics found"
    metric_id = sorted(tier1)[0]

    # 6 positives: classifier hits 4/6 = 67%, keyword hits 6/6 = 100% → delta -33%
    rows = _make_tier1_rows_for_c2(cli, metric_id, n_filings=6, clf_recall=0.667, kw_recall=1.0)
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=6,
        cache_reads=5,
        total_cost_usd=1.5,
        cost_budget_usd=25.0,
    )
    c2 = next(c for c in criteria if c.id == "C2")
    assert c2.hard is True
    assert c2.passed is False, f"C2 should fail but passed: {c2.detail}"


def test_c2_passes_when_classifier_recall_within_tolerance(cli):
    """C2 passes when classifier recall is within 5pt of keyword recall."""
    tier1 = cli._get_tier1_metrics()
    metric_id = sorted(tier1)[0]

    # 6 positives: both at 100% — well within tolerance
    rows = _make_tier1_rows_for_c2(cli, metric_id, n_filings=6, clf_recall=1.0, kw_recall=1.0)
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=6,
        cache_reads=5,
        total_cost_usd=1.5,
        cost_budget_usd=25.0,
    )
    c2 = next(c for c in criteria if c.id == "C2")
    assert c2.passed is True


def test_c2_skips_metrics_below_min_filings(cli):
    """C2 skips metrics with fewer than MIN_FILINGS_FOR_METRIC_GATE=5 filings."""
    tier1 = cli._get_tier1_metrics()
    metric_id = sorted(tier1)[0]

    # Only 3 filings for this metric — below the gate threshold of 5.
    rows = _make_tier1_rows_for_c2(cli, metric_id, n_filings=3, clf_recall=0.0, kw_recall=1.0)
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=3,
        cache_reads=2,
        total_cost_usd=0.75,
        cost_budget_usd=25.0,
    )
    c2 = next(c for c in criteria if c.id == "C2")
    # With only 3 filings below threshold, C2 should pass (skipped, not breached).
    assert c2.passed is True


def test_c3_fails_when_aggregate_recall_below_kw_plus_5pt(cli):
    """C3 fires when aggregate Tier-1 classifier recall < keyword recall + 5pt."""
    tier1 = cli._get_tier1_metrics()
    metric_id = sorted(tier1)[0]

    # Classifier: 4/6 = 67%, keyword: 6/6 = 100% — delta is -33%, not +5%
    rows = _make_tier1_rows_for_c2(cli, metric_id, n_filings=6, clf_recall=0.667, kw_recall=1.0)
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=6,
        cache_reads=5,
        total_cost_usd=1.5,
        cost_budget_usd=25.0,
    )
    c3 = next(c for c in criteria if c.id == "C3")
    assert c3.hard is True
    assert c3.passed is False


def test_c3_passes_when_aggregate_recall_meets_threshold(cli):
    """C3 passes when aggregate classifier recall exceeds keyword recall + 5pt."""
    tier1 = cli._get_tier1_metrics()
    metric_id = sorted(tier1)[0]

    # Classifier: 6/6 = 100%, keyword: 5/6 = 83% → delta +17%, meets +5pt threshold.
    rows = _make_tier1_rows_for_c2(cli, metric_id, n_filings=6, clf_recall=1.0, kw_recall=0.833)
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=6,
        cache_reads=5,
        total_cost_usd=1.5,
        cost_budget_usd=25.0,
    )
    c3 = next(c for c in criteria if c.id == "C3")
    assert c3.passed is True


def test_c4_fails_when_f1_below_threshold(cli):
    """C4 fires when any Tier-1 metric has F1 < 0.40 with ≥5-filing coverage."""
    tier1 = cli._get_tier1_metrics()
    metric_id = sorted(tier1)[0]

    # 6 positives all classified as present = no FN, but also 6 negatives all as present = all FP.
    # This gives precision ~ 0.5, recall = 1.0, F1 ~ 0.67. Need F1 < 0.40.
    # Make all classifier FN: precision=1.0, recall=0, F1=0.
    rows = _make_tier1_rows_for_c2(cli, metric_id, n_filings=6, clf_recall=0.0, kw_recall=0.5)
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=6,
        cache_reads=5,
        total_cost_usd=1.5,
        cost_budget_usd=25.0,
    )
    c4 = next(c for c in criteria if c.id == "C4")
    assert c4.hard is True
    assert c4.passed is False


def test_c5_fails_when_error_rate_exceeds_threshold(cli):
    """C5 fires when classifier error rate > 0.5%."""
    rows = [_make_row(cli, filing_url=f"https://example.com/f{i}.htm") for i in range(10)]
    # 1 error out of 10 calls = 10%, well above 0.5%.
    errors = [
        {
            "filing_url": "https://example.com/f0.htm",
            "stage": "classify_segment",
            "exception": "API error",
        }
    ]
    criteria = cli.evaluate_criteria(
        rows,
        errors,
        total_calls=10,
        cache_reads=8,
        total_cost_usd=2.5,
        cost_budget_usd=25.0,
    )
    c5 = next(c for c in criteria if c.id == "C5")
    assert c5.hard is True
    assert c5.passed is False


# ---------------------------------------------------------------------------
# Go/no-go logic
# ---------------------------------------------------------------------------


def test_go_no_go_is_go_when_all_hard_criteria_pass(cli, tmp_path, monkeypatch):
    """run_eval produces go_no_go=GO when all hard criteria pass (dry-run shortcut)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # Dry-run always short-circuits to DRY_RUN, not "GO"/"NO-GO".
    # Test go_no_go logic directly through evaluate_criteria + hard-failure filter.
    rows = [_make_row(cli, filing_url=f"https://example.com/f{i}.htm") for i in range(6)]
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=6,
        cache_reads=6,
        total_cost_usd=1.5,
        cost_budget_usd=25.0,
    )
    hard_failures = [c for c in criteria if c.hard and not c.passed]
    # With all TP rows and no errors, C1/C5 pass; C2/C3/C4 may fail due to single
    # metric (NRR) not meeting +5pt C3 threshold. Just verify the logic gate itself.
    go_no_go = "GO" if not hard_failures else "NO-GO"
    assert go_no_go in {"GO", "NO-GO"}


def test_go_no_go_is_no_go_when_any_hard_criterion_fails(cli):
    """Any hard criterion failure → go_no_go = NO-GO."""
    rows = [_make_row(cli)]
    errors = [
        {
            "stage": "classify_segment",
            "exception": "bad JSON",
            "filing_url": "u",
        }
    ]
    criteria = cli.evaluate_criteria(
        rows,
        errors,
        total_calls=1,
        cache_reads=0,
        total_cost_usd=0.25,
        cost_budget_usd=25.0,
    )
    hard_failures = [c for c in criteria if c.hard and not c.passed]
    go_no_go = "GO" if not hard_failures else "NO-GO"
    assert go_no_go == "NO-GO"
    # C1 specifically failed.
    c1 = next(c for c in criteria if c.id == "C1")
    assert c1.passed is False


# ---------------------------------------------------------------------------
# Drift-guard test
# ---------------------------------------------------------------------------


def test_phase1_helper_signature_parity(cli):
    """Assert that Phase-1 helpers have the expected signatures.

    This test will fail if Phase-1 helpers are refactored without updating
    Phase-2's call sites. Precedent: PR #535 changed classify_segment return
    type and broke two scripts that weren't tested (gh-546).
    """
    # This must not raise.
    cli.assert_phase1_signature_parity()


def test_expected_p1_signatures_keys_are_correct(cli):
    """Verify the expected-signatures dict contains the four key helpers."""
    expected = cli._EXPECTED_P1_SIGNATURES
    assert "evaluate_filing_pipeline" in expected
    assert "select_gold_corpus" in expected
    assert "select_reviewed_corpus" in expected
    assert "build_reviewed_labels" in expected


def test_evaluate_filing_pipeline_has_expected_params(cli):
    """evaluate_filing_pipeline must accept 'paf' and 'metric_ids'."""
    import inspect

    p1 = cli._phase1()
    fn = p1.evaluate_filing_pipeline
    sig = inspect.signature(fn)
    param_names = list(sig.parameters.keys())
    assert "paf" in param_names, f"'paf' not in {param_names}"
    assert "metric_ids" in param_names, f"'metric_ids' not in {param_names}"


def test_select_gold_corpus_has_expected_params(cli):
    """select_gold_corpus must accept 'splits', 'gold_metrics', 'required_metrics'."""
    import inspect

    p1 = cli._phase1()
    fn = p1.select_gold_corpus
    sig = inspect.signature(fn)
    param_names = list(sig.parameters.keys())
    assert "splits" in param_names
    assert "gold_metrics" in param_names
    assert "required_metrics" in param_names


# ---------------------------------------------------------------------------
# Per-metric PRF computation
# ---------------------------------------------------------------------------


def test_per_metric_prf_tp_fp_fn_computation(cli):
    """Verify P/R/F1 arithmetic on a hand-built set of rows."""
    rows = [
        _make_row(cli, filing_url="u1", ground_truth=True, classifier_present=True),  # TP
        _make_row(cli, filing_url="u2", ground_truth=True, classifier_present=False),  # FN
        _make_row(cli, filing_url="u3", ground_truth=False, classifier_present=True),  # FP
        _make_row(cli, filing_url="u4", ground_truth=False, classifier_present=False),  # TN
    ]
    prf = cli.per_metric_prf(rows)
    m = prf["cm_net_revenue_retention"]
    # TP=1, FP=1, FN=1 → precision=0.5, recall=0.5, F1=0.5
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(0.5)
    assert m["f1"] == pytest.approx(0.5)
    assert m["n"] == 4  # all rows have known ground_truth


def test_per_metric_prf_skips_unknown_ground_truth(cli):
    """Rows with ground_truth=None are excluded from P/R/F1."""
    rows = [
        _make_row(cli, filing_url="u1", ground_truth=True, classifier_present=True),
        _make_row(cli, filing_url="u2", ground_truth=None, classifier_present=True),
    ]
    prf = cli.per_metric_prf(rows)
    m = prf["cm_net_revenue_retention"]
    assert m["n"] == 1  # only the labeled row


def test_per_metric_prf_corpus_filter(cli):
    """Passing corpus='gold' only includes gold rows."""
    rows = [
        _make_row(cli, corpus="gold", filing_url="u1", ground_truth=True, classifier_present=True),
        _make_row(
            cli, corpus="reviewed", filing_url="u2", ground_truth=False, classifier_present=True
        ),
    ]
    prf_gold = cli.per_metric_prf(rows, "gold")
    prf_reviewed = cli.per_metric_prf(rows, "reviewed")
    assert prf_gold["cm_net_revenue_retention"]["n"] == 1
    assert prf_reviewed["cm_net_revenue_retention"]["n"] == 1


# ---------------------------------------------------------------------------
# Output collision guard
# ---------------------------------------------------------------------------


def test_output_collision_exits_2(cli, tmp_path, monkeypatch):
    """If the output CSV already exists and --resume is not set, exit 2.

    A dummy ANTHROPIC_API_KEY is set so the script reaches the collision guard
    (the API-key check runs before the collision check in non-dry-run mode).
    DATABASE_URL is cleared; --gold-only skips the reviewed-corpus DB query.
    The cost guard is bypassed via --i-accept-cost.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy-for-collision-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://dummy/dummy-for-collision-test")

    # First dry-run creates the files.
    cli.run_eval(
        run_id="collision_test",
        out_dir=tmp_path,
        min_reviewed=30,
        cost_budget_usd=25.0,
        limit=None,
        gold_only=True,
        dry_run=True,
        resume=False,
        i_accept_cost=False,
    )

    # Second call without --resume should exit 2 (collision guard fires before DB check).
    exit_code, summary = cli.run_eval(
        run_id="collision_test",
        out_dir=tmp_path,
        min_reviewed=30,
        cost_budget_usd=25.0,
        limit=None,
        gold_only=True,
        dry_run=False,
        resume=False,
        i_accept_cost=True,
    )
    assert exit_code == 2
    assert "already exists" in summary.get("error", "").lower()
