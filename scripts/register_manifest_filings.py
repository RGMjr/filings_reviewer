#!/usr/bin/env python3
"""
Register filings from filings_manifest.json into the database.

Reads data/fixtures/filings_manifest.json, fetches metadata from EDGAR for
each unregistered filing, and registers companies + filings in the database.
Already-registered filings (matched by accession number) are skipped.

Usage:
    python3 scripts/register_manifest_filings.py
    python3 scripts/register_manifest_filings.py --dry-run
    python3 scripts/register_manifest_filings.py --limit 10 --verbose
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.infra.sec_client import FilingMetadata, SECClient

logger = logging.getLogger(__name__)

EDGAR_BASE = "https://www.sec.gov"
SUBMISSIONS_BASE = "https://data.sec.gov/submissions"


def format_accession_dashed(accession_nodash: str) -> str:
    """Convert 18-digit no-dash accession to dashed format (10-2-6)."""
    return f"{accession_nodash[:10]}-{accession_nodash[10:12]}-{accession_nodash[12:]}"


def get_existing_accessions(db: DatabaseAdapter) -> set[str]:
    """Return set of accession numbers already in DB, normalized (no dashes)."""
    rows = db.query("SELECT REPLACE(accession_number, '-', '') AS acc FROM filings")
    return {row["acc"] for row in rows}


def load_manifest(manifest_path: Path) -> list[dict]:
    with open(manifest_path) as f:
        return json.load(f)


def get_filing_metadata(
    sec: SECClient, cik: str, accession_dashed: str
) -> FilingMetadata | None:
    """
    Look up filing metadata from EDGAR.

    Tries the recent submissions first. If not found, walks paginated
    submission files (for older filings not in 'recent').
    """
    # Fast path: recent submissions
    metadata = sec.get_filing_by_accession(cik, accession_dashed)
    if metadata is not None:
        return metadata

    # Slow path: paginated historical submissions
    cik_padded = cik.zfill(10)
    try:
        data = sec._make_request(f"{SUBMISSIONS_BASE}/CIK{cik_padded}.json")
    except Exception as e:
        logger.debug(f"Failed to fetch submissions for CIK {cik}: {e}")
        return None

    company_name = data.get("name", "")
    ticker = (data.get("tickers") or [None])[0]
    extra_files = data.get("filings", {}).get("files", [])

    for file_info in extra_files:
        try:
            page = sec._make_request(f"{SUBMISSIONS_BASE}/{file_info['name']}")
        except Exception:
            continue

        accession_numbers = page.get("accessionNumber", [])
        try:
            idx = accession_numbers.index(accession_dashed)
        except ValueError:
            continue

        # Found it in this page
        primary_docs = page.get("primaryDocument", [])
        accession_no_dashes = accession_dashed.replace("-", "")
        cik_int = str(int(cik))  # strip leading zeros for URL
        primary_doc_url = (
            f"{EDGAR_BASE}/Archives/edgar/data/{cik_int}/{accession_no_dashes}/"
            f"{primary_docs[idx]}"
        )
        txt_url = (
            f"{EDGAR_BASE}/cgi-bin/viewer?action=view&cik={cik}"
            f"&accession_number={accession_dashed}&xbrl_type=v"
        )

        return FilingMetadata(
            cik=cik,
            company_name=company_name,
            form_type=page.get("form", [])[idx],
            filing_date=page.get("filingDate", [])[idx],
            accession_number=accession_dashed,
            primary_doc_url=primary_doc_url,
            txt_url=txt_url,
            ticker=ticker,
        )

    logger.warning(f"Accession {accession_dashed} not found in any submissions page for CIK {cik}")
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register filings from manifest into the database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be registered without writing to the database",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of new filings to register",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each filing as it is processed",
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string (defaults to DATABASE_URL from .env)",
    )
    parser.add_argument(
        "--user-agent",
        default="CMASB Filings Analyzer rgmarkey@gmail.com",
        help="User agent for SEC EDGAR requests",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    load_dotenv()
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )

    manifest_path = (
        Path(__file__).parent.parent / "data" / "fixtures" / "filings_manifest.json"
    )
    if not manifest_path.exists():
        logger.error(f"Manifest not found: {manifest_path}")
        sys.exit(1)

    logger.info("=" * 70)
    logger.info("Register Manifest Filings")
    logger.info("=" * 70)
    logger.info(f"Manifest: {manifest_path}")
    logger.info(f"Database: {db_url}")
    logger.info(f"Dry run: {args.dry_run}")

    manifest = load_manifest(manifest_path)
    logger.info(f"Manifest entries: {len(manifest)}")

    db = DatabaseAdapter(db_url)
    existing = get_existing_accessions(db)
    logger.info(f"Already registered accessions: {len(existing)}")

    # Filter to unregistered entries
    to_register = [
        entry for entry in manifest if entry["accession_number"] not in existing
    ]
    n_unregistered = len(to_register)
    logger.info(f"New filings to register: {n_unregistered}")

    if args.limit is not None:
        to_register = to_register[: args.limit]
        logger.info(f"Applying --limit: will process {len(to_register)}")

    if not to_register:
        logger.info("Nothing to register. All manifest entries already in DB.")
        return

    sec = SECClient(user_agent=args.user_agent)

    registered = 0
    failed = 0

    for i, entry in enumerate(to_register, 1):
        cik = entry["cik"]
        accession_nodash = entry["accession_number"]
        accession_dashed = format_accession_dashed(accession_nodash)

        if args.verbose:
            logger.info(f"[{i}/{len(to_register)}] CIK={cik} accession={accession_dashed}")

        if args.dry_run:
            logger.info(
                f"  DRY RUN: would fetch EDGAR metadata for {cik} / {accession_dashed}"
            )
            registered += 1
            continue

        metadata = get_filing_metadata(sec, cik, accession_dashed)
        if metadata is None:
            logger.warning(
                f"  SKIP: EDGAR lookup failed for CIK={cik} acc={accession_dashed}"
            )
            failed += 1
            continue

        try:
            company_id = db.upsert_company(
                cik=metadata.cik,
                company_name=metadata.company_name,
                ticker=metadata.ticker,
            )
            filing_id = db.upsert_filing(
                company_id=company_id,
                cik=metadata.cik,
                accession_number=metadata.accession_number,
                form_type=metadata.form_type,
                filing_date=metadata.filing_date,
                sec_html_url=metadata.primary_doc_url,
                sec_txt_url=metadata.txt_url,
                is_in_scope_phase1=True,
                is_post_combination=False,
                is_spac=False,
                is_first_time_issuer=False,
                is_investment_vehicle=False,
                is_resource_extraction=False,
                processing_status="pending",
            )
            if args.verbose:
                logger.info(
                    f"  OK: {metadata.company_name} | {metadata.form_type} | "
                    f"{metadata.filing_date} → company_id={company_id} filing_id={filing_id}"
                )
            registered += 1
        except Exception as e:
            logger.error(f"  DB error for CIK={cik} acc={accession_dashed}: {e}")
            failed += 1

    logger.info("")
    logger.info("=" * 70)
    logger.info("Summary")
    logger.info("=" * 70)
    logger.info(f"  Already in DB (skipped): {len(manifest) - n_unregistered}")
    logger.info(f"  Registered:              {registered}")
    logger.info(f"  Failed:                  {failed}")
    if args.dry_run:
        logger.info("  (dry run — no changes written)")
    logger.info("")

    if failed > 0:
        logger.warning(f"{failed} filing(s) failed. Check logs above for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
