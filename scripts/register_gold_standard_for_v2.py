#!/usr/bin/env python3
"""
Register gold standard filings in the DB so batch_v2_extraction.py can process them.

For each company in data/gold_standard/ that has a metadata.json and filing.html,
this script:
  1. Upserts the company into `companies`
  2. Upserts the filing into `filings` with html_storage_path pointing to the local file
  3. Sets processing_status='fetched' so batch_v2_extraction picks it up

Safe to re-run — all operations are upserts.

Usage:
    python3 scripts/register_gold_standard_for_v2.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Gold standard companies to register (directory name → metadata overrides)
# Keys must match data/gold_standard/ directory names exactly.
GOLD_STANDARD_COMPANIES: dict[str, dict] = {
    "Chewy,_Inc_": {
        "company_name": "Chewy, Inc.",
        "form_type": "S-1/A",
        "filing_date": "2019-06-12",
        "period_end_date": "2019-02-03",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1766502/000119312519170917/",
    },
    "Datadog,_Inc_": {
        "company_name": "Datadog, Inc.",
        "form_type": "S-1",
        "filing_date": "2019-09-16",
        "period_end_date": "2018-12-31",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1561550/000119312519246194/",
    },
    "Farfetch_Limited": {
        "company_name": "Farfetch Limited",
        "form_type": "F-1",
        "filing_date": "2018-09-21",
        "period_end_date": "2017-12-31",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1740915/000119312518267302/",
    },
    "Flywire_Corp": {
        "company_name": "Flywire Corp",
        "form_type": "S-1",
        "filing_date": "2021-05-05",
        "period_end_date": "2020-12-31",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1580560/000119312526067540/",
    },
    "Gitlab_Inc_": {
        "company_name": "Gitlab Inc.",
        "form_type": "S-1",
        "filing_date": "2021-09-17",
        "period_end_date": "2021-01-31",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1653482/000162828021019971/",
    },
    "Kingsoft_Cloud_Holdings_Ltd": {
        "company_name": "Kingsoft Cloud Holdings Ltd",
        "form_type": "F-1",
        "filing_date": "2020-05-08",
        "period_end_date": "2019-12-31",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1795589/000119312520251765/",
    },
    "Maplebear_Inc_": {
        "company_name": "Maplebear Inc.",
        "form_type": "S-1",
        "filing_date": "2023-08-25",
        "period_end_date": "2022-12-31",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1579091/000119312523235646/",
    },
    "Robinhood_Markets,_Inc_": {
        "company_name": "Robinhood Markets, Inc.",
        "form_type": "S-1",
        "filing_date": "2021-07-01",
        "period_end_date": "2020-12-31",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1783879/000162828021019902/",
    },
    "Samsara_Inc_": {
        "company_name": "Samsara Inc.",
        "form_type": "S-1",
        "filing_date": "2021-11-16",
        "period_end_date": "2021-01-29",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1642896/000119312521348620/",
    },
    "Samsara_Vision_Inc_": {
        "company_name": "Samsara Vision Inc.",
        "form_type": "S-1",
        "filing_date": "2022-03-30",
        "period_end_date": "2021-12-31",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1824988/000110465922039859/",
    },
    "Slack_Technologies": {
        "company_name": "Slack Technologies",
        "form_type": "S-1",
        "filing_date": "2019-04-26",
        "period_end_date": "2019-01-31",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/",
    },
    "Snowflake_Inc": {
        "company_name": "Snowflake Inc",
        "form_type": "S-1",
        "filing_date": "2020-09-16",
        "period_end_date": "2020-01-31",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1640147/000162828020013518/",
    },
    "Tenable_Holdings,_Inc_": {
        "company_name": "Tenable Holdings, Inc.",
        "form_type": "S-1",
        "filing_date": "2018-07-26",
        "period_end_date": "2017-12-31",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1660280/000119312518224207/",
    },
    "Torrid_Holdings_Inc_": {
        "company_name": "Torrid Holdings Inc.",
        "form_type": "S-1",
        "filing_date": "2021-07-01",
        "period_end_date": "2021-01-30",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1792781/000119312521203834/",
    },
}


def register(dry_run: bool = False) -> None:
    import psycopg

    gs_dir = PROJECT_ROOT / "data" / "gold_standard"
    registered = []
    skipped = []

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")

    conn = psycopg.connect(db_url)

    for dir_name, overrides in GOLD_STANDARD_COMPANIES.items():
        company_dir = gs_dir / dir_name
        meta_path = company_dir / "metadata.json"
        html_path = company_dir / "filing.html"

        if not meta_path.exists():
            logger.warning(f"No metadata.json for {dir_name}, skipping")
            skipped.append(dir_name)
            continue
        if not html_path.exists():
            logger.warning(f"No filing.html for {dir_name}, skipping")
            skipped.append(dir_name)
            continue

        meta = json.loads(meta_path.read_text())
        cik = str(meta["cik"])
        accession = str(meta["accession_number"])
        company_name = overrides["company_name"]
        html_storage_path = str(html_path.resolve())

        logger.info(f"{'[DRY RUN] ' if dry_run else ''}Registering {company_name} (CIK={cik})")

        if dry_run:
            registered.append(dir_name)
            continue

        with conn.transaction():
            cur = conn.cursor()

            # Upsert company
            cur.execute(
                """
                INSERT INTO companies (cik, company_name)
                VALUES (%s, %s)
                ON CONFLICT (cik) DO UPDATE SET company_name = EXCLUDED.company_name
                RETURNING company_id
                """,
                (cik, company_name),
            )
            row = cur.fetchone()
            if row:
                company_id = row[0]
            else:
                cur.execute("SELECT company_id FROM companies WHERE cik = %s", (cik,))
                company_id = cur.fetchone()[0]

            # Upsert filing
            cur.execute(
                """
                INSERT INTO filings (
                    company_id, cik, accession_number, form_type, filing_date,
                    period_end_date, sec_html_url, is_in_scope_phase1,
                    processing_status, html_storage_path
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, true, 'fetched', %s)
                ON CONFLICT (company_id, accession_number) DO UPDATE SET
                    processing_status = 'fetched',
                    html_storage_path = EXCLUDED.html_storage_path
                RETURNING filing_id
                """,
                (
                    company_id, cik, accession,
                    overrides["form_type"], overrides["filing_date"],
                    overrides.get("period_end_date"),
                    overrides["sec_html_url"],
                    html_storage_path,
                ),
            )
            filing_id = cur.fetchone()[0]
            logger.info(f"  -> filing_id={filing_id}")
            registered.append(dir_name)

    conn.close()

    logger.info(f"\nRegistered: {len(registered)}, Skipped: {len(skipped)}")
    if registered:
        logger.info("Companies registered:")
        for name in registered:
            logger.info(f"  {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show what would be registered without writing to DB")
    args = parser.parse_args()
    register(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
