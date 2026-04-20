#!/usr/bin/env python3
"""
Ticker Onboarding CLI.

Surfaces un-ingested filings by document type, year, and industry (everyday
language → SIC codes) and drives them through the V2 pipeline end-to-end.

Subcommands:

    discover  Read-only: print candidate table (NEW + ALREADY EXTRACTED buckets)
    populate  Wraps UniverseBuilder.build_universe for a single year (idempotent)
    onboard   discover + FilingFetcher + V2Pipeline + persist

Usage:
    # Preview 2015 software S-1/F-1 registrations not yet extracted:
    python3 scripts/onboard_tickers.py discover \
        --industry software --year 2015 --form-type s1f1

    # Populate 2015 universe first (one-time per year; idempotent):
    python3 scripts/onboard_tickers.py populate --year 2015

    # Fetch + extract first 3 candidates:
    python3 scripts/onboard_tickers.py onboard \
        --industry software --year 2015 --form-type s1f1 --limit 3

    # Dry run:
    python3 scripts/onboard_tickers.py onboard \
        --industry software --year 2015 --form-type s1f1 --dry-run

Re-extraction guard: filings with a v2_documents row are skipped by default.
Pass --include-already-extracted to enter an interactive [a]ll / [y]es / [N]o /
[q]uit prompt per filing. Filings with human review decisions trigger a second
prompt before proceeding (purging decisions is irreversible — see
.claude/rules/v2-pipeline.md "Reviewed-Filing Guard").
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.extraction_v2.exceptions import ReviewedFilingError  # noqa: E402
from src.extraction_v2.persistence import V2PersistenceAdapter  # noqa: E402
from src.extraction_v2.pipeline import process_filing  # noqa: E402
from src.filing_fetcher.filing_fetcher import FilingFetcher  # noqa: E402
from src.infra.db import DatabaseAdapter  # noqa: E402
from src.infra.logging_config import configure_logging  # noqa: E402
from src.infra.sec_client import FilingMetadata, SECClient  # noqa: E402
from src.universe.onboarding import (  # noqa: E402
    FORM_TYPE_BUNDLES,
    Candidate,
    _build_discovery_sql,  # noqa: F401 — accessed by tests as cli._build_discovery_sql
    count_review_decisions,
    discover_candidates,
    load_industry_map,
    parse_year_arg,
    resolve_form_types,
    resolve_industry,
)
from src.universe.universe_builder import UniverseBuilder  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_YAML_PATH = PROJECT_ROOT / "config" / "industry_sic_codes.yaml"


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------


def _fmt_row(c: Candidate, extra_col: bool = False) -> str:
    ticker = c.ticker or "—"
    name = (c.company_name[:30]) if len(c.company_name) > 30 else c.company_name
    base = (
        f"  {c.filing_id:<9} {c.cik:<12} {ticker:<7} {name:<30} "
        f"{c.form_type:<8} {c.filing_date:<12}"
    )
    if extra_col:
        base += f" {c.extracted_at or '—':<20}"
    return base


def print_bucket(title: str, rows: list[Candidate], show_extracted_at: bool = False) -> None:
    if not rows:
        return
    header_cols = (
        "  filing_id cik          ticker  company_name                   form     filed       "
    )
    if show_extracted_at:
        header_cols += "extracted_at"
    print()
    print(f"  {title}")
    print(f"  {header_cols}")
    print("  " + "─" * (len(header_cols) - 2))
    for c in rows:
        print(_fmt_row(c, extra_col=show_extracted_at))


# ---------------------------------------------------------------------------
# Interactive guards
# ---------------------------------------------------------------------------


def prompt_already_extracted(
    extracted: list[Candidate],
    auto_yes: bool,
) -> dict[int, bool]:
    """Return {filing_id: should_reextract}. Defaults to False for every filing."""
    decisions: dict[int, bool] = {c.filing_id: False for c in extracted}
    if not extracted:
        return decisions
    if auto_yes:
        logger.warning(
            "--yes passed: auto-confirming re-extraction for %d already-extracted filings",
            len(extracted),
        )
        for c in extracted:
            decisions[c.filing_id] = True
        return decisions

    apply_all = False
    for c in extracted:
        if apply_all:
            decisions[c.filing_id] = True
            continue
        prompt = (
            f"\nFiling {c.filing_id} ({c.cik}, "
            f"{c.ticker or '—'}, {c.company_name}, {c.form_type}, {c.filing_date})"
            " is already extracted.\n"
            "Re-extract?  [a]ll remaining  [y]es this one  [N]o (default, skip)  [q]uit: "
        )
        ans = input(prompt).strip().lower()
        if ans == "q":
            logger.warning("Quit requested — aborting before any writes.")
            raise SystemExit(2)
        if ans == "a":
            apply_all = True
            decisions[c.filing_id] = True
        elif ans == "y":
            decisions[c.filing_id] = True
        else:
            decisions[c.filing_id] = False
    return decisions


def prompt_reviewed_filing(candidate: Candidate, decision_count: int, reviewer_count: int) -> bool:
    """Second guard: confirm purging review decisions before force-reextracting."""
    print()
    print(
        f"  WARNING: Filing {candidate.filing_id} ({candidate.company_name}) has "
        f"{decision_count} review decision(s) from {reviewer_count} reviewer(s)."
    )
    print("  Re-extracting will PURGE these decisions (no archive; recovery requires DB backup).")
    ans = input("  Purge and re-extract? [y/N]: ").strip().lower()
    return ans == "y"


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_discover(args: argparse.Namespace, db: DatabaseAdapter) -> int:
    industry_map = load_industry_map()
    canonical, sic_codes = resolve_industry(args.industry, industry_map)
    form_types = resolve_form_types(args.form_type)
    if getattr(args, "exclude_amendments", False):
        form_types = [ft for ft in form_types if not ft.endswith("/A")]
    year_min, year_max = parse_year_arg(args.year)

    print(f"Industry {canonical!r} resolved to SIC codes: {', '.join(sic_codes)}")
    print(f"Form types: {', '.join(form_types)}")
    print(f"Year range: {year_min}-{year_max}")

    candidates = discover_candidates(db, form_types, year_min, year_max, sic_codes)
    new = [c for c in candidates if not c.already_extracted]
    already = [c for c in candidates if c.already_extracted]

    print()
    print(
        f"Discovered {len(candidates)} filing(s): {len(new)} NEW, {len(already)} ALREADY EXTRACTED."
    )

    if args.limit and len(new) > args.limit:
        print(f"(Showing first --limit={args.limit} NEW rows; re-run without --limit to see all.)")
        new = new[: args.limit]

    print_bucket("NEW (not yet extracted):", new)
    print_bucket(
        "ALREADY EXTRACTED — default: SKIP on onboard:",
        already,
        show_extracted_at=True,
    )
    return 0


def cmd_populate(args: argparse.Namespace, db: DatabaseAdapter) -> int:
    if "-" in args.year:
        raise SystemExit("populate takes a single year (YYYY); use discover/onboard for ranges")
    year = int(args.year)
    form_types = resolve_form_types(args.form_type)
    sec_client = SECClient(user_agent=args.user_agent)
    builder = UniverseBuilder(sec_client=sec_client, db=db)
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    limit = getattr(args, "limit", None)
    logger.info(
        "Populating universe for %s to %s (form_types=%s, limit=%s) …",
        start,
        end,
        form_types,
        limit,
    )
    count = builder.build_universe(start, end, form_types=form_types, limit=limit)
    logger.info("Done. In-scope filings (Phase 1 only): %d", count)
    return 0


def cmd_onboard(args: argparse.Namespace, db: DatabaseAdapter) -> int:
    industry_map = load_industry_map()
    canonical, sic_codes = resolve_industry(args.industry, industry_map)
    form_types = resolve_form_types(args.form_type)
    if getattr(args, "exclude_amendments", False):
        form_types = [ft for ft in form_types if not ft.endswith("/A")]
    year_min, year_max = parse_year_arg(args.year)

    print(f"Industry {canonical!r} resolved to SIC codes: {', '.join(sic_codes)}")
    print(f"Form types: {', '.join(form_types)}")
    print(f"Year range: {year_min}-{year_max}")

    candidates = discover_candidates(db, form_types, year_min, year_max, sic_codes)
    new = [c for c in candidates if not c.already_extracted]
    already = [c for c in candidates if c.already_extracted]

    if args.limit and len(new) > args.limit:
        new = new[: args.limit]

    print_bucket("NEW (will onboard):", new)
    print_bucket(
        "ALREADY EXTRACTED — default: SKIP:",
        already,
        show_extracted_at=True,
    )

    # Guard A: already-extracted bucket
    reextract_decisions: dict[int, bool] = {c.filing_id: False for c in already}
    if args.include_already_extracted:
        reextract_decisions = prompt_already_extracted(already, auto_yes=args.yes)
    else:
        if already:
            print(
                f"\n(Skipping {len(already)} already-extracted filing(s). "
                "Pass --include-already-extracted to prompt for re-extraction.)"
            )

    # Build final execution list: all NEW + selected ALREADY-EXTRACTED
    to_process: list[tuple[Candidate, bool]] = [(c, False) for c in new]
    for c in already:
        if reextract_decisions.get(c.filing_id):
            to_process.append((c, True))

    if not to_process:
        print("\nNothing to onboard.")
        return 0

    print(f"\nReady to onboard {len(to_process)} filing(s).")
    if args.dry_run:
        print("DRY RUN — no fetch, no extract, no writes.")
        for c, force in to_process:
            tag = " (re-extract)" if force else ""
            print(f"  would process filing_id={c.filing_id} {c.company_name}{tag}")
        return 0

    sec_client = SECClient(user_agent=args.user_agent)
    fetcher = FilingFetcher(
        storage_root=args.storage_root,
        user_agent=args.user_agent,
        db=db,
        sec_client=sec_client,
    )
    persistence = V2PersistenceAdapter(db)

    succeeded = 0
    failed = 0
    skipped_reviewed = 0
    for c, force in to_process:
        # Guard B: reviewed-filing second prompt (only when force is about to be used)
        if force:
            dec_n, rev_n = count_review_decisions(db, c.filing_id)
            if dec_n > 0 and not prompt_reviewed_filing(c, dec_n, rev_n):
                logger.warning("Skipping filing_id=%d (reviewer-work guard declined)", c.filing_id)
                skipped_reviewed += 1
                continue

        md = FilingMetadata(
            cik=c.cik,
            company_name=c.company_name,
            form_type=c.form_type,
            filing_date=c.filing_date,
            accession_number=c.accession_number,
            primary_doc_url=c.primary_doc_url,
            txt_url=c.txt_url,
            ticker=c.ticker,
        )
        logger.info(
            "Fetching filing_id=%d cik=%s accession=%s …",
            c.filing_id,
            c.cik,
            c.accession_number,
        )
        content = fetcher.fetch_filing(md, fetch_txt=not args.skip_txt)
        if content is None or content.html_path is None:
            logger.error("Fetch failed for filing_id=%d", c.filing_id)
            failed += 1
            continue

        try:
            doc_date = date.fromisoformat(c.filing_date) if c.filing_date else None
            result = process_filing(
                html_path=content.html_path,
                filing_id=c.filing_id,
                cik=c.cik,
                accession_number=c.accession_number,
                document_date=doc_date,
            )
            persistence.persist_pipeline_result(
                result, c.filing_id, ticker=c.ticker, document_date=doc_date, force=force
            )
            succeeded += 1
            logger.info(
                "filing_id=%d: %d facts persisted (force=%s)",
                c.filing_id,
                result.fact_count,
                force,
            )
        except ReviewedFilingError as e:
            logger.error(
                "filing_id=%d blocked by ReviewedFilingError: %s "
                "(see .claude/rules/v2-pipeline.md)",
                c.filing_id,
                e,
            )
            failed += 1
        except Exception as e:  # noqa: BLE001
            logger.error("filing_id=%d failed: %s", c.filing_id, e, exc_info=True)
            failed += 1

    print(
        f"\nOnboard complete: succeeded={succeeded} failed={failed} "
        f"skipped_reviewed={skipped_reviewed}"
    )
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Ticker onboarding CLI (discover / populate / onboard).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--database-url", help="Override DATABASE_URL from .env")
    p.add_argument(
        "--user-agent",
        default=os.getenv("SEC_USER_AGENT", "CMASB Filings Analyzer rgmarkey@gmail.com"),
        help="User agent for SEC requests",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def _add_filter_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--industry", required=True, help="Industry name (e.g. 'software')")
        sp.add_argument(
            "--year",
            required=True,
            help="YYYY or YYYY-YYYY. Required to prevent unbounded onboards.",
        )
        sp.add_argument(
            "--form-type",
            default="s1f1",
            choices=sorted(FORM_TYPE_BUNDLES.keys()),
            help="Form-type bundle (default: s1f1)",
        )
        sp.add_argument("--limit", type=int, help="Cap on NEW filings processed/shown")
        sp.add_argument(
            "--exclude-amendments",
            action="store_true",
            help="Drop S-1/A and F-1/A from the form-type set (keep only original S-1 / F-1). "
            "Removes many shell filings that exist only as amendments.",
        )

    d = sub.add_parser("discover", help="Read-only: print candidate table")
    _add_filter_args(d)

    pop = sub.add_parser("populate", help="Run UniverseBuilder for a single year")
    pop.add_argument("--year", required=True, help="Single year YYYY")
    pop.add_argument(
        "--form-type",
        default="s1f1",
        choices=sorted(FORM_TYPE_BUNDLES.keys()),
        help="Form-type bundle to populate (default: s1f1). Use '10k' for 10-K/10-K/A filings.",
    )
    pop.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap on in-scope filings processed. Useful for test runs; a full "
        "year of 10-K filings is ~5-10k documents and ~15 minutes of SEC "
        "traffic without this brake.",
    )

    o = sub.add_parser("onboard", help="Fetch + extract NEW (and optionally re-extract)")
    _add_filter_args(o)
    o.add_argument(
        "--storage-root",
        default="data/filings",
        help="Root directory for filing storage (default: data/filings)",
    )
    o.add_argument("--dry-run", action="store_true", help="Print plan; no writes.")
    o.add_argument("--skip-txt", action="store_true", help="Skip TXT download.")
    o.add_argument(
        "--include-already-extracted",
        action="store_true",
        help="Include already-extracted filings in interactive prompt.",
    )
    o.add_argument(
        "--yes",
        action="store_true",
        help="Auto-confirm re-extraction for every already-extracted filing. "
        "Requires --include-already-extracted. Reviewed-filing prompt still fires.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "onboard" and args.yes and not args.include_already_extracted:
        parser.error("--yes requires --include-already-extracted")

    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        parser.error("DATABASE_URL not set (see .env)")
    db = DatabaseAdapter(db_url)

    if args.command == "discover":
        return cmd_discover(args, db)
    if args.command == "populate":
        return cmd_populate(args, db)
    if args.command == "onboard":
        return cmd_onboard(args, db)
    parser.error(f"Unknown command: {args.command}")
    return 1  # unreachable


if __name__ == "__main__":
    sys.exit(main())
