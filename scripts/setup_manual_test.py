#!/usr/bin/env python3
"""
Setup script for manual testing of the human review system.

This script:
1. Ensures database schema is ready
2. Loads test data for Farfetch and Samsara
3. Processes filings and generates review candidates
4. Starts the Flask application for manual testing

Usage:
    python3 scripts/setup_manual_test.py
"""

import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extraction.html_segmenter import HTMLSegmenter
from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging
from src.infra.sec_client import SECClient
from src.review.helpers import generate_candidates_for_filing

# Configure logging
configure_logging(level="INFO")
logger = logging.getLogger(__name__)

# Use real filings from data/filings directory
# (These will be auto-discovered, no hardcoded test companies)


class ManualTestSetup:
    """Orchestrates setup for manual testing."""

    def __init__(self, db_url: str):
        self.db = DatabaseAdapter(db_url)
        self.segmenter = HTMLSegmenter()
        self.data_dir = Path("data/filings")
        self.stats = {
            "companies_created": 0,
            "filings_processed": 0,
            "segments_created": 0,
            "candidates_generated": 0,
        }

    def run(self) -> bool:
        """Run full setup process."""
        try:
            logger.info("=" * 80)
            logger.info("MANUAL TEST SETUP - Starting")
            logger.info("=" * 80)

            # Step 1: Check database connection
            if not self._check_database():
                return False

            # Step 2: Ensure schema exists
            if not self._ensure_schema():
                return False

            # Step 3: Find and process real filing files
            self._process_real_filings()

            # Step 4: Generate candidates for existing filings
            self._process_existing_filings()

            # Step 5: Print summary
            self._print_summary()

            # Step 6: Start Flask
            self._start_flask()

            return True

        except Exception as e:
            logger.error(f"Setup failed: {e}", exc_info=True)
            return False

    def _check_database(self) -> bool:
        """Verify database connection."""
        logger.info("Checking database connection...")
        result = self.db.query("SELECT current_database(), version();")
        if result:
            db_name = result[0]["current_database"]
            logger.info(f"✓ Connected to database: {db_name}")
            return True
        else:
            logger.error("✗ Database connection failed")
            return False

    def _ensure_schema(self) -> bool:
        """Ensure review tables exist."""
        logger.info("Checking review tables...")

        # Check if review_candidates table exists (in public schema)
        result = self.db.query("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'review_candidates'
            );
        """)

        if result and result[0]["exists"]:
            logger.info("✓ Review tables exist")
            return True
        else:
            logger.warning("✗ Review tables not found")
            logger.info("Run: PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis < sql/07_create_review_schema.sql")
            return False

    def _process_real_filings(self) -> None:
        """Find and process real filing files from data/filings directory."""
        logger.info("\n--- Finding real filing files ---")

        # Priority CIKs to look for (no hardcoded names - will fetch from SEC)
        # Note: Company names are fetched from SEC EDGAR to ensure accuracy
        PRIORITY_CIKS = [
            "0001740915",  # Farfetch
            "0001764925",  # Slack
            "0001644378",  # Snap
            "0001640147",  # Snowflake (correct CIK)
            "0001261333",  # DocuSign (correct CIK)
        ]

        # Initialize SEC client for company name lookups
        sec_client = SECClient()

        # Look for priority company filings first
        filing_files = []
        for cik in PRIORITY_CIKS:
            cik_files = list(self.data_dir.glob(f"{cik}/*/primary.htm"))
            if cik_files:
                logger.info(f"✓ Found {len(cik_files)} filing(s) for CIK: {cik}")
                filing_files.extend(cik_files[:1])  # Take first filing per company

        # If we don't have enough priority filings, find any primary.htm files
        if len(filing_files) < 3:
            logger.info("Looking for additional filing files...")
            all_files = list(self.data_dir.glob("*/*/primary.htm"))
            # Filter out already-added priority files
            additional_files = [f for f in all_files if f not in filing_files]
            filing_files.extend(additional_files[:3 - len(filing_files)])

        if not filing_files:
            logger.warning("No filing files found in data/filings")
            logger.info("Looking for: data/filings/[CIK]/[accession]/primary.htm")
            return

        logger.info(f"\nProcessing {len(filing_files)} filing file(s)")

        for filing_path in filing_files:
            # Extract CIK and accession from path
            # Path format: data/filings/0001234567/000123456789012345/primary.htm
            cik = filing_path.parent.parent.name

            # Get company name from SEC EDGAR API (not hardcoded)
            company_name = self._get_company_name_from_sec(sec_client, cik)

            logger.info(f"\nProcessing: {company_name} (CIK: {cik})")

            # Ensure company exists (create minimal record with real name)
            company_id = self._ensure_company_from_cik(cik, company_name)
            if not company_id:
                logger.warning(f"Could not create company for CIK {cik}")
                continue

            # Process the filing
            self._process_filing(company_id, filing_path)

    def _get_company_name_from_sec(self, sec_client: SECClient, cik: str) -> str:
        """Fetch company name from SEC EDGAR API.

        This ensures we always use the official company name from SEC,
        preventing mismatches between CIK and company name.
        """
        try:
            company_info = sec_client.get_company_info(cik)
            if company_info and company_info.get("name"):
                return company_info["name"]
        except Exception as e:
            logger.warning(f"Could not fetch company name from SEC for CIK {cik}: {e}")

        # Fallback to generic name if SEC lookup fails
        return f"Company {cik}"

    def _ensure_company_from_cik(self, cik: str, company_name: str | None = None) -> int | None:
        """Ensure company exists, creating minimal record if needed."""
        # Check if exists
        result = self.db.query(
            "SELECT company_id FROM companies WHERE cik = %(cik)s;",
            {"cik": cik}
        )

        if result:
            company_id = result[0]["company_id"]
            logger.info(f"✓ Company exists (ID: {company_id})")
            return company_id

        # Create minimal company record with provided name or default
        name = company_name if company_name else f"Company {cik}"
        result = self.db.query("""
            INSERT INTO companies (cik, company_name)
            VALUES (%(cik)s, %(name)s)
            RETURNING company_id;
        """, {"cik": cik, "name": name})

        if result:
            company_id = result[0]["company_id"]
            logger.info(f"✓ Created company (ID: {company_id})")
            self.stats["companies_created"] += 1
            return company_id

        return None

    def _process_existing_filings(self) -> None:
        """Generate candidates for existing filings that don't have any."""
        logger.info("\n--- Processing existing filings ---")

        # Find filings with segments but no candidates
        result = self.db.query("""
            SELECT DISTINCT f.filing_id, f.company_id, c.company_name
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE EXISTS (
                SELECT 1 FROM source_segments ss WHERE ss.filing_id = f.filing_id
            )
            AND NOT EXISTS (
                SELECT 1 FROM review_candidates rc WHERE rc.filing_id = f.filing_id
            )
            LIMIT 5;
        """)

        if not result:
            logger.info("No filings need candidate generation")
            return

        logger.info(f"Found {len(result)} filing(s) needing candidates")

        for row in result:
            filing_id = row["filing_id"]
            company_name = row["company_name"]

            logger.info(f"Processing filing {filing_id} ({company_name})...")
            self._generate_candidates(filing_id)

    def _ensure_company(self, config: dict) -> int | None:
        """Ensure company exists in database."""
        cik = config["cik"]

        # Check if exists
        result = self.db.query(
            "SELECT company_id FROM companies WHERE cik = %(cik)s;",
            {"cik": cik}
        )

        if result:
            company_id = result[0]["company_id"]
            logger.info(f"✓ Company exists (ID: {company_id})")
            return company_id

        # Create company
        result = self.db.query("""
            INSERT INTO companies (cik, company_name, ticker)
            VALUES (%(cik)s, %(name)s, %(ticker)s)
            RETURNING company_id;
        """, {"cik": cik, "name": config["name"], "ticker": config.get("ticker")})

        if result:
            company_id = result[0]["company_id"]
            logger.info(f"✓ Created company (ID: {company_id})")
            self.stats["companies_created"] += 1
            return company_id

        return None

    def _find_filing_files(self, cik: str) -> list[Path]:
        """Find HTML filing files for a CIK."""
        cik_dir = self.data_dir / cik

        if not cik_dir.exists():
            return []

        # Find all HTML files in subdirectories
        filing_files = list(cik_dir.glob("*/*.html")) + list(cik_dir.glob("*.html"))

        logger.info(f"Found {len(filing_files)} filing file(s)")
        return filing_files

    def _process_filing(self, company_id: int, filing_path: Path) -> None:
        """Process a single filing file."""
        logger.info(f"Processing: {filing_path.name}")

        # Generate accession number from path
        accession = filing_path.parent.name.replace("-", "")
        if len(accession) < 18:
            accession = f"{accession:0>18}"

        # Step 1: Ensure filing exists
        filing_id = self._ensure_filing(company_id, accession, filing_path)
        if not filing_id:
            return

        # Step 2: Check if segments exist
        existing_segments = self.db.query(
            "SELECT COUNT(*) FROM source_segments WHERE filing_id = %(filing_id)s;",
            {"filing_id": filing_id}
        )

        if existing_segments and existing_segments[0]["count"] > 0:
            logger.info(f"✓ Filing already has {existing_segments[0]['count']} segments")
        else:
            # Step 3: Generate segments
            self._generate_segments(filing_id, filing_path)

        # Step 4: Generate review candidates
        self._generate_candidates(filing_id)

    def _ensure_filing(self, company_id: int, accession: str, filing_path: Path) -> int | None:
        """Ensure filing exists in database."""
        # Check if exists
        result = self.db.query(
            "SELECT filing_id FROM filings WHERE accession_number = %(accession)s;",
            {"accession": accession}
        )

        if result:
            filing_id = result[0]["filing_id"]
            logger.info(f"✓ Filing exists (ID: {filing_id})")
            return filing_id

        # Get CIK from company (required for filings table)
        company_result = self.db.query(
            "SELECT cik FROM companies WHERE company_id = %(company_id)s;",
            {"company_id": company_id}
        )

        if not company_result:
            logger.error(f"Company {company_id} not found")
            return None

        cik = company_result[0]["cik"]

        # Construct SEC EDGAR URL as directory (actual document will be resolved dynamically)
        # Remove leading zeros from CIK for URL (e.g., "0001928446" -> "1928446")
        # Note: Don't hardcode "primary.htm" - SEC uses different filenames per filing
        cik_for_url = cik.lstrip("0")
        sec_html_url = f"https://www.sec.gov/Archives/edgar/data/{cik_for_url}/{accession}/"

        # Create filing
        result = self.db.query("""
            INSERT INTO filings (company_id, cik, form_type, filing_date, accession_number, sec_html_url)
            VALUES (%(company_id)s, %(cik)s, %(form_type)s, CURRENT_DATE, %(accession)s, %(sec_html_url)s)
            RETURNING filing_id;
        """, {
            "company_id": company_id,
            "cik": cik,
            "form_type": "S-1",
            "accession": accession,
            "sec_html_url": sec_html_url
        })

        if result:
            filing_id = result[0]["filing_id"]
            logger.info(f"✓ Created filing (ID: {filing_id})")
            self.stats["filings_processed"] += 1
            return filing_id

        return None

    def _generate_segments(self, filing_id: int, filing_path: Path) -> None:
        """Generate source segments from HTML."""
        logger.info("Generating segments...")

        try:
            # Use HTMLSegmenter to parse the filing (it reads the file itself)
            segments = self.segmenter.segment_filing(filing_id, str(filing_path))
            logger.info(f"Generated {len(segments)} segments")

            if not segments:
                logger.warning("No segments generated from filing")
                return

            # Insert into database
            inserted = 0
            for i, seg in enumerate(segments):
                try:
                    self.db.execute("""
                        INSERT INTO source_segments (
                            filing_id, segment_type, section_path, section_heading,
                            raw_text, raw_html, sequence_index
                        )
                        VALUES (
                            %(filing_id)s, %(segment_type)s, %(section_path)s,
                            %(section_heading)s, %(raw_text)s, %(raw_html)s, %(sequence_index)s
                        );
                    """, {
                        "filing_id": seg.filing_id,
                        "segment_type": seg.segment_type,
                        "section_path": seg.section_path,
                        "section_heading": seg.section_heading,
                        "raw_text": seg.raw_text,
                        "raw_html": seg.raw_html,
                        "sequence_index": i,
                    })
                    inserted += 1
                except Exception as e:
                    logger.warning(f"Failed to insert segment {i}: {e}")
                    continue

            logger.info(f"✓ Inserted {inserted} segments into database")
            self.stats["segments_created"] += inserted

        except Exception as e:
            logger.error(f"Error generating segments: {e}", exc_info=True)

    def _generate_candidates(self, filing_id: int) -> None:
        """Generate review candidates for filing."""
        logger.info("Generating review candidates...")

        try:
            # Check if candidates already exist
            existing = self.db.query(
                "SELECT COUNT(*) FROM review_candidates WHERE filing_id = %(filing_id)s;",
                {"filing_id": filing_id}
            )

            if existing and existing[0]["count"] > 0:
                count = existing[0]["count"]
                logger.info(f"✓ Filing already has {count} candidates")
                return

            # Generate new candidates (save=True to persist to database)
            candidates = generate_candidates_for_filing(
                db=self.db,
                filing_id=filing_id,
                save=True,
            )

            if candidates:
                logger.info(f"✓ Generated and saved {len(candidates)} candidates")
                self.stats["candidates_generated"] += len(candidates)
            else:
                logger.warning("No candidates generated")

        except Exception as e:
            logger.error(f"Error generating candidates: {e}", exc_info=True)

    def _print_summary(self) -> None:
        """Print setup summary."""
        logger.info("\n" + "=" * 80)
        logger.info("SETUP COMPLETE - Summary")
        logger.info("=" * 80)

        # Database stats
        result = self.db.query("""
            SELECT
                (SELECT COUNT(*) FROM companies) as companies,
                (SELECT COUNT(*) FROM filings) as filings,
                (SELECT COUNT(*) FROM source_segments) as segments,
                (SELECT COUNT(*) FROM review_candidates) as candidates,
                (SELECT COUNT(*) FROM review_decisions) as decisions;
        """)

        if result:
            row = result[0]
            logger.info("\nDatabase totals:")
            logger.info(f"  Companies:  {row['companies']}")
            logger.info(f"  Filings:    {row['filings']}")
            logger.info(f"  Segments:   {row['segments']}")
            logger.info(f"  Candidates: {row['candidates']}")
            logger.info(f"  Decisions:  {row['decisions']}")

        logger.info("\nThis session:")
        logger.info(f"  Companies created:     {self.stats['companies_created']}")
        logger.info(f"  Filings processed:     {self.stats['filings_processed']}")
        logger.info(f"  Segments created:      {self.stats['segments_created']}")
        logger.info(f"  Candidates generated:  {self.stats['candidates_generated']}")

        # Candidates by filing
        result = self.db.query("""
            SELECT
                f.filing_id,
                c.company_name,
                COUNT(rc.candidate_id) as candidate_count,
                COUNT(rd.decision_id) as decision_count
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            LEFT JOIN review_candidates rc ON f.filing_id = rc.filing_id
            LEFT JOIN review_decisions rd ON rc.candidate_id = rd.candidate_id
            GROUP BY f.filing_id, c.company_name
            HAVING COUNT(rc.candidate_id) > 0
            ORDER BY f.filing_id;
        """)

        if result:
            logger.info("\nFilings ready for review:")
            for row in result:
                logger.info(f"  Filing {row['filing_id']} ({row['company_name']}): {row['candidate_count']} candidates, {row['decision_count']} decisions")

        logger.info("\n" + "=" * 80)

    def _start_flask(self) -> None:
        """Start Flask application."""
        logger.info("\nStarting Flask application...")
        logger.info("=" * 80)
        logger.info("Open your browser to: http://localhost:5001/filings")
        logger.info("Press Ctrl+C to stop the server")
        logger.info("=" * 80 + "\n")

        # Set environment
        os.environ["FLASK_APP"] = "src/web/app.py"
        os.environ["FLASK_ENV"] = "development"

        # Import and run Flask
        from src.web.app import create_app
        app = create_app()
        app.run(host="0.0.0.0", port=5001, debug=True)


def main():
    """Main entry point."""
    # Get database URL from environment
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://dev:dev@localhost:5433/filings_analysis"
    )

    logger.info(f"Using database: {db_url.split('@')[1] if '@' in db_url else db_url}")

    # Run setup
    setup = ManualTestSetup(db_url)
    success = setup.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
