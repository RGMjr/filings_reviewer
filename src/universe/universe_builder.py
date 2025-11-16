"""
UniverseBuilder component for Customer Metrics Filings Analysis.

Discovers and maintains the Phase 1 universe of S-1/F-1 filings for first-time issuers.
Excludes SPACs and secondary-only offerings.

Per 05_COMPONENT_INTERFACE_SPECS.md Section 3.
"""

import logging
from typing import Optional

from src.infra.db import DatabaseAdapter
from src.infra.sec_client import SECClient, FilingMetadata
from src.universe.classifiers import (
    classify_spac,
    classify_first_time_issuer,
    classify_offering_type,
    is_in_scope_phase1,
)

logger = logging.getLogger(__name__)


class UniverseBuilder:
    """
    Build and maintain the universe of in-scope filings.

    Responsibilities:
    - Query EDGAR for S-1/F-1 filings in a date range
    - Classify filings (SPAC, first-time issuer, offering type)
    - Upsert companies and filings tables
    - Set is_in_scope_phase1 flag

    Per 04_SYSTEM_ARCHITECTURE.md Section 4.1 and 05_COMPONENT_INTERFACE_SPECS.md Section 3.
    """

    def __init__(self, sec_client: SECClient, db: DatabaseAdapter):
        """
        Initialize UniverseBuilder.

        Args:
            sec_client: SEC EDGAR API client
            db: Database adapter
        """
        self.sec_client = sec_client
        self.db = db

    def build_universe(self, start_date: str, end_date: str) -> int:
        """
        Discover and upsert companies and filings for the given date range.

        Args:
            start_date: ISO date string, inclusive (e.g., "2015-01-01")
            end_date: ISO date string, inclusive (e.g., "2025-12-31")

        Returns:
            Number of filings marked as in-scope for Phase 1

        Process:
            1. Query SEC for S-1/F-1 filings in date range
            2. For each filing:
                a. Upsert company
                b. Classify (SPAC, first-time issuer, offering type)
                c. Upsert filing with classification flags
            3. Return count of in-scope filings
        """
        logger.info(f"Building universe for {start_date} to {end_date}")

        # Query SEC for S-1 and F-1 filings
        form_types = ['S-1', 'S-1/A', 'F-1', 'F-1/A']
        filings = self.sec_client.search_filings(start_date, end_date, form_types)

        logger.info(f"Found {len(filings)} filings from EDGAR")

        # Process each filing
        in_scope_count = 0
        requires_review_count = 0

        for filing in filings:
            try:
                is_in_scope = self._process_filing(filing)
                if is_in_scope:
                    in_scope_count += 1

            except Exception as e:
                logger.error(
                    f"Error processing filing {filing.accession_number}: {e}",
                    exc_info=True,
                )
                requires_review_count += 1

        logger.info(
            f"Universe build complete: "
            f"{in_scope_count} in-scope filings, "
            f"{requires_review_count} require manual review"
        )

        return in_scope_count

    def _process_filing(self, filing: FilingMetadata) -> bool:
        """
        Process a single filing: classify and upsert to database.

        Args:
            filing: Filing metadata from SEC

        Returns:
            True if filing is in-scope for Phase 1, False otherwise
        """
        # 1. Upsert company
        company_id = self.db.upsert_company(
            cik=filing.cik,
            company_name=filing.company_name,
            ticker=filing.ticker,
        )

        # 2. Classify SPAC
        # For v0.1, we use company name only (no filing text yet)
        is_spac, spac_method = classify_spac(filing.company_name)

        # 3. Classify first-time issuer
        previous_ipo_date = self.db.get_first_ipo_filing_date(filing.cik)
        is_first_time, fti_method = classify_first_time_issuer(
            cik=filing.cik,
            filing_date=filing.filing_date,
            previous_ipo_date=previous_ipo_date,
        )

        # 4. Classify offering type
        # For v0.1, we don't have filing text yet, so this will be uncertain
        offering_type, offering_method = classify_offering_type(filing_text=None)

        # 5. Determine if in scope
        in_scope = is_in_scope_phase1(
            is_spac=is_spac,
            is_first_time_issuer=is_first_time,
            offering_type=offering_type,
            form_type=filing.form_type,
        )

        # 6. Determine overall classification method
        classification_method = self._determine_classification_method(
            spac_method, fti_method, offering_method
        )

        # 7. Upsert filing
        filing_id = self.db.upsert_filing(
            company_id=company_id,
            cik=filing.cik,
            accession_number=filing.accession_number,
            form_type=filing.form_type,
            filing_date=filing.filing_date,
            sec_html_url=filing.primary_doc_url,
            sec_txt_url=filing.txt_url,
            is_in_scope_phase1=in_scope,
            is_first_time_issuer=is_first_time,
            is_spac=is_spac,
            offering_type=offering_type,
            classification_method=classification_method,
            processing_status='pending',
        )

        # Log classification results
        logger.debug(
            f"Processed filing {filing.accession_number}: "
            f"in_scope={in_scope}, is_spac={is_spac}, "
            f"is_first_time_issuer={is_first_time}, "
            f"offering_type={offering_type}, "
            f"method={classification_method}"
        )

        if classification_method == 'uncertain':
            logger.warning(
                f"Filing {filing.accession_number} ({filing.company_name}) "
                f"requires manual review"
            )

        return in_scope

    def _determine_classification_method(
        self, spac_method: str, fti_method: str, offering_method: str
    ) -> str:
        """
        Determine overall classification method based on individual classifiers.

        Args:
            spac_method: Method used for SPAC classification
            fti_method: Method used for first-time issuer classification
            offering_method: Method used for offering type classification

        Returns:
            'heuristic' if all are heuristic, 'uncertain' if any are uncertain,
            'manual_review' if manual intervention is needed
        """
        methods = {spac_method, fti_method, offering_method}

        if 'manual_review' in methods:
            return 'manual_review'
        elif 'uncertain' in methods:
            return 'uncertain'
        else:
            return 'heuristic'

    def get_coverage_stats(self) -> dict:
        """
        Get coverage statistics for the universe.

        Returns:
            Dictionary with coverage metrics:
            - total_companies: Number of unique companies
            - total_filings: Total number of filings
            - in_scope_filings: Number of in-scope Phase 1 filings
            - spac_count: Number of SPACs
            - first_time_issuer_count: Number of first-time issuers
            - by_year: Dict of filings per year
        """
        # Total companies
        companies_result = self.db.query("SELECT COUNT(*) as count FROM companies")
        total_companies = companies_result[0]["count"] if companies_result else 0

        # Total filings
        filings_result = self.db.query("SELECT COUNT(*) as count FROM filings")
        total_filings = filings_result[0]["count"] if filings_result else 0

        # In-scope filings
        in_scope_count = self.db.get_in_scope_filing_count()

        # SPAC count
        spac_result = self.db.query(
            "SELECT COUNT(*) as count FROM filings WHERE is_spac = true"
        )
        spac_count = spac_result[0]["count"] if spac_result else 0

        # First-time issuer count
        fti_result = self.db.query(
            "SELECT COUNT(*) as count FROM filings WHERE is_first_time_issuer = true"
        )
        fti_count = fti_result[0]["count"] if fti_result else 0

        # Filings by year
        by_year_result = self.db.query(
            """
            SELECT
                EXTRACT(YEAR FROM filing_date) as year,
                COUNT(*) as count
            FROM filings
            GROUP BY EXTRACT(YEAR FROM filing_date)
            ORDER BY year
            """
        )
        by_year = {int(row["year"]): row["count"] for row in by_year_result}

        stats = {
            "total_companies": total_companies,
            "total_filings": total_filings,
            "in_scope_filings": in_scope_count,
            "spac_count": spac_count,
            "first_time_issuer_count": fti_count,
            "by_year": by_year,
        }

        logger.info(f"Coverage stats: {stats}")
        return stats
