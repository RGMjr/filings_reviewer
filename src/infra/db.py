"""
Database adapter for Customer Metrics Filings Analysis.

Provides a clean interface for database operations using psycopg3.
"""

import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


class DatabaseAdapter:
    """
    Database adapter for Postgres operations.

    Provides connection pooling and common query patterns for the filings analysis system.
    """

    def __init__(self, connection_string: str):
        """
        Initialize the database adapter.

        Args:
            connection_string: PostgreSQL connection string
                (e.g., "postgresql://user:password@localhost/dbname")
        """
        self.connection_string = connection_string
        self._connection = None

    @contextmanager
    def get_connection(self):
        """
        Get a database connection context manager.

        Yields:
            psycopg connection object
        """
        conn = psycopg.connect(self.connection_string, row_factory=dict_row)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error, rolling back: {e}")
            raise
        finally:
            conn.close()

    def execute_script(self, sql_file_path: str) -> None:
        """
        Execute a SQL script file.

        Args:
            sql_file_path: Path to SQL file
        """
        with open(sql_file_path, 'r') as f:
            sql = f.read()

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)

        logger.info(f"Executed SQL script: {sql_file_path}")

    def upsert_company(
        self,
        cik: str,
        company_name: str,
        ticker: Optional[str] = None,
        country_of_domicile: Optional[str] = None,
        industry_code: Optional[str] = None,
        industry_classification_source: Optional[str] = None,
    ) -> int:
        """
        Insert or update a company record.

        Args:
            cik: SEC Central Index Key
            company_name: Official issuer name
            ticker: Stock ticker symbol
            country_of_domicile: Country of incorporation
            industry_code: Industry classification code
            industry_classification_source: Source of industry code

        Returns:
            company_id of the upserted record
        """
        sql = """
            INSERT INTO companies (
                cik, company_name, ticker, country_of_domicile,
                industry_code, industry_classification_source, updated_at
            )
            VALUES (%(cik)s, %(company_name)s, %(ticker)s, %(country_of_domicile)s,
                    %(industry_code)s, %(industry_classification_source)s, now())
            ON CONFLICT (cik) DO UPDATE SET
                company_name = EXCLUDED.company_name,
                ticker = COALESCE(EXCLUDED.ticker, companies.ticker),
                country_of_domicile = COALESCE(EXCLUDED.country_of_domicile, companies.country_of_domicile),
                industry_code = COALESCE(EXCLUDED.industry_code, companies.industry_code),
                industry_classification_source = COALESCE(EXCLUDED.industry_classification_source, companies.industry_classification_source),
                updated_at = now()
            RETURNING company_id
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "cik": cik,
                        "company_name": company_name,
                        "ticker": ticker,
                        "country_of_domicile": country_of_domicile,
                        "industry_code": industry_code,
                        "industry_classification_source": industry_classification_source,
                    },
                )
                result = cur.fetchone()
                company_id = result["company_id"]

        logger.debug(f"Upserted company: cik={cik}, company_id={company_id}")
        return company_id

    def upsert_filing(
        self,
        company_id: int,
        cik: str,
        accession_number: str,
        form_type: str,
        filing_date: str,
        sec_html_url: str,
        period_end_date: Optional[str] = None,
        sec_txt_url: Optional[str] = None,
        is_in_scope_phase1: bool = False,
        is_first_time_issuer: Optional[bool] = None,
        is_spac: Optional[bool] = None,
        offering_type: Optional[str] = None,
        classification_method: Optional[str] = None,
        processing_status: str = "pending",
    ) -> int:
        """
        Insert or update a filing record.

        Args:
            company_id: Foreign key to companies table
            cik: SEC Central Index Key
            accession_number: SEC accession number
            form_type: SEC form type (e.g., 'S-1', 'F-1')
            filing_date: Date filed with SEC (ISO format)
            sec_html_url: URL to HTML filing
            period_end_date: Period end date (ISO format)
            sec_txt_url: URL to text filing
            is_in_scope_phase1: Whether filing is in Phase 1 scope
            is_first_time_issuer: Whether this is a first-time issuer
            is_spac: Whether issuer is a SPAC
            offering_type: Type of offering ('primary', 'secondary', 'mixed')
            classification_method: How flags were determined
            processing_status: Current processing status

        Returns:
            filing_id of the upserted record
        """
        sql = """
            INSERT INTO filings (
                company_id, cik, accession_number, form_type, filing_date,
                period_end_date, sec_html_url, sec_txt_url,
                is_in_scope_phase1, is_first_time_issuer, is_spac,
                offering_type, classification_method, processing_status, updated_at
            )
            VALUES (
                %(company_id)s, %(cik)s, %(accession_number)s, %(form_type)s, %(filing_date)s,
                %(period_end_date)s, %(sec_html_url)s, %(sec_txt_url)s,
                %(is_in_scope_phase1)s, %(is_first_time_issuer)s, %(is_spac)s,
                %(offering_type)s, %(classification_method)s, %(processing_status)s, now()
            )
            ON CONFLICT (company_id, accession_number) DO UPDATE SET
                form_type = EXCLUDED.form_type,
                filing_date = EXCLUDED.filing_date,
                period_end_date = COALESCE(EXCLUDED.period_end_date, filings.period_end_date),
                sec_html_url = EXCLUDED.sec_html_url,
                sec_txt_url = COALESCE(EXCLUDED.sec_txt_url, filings.sec_txt_url),
                is_in_scope_phase1 = EXCLUDED.is_in_scope_phase1,
                is_first_time_issuer = COALESCE(EXCLUDED.is_first_time_issuer, filings.is_first_time_issuer),
                is_spac = COALESCE(EXCLUDED.is_spac, filings.is_spac),
                offering_type = COALESCE(EXCLUDED.offering_type, filings.offering_type),
                classification_method = COALESCE(EXCLUDED.classification_method, filings.classification_method),
                processing_status = EXCLUDED.processing_status,
                updated_at = now()
            RETURNING filing_id
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "company_id": company_id,
                        "cik": cik,
                        "accession_number": accession_number,
                        "form_type": form_type,
                        "filing_date": filing_date,
                        "period_end_date": period_end_date,
                        "sec_html_url": sec_html_url,
                        "sec_txt_url": sec_txt_url,
                        "is_in_scope_phase1": is_in_scope_phase1,
                        "is_first_time_issuer": is_first_time_issuer,
                        "is_spac": is_spac,
                        "offering_type": offering_type,
                        "classification_method": classification_method,
                        "processing_status": processing_status,
                    },
                )
                result = cur.fetchone()
                filing_id = result["filing_id"]

        logger.debug(
            f"Upserted filing: accession={accession_number}, filing_id={filing_id}"
        )
        return filing_id

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> None:
        """
        Execute a SQL statement (UPDATE, DELETE, etc.) without returning results.

        Args:
            sql: SQL statement
            params: Query parameters
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                conn.commit()

    def query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """
        Execute a SELECT query and return results as list of dicts.

        Args:
            sql: SQL query string
            params: Query parameters

        Returns:
            List of result rows as dictionaries
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                return cur.fetchall()

    def get_company_by_cik(self, cik: str) -> Optional[Dict]:
        """
        Get a company record by CIK.

        Args:
            cik: SEC Central Index Key

        Returns:
            Company record as dict, or None if not found
        """
        sql = "SELECT * FROM companies WHERE cik = %(cik)s"
        results = self.query(sql, {"cik": cik})
        return results[0] if results else None

    def get_first_ipo_filing_date(self, cik: str) -> Optional[str]:
        """
        Get the filing date of the first IPO-type filing for a CIK.

        Used to determine if a filing is from a first-time issuer.

        Args:
            cik: SEC Central Index Key

        Returns:
            ISO date string of first IPO filing, or None if not found
        """
        sql = """
            SELECT MIN(filing_date) as first_filing_date
            FROM filings
            WHERE cik = %(cik)s
            AND form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
        """
        results = self.query(sql, {"cik": cik})
        if results and results[0]["first_filing_date"]:
            return str(results[0]["first_filing_date"])
        return None

    def get_in_scope_filing_count(self) -> int:
        """
        Get count of filings where is_in_scope_phase1 = true.

        Returns:
            Count of in-scope filings
        """
        sql = "SELECT COUNT(*) as count FROM filings WHERE is_in_scope_phase1 = true"
        results = self.query(sql)
        return results[0]["count"] if results else 0
