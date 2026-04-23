#!/usr/bin/env python3
"""Vision benchmark harness.

Two modes:

  --build-corpus   Export a stratified manifest from v2_image_review_decisions.
                   Writes to tests/fixtures/image_benchmark/manifest.json.
                   DB-read-only; never mutates any rows.

  --provider       Run the chart/table extraction pipeline against each image
                   in the corpus manifest and produce a benchmark report.
                   Saves to data/image_benchmarks/baseline_<date>.json.

Usage examples::

    # Build / refresh the frozen corpus manifest (requires DB access)
    python3 scripts/benchmark_vision.py --build-corpus \\
        --database-url "$TEST_DATABASE_URL"

    # Run the benchmark against the current prod GPT-4o path (limit 10 for smoke)
    python3 scripts/benchmark_vision.py --provider current --limit 10 \\
        --database-url "$TEST_DATABASE_URL"

    # Full baseline run (writes to data/image_benchmarks/baseline_<date>.json)
    python3 scripts/benchmark_vision.py --provider current \\
        --database-url "$TEST_DATABASE_URL"

Scope boundaries
----------------
- Does NOT modify vision_client.py (Wave B2 territory).
- Does NOT re-persist facts for reviewed filings (respects reviewed-filing guard).
- DB writes: none.  All DB access is read-only.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
MANIFEST_PATH = REPO_ROOT / "tests" / "fixtures" / "image_benchmark" / "manifest.json"
BENCHMARK_OUTPUT_DIR = REPO_ROOT / "data" / "image_benchmarks"

# Stratification targets: minimum images per stratum.
# If the DB has fewer than MIN_PER_STRATUM for a given stratum, we take all.
MIN_PER_STRATUM = 5
MAX_PER_STRATUM = 30

# Tier-1 heavy subset: ensure at least this many tier-1 images in the corpus.
TIER1_TARGET = 40

# Hard-OCR subset: ensure at least this many hard-OCR images.
HARD_OCR_TARGET = 20

# ---- DB query -----------------------------------------------------------------

_CORPUS_QUERY = """
SELECT
    d.img_id::text                               AS img_id,
    f.accession_number                           AS filing_key,
    v.filename                                   AS filename,
    d.decision                                   AS decision,
    d.chart_type                                 AS chart_type,
    d.rejection_reason                           AS rejection_reason,
    d.reviewer_notes                             AS reviewer_notes,
    v.file_path                                  AS storage_key,
    f.accession_number                           AS accession_number,
    c.cik                                        AS cik,
    c.company_name                               AS company_name,
    v.relevance_score                            AS relevance_score
FROM v2_image_review_decisions d
JOIN v2_image_assets           v ON v.img_id = d.img_id
JOIN filings                   f ON v.doc_id = f.filing_id
JOIN companies                 c ON f.company_id = c.company_id
ORDER BY d.created_at
"""

_TIER1_FACTS_QUERY = """
SELECT
    ia.img_id::text  AS img_id,
    COUNT(*)         AS tier1_count
FROM v2_metric_facts mf
JOIN v2_image_assets ia ON ia.img_id = mf.image_asset_id
WHERE mf.metric_id IN (
    'cm_customer_retention_rate',
    'cm_net_revenue_retention',
    'cm_gross_revenue_retention',
    'cm_revenue_by_cohort',
    'cm_transactions_by_cohort',
    'cm_balance_by_cohort',
    'cm_gross_margin_by_cohort',
    'cm_revenue_concentration',
    'cm_lifetime_value_per_customer',
    'cm_customer_acquisition_cost',
    'cm_ltv_to_cac_ratio',
    'cm_ltv_to_cac_ratio_by_cohort',
    'cm_large_customers_period_end',
    'cm_new_customers_acquired',
    'cm_customers_period_end_by_tenure'
)
GROUP BY ia.img_id
"""


# ---- Stratification -----------------------------------------------------------

from src.gold_standard.image_eval import (  # noqa: E402 — after sys.path hack above
    is_hard_ocr_image,
    is_tier1_image,
    stratum_label,
)


def _stratify_corpus(
    rows: list[dict[str, Any]],
    tier1_facts: dict[str, int],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Build a stratified corpus from DB rows.

    Strategy:
    1. Bin rows by stratum label.
    2. From each stratum take MIN_PER_STRATUM..MAX_PER_STRATUM rows (random sample).
    3. Top-up tier-1 images to TIER1_TARGET.
    4. Top-up hard-OCR images to HARD_OCR_TARGET.
    5. Annotate each entry with tier/subset flags.
    """
    # Build stratum buckets
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = stratum_label(row["decision"], row.get("chart_type"), row.get("rejection_reason"))
        buckets.setdefault(label, []).append(row)

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    # Phase 1: per-stratum sampling
    for _label, bucket in sorted(buckets.items()):
        rng.shuffle(bucket)
        take = min(MAX_PER_STRATUM, max(MIN_PER_STRATUM, len(bucket)))
        for row in bucket[:take]:
            if row["img_id"] not in selected_ids:
                selected_ids.add(row["img_id"])
                selected.append(row)

    # Phase 2: top-up tier-1 heavy subset
    tier1_selected = sum(1 for r in selected if is_tier1_image(r.get("chart_type")))
    if tier1_selected < TIER1_TARGET:
        tier1_candidates = [
            r
            for r in rows
            if r["img_id"] not in selected_ids and is_tier1_image(r.get("chart_type"))
        ]
        rng.shuffle(tier1_candidates)
        for row in tier1_candidates[: TIER1_TARGET - tier1_selected]:
            selected_ids.add(row["img_id"])
            selected.append(row)

    # Phase 3: top-up hard-OCR subset
    hard_ocr_selected = sum(1 for r in selected if is_hard_ocr_image(r.get("chart_type")))
    if hard_ocr_selected < HARD_OCR_TARGET:
        hard_ocr_candidates = [
            r
            for r in rows
            if r["img_id"] not in selected_ids and is_hard_ocr_image(r.get("chart_type"))
        ]
        rng.shuffle(hard_ocr_candidates)
        for row in hard_ocr_candidates[: HARD_OCR_TARGET - hard_ocr_selected]:
            selected_ids.add(row["img_id"])
            selected.append(row)

    # Annotate
    result = []
    for row in selected:
        entry: dict[str, Any] = {
            "img_id": row["img_id"],
            "filing_key": row["filing_key"],
            "filename": row["filename"],
            "decision": row["decision"],
            "chart_type": row.get("chart_type"),
            "rejection_reason": row.get("rejection_reason"),
            "reviewer_notes": row.get("reviewer_notes") or "",
            "storage_key": row["storage_key"],
            "company_name": row.get("company_name", ""),
            "cik": row.get("cik", ""),
            "relevance_score": row.get("relevance_score"),
            "stratum": stratum_label(
                row["decision"], row.get("chart_type"), row.get("rejection_reason")
            ),
            "is_tier1": is_tier1_image(row.get("chart_type")),
            "is_hard_ocr": is_hard_ocr_image(row.get("chart_type")),
            "tier1_facts_in_db": tier1_facts.get(row["img_id"], 0),
        }
        result.append(entry)

    return result


def _stratum_table(corpus: list[dict[str, Any]]) -> str:
    """Format a text table showing corpus size per stratum."""
    counts: dict[str, int] = {}
    for entry in corpus:
        counts[entry["stratum"]] = counts.get(entry["stratum"], 0) + 1
    lines = [f"{'Stratum':<35} {'Count':>6}"]
    lines.append("-" * 42)
    for stratum in sorted(counts):
        lines.append(f"{stratum:<35} {counts[stratum]:>6}")
    lines.append("-" * 42)
    lines.append(f"{'TOTAL':<35} {sum(counts.values()):>6}")
    tier1_count = sum(1 for e in corpus if e.get("is_tier1"))
    hard_ocr_count = sum(1 for e in corpus if e.get("is_hard_ocr"))
    lines.append(f"\n  Tier-1 images   : {tier1_count}")
    lines.append(f"  Hard-OCR images : {hard_ocr_count}")
    return "\n".join(lines)


# ---- Benchmark runner ---------------------------------------------------------


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    """Load corpus entries from manifest JSON."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    corpus: list[dict[str, Any]] = data.get("corpus", [])
    if not corpus:
        raise ValueError(f"Corpus in {path} is empty.  Run with --build-corpus first.")
    return corpus


def _run_current_provider(
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Run the current production extraction path against one corpus image.

    Returns a dict with benchmark fields compatible with ImageRunRecord.
    Does NOT re-persist any facts (read-only).

    Production path: VisionClient (GPT-4o) -> analyze_image_for_text
    We call analyze_image_for_text rather than the full OCR stage because:
    - We cannot safely call the full pipeline without risking persistence.
    - analyze_image_for_text returns contains_chart and chart_hint, which
      is sufficient to measure chart detection P/R.
    """
    from src.infra.image_storage import get_image_storage
    from src.llm.vision_client import VisionClient

    storage = get_image_storage()
    storage_key = entry.get("storage_key", "")

    t0 = time.perf_counter()
    try:
        image_bytes = storage.get_bytes(storage_key)
    except FileNotFoundError:
        logger.warning("Image not found in storage: %s (img_id=%s)", storage_key, entry["img_id"])
        return {
            "img_id": entry["img_id"],
            "predicted_relevant": False,
            "predicted_chart_type": None,
            "parse_failed": False,
            "cost_usd": 0.0,
            "latency_ms": 0,
            "raw_output": "",
            "title_extracted": "",
            "legend_extracted": "",
            "ocr_cells_extracted": [],
            "axis_labels_extracted": [],
            "tier1_facts_extracted": 0,
            "skipped": True,
            "skip_reason": "missing_bytes",
        }

    client = VisionClient()
    try:
        result = client.analyze_image_for_text(image_bytes)
    except Exception as exc:
        logger.warning("Vision API error for img_id=%s: %s", entry["img_id"], exc)
        return {
            "img_id": entry["img_id"],
            "predicted_relevant": False,
            "predicted_chart_type": None,
            "parse_failed": True,
            "cost_usd": 0.0,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "raw_output": str(exc),
            "title_extracted": "",
            "legend_extracted": "",
            "ocr_cells_extracted": [],
            "axis_labels_extracted": [],
            "tier1_facts_extracted": 0,
            "skipped": False,
            "skip_reason": None,
        }

    latency_ms = int((time.perf_counter() - t0) * 1000)

    return {
        "img_id": entry["img_id"],
        "predicted_relevant": result.contains_chart,
        "predicted_chart_type": result.chart_hint if result.contains_chart else None,
        "parse_failed": False,
        "cost_usd": result.cost_usd,
        "latency_ms": latency_ms,
        "raw_output": result.raw_response,
        "title_extracted": "",
        "legend_extracted": "",
        "ocr_cells_extracted": [],
        "axis_labels_extracted": [],
        "tier1_facts_extracted": 0,
        "skipped": False,
        "skip_reason": None,
    }


def _run_benchmark(
    corpus: list[dict[str, Any]],
    provider: str,
    limit: int | None,
) -> list[dict[str, Any]]:
    """Run the benchmark harness against the corpus and return raw run records."""
    if limit is not None:
        corpus = corpus[:limit]

    run_records = []
    n = len(corpus)
    for i, entry in enumerate(corpus):
        logger.info(
            "  [%d/%d] img_id=%s  stratum=%s", i + 1, n, entry["img_id"], entry.get("stratum", "?")
        )

        if provider == "current":
            result = _run_current_provider(entry)
        else:
            raise NotImplementedError(f"Provider {provider!r} not yet implemented (Wave B2).")

        result["reviewer_decision"] = entry["decision"]
        result["reviewer_chart_type"] = entry.get("chart_type")
        result["reviewer_notes"] = entry.get("reviewer_notes", "")
        result["tier1_facts_in_db"] = entry.get("tier1_facts_in_db", 0)
        result["stratum"] = entry.get("stratum", "unknown")
        result["is_tier1"] = entry.get("is_tier1", False)
        result["provider"] = provider
        run_records.append(result)

    return run_records


def _build_eval_results(run_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert raw run records to ImageRunRecord objects and aggregate metrics."""
    from src.gold_standard.image_eval import ImageRunRecord, aggregate_results

    records = []
    for r in run_records:
        if r.get("skipped"):
            continue
        records.append(
            ImageRunRecord(
                img_id=r["img_id"],
                reviewer_decision=r["reviewer_decision"],
                reviewer_chart_type=r.get("reviewer_chart_type"),
                reviewer_notes=r.get("reviewer_notes", ""),
                tier1_facts_in_db=r.get("tier1_facts_in_db", 0),
                predicted_chart_type=r.get("predicted_chart_type"),
                predicted_relevant=bool(r.get("predicted_relevant", False)),
                ocr_cells_extracted=r.get("ocr_cells_extracted", []),
                ocr_cells_reference=[],
                axis_labels_extracted=r.get("axis_labels_extracted", []),
                axis_labels_reference=[],
                title_extracted=r.get("title_extracted", ""),
                legend_extracted=r.get("legend_extracted", ""),
                tier1_facts_extracted=r.get("tier1_facts_extracted", 0),
                parse_failed=bool(r.get("parse_failed", False)),
                cost_usd=float(r.get("cost_usd", 0.0)),
                latency_ms=int(r.get("latency_ms", 0)),
                raw_output=r.get("raw_output", ""),
                provider=r.get("provider", "unknown"),
            )
        )

    agg = aggregate_results(records)
    return {
        "chart_detection_precision": agg.chart_detection_precision,
        "chart_detection_recall": agg.chart_detection_recall,
        "chart_detection_f1": agg.chart_detection_f1,
        "ocr_cell_accuracy": agg.ocr_cell_accuracy,
        "ocr_axis_label_accuracy": agg.ocr_axis_label_accuracy,
        "title_match_score": agg.title_match_score,
        "legend_match_score": agg.legend_match_score,
        "tier1_fact_recall": agg.tier1_fact_recall,
        "parse_failure_rate": agg.parse_failure_rate,
        "mean_cost_usd": agg.mean_cost_usd,
        "mean_latency_ms": agg.mean_latency_ms,
        "n_images": agg.n_images,
        "n_relevant": agg.n_relevant,
        "n_not_relevant": agg.n_not_relevant,
        "n_skipped": sum(1 for r in run_records if r.get("skipped")),
        "n_missing_bytes": sum(1 for r in run_records if r.get("skip_reason") == "missing_bytes"),
    }


# ---- CLI ---------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Vision benchmark harness — build corpus or run evaluations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build corpus manifest from DB
  python3 scripts/benchmark_vision.py --build-corpus \\
      --database-url "$TEST_DATABASE_URL"

  # Smoke test (10 images)
  python3 scripts/benchmark_vision.py --provider current --limit 10 \\
      --database-url "$TEST_DATABASE_URL"

  # Full baseline run
  python3 scripts/benchmark_vision.py --provider current \\
      --database-url "$TEST_DATABASE_URL"
        """,
    )
    parser.add_argument(
        "--build-corpus",
        action="store_true",
        help="Export a stratified corpus manifest from v2_image_review_decisions.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="current",
        choices=["current"],
        help="Vision provider to benchmark.  'current' = prod GPT-4o path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of corpus images evaluated (for smoke testing).",
    )
    parser.add_argument(
        "--manifest",
        type=str,
        default=str(MANIFEST_PATH),
        help="Path to the corpus manifest JSON (default: tests/fixtures/image_benchmark/manifest.json).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help=(
            "Path to write the benchmark report JSON.  "
            "Defaults to data/image_benchmarks/baseline_<date>.json."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for stratified sampling (default: 42).",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="PostgreSQL connection string (defaults to DATABASE_URL from .env).",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    args = _parse_args()

    db_url = (
        args.database_url or os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    )
    if not db_url:
        logger.error("No database URL found.  Pass --database-url or set TEST_DATABASE_URL.")
        sys.exit(1)

    from src.infra.db import DatabaseAdapter

    db = DatabaseAdapter(db_url)

    # ------------------------------------------------------------------ #
    # Mode 1: build corpus manifest
    # ------------------------------------------------------------------ #
    if args.build_corpus:
        logger.info("Querying v2_image_review_decisions for corpus...")
        rows = db.query(_CORPUS_QUERY, {})
        logger.info("  %d labeled images in DB", len(rows))

        # Fetch tier-1 fact counts per image
        logger.info("Fetching Tier-1 fact counts per image...")
        try:
            fact_rows = db.query(_TIER1_FACTS_QUERY, {})
            tier1_facts: dict[str, int] = {r["img_id"]: r["tier1_count"] for r in fact_rows}
        except Exception as exc:
            logger.warning("Could not fetch tier-1 fact counts: %s.  Defaulting to 0.", exc)
            tier1_facts = {}

        rng = random.Random(args.seed)
        corpus = _stratify_corpus(rows, tier1_facts, rng)

        logger.info("\nCorpus summary:\n%s", _stratum_table(corpus))

        manifest = {
            "_schema": "image_benchmark_manifest_v1",
            "_generated_by": "scripts/benchmark_vision.py --build-corpus",
            "_generated_date": date.today().isoformat(),
            "_seed": args.seed,
            "_total_labeled_in_db": len(rows),
            "corpus": corpus,
        }

        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, default=str)
        logger.info("Manifest written to %s  (%d entries)", manifest_path, len(corpus))
        return

    # ------------------------------------------------------------------ #
    # Mode 2: run benchmark
    # ------------------------------------------------------------------ #
    manifest_path = Path(args.manifest)
    logger.info("Loading corpus manifest from %s ...", manifest_path)
    corpus = _load_manifest(manifest_path)
    logger.info("  Corpus: %d images", len(corpus))

    if args.limit:
        logger.info("  Limiting to %d images (--limit)", args.limit)

    logger.info("Running benchmark with provider=%r ...", args.provider)
    run_records = _run_benchmark(corpus, args.provider, args.limit)

    logger.info("Computing metrics ...")
    eval_metrics = _build_eval_results(run_records)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        BENCHMARK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = BENCHMARK_OUTPUT_DIR / f"baseline_{date.today().isoformat()}.json"

    report = {
        "provider": args.provider,
        "run_date": date.today().isoformat(),
        "manifest_path": str(manifest_path),
        "limit": args.limit,
        "metrics": eval_metrics,
        "run_records": run_records,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    logger.info("\n=== Benchmark Results ===")
    m = eval_metrics
    logger.info(
        "  Chart detection  P=%.3f  R=%.3f  F1=%.3f",
        m["chart_detection_precision"],
        m["chart_detection_recall"],
        m["chart_detection_f1"],
    )
    logger.info("  OCR cell accuracy      : %.3f", m["ocr_cell_accuracy"])
    logger.info("  Tier-1 fact recall     : %.3f", m["tier1_fact_recall"])
    logger.info("  Parse failure rate     : %.3f", m["parse_failure_rate"])
    logger.info(
        "  Cost / image           : $%.5f  |  Latency: %dms",
        m["mean_cost_usd"],
        int(m["mean_latency_ms"]),
    )
    logger.info(
        "  Images: total=%d  relevant=%d  not_relevant=%d  skipped=%d",
        m["n_images"],
        m["n_relevant"],
        m["n_not_relevant"],
        m.get("n_skipped", 0),
    )
    logger.info("\nReport written to %s", output_path)


if __name__ == "__main__":
    main()
