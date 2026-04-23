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
      collected in v2_image_review_decisions.
    - Defaults to $TEST_DATABASE_URL (local Docker) so you must pass
      --database-url explicitly for production Neon (or set DATABASE_URL to the
      prod URL and pass --use-env-database-url).
    - The trained artifact is written to data/image_model/relevance_model.joblib,
      which src/shared/image_features.predict_relevance() loads at runtime.
    - Set USE_LEARNED_TRIAGE=true in the environment to activate the model gate
      in the extraction pipeline.
"""

from __future__ import annotations

import argparse
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
    args = parser.parse_args()

    configure_logging(level="INFO")

    if not args.database_url and args.source in ("sec", "all"):
        logger.error("No database URL available. Set $TEST_DATABASE_URL or pass --database-url.")
        sys.exit(1)

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
