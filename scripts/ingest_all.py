#!/usr/bin/env python3
"""
Unified batch ingestion wrapper — run transcripts and/or presentations.

Calls ingest_transcripts.py and ingest_presentations.py as subprocesses and
reports a combined summary.

Usage:
    # Run both (default)
    python3 scripts/ingest_all.py --tickers CRM ADBE --limit 3 --dry-run

    # Transcripts only
    python3 scripts/ingest_all.py --type transcript --tickers CRM --dry-run

    # Presentations only (write to DB)
    python3 scripts/ingest_all.py --type presentation --tickers ADBE --persist

    # With circuit breaker and resume
    python3 scripts/ingest_all.py --tickers CRM ADBE --max-failures 5 --resume

Environment variables:
    DATABASE_URL     PostgreSQL connection string (required for --persist)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"


# ---------------------------------------------------------------------------
# Summary parsing helpers
# ---------------------------------------------------------------------------


def _parse_ingested(output: str) -> int:
    """Extract 'Ingested: N' from script output."""
    m = re.search(r"Ingested:\s+(\d+)", output)
    return int(m.group(1)) if m else 0


def _parse_skipped(output: str) -> int:
    """Extract 'Skipped: N' from script output."""
    m = re.search(r"Skipped:\s+(\d+)", output)
    return int(m.group(1)) if m else 0


def _parse_errors(output: str) -> int:
    """Extract 'Errors: N' from script output."""
    m = re.search(r"Errors:\s+(\d+)", output)
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


def _run_script(
    script_name: str,
    extra_args: list[str],
    pass_tickers_as: str = "--tickers",
    tickers: list[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    persist: bool = False,
    max_failures: int | None = None,
    resume: bool = False,
) -> tuple[int, str]:
    """Run a child script, streaming output. Returns (returncode, combined_output)."""
    cmd: list[str] = [sys.executable, str(SCRIPTS_DIR / script_name)]

    if tickers:
        cmd += [pass_tickers_as] + tickers
    if limit is not None:
        cmd += ["--limit", str(limit)]
    if dry_run:
        cmd += ["--dry-run"]
    if persist:
        cmd += ["--persist"]
    if max_failures is not None:
        cmd += ["--max-failures", str(max_failures)]
    if resume:
        cmd += ["--resume"]
    cmd += extra_args

    print(f"\n{'=' * 70}")
    print(f"Running: {' '.join(cmd)}")
    print("=" * 70)

    proc = subprocess.run(cmd, capture_output=False, text=True)
    # We stream output live (capture_output=False), so return empty string
    return proc.returncode, ""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Unified ingestion wrapper for transcripts and presentations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--type",
        choices=["transcript", "presentation"],
        default=None,
        dest="ingest_type",
        help="Limit to one document type (default: both)",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        required=True,
        metavar="TICKER",
        help="One or more ticker symbols",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        metavar="N",
        help="Max documents per ticker per source (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline but do not write to the database",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Write results to the database (for presentations, overrides --dry-run)",
    )
    parser.add_argument(
        "--max-failures",
        type=int,
        default=None,
        metavar="N",
        help="Circuit breaker: abort after N consecutive failures",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip tickers already completed per their progress files",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    tickers = [t.upper() for t in args.tickers]
    results: dict[str, tuple[int, str]] = {}

    # Run transcripts
    if args.ingest_type in (None, "transcript"):
        rc, out = _run_script(
            "ingest_transcripts.py",
            extra_args=["--source", "huggingface"],
            pass_tickers_as="--tickers",
            tickers=tickers,
            limit=args.limit,
            dry_run=args.dry_run,
            max_failures=args.max_failures,
            resume=args.resume,
        )
        results["transcript"] = (rc, out)

    # Run presentations
    if args.ingest_type in (None, "presentation"):
        rc, out = _run_script(
            "ingest_presentations.py",
            extra_args=[],
            pass_tickers_as="--ticker",
            tickers=tickers,
            limit=args.limit,
            dry_run=not args.persist,
            persist=args.persist,
            max_failures=args.max_failures,
            resume=args.resume,
        )
        results["presentation"] = (rc, out)

    # Combined summary
    print(f"\n{'=' * 70}")
    print("COMBINED INGESTION SUMMARY")
    print("=" * 70)
    overall_rc = 0
    for dtype, (rc, _out) in results.items():
        status = "OK" if rc == 0 else f"FAILED (rc={rc})"
        print(f"  {dtype:<14}  {status}")
        if rc not in (0, 2):
            overall_rc = rc
        elif rc == 2:
            overall_rc = 2

    print()
    return overall_rc


if __name__ == "__main__":
    sys.exit(main())
