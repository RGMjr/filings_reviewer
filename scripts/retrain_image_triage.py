#!/usr/bin/env python3
"""
Monthly retrain wrapper for the image relevance triage model.

Orchestrates the two-step retrain pipeline:
  1. export_image_training_data.py  — regenerate training CSV from live DB
  2. train_image_relevance_model.py — retrain the gradient-boosted classifier

Usage:
    python3 scripts/retrain_image_triage.py
    python3 scripts/retrain_image_triage.py --database-url postgresql://...
    python3 scripts/retrain_image_triage.py --dry-run
    python3 scripts/retrain_image_triage.py --model-type gbt

Operator notes:
    - Run monthly after a batch of new human image review decisions have been
      collected. Both reviewer surfaces feed the export: v2_image_review_decisions
      (legacy, image-level relevant/not_relevant) and v2_image_metric_confirmations
      (per-metric A/R/C/Add/Skip, sql/47) aggregated to image-level.
    - Defaults to $TEST_DATABASE_URL (local Docker) so you must pass
      --database-url explicitly for production Neon (or set DATABASE_URL to the
      prod URL and pass --use-env-database-url).
    - When R2_BUCKET is set (prod / staging), the wrapper uploads the joblib
      + report + training CSV to ``models/image_relevance/<run_id>/...`` and
      writes a ``models/image_relevance/latest_run_id.txt`` pointer last; the
      loader (src/shared/image_features._load_model) reads the pointer on cold
      start. Local dev (R2_BUCKET unset) writes only to data/image_model/ as
      before. See .claude/rules/infrastructure.md#model-artifact-storage.
    - model_training_runs.model_path / report_path columns hold opaque storage
      keys post-gh-391 (e.g. ``models/image_relevance/<uuid>/relevance_model.joblib``),
      not absolute filesystem paths.
    - Single-writer to ``latest_run_id.txt`` is guaranteed for web-triggered
      retrains by the concurrency gate in api_unified.py. CLI users invoking
      this script directly bypass that gate; do not run two retrains against
      the same R2 bucket concurrently.
    - The trained artifact is also written to data/image_model/relevance_model.joblib
      locally as scratch (subprocess output target); when R2 is the source of
      truth the loader reads from R2, not from this file.
    - Set USE_LEARNED_TRIAGE=true in the environment to activate the model gate
      in the extraction pipeline.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.infra.logging_config import configure_logging

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
EXPORT_SCRIPT = ROOT / "scripts" / "export_image_training_data.py"
TRAIN_SCRIPT = ROOT / "scripts" / "train_image_relevance_model.py"
DEFAULT_CSV = ROOT / "data" / "image_model" / "training_data.csv"
DEFAULT_MODEL = ROOT / "data" / "image_model" / "relevance_model.joblib"
DEFAULT_REPORT = ROOT / "data" / "image_model" / "model_report.txt"


def _storage_keys_for_run(run_id: str) -> dict[str, str]:
    """Return per-run storage keys. Stable shape for both backends."""
    from src.infra.model_storage import model_key_for_run

    return {
        "model_key": model_key_for_run(run_id, "relevance_model.joblib"),
        "report_key": model_key_for_run(run_id, "model_report.txt"),
        "csv_key": model_key_for_run(run_id, "training_data.csv"),
    }


def _upload_artifacts(
    run_id: str,
    *,
    model_path: str,
    report_path: str,
    csv_path: str,
) -> dict[str, str]:
    """Upload the three artifacts and the latest_run_id pointer (pointer last).

    Returns the storage-key dict so the caller can write the per-run keys back
    to model_training_runs. Errors propagate so the orchestrator's try/except
    flips the run row to status='failed'. The pointer is uploaded last so a
    partial-upload failure leaves the previous pointer valid.
    """
    # Local import keeps the wrapper snappy on --dry-run / --help paths.
    from src.infra.model_storage import LATEST_POINTER_KEY, get_model_storage

    storage = get_model_storage()
    keys = _storage_keys_for_run(run_id)

    uploads: list[tuple[str, Path, str]] = [
        (keys["model_key"], Path(model_path), "application/octet-stream"),
        (keys["report_key"], Path(report_path), "text/plain"),
        (keys["csv_key"], Path(csv_path), "text/csv"),
    ]
    for key, path, content_type in uploads:
        # Trust read_bytes() to raise FileNotFoundError with a clear traceback
        # — pre-checking with path.exists() is TOCTOU and adds nothing.
        data = path.read_bytes()
        logger.info("Uploading %s -> %s (%d bytes)", path, key, len(data))
        storage.put_bytes(key, data, content_type=content_type)

    # Pointer last — a half-uploaded artifact set must not become "latest".
    logger.info("Updating %s -> %s", LATEST_POINTER_KEY, run_id)
    storage.put_bytes(LATEST_POINTER_KEY, run_id.encode("utf-8"), content_type="text/plain")

    return keys


def _run(cmd: list[str], *, dry_run: bool) -> None:
    """Log and optionally execute a subprocess command."""
    pretty = " ".join(str(c) for c in cmd)
    if dry_run:
        logger.info("[dry-run] would run: %s", pretty)
        return
    logger.info("Running: %s", pretty)
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        logger.error("Command failed (exit %d): %s", result.returncode, pretty)
        sys.exit(result.returncode)


def _count_training_rows(csv_path: str) -> tuple[int, int]:
    """Return (total_rows, positive_rows) for the export CSV.

    Positive = decision == 'relevant' (matches the export-script label
    convention at scripts/export_image_training_data.py:70).
    """
    if not Path(csv_path).exists():
        return 0, 0
    total = 0
    positive = 0
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            if row.get("decision") == "relevant":
                positive += 1
    return total, positive


def _update_run_status(
    database_url: str | None,
    run_id: str,
    *,
    status: str,
    error: str | None = None,
    num_training_rows: int | None = None,
    num_positive_rows: int | None = None,
    model_path: str | None = None,
    report_path: str | None = None,
) -> None:
    """Write status/metrics back to a model_training_runs row.

    Errors here are swallowed — the script's primary job is the retrain, and
    a DB write failure shouldn't mask the original outcome. Logs the failure
    so an operator can reconcile manually.
    """
    if not database_url:
        logger.warning("No database_url available; skipping run-id status update.")
        return
    try:
        # Local import keeps the CLI snappy when --run-id is unset.
        import psycopg  # type: ignore[import-untyped]

        with psycopg.connect(database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE model_training_runs
                   SET status            = %(status)s,
                       error             = %(error)s,
                       num_training_rows = %(num_training_rows)s,
                       num_positive_rows = %(num_positive_rows)s,
                       model_path        = %(model_path)s,
                       report_path       = %(report_path)s,
                       completed_at      = NOW()
                 WHERE id = %(run_id)s
                """,
                {
                    "run_id": run_id,
                    "status": status,
                    "error": error,
                    "num_training_rows": num_training_rows,
                    "num_positive_rows": num_positive_rows,
                    "model_path": model_path,
                    "report_path": report_path,
                },
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to update model_training_runs row %s: %s", run_id, exc)


def _finalize_run(args: argparse.Namespace) -> None:
    """Upload artifacts to storage, then write status='succeeded' + metrics.

    The DB row's model_path / report_path columns receive opaque storage keys
    (not local filesystem paths) — see .claude/rules/infrastructure.md#model-artifact-storage.
    Pointer write happens inside _upload_artifacts so a failure there raises
    before the DB row is finalized; the orchestrator's try/except then flips
    status='failed'.
    """
    if args.dry_run:
        # Dry-run produced no artifact; mark succeeded with zero rows so the row
        # doesn't sit forever, but skip path/metric fields.
        _update_run_status(args.database_url, args.run_id, status="succeeded")
        return
    total, positive = _count_training_rows(args.output_csv)
    keys = _upload_artifacts(
        args.run_id,
        model_path=args.output_model,
        report_path=args.output_report,
        csv_path=args.output_csv,
    )
    _update_run_status(
        args.database_url,
        args.run_id,
        status="succeeded",
        num_training_rows=total,
        num_positive_rows=positive,
        model_path=keys["model_key"],
        report_path=keys["report_key"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monthly retrain wrapper for the image relevance triage model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=os.environ.get("TEST_DATABASE_URL"),
        help=(
            "Database connection string for the export step. "
            "Defaults to $TEST_DATABASE_URL. Pass the Neon URL for production retrains."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log the commands that would run without executing them.",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default=str(DEFAULT_CSV),
        help=f"Path for the exported training CSV (default: {DEFAULT_CSV})",
    )
    parser.add_argument(
        "--output-model",
        type=str,
        default=str(DEFAULT_MODEL),
        help=f"Path for the saved model artifact (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--output-report",
        type=str,
        default=str(DEFAULT_REPORT),
        help=f"Path for the training report (default: {DEFAULT_REPORT})",
    )
    parser.add_argument(
        "--model-type",
        choices=["logistic", "gbt"],
        default="logistic",
        help="Model class to train (default: logistic). Use 'gbt' for gradient-boosted.",
    )
    parser.add_argument(
        "--source",
        choices=["sec", "pres", "all"],
        default="all",
        help="Which source to export for training data (default: all).",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help=(
            "Optional model_training_runs.id (UUID). When set, the script writes "
            "status/metrics/error back to that row on completion or failure. "
            "Used by the web-triggered retrain endpoint; CLI invocations should "
            "leave this unset."
        ),
    )
    args = parser.parse_args()

    configure_logging(level="INFO")

    if not args.database_url and args.source in ("sec", "all"):
        logger.error("No database URL available. Set $TEST_DATABASE_URL or pass --database-url.")
        sys.exit(1)

    # If a run-id was supplied, wrap the orchestration in try/except so a Python
    # exception flips the row to status='failed'. SIGKILL/OOM still leak (the
    # script never re-enters Python after the signal) — those need manual psql
    # cleanup; tracked in docs/known-issues/.
    if args.run_id:
        try:
            _orchestrate(args)
        except SystemExit as exc:
            # _run() calls sys.exit(rc) on subprocess failure — surface as failed.
            _update_run_status(
                args.database_url,
                args.run_id,
                status="failed",
                error=f"subprocess exited with code {exc.code}",
            )
            raise
        except Exception as exc:  # noqa: BLE001
            _update_run_status(
                args.database_url,
                args.run_id,
                status="failed",
                error=str(exc),
            )
            raise
        else:
            _finalize_run(args)
        return

    _orchestrate(args)


def _orchestrate(args: argparse.Namespace) -> None:
    """Run the export + train pipeline. Caller wraps in try/except for run-id mode."""

    # ------------------------------------------------------------------
    # Step 1: Export training data from live DB
    # ------------------------------------------------------------------
    logger.info("=== Step 1: Export training data ===")
    export_cmd: list[str] = [
        sys.executable,
        str(EXPORT_SCRIPT),
        "--output",
        args.output_csv,
        "--source",
        args.source,
    ]
    if args.database_url:
        export_cmd += ["--database-url", args.database_url]

    _run(export_cmd, dry_run=args.dry_run)

    if not args.dry_run and not Path(args.output_csv).exists():
        logger.error("Export step produced no output at %s — aborting.", args.output_csv)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 2: Retrain the model
    # ------------------------------------------------------------------
    logger.info("=== Step 2: Retrain model ===")
    train_cmd: list[str] = [
        sys.executable,
        str(TRAIN_SCRIPT),
        "--input",
        args.output_csv,
        "--output",
        args.output_model,
        "--report",
        args.output_report,
        "--model-type",
        args.model_type,
    ]
    _run(train_cmd, dry_run=args.dry_run)

    if args.dry_run:
        logger.info("Dry-run complete. No files were written.")
    else:
        logger.info(
            "Retrain complete. Model: %s  Report: %s",
            args.output_model,
            args.output_report,
        )
        logger.info(
            "Set USE_LEARNED_TRIAGE=true + LEARNED_TRIAGE_MIN=0.4 to activate the model gate."
        )


if __name__ == "__main__":
    main()
