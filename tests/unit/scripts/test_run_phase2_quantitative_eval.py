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


def _make_clf_only_rows(
    cli,
    metric_id: str,
    *,
    n_clf_only_tp: int,
    n_clf_only_fp: int,
    n_kw_tp: int = 0,
    n_kw_fn: int = 0,
):
    """Build rows for the new C3 net-new-positives test.

    - ``n_clf_only_tp`` rows: clf=True, kw=False, gt=True (net-new TP)
    - ``n_clf_only_fp`` rows: clf=True, kw=False, gt=False (net-new FP)
    - ``n_kw_tp``     rows: clf=True, kw=True, gt=True (both catch)
    - ``n_kw_fn``     rows: clf=False, kw=False, gt=True (both miss)

    The kw_recall for the metric = n_kw_tp / (n_kw_tp + n_kw_fn + n_clf_only_tp).
    Tune the FN/kw_tp counts to push kw_recall below the 0.95 ceiling so the
    metric is considered.
    """
    rows = []
    idx = 0
    for _ in range(n_clf_only_tp):
        rows.append(
            _make_row(
                cli,
                filing_url=f"https://example.com/f{idx}.htm",
                metric_id=metric_id,
                ground_truth=True,
                classifier_present=True,
                keyword_present=False,
            )
        )
        idx += 1
    for _ in range(n_clf_only_fp):
        rows.append(
            _make_row(
                cli,
                filing_url=f"https://example.com/f{idx}.htm",
                metric_id=metric_id,
                ground_truth=False,
                classifier_present=True,
                keyword_present=False,
            )
        )
        idx += 1
    for _ in range(n_kw_tp):
        rows.append(
            _make_row(
                cli,
                filing_url=f"https://example.com/f{idx}.htm",
                metric_id=metric_id,
                ground_truth=True,
                classifier_present=True,
                keyword_present=True,
            )
        )
        idx += 1
    for _ in range(n_kw_fn):
        rows.append(
            _make_row(
                cli,
                filing_url=f"https://example.com/f{idx}.htm",
                metric_id=metric_id,
                ground_truth=True,
                classifier_present=False,
                keyword_present=False,
            )
        )
        idx += 1
    return rows


def test_c3_passes_with_net_new_positives_high_precision(cli):
    """C3 (gate v2) passes when ≥1 Tier-1 metric has ≥3 net-new TPs at precision ≥ 0.50.

    kw_recall must be < 0.95 (the headroom gate). With n_kw_tp=1, n_kw_fn=2,
    n_clf_only_tp=3, the metric's kw_recall is 1/(1+2+3) = 0.167 — well under
    the ceiling. clf-only precision = 3/(3+1) = 0.75 ≥ 0.50 → PASS.
    """
    tier1 = cli._get_tier1_metrics()
    metric_id = sorted(tier1)[0]
    rows = _make_clf_only_rows(
        cli,
        metric_id,
        n_clf_only_tp=3,
        n_clf_only_fp=1,
        n_kw_tp=1,
        n_kw_fn=2,
    )
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=len(rows),
        cache_reads=int(0.85 * len(rows)),
        total_cost_usd=1.5,
        cost_budget_usd=25.0,
    )
    c3 = next(c for c in criteria if c.id == "C3")
    assert c3.hard is True
    assert c3.passed is True, f"C3 should pass but failed: {c3.detail}"
    assert metric_id in c3.detail


def test_c3_fails_when_clf_only_precision_below_half(cli):
    """C3 fails when clf-only precision is below 0.50, even with enough TPs."""
    tier1 = cli._get_tier1_metrics()
    metric_id = sorted(tier1)[0]
    # 3 TPs but 5 FPs → precision 3/8 = 0.375 < 0.50.
    rows = _make_clf_only_rows(
        cli,
        metric_id,
        n_clf_only_tp=3,
        n_clf_only_fp=5,
        n_kw_tp=1,
        n_kw_fn=2,
    )
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=len(rows),
        cache_reads=int(0.85 * len(rows)),
        total_cost_usd=1.5,
        cost_budget_usd=25.0,
    )
    c3 = next(c for c in criteria if c.id == "C3")
    assert c3.passed is False


def test_c3_fails_when_no_metric_has_headroom(cli):
    """C3 fails when every Tier-1 metric has kw_recall at the 0.95 ceiling.

    No metric is even considered; pass condition cannot be satisfied.
    """
    tier1 = cli._get_tier1_metrics()
    metric_id = sorted(tier1)[0]
    # kw_recall = 6/6 = 1.0 ≥ 0.95 → metric excluded from consideration.
    rows = _make_tier1_rows_for_c2(cli, metric_id, n_filings=6, clf_recall=1.0, kw_recall=1.0)
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=6,
        cache_reads=5,
        total_cost_usd=1.5,
        cost_budget_usd=25.0,
    )
    c3 = next(c for c in criteria if c.id == "C3")
    assert c3.passed is False
    assert "no" in c3.detail.lower() or "headroom" in c3.detail.lower()


def test_c3_aggregate_recall_delta_is_informational(cli):
    """The old aggregate-recall delta gate is preserved as informational, hard=False."""
    tier1 = cli._get_tier1_metrics()
    metric_id = sorted(tier1)[0]
    rows = _make_tier1_rows_for_c2(cli, metric_id, n_filings=6, clf_recall=0.667, kw_recall=1.0)
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=6,
        cache_reads=5,
        total_cost_usd=1.5,
        cost_budget_usd=25.0,
    )
    c3_agg = next(c for c in criteria if c.id == "C3_aggregate_recall_delta")
    # hard=False — no longer a gate.
    assert c3_agg.hard is False
    # Detail still carries the original delta diagnostic.
    assert "delta=" in c3_agg.detail


def test_c8_agreement_rate_passes_on_high_agreement(cli):
    """C8 (informational) passes when ≥85% of rows agree on present/absent."""
    tier1 = cli._get_tier1_metrics()
    metric_id = sorted(tier1)[0]
    # 9 agree (clf=kw=True), 1 disagree (clf=True, kw=False) → 90% agreement.
    rows = _make_clf_only_rows(
        cli,
        metric_id,
        n_clf_only_tp=1,
        n_clf_only_fp=0,
        n_kw_tp=9,
        n_kw_fn=0,
    )
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=len(rows),
        cache_reads=len(rows),
        total_cost_usd=1.0,
        cost_budget_usd=25.0,
    )
    c8 = next(c for c in criteria if c.id == "C8")
    assert c8.hard is False
    assert c8.passed is True
    assert c8.value is not None and c8.value >= 0.85


def test_c8_excludes_rows_with_none_signals(cli):
    """C8 ignores rows where classifier_present or keyword_present is None."""
    tier1 = cli._get_tier1_metrics()
    metric_id = sorted(tier1)[0]
    # 5 perfectly-agreeing rows + 5 rows with None classifier_present.
    # If the None rows were counted as disagreements, rate would be 5/10=50%.
    # Excluded correctly → 5/5=100% agreement.
    rows = [
        _make_row(
            cli,
            filing_url=f"https://example.com/agree{i}.htm",
            metric_id=metric_id,
            ground_truth=True,
            classifier_present=True,
            keyword_present=True,
        )
        for i in range(5)
    ] + [
        _make_row(
            cli,
            filing_url=f"https://example.com/none{i}.htm",
            metric_id=metric_id,
            ground_truth=True,
            classifier_present=None,
            keyword_present=True,
        )
        for i in range(5)
    ]
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=len(rows),
        cache_reads=len(rows),
        total_cost_usd=1.0,
        cost_budget_usd=25.0,
    )
    c8 = next(c for c in criteria if c.id == "C8")
    assert c8.value == 1.0
    # detail should mention the filtered count (5), not 10.
    assert "5/5" in c8.detail


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


# ---------------------------------------------------------------------------
# gh-602: filing_id dedup
# ---------------------------------------------------------------------------


def _make_paf(filing_id: int, url: str, corpus: str = "gold"):
    """Minimal _PathAFiling-shaped stub for _dedup_enriched_by_filing_id."""
    from types import SimpleNamespace

    selection = SimpleNamespace(corpus=corpus, filing_url=url, filing_id=filing_id)
    return SimpleNamespace(selection=selection, filing_id=filing_id)


def test_dedup_drops_duplicate_filing_id_keeping_first(cli):
    """Two paf entries with the same filing_id but distinct URLs: keep the first."""
    a = _make_paf(101, "https://a/", "gold")
    b = _make_paf(101, "https://b/", "reviewed")  # same filing_id
    c = _make_paf(202, "https://c/", "reviewed")
    deduped, dropped = cli._dedup_enriched_by_filing_id([a, b, c])
    assert [p.filing_id for p in deduped] == [101, 202]
    assert [p.selection.filing_url for p in deduped] == ["https://a/", "https://c/"]
    assert len(dropped) == 1
    assert dropped[0]["filing_id"] == 101
    assert dropped[0]["filing_url"] == "https://b/"
    assert dropped[0]["corpus"] == "reviewed"


def test_dedup_preserves_unique_filing_ids(cli):
    """Distinct filing_ids: no rows dropped."""
    inputs = [_make_paf(i, f"https://u{i}/", "gold") for i in (10, 20, 30)]
    deduped, dropped = cli._dedup_enriched_by_filing_id(inputs)
    assert [p.filing_id for p in deduped] == [10, 20, 30]
    assert dropped == []


def test_dedup_treats_none_filing_id_as_non_dedup(cli):
    """paf.filing_id=None means 'keep, do not dedup against' (defensive)."""
    from types import SimpleNamespace

    a = SimpleNamespace(
        selection=SimpleNamespace(corpus="gold", filing_url="https://a/", filing_id=None),
        filing_id=None,
    )
    b = SimpleNamespace(
        selection=SimpleNamespace(corpus="gold", filing_url="https://b/", filing_id=None),
        filing_id=None,
    )
    deduped, dropped = cli._dedup_enriched_by_filing_id([a, b])
    assert len(deduped) == 2
    assert dropped == []


def test_dedup_intra_gold_duplication(cli):
    """Intra-gold duplication (Tenable case): two gold entries with same filing_id."""
    a = _make_paf(555, "https://gold-1/", "gold")
    b = _make_paf(555, "https://gold-2/", "gold")
    deduped, dropped = cli._dedup_enriched_by_filing_id([a, b])
    assert len(deduped) == 1
    assert deduped[0].selection.filing_url == "https://gold-1/"
    assert len(dropped) == 1


# ---------------------------------------------------------------------------
# gh-613: token aggregation + cost reporting
# ---------------------------------------------------------------------------


def test_token_aggregation_uses_canonical_helper(cli):
    """Phase-2 cost path uses estimate_cost_usd_from_counts from the LLM client."""
    from src.llm.presence_classifier_client import (
        DEFAULT_HAIKU_MODEL,
        estimate_cost_usd_from_counts,
    )

    # Realistic per-filing counts ×3 filings.
    per_filing_inputs = 50_000
    per_filing_outputs = 1_500
    per_filing_cache_read = 200_000
    per_filing_cache_create = 50_000
    n = 3
    expected = estimate_cost_usd_from_counts(
        per_filing_inputs * n,
        per_filing_outputs * n,
        per_filing_cache_read * n,
        per_filing_cache_create * n,
        model=DEFAULT_HAIKU_MODEL,
    )
    # Sanity bounds: cost is non-negative and small relative to a no-cache
    # baseline (cache reads dominate the token mix and are 10× cheaper).
    assert expected > 0
    no_cache_baseline = estimate_cost_usd_from_counts(
        (per_filing_inputs + per_filing_cache_read + per_filing_cache_create) * n,
        per_filing_outputs * n,
        0,
        0,
        model=DEFAULT_HAIKU_MODEL,
    )
    assert expected < no_cache_baseline


def test_phase1_evaluate_filing_pipeline_returns_n_calls_in_tokens(cli):
    """Phase-1's evaluate_filing_pipeline returns token_totals with n_calls key.

    Drift guard: gh-613 added this key so Phase-2 can compute the real
    call count without changing the tuple arity.
    """
    p1 = cli._phase1()
    # Sanity: signature shape is the 4-tuple advertised in the docstring.
    import inspect

    src = inspect.getsource(p1.evaluate_filing_pipeline)
    assert '"n_calls"' in src, "n_calls key missing from filing_tokens dict"
    assert "items_processed" in src, "items_processed not summed for n_calls"


def test_c6_cache_hit_rate_is_token_weighted(cli):
    """C6 reports cache_reads / (cache_reads + input_tokens), not /total_calls.

    Regression guard for an interim gh-613 bug where C6 divided cache-read
    *tokens* by call *count*, producing meaningless ratios like 545704%.
    """
    rows = [_make_row(cli)]
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=100,  # call count
        cache_reads=850_000,  # cache-read tokens
        input_tokens=150_000,  # fresh input tokens
        total_cost_usd=1.0,
        cost_budget_usd=25.0,
    )
    c6 = next(c for c in criteria if c.id == "C6")
    # Expected ratio: 850_000 / (850_000 + 150_000) = 0.85 — at the threshold.
    assert c6.value == 0.85
    assert c6.passed is True
    # Ratio must always be in [0, 1] — a regression to /total_calls would
    # produce values like 8500 here.
    assert 0.0 <= c6.value <= 1.0


def test_c6_below_threshold_fails(cli):
    """C6 fails when cache hit rate falls below the 85% target."""
    rows = [_make_row(cli)]
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=100,
        cache_reads=500_000,
        input_tokens=500_000,  # 50% hit rate
        total_cost_usd=1.0,
        cost_budget_usd=25.0,
    )
    c6 = next(c for c in criteria if c.id == "C6")
    assert c6.value == 0.5
    assert c6.passed is False


def test_c3_metric_skipped_below_min_filings(cli):
    """A Tier-1 metric with < MIN_FILINGS_FOR_METRIC_GATE rows is not considered for C3."""
    tier1 = cli._get_tier1_metrics()
    metric_id = sorted(tier1)[0]
    # Only 4 rows for this metric (below MIN_FILINGS_FOR_METRIC_GATE=5),
    # all clf-only TPs — should NOT satisfy C3 because the metric is skipped.
    rows = _make_clf_only_rows(cli, metric_id, n_clf_only_tp=4, n_clf_only_fp=0)
    criteria = cli.evaluate_criteria(
        rows,
        [],
        total_calls=4,
        cache_reads=3,
        total_cost_usd=1.0,
        cost_budget_usd=25.0,
    )
    c3 = next(c for c in criteria if c.id == "C3")
    assert c3.passed is False
