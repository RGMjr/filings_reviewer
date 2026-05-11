"""Phase-2 held-out + reviewed-corpus quantitative eval for the LLM presence classifier.

Runs the full V2 pipeline (Path A) across a ≥30-filing corpus drawn from
two sources — held-out gold (test + calibration splits) and a reviewed
production slice — and writes a per-(corpus, filing, metric) CSV plus an
aggregate summary JSON with hard pass/fail criteria.

This is Gate 2 of 2 before flipping ``presence_classifier_enabled`` in
production. Gate 1 (the qualitative smoke eval) is ``scripts/run_phase1_eval.py``;
it must pass first.

Path A only
-----------

Phase 2 runs only Path A — the full V2 pipeline per filing with
``enable_llm_presence_classifier=True`` and ``retain_context=True``.
Path B (direct segment scoring) was appropriate for cheap smoke; not for a
go/no-go gate. Keyword baseline per filing comes from
``PipelineResult.context.candidates`` (not from a DB join).

Corpus
------

  Gold slice (``test`` + ``calibration`` splits from ``split_v1.json``):
      All eligible filings — no limit applied unless ``--limit`` is set.
      Train is excluded: few-shots were mined from train, scoring it leaks
      prompts.

  Reviewed slice:
      Drawn from production via ``v2_review_decisions × v2_metric_facts``
      (text source only), ordered by reviewer-decision density, deduplicated
      against gold URLs. Skipped when ``--gold-only`` is set. Fails with
      exit 2 if fewer than ``--min-reviewed N`` (default 30) eligible filings
      exist after deduplication.

Pass/fail criteria
------------------

  C1. Zero prompt/parse errors from classify_segment          — Hard
  C2. Per-Tier-1-metric classifier recall ≥ kw recall − 5pt  — Hard
  C3. Aggregate Tier-1 classifier recall ≥ kw recall + 5pt   — Hard
  C4. No Tier-1 metric with classifier F1 < 0.40             — Hard
  C5. Classifier error rate ≤ 0.5% of calls                  — Hard
  C6. Cache hit rate ≥ 85%                                    — Informational
  C7. Total cost ≤ --cost-budget USD                          — Informational

``go_no_go = "GO"`` iff all hard criteria (C1–C5) pass.

Exit codes
----------

  0 — go_no_go == "GO"
  1 — go_no_go == "NO-GO" (CSV + summary still written for triage)
  2 — preconditions not met (missing API key / DB, insufficient reviewed
      corpus, prior output exists)

Resume
------

``--resume`` skips filings whose ``(corpus, filing_url)`` pair already
appears in ``phase2_quantitative_<run_id>.partial.csv``. Rows are written
per-filing before moving to the next; the partial CSV is renamed to the
main CSV on completion.

Cost guard
----------

Before starting API calls, the script estimates cost based on filing count ×
average cost per filing. If the estimate exceeds ``--cost-budget``, the
``--i-accept-cost`` flag is required to proceed.

Gold-negative caveat
--------------------

Gold "negatives" — pairs absent from ``golden_set_*.csv`` — are weakly-true
negatives. Gold is incomplete by construction; per-metric precision against
gold is biased high. Recall is the trustworthy signal.
"""

from __future__ import annotations

import argparse
import csv
import inspect
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_CSV = REPO_ROOT / "data" / "gold_standard" / "golden_set_260408.csv"
SPLIT_FILE = REPO_ROOT / "data" / "gold_standard" / "split_v1.json"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "eval"

# Minimum filings in a coverage bucket before the per-metric gate fires.
MIN_FILINGS_FOR_METRIC_GATE = 5

# Hard gate thresholds.
RECALL_DELTA_TOLERANCE = 0.05  # C2: per-metric may be up to 5pt below keyword
AGGREGATE_RECALL_IMPROVEMENT = 0.05  # C3: aggregate must be 5pt above keyword
MIN_F1_THRESHOLD = 0.40  # C4: no Tier-1 metric F1 below 0.40
MAX_ERROR_RATE = 0.005  # C5: ≤ 0.5% of classify_segment calls may error

# Cost estimation: ~$0.25 per filing (Haiku, includes prompt-cache amortised).
# Real cost varies by filing length; this is a conservative planning estimate.
_COST_PER_FILING_USD = 0.25

logger = logging.getLogger("run_phase2_quantitative_eval")

# ---------------------------------------------------------------------------
# Import Phase-1 helpers via sys.path (avoids forking the shared logic)
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Lazy import — only called when the helpers are first needed.
_p1: Any = None


def _phase1() -> Any:
    """Return the run_phase1_eval module (loaded once on first call)."""
    global _p1
    if _p1 is None:
        import importlib.util

        mod_name = "run_phase1_eval"
        if mod_name in sys.modules:
            _p1 = sys.modules[mod_name]
        else:
            spec = importlib.util.spec_from_file_location(
                mod_name, _SCRIPTS_DIR / "run_phase1_eval.py"
            )
            assert spec is not None and spec.loader is not None
            import importlib

            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            _p1 = mod
    return _p1


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

CSV_FIELDS = (
    "run_id",
    "run_started_at",
    "run_finished_at",
    "corpus",
    "filing_url",
    "filing_id",
    "issuer_key",
    "metric_id",
    "ground_truth",
    "classifier_present",
    "classifier_score",
    "classifier_model",
    "classifier_sonnet_fallback",
    "keyword_present",
    "agreement",
    "classification",
    "prompt_version",
    "section_type",
    "notes",
)


@dataclass
class Phase2Row:
    run_id: str
    run_started_at: str
    run_finished_at: str
    corpus: str
    filing_url: str
    filing_id: int | None
    issuer_key: str
    metric_id: str
    ground_truth: bool | None
    classifier_present: bool | None
    classifier_score: float | None
    classifier_model: str | None
    classifier_sonnet_fallback: bool | None
    keyword_present: bool | None
    agreement: str  # "agree" | "disagree" | "n/a"
    classification: str  # "TP" | "FP" | "FN" | "TN" | "skipped"
    prompt_version: str | None
    section_type: str | None
    notes: str

    def as_dict(self) -> dict[str, Any]:
        def _b(v: bool | None) -> str:
            return "" if v is None else ("true" if v else "false")

        return {
            "run_id": self.run_id,
            "run_started_at": self.run_started_at,
            "run_finished_at": self.run_finished_at,
            "corpus": self.corpus,
            "filing_url": self.filing_url,
            "filing_id": self.filing_id if self.filing_id is not None else "",
            "issuer_key": self.issuer_key,
            "metric_id": self.metric_id,
            "ground_truth": _b(self.ground_truth),
            "classifier_present": _b(self.classifier_present),
            "classifier_score": (
                f"{self.classifier_score:.4f}" if self.classifier_score is not None else ""
            ),
            "classifier_model": self.classifier_model or "",
            "classifier_sonnet_fallback": _b(self.classifier_sonnet_fallback),
            "keyword_present": _b(self.keyword_present),
            "agreement": self.agreement,
            "classification": self.classification,
            "prompt_version": self.prompt_version or "",
            "section_type": self.section_type or "",
            "notes": self.notes,
        }


@dataclass
class CriterionResult:
    id: str
    description: str
    hard: bool
    passed: bool
    detail: str = ""
    value: float | None = None
    threshold: float | None = None


@dataclass
class Phase2Result:
    go_no_go: str  # "GO" | "NO-GO" | "DRY_RUN"
    criteria: list[CriterionResult] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tier-1 metric set
# ---------------------------------------------------------------------------


def _get_tier1_metrics() -> frozenset[str]:
    """Return the Tier-1 metric set from the canonical YAML config.

    Reads via ``src.shared.keyword_config.get_metric_tiers`` — the same
    path used by ``src.gold_standard.v2_validator.get_tier``. Do NOT
    re-list here; this is the authoritative source.
    """
    from src.shared.keyword_config import get_metric_tiers

    tiers = get_metric_tiers()
    return frozenset(mid for mid, t in tiers.items() if t == 1)


# ---------------------------------------------------------------------------
# Corpus selection (delegates to Phase-1 helpers)
# ---------------------------------------------------------------------------


def _select_all_gold_corpus(
    splits: Any,
    gold_metrics: dict[str, set[str]],
    metric_ids: list[str],
    *,
    limit: int | None,
) -> list[Any]:
    """Select ALL eligible gold filings (test + calibration), not just 5.

    For Phase 2 we want the full held-out slice, not the Phase-1 5-filing
    greedy sample. We bypass ``select_gold_corpus``'s coverage-greedy
    selection and instead take all eligible filings deterministically (sorted
    by URL) up to ``limit`` if set.
    """
    p1 = _phase1()
    eligible_urls = sorted(splits.test_urls | splits.calibration_urls)
    chosen = eligible_urls[:limit] if limit is not None else eligible_urls
    return [
        p1.FilingSelection(
            corpus="gold",
            filing_url=url,
            filing_id=None,
            issuer_key=splits.issuer_lookup.get(url, ""),
            company=splits.company_lookup.get(url),
        )
        for url in chosen
    ]


def _select_reviewed_corpus_phase2(
    db_url: str,
    *,
    exclude_urls: frozenset[str],
    min_reviewed: int,
    limit: int | None,
) -> tuple[list[Any], str | None]:
    """Select reviewed filings; return (filings, error_msg).

    Queries up to 200 candidates and deduplicates; fails if fewer than
    ``min_reviewed`` survive after deduplication against gold URLs.
    """
    p1 = _phase1()
    # Pull a larger pool so dedup doesn't under-deliver.
    large_limit = max(min_reviewed * 3, 200)
    filings = p1.select_reviewed_corpus(db_url, exclude_urls=exclude_urls, limit=large_limit)
    # select_reviewed_corpus already deduplicates by URL via exclude_urls.
    effective_limit = limit if limit is not None else None
    if effective_limit is not None:
        filings = filings[:effective_limit]
    else:
        filings = filings  # all of them
    if len(filings) < min_reviewed:
        return filings, (
            f"Reviewed corpus has only {len(filings)} eligible filings after "
            f"deduplication against gold; --min-reviewed is {min_reviewed}. "
            "Run `scripts/run_phase1_eval.py` first to confirm the DB has "
            "enough reviewed-filing coverage."
        )
    return filings, None


# ---------------------------------------------------------------------------
# Row construction (mirrors Phase-1's _classify_eval_row)
# ---------------------------------------------------------------------------


def _make_row(
    *,
    run_id: str,
    run_started_at: str,
    run_finished_at: str,
    filing: Any,
    metric_id: str,
    ground_truth: bool | None,
    aggregate: Any | None,
    keyword_present: bool | None,
) -> Phase2Row:
    classifier_present: bool | None = aggregate.present if aggregate else None
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
    return Phase2Row(
        run_id=run_id,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        corpus=filing.corpus,
        filing_url=filing.filing_url,
        filing_id=filing.filing_id,
        issuer_key=filing.issuer_key,
        metric_id=metric_id,
        ground_truth=ground_truth,
        classifier_present=classifier_present,
        classifier_score=aggregate.score if aggregate else None,
        classifier_model=aggregate.model if aggregate else None,
        classifier_sonnet_fallback=aggregate.sonnet_fallback if aggregate else None,
        keyword_present=keyword_present,
        agreement=agreement,
        classification=classification,
        prompt_version=aggregate.prompt_version if aggregate else None,
        section_type=aggregate.section_type if aggregate else None,
        notes="",
    )


# ---------------------------------------------------------------------------
# Per-metric P/R/F1 (operates on Phase2Row)
# ---------------------------------------------------------------------------


def per_metric_prf(
    rows: list[Phase2Row],
    corpus: str | None = None,
) -> dict[str, dict[str, float]]:
    """Compute per-metric precision/recall/F1 on ``rows``.

    If ``corpus`` is not None, only rows from that corpus are included.
    Rows with ``ground_truth is None`` are skipped (unknown label).
    """
    out: dict[str, dict[str, float]] = {}
    by_metric: dict[str, list[Phase2Row]] = {}
    for r in rows:
        if corpus is not None and r.corpus != corpus:
            continue
        if r.ground_truth is None:
            continue
        by_metric.setdefault(r.metric_id, []).append(r)
    for metric, mrows in by_metric.items():
        tp = sum(1 for r in mrows if r.ground_truth and r.classifier_present)
        fp = sum(1 for r in mrows if not r.ground_truth and r.classifier_present)
        fn = sum(1 for r in mrows if r.ground_truth and not r.classifier_present)
        n = len(mrows)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        kw_positives = [r for r in mrows if r.ground_truth and r.keyword_present is not None]
        kw_recall = (
            sum(1 for r in kw_positives if r.keyword_present) / len(kw_positives)
            if kw_positives
            else None
        )
        out[metric] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "n": n,
            "kw_recall": round(kw_recall, 4) if kw_recall is not None else None,
        }
    return out


# ---------------------------------------------------------------------------
# Pass/fail criteria evaluation
# ---------------------------------------------------------------------------


def evaluate_criteria(
    rows: list[Phase2Row],
    errors: list[dict[str, Any]],
    *,
    total_calls: int,
    cache_reads: int,
    total_cost_usd: float,
    cost_budget_usd: float,
) -> list[CriterionResult]:
    """Evaluate C1–C7 against the accumulated rows and cost metrics."""
    tier1 = _get_tier1_metrics()
    prf = per_metric_prf(rows)

    results: list[CriterionResult] = []

    # C1 — zero prompt/parse errors from classify_segment.
    prompt_errors = [
        e for e in errors if e.get("stage") == "classify_segment" and e.get("exception")
    ]
    c1 = CriterionResult(
        id="C1",
        description="Zero prompt/parse errors from classify_segment",
        hard=True,
        passed=len(prompt_errors) == 0,
        detail=f"{len(prompt_errors)} errors" if prompt_errors else "0 errors",
        value=float(len(prompt_errors)),
        threshold=0.0,
    )
    results.append(c1)

    # C2 — per-Tier-1-metric classifier recall ≥ keyword recall − 5pt.
    c2_breaches: list[str] = []
    c2_skipped: list[str] = []
    for mid in sorted(tier1):
        m = prf.get(mid)
        if m is None or m["n"] < MIN_FILINGS_FOR_METRIC_GATE:
            c2_skipped.append(mid)
            continue
        kw_r = m.get("kw_recall")
        if kw_r is None:
            c2_skipped.append(mid)
            continue
        clf_r = m["recall"]
        if clf_r < kw_r - RECALL_DELTA_TOLERANCE:
            c2_breaches.append(f"{mid}: clf={clf_r:.3f} kw={kw_r:.3f} delta={clf_r - kw_r:+.3f}")
    c2 = CriterionResult(
        id="C2",
        description=(
            f"Per-Tier-1-metric classifier recall ≥ kw recall − {RECALL_DELTA_TOLERANCE:.0%} "
            f"(≥{MIN_FILINGS_FOR_METRIC_GATE}-filing coverage)"
        ),
        hard=True,
        passed=len(c2_breaches) == 0,
        detail=(
            f"{len(c2_breaches)} breaches: {'; '.join(c2_breaches)}"
            if c2_breaches
            else f"0 breaches ({len(c2_skipped)} metrics skipped — insufficient coverage)"
        ),
    )
    results.append(c2)

    # C3 — aggregate Tier-1 classifier recall ≥ keyword recall + 5pt (weighted).
    tier1_rows = [r for r in rows if r.metric_id in tier1 and r.ground_truth is not None]
    clf_positives = [r for r in tier1_rows if r.ground_truth]
    kw_rows = [r for r in clf_positives if r.keyword_present is not None]
    agg_clf_recall: float | None = None
    agg_kw_recall: float | None = None
    if clf_positives:
        agg_clf_recall = sum(1 for r in clf_positives if r.classifier_present) / len(clf_positives)
    if kw_rows:
        agg_kw_recall = sum(1 for r in kw_rows if r.keyword_present) / len(kw_rows)
    c3_passed = False
    c3_detail = ""
    if agg_clf_recall is None or agg_kw_recall is None:
        c3_detail = "Insufficient data to compute aggregate Tier-1 recall"
        c3_passed = False
    else:
        delta = agg_clf_recall - agg_kw_recall
        c3_passed = delta >= AGGREGATE_RECALL_IMPROVEMENT
        c3_detail = (
            f"clf={agg_clf_recall:.3f} kw={agg_kw_recall:.3f} delta={delta:+.3f} "
            f"(required +{AGGREGATE_RECALL_IMPROVEMENT:.3f})"
        )
    c3 = CriterionResult(
        id="C3",
        description=(
            f"Aggregate Tier-1 classifier recall ≥ kw recall + {AGGREGATE_RECALL_IMPROVEMENT:.0%}"
        ),
        hard=True,
        passed=c3_passed,
        detail=c3_detail,
        value=agg_clf_recall,
        threshold=None,
    )
    results.append(c3)

    # C4 — no Tier-1 metric with classifier F1 < 0.40 (≥5-filing coverage).
    c4_breaches: list[str] = []
    c4_skipped: list[str] = []
    for mid in sorted(tier1):
        m = prf.get(mid)
        if m is None or m["n"] < MIN_FILINGS_FOR_METRIC_GATE:
            c4_skipped.append(mid)
            continue
        if m["f1"] < MIN_F1_THRESHOLD:
            c4_breaches.append(f"{mid}: F1={m['f1']:.3f}")
    c4 = CriterionResult(
        id="C4",
        description=(
            f"No Tier-1 metric with classifier F1 < {MIN_F1_THRESHOLD:.2f} "
            f"(≥{MIN_FILINGS_FOR_METRIC_GATE}-filing coverage)"
        ),
        hard=True,
        passed=len(c4_breaches) == 0,
        detail=(
            f"{len(c4_breaches)} breaches: {'; '.join(c4_breaches)}"
            if c4_breaches
            else f"0 breaches ({len(c4_skipped)} skipped)"
        ),
    )
    results.append(c4)

    # C5 — classifier error rate ≤ 0.5% of calls.
    error_rate = len(prompt_errors) / total_calls if total_calls > 0 else 0.0
    c5 = CriterionResult(
        id="C5",
        description=f"Classifier error rate ≤ {MAX_ERROR_RATE:.1%} of calls",
        hard=True,
        passed=error_rate <= MAX_ERROR_RATE,
        detail=f"{len(prompt_errors)}/{total_calls} calls errored = {error_rate:.3%}",
        value=round(error_rate, 6),
        threshold=MAX_ERROR_RATE,
    )
    results.append(c5)

    # C6 — cache hit rate ≥ 85% (informational).
    cache_rate = cache_reads / total_calls if total_calls > 0 else 0.0
    c6 = CriterionResult(
        id="C6",
        description="Cache hit rate ≥ 85% (informational)",
        hard=False,
        passed=cache_rate >= 0.85,
        detail=f"{cache_reads}/{total_calls} cached = {cache_rate:.1%}",
        value=round(cache_rate, 4),
        threshold=0.85,
    )
    results.append(c6)

    # C7 — total cost ≤ budget (informational).
    c7 = CriterionResult(
        id="C7",
        description=f"Total cost ≤ ${cost_budget_usd:.2f} (informational)",
        hard=False,
        passed=total_cost_usd <= cost_budget_usd,
        detail=f"${total_cost_usd:.4f} spent vs budget ${cost_budget_usd:.2f}",
        value=round(total_cost_usd, 4),
        threshold=cost_budget_usd,
    )
    results.append(c7)

    return results


# ---------------------------------------------------------------------------
# Coverage report (dry-run only)
# ---------------------------------------------------------------------------


def print_coverage_report(
    gold_filings: list[Any],
    reviewed_filings: list[Any],
    gold_labels: dict[tuple[str, str], bool],
    reviewed_labels: dict[tuple[int, str], bool | None],
    metric_ids: list[str],
) -> None:
    tier1 = _get_tier1_metrics()
    gold_urls = frozenset(f.filing_url for f in gold_filings)
    reviewed_ids = frozenset(f.filing_id for f in reviewed_filings if f.filing_id is not None)

    print("\n=== Phase-2 Quantitative Gate — Coverage Report (dry-run) ===")
    print(f"\nGold slice:     {len(gold_filings)} filings")
    print(f"Reviewed slice: {len(reviewed_filings)} filings")
    print(f"Total:          {len(gold_filings) + len(reviewed_filings)} filings")
    print(f"\nMetrics scored: {len(metric_ids)}")
    print(f"Tier-1 metrics: {len(tier1)}")
    print("\nPer-metric filing coverage (Tier-1 only):")
    col = max(len(m) for m in tier1) + 2
    print(f"  {'Metric':<{col}} {'Gold':>6}  {'Reviewed':>9}  {'Total':>6}  {'Gate?':>6}")
    print(f"  {'-' * col}  {'------':>6}  {'---------':>9}  {'------':>6}  {'------':>6}")
    for mid in sorted(tier1):
        g = sum(1 for url in gold_urls if gold_labels.get((url, mid)) is True)
        r = sum(1 for fid in reviewed_ids if reviewed_labels.get((fid, mid)) is True)
        total = g + r
        gate = "YES" if total >= MIN_FILINGS_FOR_METRIC_GATE else "NO"
        print(f"  {mid:<{col}} {g:>6}  {r:>9}  {total:>6}  {gate:>6}")
    print("")


# ---------------------------------------------------------------------------
# CSV streaming helpers
# ---------------------------------------------------------------------------


def _open_csv_writer(path: Path) -> tuple[Any, Any]:
    """Open a CSV file for streaming writes; return (file_handle, DictWriter)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("w", encoding="utf-8", newline="")
    writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
    writer.writeheader()
    return fh, writer


def _append_rows(writer: Any, rows: list[Phase2Row]) -> None:
    for r in rows:
        writer.writerow(r.as_dict())


def _write_summary(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Resume helpers
# ---------------------------------------------------------------------------


def _load_partial_done(partial_path: Path) -> frozenset[tuple[str, str]]:
    """Return set of (corpus, filing_url) pairs already processed."""
    if not partial_path.exists():
        return frozenset()
    done: set[tuple[str, str]] = set()
    with partial_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            corpus = row.get("corpus", "")
            url = row.get("filing_url", "")
            if corpus and url:
                done.add((corpus, url))
    return frozenset(done)


# ---------------------------------------------------------------------------
# Main eval orchestrator
# ---------------------------------------------------------------------------


def run_eval(
    *,
    run_id: str,
    out_dir: Path,
    min_reviewed: int,
    cost_budget_usd: float,
    limit: int | None,
    gold_only: bool,
    dry_run: bool,
    resume: bool,
    i_accept_cost: bool,
) -> tuple[int, dict[str, Any]]:
    """Execute the Phase-2 quantitative eval. Returns (exit_code, summary_dict).

    Never calls run_phase1_eval.main() — tests call run_eval() directly.
    """
    run_started_at = datetime.now(UTC).isoformat()
    p1 = _phase1()

    # ---- Pre-flight: API key ----
    db_url = os.environ.get("DATABASE_URL")
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not dry_run and not api_key:
        return 2, {
            "error": (
                "ANTHROPIC_API_KEY is required for live eval. "
                "Use --dry-run to exercise corpus/label/CSV plumbing without API calls."
            ),
            "run_started_at": run_started_at,
        }

    # ---- Pre-flight: DB required for reviewed corpus ----
    if not gold_only and not db_url:
        return 2, {
            "error": (
                "DATABASE_URL is required for the reviewed corpus (and for gold "
                "filings' html_storage_path resolution). Use --gold-only to skip "
                "the reviewed corpus."
            ),
            "run_started_at": run_started_at,
        }

    # DB is also required for gold when running live (html_storage_path lookup).
    if not dry_run and not db_url:
        return 2, {
            "error": (
                "DATABASE_URL is required for Path A (gold filings need DB for "
                "html_storage_path resolution)."
            ),
            "run_started_at": run_started_at,
        }

    # ---- Pre-flight: output collision guard ----
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"phase2_quantitative_{run_id}.csv"
    summary_path = out_dir / f"phase2_quantitative_{run_id}_summary.json"
    partial_path = out_dir / f"phase2_quantitative_{run_id}.partial.csv"

    if csv_path.exists() and not resume:
        return 2, {
            "error": (
                f"Output file already exists: {csv_path}. "
                "Use a different --run-id or --resume to continue a partial run."
            ),
            "run_started_at": run_started_at,
        }

    # ---- Load enrolled metric IDs (same source as Phase 1) ----
    import yaml

    recall_aug_file = REPO_ROOT / "config" / "llm_classifier" / "recall_augmentation.yaml"
    raw_aug = yaml.safe_load(recall_aug_file.read_text())
    metric_ids: list[str] = list(raw_aug.get("enrolled_metrics") or [])

    # ---- Load splits ----
    splits = p1._load_splits(SPLIT_FILE)

    # ---- Gold corpus: all eligible filings (test + calibration) ----
    gold_filings = _select_all_gold_corpus(
        splits,
        p1._gold_metrics_per_filing(GOLD_CSV, splits.test_urls | splits.calibration_urls),
        metric_ids,
        limit=limit,
    )

    # ---- Reviewed corpus ----
    reviewed_filings: list[Any] = []
    if not gold_only:
        gold_urls = frozenset(f.filing_url for f in gold_filings)
        reviewed_filings, rev_err = _select_reviewed_corpus_phase2(
            db_url,  # type: ignore[arg-type]
            exclude_urls=gold_urls,
            min_reviewed=min_reviewed,
            limit=limit,
        )
        if rev_err:
            return 2, {"error": rev_err, "run_started_at": run_started_at}

    all_filings = gold_filings + reviewed_filings

    # ---- Build labels ----
    gold_labels = p1.build_gold_labels(
        GOLD_CSV,
        frozenset(f.filing_url for f in gold_filings),
        metric_ids,
    )
    reviewed_filing_ids = [f.filing_id for f in reviewed_filings if f.filing_id is not None]
    reviewed_labels: dict[tuple[int, str], bool | None] = (
        p1.build_reviewed_labels(db_url, reviewed_filing_ids, metric_ids)
        if (reviewed_filing_ids and db_url)
        else {}
    )

    # ---- Dry-run early-out ----
    if dry_run:
        print_coverage_report(
            gold_filings, reviewed_filings, gold_labels, reviewed_labels, metric_ids
        )
        run_finished_at = datetime.now(UTC).isoformat()
        # Write header-only CSV and a skeleton summary.
        fh, _ = _open_csv_writer(csv_path)
        fh.close()
        summary: dict[str, Any] = {
            "run_id": run_id,
            "run_started_at": run_started_at,
            "run_finished_at": run_finished_at,
            "dry_run": True,
            "go_no_go": "DRY_RUN",
            "gold_only": gold_only,
            "selected_gold_filings": [f.filing_url for f in gold_filings],
            "selected_reviewed_filings": [
                {"filing_url": f.filing_url, "filing_id": f.filing_id, "company": f.company}
                for f in reviewed_filings
            ],
            "metric_ids": metric_ids,
            "per_metric": {"gold": {}, "reviewed": {}, "merged": {}},
            "criteria": [],
            "errors": [],
            "cost": {"total_usd": 0.0, "total_calls": 0, "cache_reads": 0},
        }
        _write_summary(summary, summary_path)
        return 0, summary

    # ---- Cost guard ----
    estimated_cost = len(all_filings) * _COST_PER_FILING_USD
    logger.info(
        "Estimated cost: $%.2f for %d filings (~$%.2f/filing). Budget: $%.2f.",
        estimated_cost,
        len(all_filings),
        _COST_PER_FILING_USD,
        cost_budget_usd,
    )
    if estimated_cost > cost_budget_usd and not i_accept_cost:
        return 2, {
            "error": (
                f"Estimated cost ${estimated_cost:.2f} exceeds --cost-budget "
                f"${cost_budget_usd:.2f}. Pass --i-accept-cost to proceed."
            ),
            "estimated_cost_usd": round(estimated_cost, 2),
            "run_started_at": run_started_at,
        }

    if limit is not None:
        logger.warning(
            "--limit %d is set: this is NOT a real gate run. Results are "
            "for wiring validation only.",
            limit,
        )
    if gold_only:
        logger.warning(
            "--gold-only is set: reviewed corpus skipped. Gate results are "
            "NOT authoritative without the reviewed corpus."
        )

    # ---- Warn about existing summary path collision ----
    if summary_path.exists():
        logger.warning("Summary path %s exists; it will be overwritten.", summary_path)

    # ---- Enrich filings for Path A ----
    try:
        enriched = p1._enrich_filings_for_path_a(all_filings, db_url)
    except RuntimeError as enrich_err:
        return 2, {"error": str(enrich_err), "run_started_at": run_started_at}

    # ---- Resume: skip already-done filings ----
    done_pairs: frozenset[tuple[str, str]] = frozenset()
    if resume and partial_path.exists():
        done_pairs = _load_partial_done(partial_path)
        logger.info(
            "--resume: skipping %d already-processed (corpus, filing_url) pairs.",
            len(done_pairs),
        )

    # If resuming and partial exists, append; otherwise start fresh.
    if resume and partial_path.exists():
        partial_fh = partial_path.open("a", encoding="utf-8", newline="")
        partial_writer = csv.DictWriter(partial_fh, fieldnames=CSV_FIELDS)
    else:
        partial_fh, partial_writer = _open_csv_writer(partial_path)

    rows: list[Phase2Row] = []
    errors: list[dict[str, Any]] = []
    total_calls = 0
    cache_reads = 0
    total_cost_usd = 0.0
    run_start_ts = time.monotonic()

    n_total = len(enriched)
    for idx, paf in enumerate(enriched, 1):
        corpus = paf.selection.corpus
        url = paf.selection.filing_url
        if (corpus, url) in done_pairs:
            logger.info(
                "Filing %d/%d: SKIPPED (already done) — %s %s",
                idx,
                n_total,
                corpus,
                paf.selection.company or url,
            )
            continue

        elapsed = time.monotonic() - run_start_ts
        filings_done = idx - 1
        if filings_done > 0 and elapsed > 0:
            rate = filings_done / elapsed
            remaining = n_total - filings_done
            eta_min = remaining / rate / 60.0
        else:
            eta_min = (n_total - idx) * _COST_PER_FILING_USD / 0.25 * 60  # rough
        logger.info(
            "Filing %d/%d: %s (%s), cumulative cost $%.4f, ETA ~%.0f min",
            idx,
            n_total,
            paf.selection.company or url,
            corpus,
            total_cost_usd,
            eta_min,
        )

        fil_t0 = time.monotonic()
        aggregates, kw_present, fil_errors = p1.evaluate_filing_pipeline(paf, metric_ids)
        fil_elapsed = time.monotonic() - fil_t0
        errors.extend(fil_errors)

        # Approximate cost from token counts if available (pipeline errors → 0).
        # The pipeline doesn't surface token counts directly via Path A; use
        # filing-count × average estimate for now.
        total_cost_usd += _COST_PER_FILING_USD

        filing_rows: list[Phase2Row] = []
        for metric in metric_ids:
            if corpus == "gold":
                gt = gold_labels.get((url, metric))
            else:
                fid = paf.filing_id
                gt = reviewed_labels.get((fid, metric))
            row = _make_row(
                run_id=run_id,
                run_started_at=run_started_at,
                run_finished_at="",  # filled below on completion
                filing=paf.selection,
                metric_id=metric,
                ground_truth=gt,
                aggregate=aggregates.get(metric),
                keyword_present=kw_present.get(metric),
            )
            filing_rows.append(row)
            rows.append(row)

        _append_rows(partial_writer, filing_rows)
        partial_fh.flush()

        logger.debug(
            "Filing %d/%d complete in %.1fs: %d errors this filing",
            idx,
            n_total,
            fil_elapsed,
            len(fil_errors),
        )

    partial_fh.close()

    run_finished_at = datetime.now(UTC).isoformat()
    for r in rows:
        r.run_finished_at = run_finished_at

    # If resuming, also load prior rows so scoring covers the full corpus.
    if resume and done_pairs:
        # Re-read the partial file to pick up the rows from the previous run.
        prior_rows: list[Phase2Row] = []
        with partial_path.open(encoding="utf-8") as pf:
            reader = csv.DictReader(pf)
            for raw in reader:

                def _parse_bool(s: str) -> bool | None:
                    if s == "true":
                        return True
                    if s == "false":
                        return False
                    return None

                prior_rows.append(
                    Phase2Row(
                        run_id=raw.get("run_id", ""),
                        run_started_at=raw.get("run_started_at", ""),
                        run_finished_at=raw.get("run_finished_at", ""),
                        corpus=raw.get("corpus", ""),
                        filing_url=raw.get("filing_url", ""),
                        filing_id=int(raw["filing_id"]) if raw.get("filing_id") else None,
                        issuer_key=raw.get("issuer_key", ""),
                        metric_id=raw.get("metric_id", ""),
                        ground_truth=_parse_bool(raw.get("ground_truth", "")),
                        classifier_present=_parse_bool(raw.get("classifier_present", "")),
                        classifier_score=float(raw["classifier_score"])
                        if raw.get("classifier_score")
                        else None,
                        classifier_model=raw.get("classifier_model") or None,
                        classifier_sonnet_fallback=_parse_bool(
                            raw.get("classifier_sonnet_fallback", "")
                        ),
                        keyword_present=_parse_bool(raw.get("keyword_present", "")),
                        agreement=raw.get("agreement", "n/a"),
                        classification=raw.get("classification", "skipped"),
                        prompt_version=raw.get("prompt_version") or None,
                        section_type=raw.get("section_type") or None,
                        notes=raw.get("notes", ""),
                    )
                )
        rows = prior_rows  # prior_rows includes both old and new

    # Rename partial → final.
    partial_path.rename(csv_path)

    # ---- Criteria evaluation ----
    criteria = evaluate_criteria(
        rows,
        errors,
        total_calls=total_calls if total_calls > 0 else len(rows),
        cache_reads=cache_reads,
        total_cost_usd=total_cost_usd,
        cost_budget_usd=cost_budget_usd,
    )

    hard_failures = [c for c in criteria if c.hard and not c.passed]
    go_no_go = "GO" if not hard_failures else "NO-GO"

    # ---- Summary ----
    prf_gold = per_metric_prf(rows, "gold")
    prf_reviewed = per_metric_prf(rows, "reviewed")
    prf_merged = per_metric_prf(rows)

    summary = {
        "run_id": run_id,
        "run_started_at": run_started_at,
        "run_finished_at": run_finished_at,
        "dry_run": False,
        "go_no_go": go_no_go,
        "gold_only": gold_only,
        "limit": limit,
        "selected_gold_filings": [f.filing_url for f in gold_filings],
        "selected_reviewed_filings": [
            {"filing_url": f.filing_url, "filing_id": f.filing_id, "company": f.company}
            for f in reviewed_filings
        ],
        "metric_ids": metric_ids,
        "per_metric": {
            "gold": prf_gold,
            "reviewed": prf_reviewed,
            "merged": prf_merged,
        },
        "criteria": [
            {
                "id": c.id,
                "description": c.description,
                "hard": c.hard,
                "passed": c.passed,
                "detail": c.detail,
                "value": c.value,
                "threshold": c.threshold,
            }
            for c in criteria
        ],
        "cost": {
            "total_usd": round(total_cost_usd, 4),
            "total_calls": total_calls,
            "cache_reads": cache_reads,
            "budget_usd": cost_budget_usd,
        },
        "errors": errors,
        "gold_negative_caveat": (
            "Gold negatives are weakly-true negatives — gold-set absence "
            "does not mean labeled absent. Per-metric precision against "
            "gold is biased high by definition."
        ),
    }
    _write_summary(summary, summary_path)

    # Log criteria table.
    logger.info("=== Phase-2 Gate Results ===")
    for c in criteria:
        status = "PASS" if c.passed else "FAIL"
        kind = "HARD" if c.hard else "INFO"
        logger.info("  [%s][%s] %s: %s", status, kind, c.id, c.detail)
    logger.info("  go_no_go = %s", go_no_go)

    exit_code = 0 if go_no_go == "GO" else 1
    return exit_code, summary


# ---------------------------------------------------------------------------
# Drift-guard: verify Phase-1 helper signatures are what we expect
# ---------------------------------------------------------------------------

_EXPECTED_P1_SIGNATURES: dict[str, tuple[str, ...]] = {
    "evaluate_filing_pipeline": ("paf", "metric_ids"),
    "select_gold_corpus": ("splits", "gold_metrics", "required_metrics"),
    "select_reviewed_corpus": ("db_url",),
    "build_reviewed_labels": ("db_url", "filing_ids", "metric_ids"),
}


def assert_phase1_signature_parity() -> None:
    """Raise AssertionError if Phase-1 helper signatures drift from Phase-2 expectations.

    Called at module import time from tests (drift-guard pattern). Do NOT call
    during normal script execution — it loads Phase 1 on import, which is fine
    in tests but noisy for prod runs.
    """
    p1 = _phase1()
    for fn_name, expected_params in _EXPECTED_P1_SIGNATURES.items():
        fn = getattr(p1, fn_name, None)
        assert fn is not None, (
            f"run_phase1_eval.{fn_name} not found — Phase-1 helper was renamed or removed. "
            "Update run_phase2_quantitative_eval._EXPECTED_P1_SIGNATURES."
        )
        sig = inspect.signature(fn)
        actual_params = tuple(
            name
            for name, param in sig.parameters.items()
            if name not in ("self",)
            and param.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        )
        for expected in expected_params:
            assert expected in actual_params, (
                f"run_phase1_eval.{fn_name} is missing expected parameter {expected!r}. "
                f"Actual positional params: {actual_params}. "
                "Update _EXPECTED_P1_SIGNATURES or the call sites in run_phase2_quantitative_eval.py."
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_phase2_quantitative_eval",
        description=__doc__.split("\n\n")[0],
    )
    p.add_argument(
        "--min-reviewed",
        type=int,
        default=30,
        metavar="N",
        help="minimum eligible reviewed filings required (default 30); fail exit 2 if fewer",
    )
    p.add_argument(
        "--cost-budget",
        type=float,
        default=25.0,
        metavar="USD",
        help="cost budget in USD (default 25.0); informational gate C7",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="cap filings per corpus (warns: not a real gate run)",
    )
    p.add_argument(
        "--gold-only",
        action="store_true",
        help="skip reviewed corpus (warns: gate not authoritative)",
    )
    p.add_argument(
        "--run-id",
        default=None,
        help="override timestamp run_id (default: UTC YYYYMMDDTHHMM)",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"output directory (default {DEFAULT_OUT_DIR})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="build corpus + label tables, print coverage report, exit 0 without API calls",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="if <run_id>.partial.csv exists, skip already-processed (corpus, filing_url) pairs",
    )
    p.add_argument(
        "--i-accept-cost",
        action="store_true",
        help="required when estimated cost exceeds --cost-budget before starting API calls",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from src.infra.logging_config import configure_logging

    configure_logging(level="DEBUG" if args.verbose else "INFO")
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M")
    exit_code, summary = run_eval(
        run_id=run_id,
        out_dir=args.out_dir,
        min_reviewed=args.min_reviewed,
        cost_budget_usd=args.cost_budget,
        limit=args.limit,
        gold_only=args.gold_only,
        dry_run=args.dry_run,
        resume=args.resume,
        i_accept_cost=args.i_accept_cost,
    )
    if exit_code == 2:
        logger.error("Precondition failure: %s", summary.get("error", "<see output>"))
    elif exit_code == 1:
        logger.error("go_no_go = NO-GO. See criteria in summary JSON.")
    else:
        logger.info("go_no_go = GO. run_id=%s", run_id)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
