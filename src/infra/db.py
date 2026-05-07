"""
Database adapter for CMASB Disclosures Review.

Provides a clean interface for database operations using psycopg3.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

import psycopg
from psycopg.rows import dict_row

from src.infra.validation import ValidationError, normalize_sec_accession, validate_enum
from src.review.models import (
    IMAGE_CHART_TYPES,
    IMAGE_DECISIONS,
    IMAGE_REJECTION_REASONS,
    IMAGE_REVIEW_FILTER_STATUSES,
)

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)


def _reject_non_select(sql: str) -> None:
    """Raise ValueError if `sql` is a write that lacks RETURNING.

    `DatabaseAdapter.query` calls `cur.fetchall()` unconditionally; passing a
    bare INSERT/UPDATE/DELETE produces an opaque
    `psycopg.ProgrammingError: the last operation didn't produce records`.
    Catch the misuse here with a message that points at `db.execute`.
    """
    # Strip leading whitespace, line comments, and block comments to find the
    # first SQL token.
    stripped = sql.lstrip()
    while True:
        if stripped.startswith("--"):
            nl = stripped.find("\n")
            stripped = stripped[nl + 1 :].lstrip() if nl != -1 else ""
            continue
        if stripped.startswith("/*"):
            end = stripped.find("*/")
            stripped = stripped[end + 2 :].lstrip() if end != -1 else ""
            continue
        break
    first = stripped.split(None, 1)[0].upper() if stripped else ""
    if first in ("INSERT", "UPDATE", "DELETE") and "RETURNING" not in sql.upper():
        raise ValueError(
            f"db.query is SELECT-only (got {first} without RETURNING). "
            "Use db.execute(sql, params) for non-fetching writes, or add "
            "RETURNING to fetch result rows."
        )


# Analytical tab → SQL fragment. Tabs are the UI grouping (IPO vs Earnings vs
# Investor Day) and combine `v2_documents.document_type` with `filings.form_type`.
# Keys are validated server-side before use — fragments are string-constant SQL,
# no user input is interpolated.
TAB_SQL_FILTERS: dict[str, str] = {
    "ipo": ("d.document_type = 'sec_filing' AND f.form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')"),
    "earnings": (
        "(d.document_type = 'earnings_call' "
        "OR (d.document_type = 'sec_filing' "
        "AND f.form_type IN ('8-K', '8-K/A', '10-K', '10-K/A', '10-Q', '10-Q/A')))"
    ),
    "investor_day": "d.document_type = 'investor_presentation'",
}


def tab_filter_sql(tab: str | None) -> str:
    """Return the SQL AND-fragment for a tab key, or '' if tab is None/unknown.

    Callers splice the result into a WHERE clause alongside other filters —
    the returned string is empty or begins with 'AND ' so it is safe to append.
    """
    if tab and tab in TAB_SQL_FILTERS:
        return "AND " + TAB_SQL_FILTERS[tab]
    return ""


def infer_tab_from_filing(document_type: str | None, form_type: str | None) -> str | None:
    """Map a (document_type, form_type) pair to the analytical tab it belongs to.

    Used by cross-filing advance when the user arrived from the "All" view of
    the filings list — `next_filing` falls back to the current filing's tab so
    advancement stays within IPO / Earnings / Investor Day.
    """
    if document_type == "investor_presentation":
        return "investor_day"
    if document_type == "earnings_call":
        return "earnings"
    if document_type == "sec_filing":
        if form_type in ("S-1", "S-1/A", "F-1", "F-1/A"):
            return "ipo"
        if form_type in ("8-K", "8-K/A", "10-K", "10-K/A", "10-Q", "10-Q/A"):
            return "earnings"
    return None


class DatabaseAdapter:
    """
    Database adapter for Postgres operations.

    Provides connection management and common query patterns for the filings
    analysis system. Supports both per-operation connections (default) and
    connection pooling via psycopg_pool.

    Usage without pooling (per-operation connections):
        adapter = DatabaseAdapter(connection_string)

    Usage with pooling (recommended for Flask apps and scripts):
        from src.infra.pool import create_pool
        pool = create_pool(connection_string)
        adapter = DatabaseAdapter(connection_string, pool=pool)
    """

    def __init__(
        self,
        connection_string: str,
        pool: ConnectionPool | None = None,
    ):
        """
        Initialize the database adapter.

        Args:
            connection_string: PostgreSQL connection string
                (e.g., "postgresql://user:password@localhost/dbname")
            pool: Optional connection pool. If provided, connections are
                borrowed from the pool instead of being created per operation.
        """
        self.connection_string = connection_string
        self._pool = pool
        self._connection = None

    @contextmanager
    def get_connection(self):
        """
        Get a database connection context manager.

        If a connection pool was provided to __init__, connections are borrowed
        from the pool and automatically returned when the context exits.
        Otherwise, a new connection is created and closed per operation.

        Yields:
            psycopg connection object
        """
        if self._pool is not None:
            # Use pooled connection - returned to pool on exit
            with self._pool.connection() as conn:
                try:
                    yield conn
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    logger.error(f"Database error, rolling back: {e}")
                    raise
        else:
            # Original behavior: create/close connection per operation
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

    def close(self) -> None:
        """Close the adapter's connection pool if one was provided.

        Safe to call multiple times or when no pool exists.
        After closing, the adapter should not be used for new operations.
        """
        if self._pool is not None:
            try:
                self._pool.close()
                logger.info("DatabaseAdapter pool closed")
            except Exception as e:
                logger.error(f"Error closing pool: {e}")
            finally:
                self._pool = None

    @contextmanager
    def transaction(self):
        """
        Get a transaction context for multi-step operations.

        Use this when you need multiple database operations to succeed or fail
        together as an atomic unit. All operations within the context share
        a single connection and transaction.

        The transaction commits automatically on clean exit and rolls back
        on any exception.

        Yields:
            psycopg connection object with an open transaction

        Example:
            with db.transaction() as conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO table1 ...")
                    cur.execute("UPDATE table2 ...")
                # Both operations commit together

            # Or for complex workflows:
            with db.transaction() as conn:
                # Multiple related operations
                # All succeed or all fail
        """
        with self.get_connection() as conn:
            yield conn
            # Commit/rollback handled by get_connection()

    def execute_script(self, sql_file_path: str) -> None:
        """
        Execute a SQL script file.

        Args:
            sql_file_path: Path to SQL file

        Raises:
            ValueError: If path contains traversal sequences or doesn't end in .sql
        """
        # Security: Validate file path
        from pathlib import Path

        path = Path(sql_file_path)

        # Check for path traversal
        try:
            # Resolve to absolute path and check it doesn't escape expected directories
            path.resolve()
            # Ensure the path is within the project directory or is an absolute path to a .sql file
            if ".." in sql_file_path:
                raise ValueError("Path traversal not allowed in SQL script paths")
        except (ValueError, OSError) as e:
            raise ValueError(f"Invalid SQL script path: {e}") from e

        # Validate file extension
        if not sql_file_path.endswith(".sql"):
            raise ValueError("SQL script files must have .sql extension")

        # Validate file exists
        if not path.exists():
            raise ValueError(f"SQL script file not found: {sql_file_path}")

        with open(sql_file_path) as f:
            sql = f.read()

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)

        logger.info(f"Executed SQL script: {sql_file_path}")

    def upsert_company(
        self,
        cik: str,
        company_name: str,
        ticker: str | None = None,
        country_of_domicile: str | None = None,
        industry_code: str | None = None,
        industry_classification_source: str | None = None,
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
        period_end_date: str | None = None,
        sec_txt_url: str | None = None,
        is_in_scope_phase1: bool = False,
        is_first_time_issuer: bool | None = None,
        is_spac: bool | None = None,
        is_post_combination: bool | None = None,
        is_investment_vehicle: bool | None = None,
        is_resource_extraction: bool | None = None,
        offering_type: str | None = None,
        classification_method: str | None = None,
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
            is_post_combination: Whether this is a post-combination SPAC (de-SPAC)
            is_investment_vehicle: Whether company is an investment vehicle
            is_resource_extraction: Whether company is in resource extraction
            offering_type: Type of offering ('primary', 'secondary', 'mixed')
            classification_method: How flags were determined
            processing_status: Current processing status

        Returns:
            filing_id of the upserted record

        Raises:
            ValidationError: If accession_number has no SEC-shaped token
                (``NNNNNNNNNN-NN-NNNNNN``) embedded. Synthetic namespaces
                (``presentation:*``, ``transcript:*``) pass through unchanged.
        """
        # Canonicalize the accession before we write. Historically, a small
        # number of rows were persisted with the full EDGAR index path
        # (e.g., ``edgar/data/<cik>/<accession>.txt``) rather than the bare
        # token, which caused downstream fetchers to trip the path-traversal
        # guard. The normalizer extracts the 10-2-6 token from any plausible
        # input and leaves synthetic-namespace keys alone.
        normalized = normalize_sec_accession(accession_number)
        if normalized is None:
            raise ValidationError(
                f"Cannot persist filing: accession_number {accession_number!r} "
                "contains no SEC-shaped token (NNNNNNNNNN-NN-NNNNNN)"
            )
        accession_number = normalized

        sql = """
            INSERT INTO filings (
                company_id, cik, accession_number, form_type, filing_date,
                period_end_date, sec_html_url, sec_txt_url,
                is_in_scope_phase1, is_first_time_issuer, is_spac, is_post_combination,
                is_investment_vehicle, is_resource_extraction,
                offering_type, classification_method, processing_status, updated_at
            )
            VALUES (
                %(company_id)s, %(cik)s, %(accession_number)s, %(form_type)s, %(filing_date)s,
                %(period_end_date)s, %(sec_html_url)s, %(sec_txt_url)s,
                %(is_in_scope_phase1)s, %(is_first_time_issuer)s, %(is_spac)s, %(is_post_combination)s,
                %(is_investment_vehicle)s, %(is_resource_extraction)s,
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
                is_post_combination = COALESCE(EXCLUDED.is_post_combination, filings.is_post_combination),
                is_investment_vehicle = COALESCE(EXCLUDED.is_investment_vehicle, filings.is_investment_vehicle),
                is_resource_extraction = COALESCE(EXCLUDED.is_resource_extraction, filings.is_resource_extraction),
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
                        "is_post_combination": is_post_combination,
                        "is_investment_vehicle": is_investment_vehicle,
                        "is_resource_extraction": is_resource_extraction,
                        "offering_type": offering_type,
                        "classification_method": classification_method,
                        "processing_status": processing_status,
                    },
                )
                result = cur.fetchone()
                filing_id = result["filing_id"]

        logger.debug(f"Upserted filing: accession={accession_number}, filing_id={filing_id}")
        return filing_id

    def execute(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        *,
        fetch: bool = False,
    ) -> list[dict[str, Any]] | None:
        """
        Execute a SQL statement.

        Args:
            sql: SQL statement
            params: Query parameters
            fetch: If True, return fetched rows (for statements with RETURNING)

        Returns:
            List of rows when fetch=True, otherwise None.
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                if fetch:
                    return cur.fetchall()
        return None

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        """
        Execute a SELECT query and return results as list of dicts.

        Args:
            sql: SQL query string
            params: Query parameters

        Returns:
            List of result rows as dictionaries

        Raises:
            ValueError: if `sql` is a non-fetching write (INSERT/UPDATE/DELETE
                without RETURNING). Use `db.execute()` for those — `query`
                calls `cur.fetchall()` unconditionally and would otherwise
                surface as an opaque `psycopg.ProgrammingError`.
        """
        _reject_non_select(sql)
        result = self.execute(sql, params, fetch=True)
        return result or []

    def get_company_by_cik(self, cik: str) -> dict | None:
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

    def get_first_ipo_filing_date(self, cik: str) -> str | None:
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

    def has_prior_spac_filing(self, cik: str, filing_date: str) -> bool:
        """
        Check if a CIK has any prior SPAC filings before the given date.

        This is used to detect post-combination SPACs (de-SPACs) where the
        same CIK was previously used for a blank check SPAC entity.

        Args:
            cik: SEC Central Index Key
            filing_date: ISO date string to check before

        Returns:
            True if CIK has prior SPAC filings, False otherwise
        """
        sql = """
            SELECT COUNT(*) as count
            FROM filings
            WHERE cik = %(cik)s
              AND is_spac = true
              AND filing_date < %(filing_date)s
        """
        results = self.query(sql, {"cik": cik, "filing_date": filing_date})
        return bool(results and results[0]["count"] > 0)

    def mark_superseded_filings(self) -> int:
        """
        Mark superseded filings as out of scope.

        Two scopes, run as separate UPDATEs in a single transaction:

        1. S-1/S-1/A/F-1/F-1/A — registration-statement chain. Per company,
           keep only the most recently filed; demote earlier originals and
           interim amendments. (Existing semantics, unchanged.)
        2. 10-K/10-K/A — annual-report restatement chain. Per
           (company, fiscal year as ``period_end_date``), keep only the
           most recently filed; demote earlier originals or amendments
           for the same fiscal year. Different fiscal years remain in
           scope so multi-year analytics are preserved. Rows with NULL
           ``period_end_date`` are conservatively skipped — they cannot
           be safely paired with an amendment.

        All filings are retained in the database for historical reference.

        Returns:
            Total number of filings marked out of scope.
        """
        s1f1_sql = """
            UPDATE filings
            SET is_in_scope_phase1 = FALSE
            WHERE form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
              AND is_in_scope_phase1 = TRUE
              AND filing_id NOT IN (
                  SELECT DISTINCT ON (company_id) filing_id
                  FROM filings
                  WHERE form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
                  ORDER BY company_id, filing_date DESC NULLS LAST
              )
        """
        tenk_sql = """
            UPDATE filings
            SET is_in_scope_phase1 = FALSE
            WHERE form_type IN ('10-K', '10-K/A')
              AND is_in_scope_phase1 = TRUE
              AND period_end_date IS NOT NULL
              AND filing_id NOT IN (
                  SELECT DISTINCT ON (company_id, period_end_date) filing_id
                  FROM filings
                  WHERE form_type IN ('10-K', '10-K/A')
                    AND period_end_date IS NOT NULL
                  ORDER BY company_id, period_end_date,
                           filing_date DESC NULLS LAST
              )
        """
        affected = 0
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(s1f1_sql)
                affected += cur.rowcount
                cur.execute(tenk_sql)
                affected += cur.rowcount
                conn.commit()
        return affected

    def get_in_scope_filing_count(self) -> int:
        """
        Get count of filings where is_in_scope_phase1 = true.

        Returns:
            Count of in-scope filings
        """
        sql = "SELECT COUNT(*) as count FROM filings WHERE is_in_scope_phase1 = true"
        results = self.query(sql)
        return results[0]["count"] if results else 0

    def get_filing_with_company(self, filing_id: int) -> dict | None:
        """
        Get filing information including company details.

        Args:
            filing_id: The filing ID to retrieve

        Returns:
            Dict with filing and company info, or None if not found
        """
        sql = """
            SELECT
                f.filing_id, f.accession_number, f.form_type, f.filing_date,
                f.company_id,
                c.company_name, c.cik, c.ticker, c.industry_code
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE f.filing_id = %(filing_id)s
        """
        results = self.query(sql, {"filing_id": filing_id})
        return results[0] if results else None

    def insert_audit_log(
        self,
        session_id: str | None,
        ip_address: str | None,
        user_agent: str | None,
        route_name: str,
        http_method: str,
        url_path: str,
        filing_id: int | None,
        query_params: dict[str, Any] | None,
        response_status: int,
        response_time_ms: int | None,
    ) -> int:
        """
        Insert an audit log entry for a review route request (writes v2_audit_log).

        Returns:
            The log_id of the inserted record, or 0 if insert returned nothing.
        """
        sql = """
            INSERT INTO v2_audit_log (
                session_id, ip_address, user_agent,
                route_name, http_method, url_path,
                filing_id, query_params,
                response_status, response_time_ms
            ) VALUES (
                %(session_id)s, %(ip_address)s, %(user_agent)s,
                %(route_name)s, %(http_method)s, %(url_path)s,
                %(filing_id)s, %(query_params)s,
                %(response_status)s, %(response_time_ms)s
            )
            RETURNING log_id
        """

        params = {
            "session_id": session_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "route_name": route_name,
            "http_method": http_method,
            "url_path": url_path,
            "filing_id": filing_id,
            "query_params": json.dumps(query_params) if query_params else None,
            "response_status": response_status,
            "response_time_ms": response_time_ms,
        }

        result = self.query(sql, params)
        return result[0]["log_id"] if result else 0

    # =============================================================================
    # Image Cache Methods
    # =============================================================================

    def get_cached_image(self, cik: str, accession_no: str, filename: str) -> dict | None:
        """
        Retrieve a cached image from the image_cache table.

        Args:
            cik: CIK with leading zeros stripped (matches SEC URL convention)
            accession_no: Accession number with dashes removed
            filename: Image filename

        Returns:
            Dict with image_data (bytes), content_type (str), size_bytes (int),
            or None if not cached.
        """
        rows = self.query(
            """
            SELECT image_data, content_type, size_bytes
            FROM image_cache
            WHERE cik = %(cik)s AND accession_no = %(accession_no)s AND filename = %(filename)s
            """,
            {"cik": cik, "accession_no": accession_no, "filename": filename},
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "image_data": bytes(row["image_data"]),
            "content_type": row["content_type"],
            "size_bytes": row["size_bytes"],
        }

    def store_cached_image(
        self,
        cik: str,
        accession_no: str,
        filename: str,
        image_data: bytes,
        content_type: str,
    ) -> bool:
        """
        Store an image in the image_cache table.

        Uses ON CONFLICT DO NOTHING — idempotent, will not overwrite existing entries.

        Args:
            cik: CIK with leading zeros stripped
            accession_no: Accession number with dashes removed
            filename: Image filename
            image_data: Raw image bytes
            content_type: MIME type (e.g. "image/jpeg")

        Returns:
            True if stored, False if already existed (conflict) or on error.
        """
        rows = self.query(
            """
            INSERT INTO image_cache (cik, accession_no, filename, image_data, content_type, size_bytes)
            VALUES (%(cik)s, %(accession_no)s, %(filename)s, %(image_data)s, %(content_type)s, %(size_bytes)s)
            ON CONFLICT (cik, accession_no, filename) DO NOTHING
            RETURNING cik
            """,
            {
                "cik": cik,
                "accession_no": accession_no,
                "filename": filename,
                "image_data": image_data,
                "content_type": content_type,
                "size_bytes": len(image_data),
            },
        )
        return len(rows) > 0

    def get_image_cache_stats(self) -> dict:
        """
        Return aggregate stats for the image_cache table.

        Returns:
            Dict with count (int) and total_bytes (int).
        """
        rows = self.query(
            "SELECT COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS total_bytes FROM image_cache"
        )
        row = rows[0]
        return {"count": int(row["count"]), "total_bytes": int(row["total_bytes"])}

    # =============================================================================
    # V2 Extraction Review Methods
    # =============================================================================

    def get_v2_filings_with_facts(
        self,
        tab: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get filings that have V2 extraction results, with fact counts and review progress.

        Args:
            tab: Optional analytical tab key — see TAB_SQL_FILTERS for the
                 supported keys ("ipo", "earnings", "investor_day").
            limit: Maximum number of rows to return. None returns all rows.
            offset: Number of rows to skip (for pagination).

        Returns:
            List of dicts with filing metadata and V2 extraction stats.
        """
        conditions: list[str] = ["(f.is_spac IS NOT TRUE)"]
        params: dict[str, Any] = {}
        tab_fragment = tab_filter_sql(tab).removeprefix("AND ").strip()
        if tab_fragment:
            conditions.append(tab_fragment)
        where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT
                f.filing_id,
                c.company_name,
                c.cik,
                c.ticker,
                f.accession_number,
                f.form_type,
                f.filing_date,
                d.doc_id,
                d.document_type,
                d.status AS extraction_status,
                d.fact_count,
                d.segment_count,
                d.table_count,
                d.image_count,
                d.extract_completed_at,
                COUNT(CASE WHEN mf.review_status = 'pending_review' THEN 1 END) AS pending_count,
                COUNT(CASE WHEN mf.review_status = 'accepted' THEN 1 END) AS accepted_count,
                COUNT(CASE WHEN mf.review_status = 'rejected' THEN 1 END) AS rejected_count,
                COUNT(CASE WHEN mf.review_status = 'corrected' THEN 1 END) AS corrected_count,
                COUNT(CASE WHEN mf.review_status = 'auto_accepted' THEN 1 END) AS auto_accepted_count
            FROM v2_documents d
            JOIN filings f ON d.filing_id = f.filing_id
            JOIN companies c ON f.company_id = c.company_id
            LEFT JOIN v2_metric_facts mf ON mf.filing_id = d.filing_id
            {where_clause}
            GROUP BY f.filing_id, c.company_name, c.cik, c.ticker, f.accession_number,
                     f.form_type, f.filing_date, d.doc_id, d.document_type, d.status,
                     d.fact_count, d.segment_count, d.table_count, d.image_count,
                     d.extract_completed_at
            ORDER BY d.extract_completed_at DESC NULLS LAST
        """
        if limit is not None:
            sql += " LIMIT %(limit)s OFFSET %(offset)s"
            params["limit"] = limit
            params["offset"] = offset
        return self.query(sql, params if params else None)

    def count_v2_filings_with_facts(self) -> int:
        """Return total count of filings with V2 extraction results."""
        sql = """
            SELECT COUNT(*) AS cnt
            FROM v2_documents d
            JOIN filings f ON d.filing_id = f.filing_id
        """
        result = self.query(sql)
        return result[0]["cnt"] if result else 0

    def get_unified_filings_for_review(
        self,
        tab: str | None = None,
        limit: int = 50,
        offset: int = 0,
        hide_completed: bool = False,
        sort_by: str = "date",
        sort_dir: str = "desc",
        reviewer_ids: list[str] | None = None,
        legacy_backfill_only: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Get filings combining V2 text fact counts and image candidate counts.

        Returns one row per filing with review progress for both text facts and
        image candidates. Used by the unified filing list page.

        Args:
            tab: Optional analytical tab key — see TAB_SQL_FILTERS for the
                 supported keys ("ipo", "earnings", "investor_day").
            limit: Maximum number of rows to return.
            offset: Number of rows to skip (for pagination).
            hide_completed: If True, exclude filings with 0 pending text facts
                            and 0 pending image candidates.
            reviewer_ids: If non-empty, restrict to filings where any listed
                          reviewer touched at least one text or image decision.

        Returns:
            List of dicts with filing metadata and combined review stats. Each
            row includes a `reviewers` list of distinct reviewer_ids across
            text + image decisions (empty list = no reviewer yet).
        """
        sort_map = {
            "company": "c.company_name",
            "date": "f.filing_date",
            "text_progress": "COALESCE(tp.facts_pending, 0)",
            "image_progress": "COALESCE(ip.images_pending, 0)",
        }
        order_col = sort_map.get(sort_by, "f.filing_date")
        order_dir = "ASC" if sort_dir == "asc" else "DESC"
        # Secondary sort for stable ordering
        secondary = "" if sort_by == "company" else ", c.company_name"

        doc_type_filter = tab_filter_sql(tab)
        completed_filter = ""
        reviewer_filter = ""
        legacy_backfill_filter = ""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if hide_completed:
            completed_filter = (
                "AND (COALESCE(tp.facts_pending, 0) > 0 OR COALESCE(ip.images_pending, 0) > 0)"
            )
        if reviewer_ids:
            reviewer_filter = (
                "AND COALESCE(rp.reviewers, ARRAY[]::text[]) && %(reviewer_ids)s::text[]"
            )
            params["reviewer_ids"] = list(reviewer_ids)
        if legacy_backfill_only:
            legacy_backfill_filter = "AND COALESCE(ip.images_legacy_pending, 0) > 0"

        sql = f"""
            WITH text_progress AS (
                SELECT
                    mf.filing_id,
                    COUNT(mf.fact_id)                                                      AS fact_count,
                    COUNT(CASE WHEN mf.review_status = 'pending_review'             THEN 1 END) AS facts_pending,
                    COUNT(CASE WHEN mf.review_status IN ('accepted', 'auto_accepted') THEN 1 END) AS facts_accepted,
                    COUNT(CASE WHEN mf.review_status = 'auto_accepted'              THEN 1 END) AS facts_auto_accepted,
                    COUNT(CASE WHEN mf.review_status IN ('rejected', 'corrected')   THEN 1 END) AS facts_rejected
                FROM v2_metric_facts mf
                GROUP BY mf.filing_id
            ),
            image_progress AS (
                -- "images_reviewed" widens beyond raw review_status='reviewed' to also
                -- include images the reviewer flipped to 'skipped' via "Reject all (no
                -- relevant metrics)" — those carry per-metric reject rows in
                -- v2_image_metric_confirmations. Without this widening the filings-list
                -- progress counter under-reports completion (skipped images with
                -- confirmations are neither pending nor counted as reviewed).
                -- Mirrors the per-image badge disambiguation in unified_review.html
                -- (PR #371). True "Skip whole image" parks (skipped, zero confirmations)
                -- still don't count as reviewed.
                SELECT
                    v.filing_id,
                    COUNT(v.img_id)                                                         AS image_count,
                    COUNT(CASE WHEN v.review_status = 'pending'    THEN 1 END)              AS images_pending,
                    COUNT(
                        CASE
                            WHEN v.review_status = 'reviewed' THEN 1
                            WHEN v.review_status = 'skipped' AND EXISTS (
                                SELECT 1 FROM v2_image_metric_confirmations c
                                WHERE c.img_id = v.img_id
                            ) THEN 1
                        END
                    )                                                                       AS images_reviewed,
                    COUNT(DISTINCT CASE
                        WHEN EXISTS (
                            SELECT 1 FROM v2_image_review_decisions ird
                            WHERE ird.img_id = v.img_id AND ird.decision = 'relevant'
                        )
                        AND NOT EXISTS (
                            SELECT 1 FROM v2_image_metric_confirmations imc
                            WHERE imc.img_id = v.img_id
                        )
                        THEN v.img_id
                    END)                                                                    AS images_legacy_pending
                FROM v2_image_assets v
                WHERE v.classification NOT IN ('decorative', 'logo', 'signature')
                  AND v.filename IS NOT NULL AND v.filename != ''
                GROUP BY v.filing_id
            ),
            reviewer_progress AS (
                SELECT
                    filing_id,
                    ARRAY(SELECT DISTINCT r FROM UNNEST(array_agg(reviewer_id)) r
                          WHERE r IS NOT NULL ORDER BY r) AS reviewers
                FROM (
                    SELECT mf.filing_id, rd.reviewer_id
                    FROM v2_review_decisions rd
                    JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
                    WHERE rd.reviewer_id IS NOT NULL
                    UNION ALL
                    SELECT va.filing_id, ird.reviewer_id
                    FROM v2_image_review_decisions ird
                    JOIN v2_image_assets va ON va.img_id = ird.img_id
                    WHERE ird.reviewer_id IS NOT NULL
                ) AS combined
                GROUP BY filing_id
            )
            SELECT
                f.filing_id,
                c.company_name,
                c.cik,
                c.ticker,
                f.accession_number,
                f.form_type,
                f.filing_date,
                d.document_type,
                COALESCE(tp.fact_count,         0) AS fact_count,
                COALESCE(tp.facts_pending,      0) AS facts_pending,
                COALESCE(tp.facts_accepted,     0) AS facts_accepted,
                COALESCE(tp.facts_auto_accepted, 0) AS facts_auto_accepted,
                COALESCE(tp.facts_rejected,     0) AS facts_rejected,
                COALESCE(ip.image_count,        0) AS image_count,
                COALESCE(ip.images_pending,  0) AS images_pending,
                COALESCE(ip.images_reviewed, 0) AS images_reviewed,
                COALESCE(ip.images_legacy_pending, 0) AS images_legacy_pending,
                COALESCE(rp.reviewers, ARRAY[]::text[]) AS reviewers
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            JOIN v2_documents d ON d.filing_id = f.filing_id
            LEFT JOIN text_progress     tp ON tp.filing_id = f.filing_id
            LEFT JOIN image_progress    ip ON ip.filing_id = f.filing_id
            LEFT JOIN reviewer_progress rp ON rp.filing_id = f.filing_id
            WHERE (f.is_spac IS NOT TRUE)
            {doc_type_filter}
            {completed_filter}
            {reviewer_filter}
            {legacy_backfill_filter}
            ORDER BY {order_col} {order_dir} NULLS LAST{secondary}
            LIMIT %(limit)s OFFSET %(offset)s
        """
        return self.query(sql, params)

    def get_unified_filings_for_review_count(
        self,
        tab: str | None = None,
        hide_completed: bool = False,
        reviewer_ids: list[str] | None = None,
        legacy_backfill_only: bool = False,
    ) -> int:
        """Return total count of filings eligible for unified review.

        Args:
            tab: Optional analytical tab key — see TAB_SQL_FILTERS.
            hide_completed: If True, exclude filings with 0 pending text facts
                            and 0 pending image candidates.
            reviewer_ids: If non-empty, restrict to filings touched by any
                          listed reviewer. Must mirror
                          `get_unified_filings_for_review` so pagination totals
                          match the visible result set.

        Returns:
            Total number of matching filings.
        """
        doc_type_filter = tab_filter_sql(tab)
        completed_filter = ""
        reviewer_filter = ""
        legacy_backfill_filter = ""
        params: dict[str, Any] = {}
        if hide_completed:
            completed_filter = """
                AND (COALESCE(tp.facts_pending, 0) > 0 OR COALESCE(ip.images_pending, 0) > 0)
            """
        if reviewer_ids:
            reviewer_filter = (
                "AND COALESCE(rp.reviewers, ARRAY[]::text[]) && %(reviewer_ids)s::text[]"
            )
            params["reviewer_ids"] = list(reviewer_ids)
        if legacy_backfill_only:
            legacy_backfill_filter = "AND COALESCE(ip.images_legacy_pending, 0) > 0"

        sql = f"""
            WITH text_progress AS (
                SELECT
                    mf.filing_id,
                    COUNT(CASE WHEN mf.review_status = 'pending_review' THEN 1 END) AS facts_pending
                FROM v2_metric_facts mf
                GROUP BY mf.filing_id
            ),
            image_progress AS (
                SELECT
                    v.filing_id,
                    COUNT(CASE WHEN v.review_status = 'pending' THEN 1 END) AS images_pending,
                    COUNT(DISTINCT CASE
                        WHEN EXISTS (
                            SELECT 1 FROM v2_image_review_decisions ird
                            WHERE ird.img_id = v.img_id AND ird.decision = 'relevant'
                        )
                        AND NOT EXISTS (
                            SELECT 1 FROM v2_image_metric_confirmations imc
                            WHERE imc.img_id = v.img_id
                        )
                        THEN v.img_id
                    END) AS images_legacy_pending
                FROM v2_image_assets v
                WHERE v.classification NOT IN ('decorative', 'logo', 'signature')
                  AND v.filename IS NOT NULL AND v.filename != ''
                GROUP BY v.filing_id
            ),
            reviewer_progress AS (
                SELECT
                    filing_id,
                    ARRAY(SELECT DISTINCT r FROM UNNEST(array_agg(reviewer_id)) r
                          WHERE r IS NOT NULL) AS reviewers
                FROM (
                    SELECT mf.filing_id, rd.reviewer_id
                    FROM v2_review_decisions rd
                    JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
                    WHERE rd.reviewer_id IS NOT NULL
                    UNION ALL
                    SELECT va.filing_id, ird.reviewer_id
                    FROM v2_image_review_decisions ird
                    JOIN v2_image_assets va ON va.img_id = ird.img_id
                    WHERE ird.reviewer_id IS NOT NULL
                ) AS combined
                GROUP BY filing_id
            )
            SELECT COUNT(*) AS cnt
            FROM filings f
            JOIN v2_documents d ON d.filing_id = f.filing_id
            LEFT JOIN text_progress     tp ON tp.filing_id = f.filing_id
            LEFT JOIN image_progress    ip ON ip.filing_id = f.filing_id
            LEFT JOIN reviewer_progress rp ON rp.filing_id = f.filing_id
            WHERE (f.is_spac IS NOT TRUE)
            {doc_type_filter}
            {completed_filter}
            {reviewer_filter}
            {legacy_backfill_filter}
        """
        result = self.query(sql, params if params else None)
        return result[0]["cnt"] if result else 0

    def get_next_filing_with_pending_work(
        self,
        current_filing_id: int,
        tab: str | None = None,
        hide_completed: bool = False,
        sort_by: str = "date",
        sort_dir: str = "desc",
        reviewer_ids: list[str] | None = None,
        legacy_backfill_only: bool = False,
    ) -> int | None:
        """Return the filing_id of the next filing with pending review work.

        "Pending work" means either pending text facts OR pending images —
        otherwise image-only filings are unreachable via cross-filing
        navigation. Uses the same sort/filter logic as
        get_unified_filings_for_review and finds the first row after the
        current filing (by ROW_NUMBER) that still has pending work.

        Args:
            current_filing_id: The filing_id of the filing currently being reviewed.
            tab: Optional analytical tab key — see TAB_SQL_FILTERS.
            hide_completed: If True, restrict candidates to filings with pending work.
            sort_by: Column to sort by (same options as get_unified_filings_for_review).
            sort_dir: "asc" or "desc".
            reviewer_ids: If non-empty, restrict to filings touched by any
                          listed reviewer. Mirrors the filings-list filter so
                          cross-filing advance stays within the reviewer scope.

        Returns:
            filing_id of the next eligible filing, or None if none exists.
        """
        sort_map = {
            "company": "c.company_name",
            "date": "f.filing_date",
            "text_progress": "COALESCE(tp.facts_pending, 0)",
            "image_progress": "COALESCE(ip.images_pending, 0)",
        }
        order_col = sort_map.get(sort_by, "f.filing_date")
        order_dir = "ASC" if sort_dir == "asc" else "DESC"

        doc_type_filter = tab_filter_sql(tab)
        completed_filter = ""
        reviewer_filter = ""
        params: dict[str, Any] = {"current_filing_id": current_filing_id}
        if hide_completed:
            completed_filter = (
                "AND (COALESCE(tp.facts_pending, 0) > 0 OR COALESCE(ip.images_pending, 0) > 0)"
            )
        if reviewer_ids:
            reviewer_filter = (
                "AND COALESCE(rp.reviewers, ARRAY[]::text[]) && %(reviewer_ids)s::text[]"
            )
            params["reviewer_ids"] = list(reviewer_ids)
        # When filtering to legacy-backfill, replace the pending-work guard so filings
        # whose only remaining work is legacy backfill (images_pending=0) are reachable.
        pending_filter = (
            "AND images_legacy_pending > 0"
            if legacy_backfill_only
            else "AND (facts_pending > 0 OR images_pending > 0)"
        )

        sql = f"""
            WITH text_progress AS (
                SELECT
                    mf.filing_id,
                    COUNT(mf.fact_id) AS fact_count,
                    COUNT(CASE WHEN mf.review_status = 'pending_review' THEN 1 END) AS facts_pending,
                    COUNT(CASE WHEN mf.review_status IN ('accepted', 'auto_accepted') THEN 1 END) AS facts_accepted,
                    COUNT(CASE WHEN mf.review_status IN ('rejected', 'corrected') THEN 1 END) AS facts_rejected
                FROM v2_metric_facts mf
                GROUP BY mf.filing_id
            ),
            image_progress AS (
                -- See parallel CTE in get_unified_filings_for_review for rationale.
                SELECT
                    v.filing_id,
                    COUNT(v.img_id) AS image_count,
                    COUNT(CASE WHEN v.review_status = 'pending' THEN 1 END) AS images_pending,
                    COUNT(
                        CASE
                            WHEN v.review_status = 'reviewed' THEN 1
                            WHEN v.review_status = 'skipped' AND EXISTS (
                                SELECT 1 FROM v2_image_metric_confirmations c
                                WHERE c.img_id = v.img_id
                            ) THEN 1
                        END
                    ) AS images_reviewed,
                    COUNT(DISTINCT CASE
                        WHEN EXISTS (
                            SELECT 1 FROM v2_image_review_decisions ird
                            WHERE ird.img_id = v.img_id AND ird.decision = 'relevant'
                        )
                        AND NOT EXISTS (
                            SELECT 1 FROM v2_image_metric_confirmations imc
                            WHERE imc.img_id = v.img_id
                        )
                        THEN v.img_id
                    END) AS images_legacy_pending
                FROM v2_image_assets v
                WHERE v.classification NOT IN ('decorative', 'logo', 'signature')
                  AND v.filename IS NOT NULL AND v.filename != ''
                GROUP BY v.filing_id
            ),
            reviewer_progress AS (
                SELECT
                    filing_id,
                    ARRAY(SELECT DISTINCT r FROM UNNEST(array_agg(reviewer_id)) r
                          WHERE r IS NOT NULL) AS reviewers
                FROM (
                    SELECT mf.filing_id, rd.reviewer_id
                    FROM v2_review_decisions rd
                    JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
                    WHERE rd.reviewer_id IS NOT NULL
                    UNION ALL
                    SELECT va.filing_id, ird.reviewer_id
                    FROM v2_image_review_decisions ird
                    JOIN v2_image_assets va ON va.img_id = ird.img_id
                    WHERE ird.reviewer_id IS NOT NULL
                ) AS combined
                GROUP BY filing_id
            ),
            candidates AS (
                SELECT
                    f.filing_id,
                    ROW_NUMBER() OVER (ORDER BY {order_col} {order_dir} NULLS LAST, c.company_name) AS rn,
                    COALESCE(tp.facts_pending, 0) AS facts_pending,
                    COALESCE(ip.images_pending, 0) AS images_pending,
                    COALESCE(ip.images_legacy_pending, 0) AS images_legacy_pending
                FROM filings f
                JOIN companies c ON f.company_id = c.company_id
                JOIN v2_documents d ON d.filing_id = f.filing_id
                LEFT JOIN text_progress     tp ON tp.filing_id = f.filing_id
                LEFT JOIN image_progress    ip ON ip.filing_id = f.filing_id
                LEFT JOIN reviewer_progress rp ON rp.filing_id = f.filing_id
                WHERE (f.is_spac IS NOT TRUE)
                {doc_type_filter}
                {completed_filter}
                {reviewer_filter}
            ),
            current_rn AS (
                SELECT rn FROM candidates WHERE filing_id = %(current_filing_id)s
            )
            SELECT filing_id
            FROM candidates
            WHERE rn > (SELECT rn FROM current_rn)
              {pending_filter}
            ORDER BY rn ASC
            LIMIT 1
        """
        result = self.query(sql, params)
        return result[0]["filing_id"] if result else None

    def get_distinct_reviewers(self) -> list[str]:
        """Return the sorted list of distinct reviewer_ids across all V2
        decision tables.

        Used to populate the "Reviewed by" filter dropdown on the unified
        filings list. Cheap — both source columns have partial indexes on
        reviewer_id and the result set is tiny (bounded by the number of
        distinct reviewers).
        """
        sql = """
            SELECT reviewer_id
            FROM v2_review_decisions
            WHERE reviewer_id IS NOT NULL
            UNION
            SELECT reviewer_id
            FROM v2_image_review_decisions
            WHERE reviewer_id IS NOT NULL
            ORDER BY 1
        """
        return [row["reviewer_id"] for row in self.query(sql)]

    def get_filing_pending_counts(self, filing_id: int) -> dict[str, int]:
        """Return per-filing pending-review counts for text and image work.

        Used by `next_filing` (and any other smart-default landing) to pick
        between Text+Pending Review, Images, and Text+All Statuses without a
        full filings-list query.
        """
        sql = """
            SELECT
                COUNT(CASE WHEN mf.review_status = 'pending_review' THEN 1 END) AS facts_pending
            FROM v2_metric_facts mf
            WHERE mf.filing_id = %(filing_id)s
        """
        text_row = self.query(sql, {"filing_id": filing_id})
        facts_pending = int(text_row[0]["facts_pending"]) if text_row else 0

        sql_img = """
            SELECT
                COUNT(CASE WHEN v.review_status = 'pending' THEN 1 END) AS images_pending
            FROM v2_image_assets v
            WHERE v.filing_id = %(filing_id)s
              AND v.classification NOT IN ('decorative', 'logo', 'signature')
              AND v.filename IS NOT NULL AND v.filename != ''
        """
        img_row = self.query(sql_img, {"filing_id": filing_id})
        images_pending = int(img_row[0]["images_pending"]) if img_row else 0

        sql_legacy = """
            SELECT COUNT(DISTINCT ird.img_id) AS images_legacy_pending
            FROM v2_image_review_decisions ird
            WHERE ird.decision = 'relevant'
              AND ird.img_id IN (
                  SELECT img_id FROM v2_image_assets
                  WHERE filing_id = %(filing_id)s
                    AND classification NOT IN ('decorative', 'logo', 'signature')
                    AND filename IS NOT NULL AND filename != ''
              )
              AND NOT EXISTS (
                  SELECT 1 FROM v2_image_metric_confirmations imc
                  WHERE imc.img_id = ird.img_id
              )
        """
        legacy_row = self.query(sql_legacy, {"filing_id": filing_id})
        images_legacy_pending = int(legacy_row[0]["images_legacy_pending"]) if legacy_row else 0

        return {
            "facts_pending": facts_pending,
            "images_pending": images_pending,
            "images_legacy_pending": images_legacy_pending,
        }

    def get_v2_facts_for_filing(
        self,
        filing_id: int,
        status: str | None = None,
        metric_id: str | None = None,
        sort_by: str = "confidence_desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get V2 metric facts for a filing with optional review decisions.

        Args:
            filing_id: Filing ID
            status: Optional review_status filter ('pending_review', 'accepted', 'rejected', 'corrected', 'auto_accepted')
            metric_id: Optional canonical_metric_id filter
            sort_by: Sort order ('confidence_desc', 'confidence_asc', 'metric', 'period')
            limit: Maximum number of rows to return. None returns all rows.
            offset: Number of rows to skip (for pagination).

        Returns:
            List of fact dicts with LEFT JOINed review decision data.
        """
        conditions = ["mf.filing_id = %(filing_id)s"]
        params: dict[str, Any] = {"filing_id": filing_id}

        if status:
            conditions.append("mf.review_status = %(status)s")
            params["status"] = status

        if metric_id:
            conditions.append("mf.canonical_metric_id = %(metric_id)s")
            params["metric_id"] = metric_id

        where_clause = " AND ".join(conditions)

        # Sort options (safe - no user input in SQL)
        sort_map = {
            "confidence_desc": "mf.confidence DESC, mf.canonical_metric_id",
            "confidence_asc": "mf.confidence ASC, mf.canonical_metric_id",
            "metric": "mf.canonical_metric_id, mf.confidence DESC",
            "period": "mf.period_end DESC NULLS LAST, mf.canonical_metric_id",
        }
        order_clause = sort_map.get(sort_by, sort_map["confidence_desc"])

        sql = f"""
            SELECT
                mf.fact_id,
                mf.filing_id,
                mf.canonical_metric_id,
                mf.value,
                mf.value_raw,
                mf.unit,
                mf.currency,
                mf.period_type,
                mf.period_start,
                mf.period_end,
                mf.scope,
                mf.scope_detail,
                mf.cohort_def,
                mf.customer_type,
                mf.source_type,
                mf.source_locator,
                mf.evidence_pack,
                mf.confidence,
                mf.extraction_method,
                mf.requires_review,
                mf.review_reason,
                mf.review_status,
                mf.pipeline_version,
                mf.created_at,
                mf.updated_at,
                rd.decision_id,
                rd.decision,
                rd.assigned_metric_id AS decision_metric_id,
                rd.corrected_value,
                rd.rejection_reason,
                rd.rejection_category,
                rd.reviewer_id,
                rd.reviewer_notes,
                rd.review_time_seconds,
                rd.created_at AS decision_created_at
            FROM v2_metric_facts mf
            LEFT JOIN v2_review_decisions rd ON rd.fact_id = mf.fact_id
            WHERE {where_clause}
            ORDER BY {order_clause}
        """
        if limit is not None:
            sql += " LIMIT %(limit)s OFFSET %(offset)s"
            params["limit"] = limit
            params["offset"] = offset
        return self.query(sql, params)

    def count_v2_facts_for_filing(
        self,
        filing_id: int,
        status: str | None = None,
        metric_id: str | None = None,
    ) -> int:
        """Return count of V2 metric facts for a filing, with optional filters."""
        conditions = ["mf.filing_id = %(filing_id)s"]
        params: dict[str, Any] = {"filing_id": filing_id}
        if status:
            conditions.append("mf.review_status = %(status)s")
            params["status"] = status
        if metric_id:
            conditions.append("mf.canonical_metric_id = %(metric_id)s")
            params["metric_id"] = metric_id
        where_clause = " AND ".join(conditions)
        sql = f"SELECT COUNT(*) AS cnt FROM v2_metric_facts mf WHERE {where_clause}"
        result = self.query(sql, params)
        return result[0]["cnt"] if result else 0

    def get_segment_context(self, filing_id: int, segment_id: str, window: int = 2) -> list[dict]:
        """
        Return the target segment plus up to `window` neighbors on each side,
        ordered by sequence_idx. Used to show surrounding paragraph context
        in the V2 review UI when evidence_pack lacks context_before/after.
        """
        return self.query(
            """
            WITH target AS (
                SELECT sequence_idx
                FROM v2_segments
                WHERE segment_id = %(segment_id)s AND filing_id = %(filing_id)s
            )
            SELECT s.segment_id::text, s.segment_type, s.segment_text,
                   s.section_path, s.section_type, s.sequence_idx
            FROM v2_segments s, target t
            WHERE s.filing_id = %(filing_id)s
              AND s.sequence_idx BETWEEN t.sequence_idx - %(window)s
                                     AND t.sequence_idx + %(window)s
            ORDER BY s.sequence_idx
            """,
            {"filing_id": filing_id, "segment_id": segment_id, "window": window},
        )

    def get_v2_image_ocr_segments_for_filing(self, filing_id: int) -> list[dict]:
        """
        Return v2_segments rows synthesized from full-page-image OCR
        (source_type='image_ocr'), joined to their source v2_image_assets row.

        Used by the unified review text tab to surface OCR'd image text even
        when the extraction pipeline produced no v2_metric_facts rows from it.
        Each row links back to its source image via source_img_id so the
        reviewer can click through to the image queue.
        """
        return self.query(
            """
            SELECT s.segment_id::text AS segment_id,
                   s.segment_text,
                   s.sequence_idx,
                   s.section_path,
                   s.section_type,
                   s.source_img_id::text AS source_img_id,
                   ia.filename AS image_filename,
                   ia.ocr_text AS image_ocr_text
            FROM v2_segments s
            LEFT JOIN v2_image_assets ia ON ia.img_id = s.source_img_id
            WHERE s.filing_id = %(filing_id)s
              AND s.source_type = 'image_ocr'
            ORDER BY s.sequence_idx
            """,
            {"filing_id": filing_id},
        )

    def get_table_context(self, filing_id: int, table_id: str) -> dict | None:
        """
        Return table metadata and a reconstructed HTML table for a V2 table fact.
        Used to show the full table in the review UI when evidence_pack
        only has header_path/stub_path with no surrounding text.

        raw_html is not stored in the DB (persistence.py drops it), so the
        HTML is reconstructed from v2_table_cells.
        """
        meta_rows = self.query(
            """
            SELECT table_id::text, section_path, section_type, row_count, col_count
            FROM v2_tables
            WHERE table_id = %(table_id)s AND filing_id = %(filing_id)s
            LIMIT 1
            """,
            {"filing_id": filing_id, "table_id": table_id},
        )
        if not meta_rows:
            return None
        meta = dict(meta_rows[0])

        cell_rows = self.query(
            """
            SELECT row_idx, col_idx, cell_text, is_header, is_stub
            FROM v2_table_cells
            WHERE table_id = %(table_id)s
            ORDER BY row_idx, col_idx
            """,
            {"table_id": table_id},
        )

        # Reconstruct HTML table from cells
        if cell_rows:
            grid: dict[tuple[int, int], dict] = {(r["row_idx"], r["col_idx"]): r for r in cell_rows}
            max_row = max(r["row_idx"] for r in cell_rows)
            max_col = max(r["col_idx"] for r in cell_rows)
            html_parts = [
                '<table class="table table-sm table-bordered" style="font-size:0.82rem;">'
            ]
            for row in range(max_row + 1):
                html_parts.append("<tr>")
                for col in range(max_col + 1):
                    cell = grid.get((row, col))
                    text = cell["cell_text"] if cell else ""
                    tag = "th" if (cell and (cell["is_header"] or cell["is_stub"])) else "td"
                    html_parts.append(f"<{tag}>{text}</{tag}>")
                html_parts.append("</tr>")
            html_parts.append("</table>")
            meta["raw_html"] = "".join(html_parts)
        else:
            meta["raw_html"] = None

        return meta

    def get_v2_fact_by_id(self, fact_id: str) -> dict | None:
        """Get a single V2 fact by its UUID."""
        rows = self.query(
            """
            SELECT mf.*, rd.decision_id, rd.decision, rd.reviewer_id, rd.created_at AS decision_created_at
            FROM v2_metric_facts mf
            LEFT JOIN v2_review_decisions rd ON rd.fact_id = mf.fact_id
            WHERE mf.fact_id = %(fact_id)s
            """,
            {"fact_id": fact_id},
        )
        return rows[0] if rows else None

    def insert_v2_review_decision(
        self,
        fact_id: str,
        decision: str,
        reviewer_id: str = "web_reviewer",
        assigned_metric_id: str | None = None,
        corrected_value: float | None = None,
        rejection_reason: str | None = None,
        rejection_category: str | None = None,
        reviewer_notes: str | None = None,
        review_time_seconds: int | None = None,
    ) -> str:
        """
        Insert a V2 review decision. The DB trigger auto-updates review_status on v2_metric_facts.

        Args:
            fact_id: UUID of the metric fact being reviewed
            decision: 'accept', 'reject', or 'correct'
            reviewer_id: Identifier for the reviewer
            assigned_metric_id: If corrected to a different metric
            corrected_value: If value was corrected
            rejection_reason: Free-text reason for rejection
            rejection_category: Category of rejection
            reviewer_notes: Additional notes
            review_time_seconds: Time spent reviewing

        Returns:
            decision_id (UUID) of the inserted decision
        """
        sql = """
            INSERT INTO v2_review_decisions (
                fact_id, decision, assigned_metric_id, corrected_value,
                rejection_reason, rejection_category,
                reviewer_id, reviewer_notes, review_time_seconds
            )
            VALUES (
                %(fact_id)s, %(decision)s, %(assigned_metric_id)s, %(corrected_value)s,
                %(rejection_reason)s, %(rejection_category)s,
                %(reviewer_id)s, %(reviewer_notes)s, %(review_time_seconds)s
            )
            RETURNING decision_id
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "fact_id": fact_id,
                        "decision": decision,
                        "assigned_metric_id": assigned_metric_id,
                        "corrected_value": corrected_value,
                        "rejection_reason": rejection_reason,
                        "rejection_category": rejection_category,
                        "reviewer_id": reviewer_id,
                        "reviewer_notes": reviewer_notes,
                        "review_time_seconds": review_time_seconds,
                    },
                )
                result = cur.fetchone()
                return str(result["decision_id"])

    def delete_v2_review_decision(self, decision_id: str) -> dict | None:
        """
        Delete a V2 review decision (undo). Resets fact review_status to pending_review.

        Args:
            decision_id: UUID of the decision to delete

        Returns:
            Dict with fact_id and filing_id if deleted, None if not found
        """
        # Get fact_id before deleting
        decision = self.query(
            """
            SELECT rd.decision_id, rd.fact_id, mf.filing_id
            FROM v2_review_decisions rd
            JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
            WHERE rd.decision_id = %(decision_id)s
            """,
            {"decision_id": decision_id},
        )
        if not decision:
            return None

        fact_id = decision[0]["fact_id"]
        filing_id = decision[0]["filing_id"]

        # Delete decision
        self.execute(
            "DELETE FROM v2_review_decisions WHERE decision_id = %(decision_id)s",
            {"decision_id": decision_id},
        )

        # Reset fact status (trigger only fires on INSERT, not DELETE)
        self.execute(
            """
            UPDATE v2_metric_facts
            SET review_status = CASE
                WHEN requires_review THEN 'pending_review'
                ELSE 'auto_accepted'
            END,
            updated_at = NOW()
            WHERE fact_id = %(fact_id)s
            """,
            {"fact_id": fact_id},
        )

        return {"fact_id": str(fact_id), "filing_id": filing_id}

    def insert_manual_v2_metric_fact(
        self,
        filing_id: int,
        canonical_metric_id: str,
        value_raw: str,
        value: float | None,
        unit: str,
        period_type: str | None,
        period_end: str | None,
        scope: str,
        reviewer_id: str,
        reviewer_notes: str | None,
    ) -> str:
        """
        Manually add a metric fact that the pipeline missed.

        Creates both the fact record and its review decision in a single
        transaction. The fact is inserted with review_status='accepted' and
        extraction_method='manual' so it bypasses the normal review queue.

        Args:
            filing_id: Filing ID (maps to v2_metric_facts.filing_id).
            canonical_metric_id: Metric identifier from the metrics table.
            value_raw: Original text representation, e.g. "112%".
            value: Parsed numeric value, or None if not parseable.
            unit: One of 'percent', 'currency', 'count', 'ratio',
                  'basis_points', 'other'.
            period_type: One of 'annual', 'quarterly', 'trailing', 'ytd',
                         'point_in_time', 'other', or None.
            period_end: ISO date string (YYYY-MM-DD) or None.
            scope: One of 'company', 'segment', 'geography', 'product',
                   'customer_type', 'cohort', 'other'.
            reviewer_id: Identifier for the reviewer.
            reviewer_notes: Optional notes; "Manually added: " prefix is
                            prepended when None.

        Returns:
            fact_id (UUID string) of the newly inserted fact.
        """
        notes = (
            reviewer_notes if reviewer_notes is not None else "Manually added: no notes provided"
        )

        fact_sql = """
            INSERT INTO v2_metric_facts (
                fact_id,
                filing_id,
                canonical_metric_id,
                value,
                value_raw,
                unit,
                period_type,
                period_end,
                scope,
                source_type,
                source_locator,
                evidence_pack,
                confidence,
                extraction_method,
                requires_review,
                review_status,
                pipeline_version
            )
            VALUES (
                gen_random_uuid(),
                %(filing_id)s,
                %(canonical_metric_id)s,
                %(value)s,
                %(value_raw)s,
                %(unit)s,
                %(period_type)s,
                %(period_end)s::DATE,
                %(scope)s,
                'text',
                '{}',
                '{}',
                1.0,
                'manual',
                FALSE,
                'accepted',
                '2.0.0'
            )
            RETURNING fact_id
        """
        decision_sql = """
            INSERT INTO v2_review_decisions (
                fact_id,
                decision,
                reviewer_id,
                reviewer_notes
            )
            VALUES (
                %(fact_id)s,
                'accept',
                %(reviewer_id)s,
                %(reviewer_notes)s
            )
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    fact_sql,
                    {
                        "filing_id": filing_id,
                        "canonical_metric_id": canonical_metric_id,
                        "value": value,
                        "value_raw": value_raw,
                        "unit": unit,
                        "period_type": period_type,
                        "period_end": period_end,
                        "scope": scope,
                    },
                )
                row = cur.fetchone()
                fact_id = str(row["fact_id"])
                cur.execute(
                    decision_sql,
                    {
                        "fact_id": fact_id,
                        "reviewer_id": reviewer_id,
                        "reviewer_notes": notes,
                    },
                )
        return fact_id

    def get_v2_review_stats(self) -> dict:
        """
        Return aggregate V2 review statistics across all companies/filings.

        Returns a dict with:
          - ``per_company``: list of per-company rows (company_name, cik,
            filing_count, fact_count, reviewed_count, pending_count,
            accepted_count, rejected_count, auto_accepted_count)
          - ``totals``: aggregate totals across all companies
          - ``confidence_bands``: counts for high (>=0.9), medium (0.7-0.9),
            low (<0.7) confidence facts
        """
        per_company_sql = """
            SELECT
                c.company_name,
                c.cik,
                c.ticker,
                COUNT(DISTINCT f.filing_id)                                         AS filing_count,
                COUNT(mf.fact_id)                                                   AS fact_count,
                COUNT(CASE WHEN mf.review_status != 'pending_review' THEN 1 END)   AS reviewed_count,
                COUNT(CASE WHEN mf.review_status = 'pending_review' THEN 1 END)    AS pending_count,
                COUNT(CASE WHEN mf.review_status = 'accepted' THEN 1 END)          AS accepted_count,
                COUNT(CASE WHEN mf.review_status = 'rejected' THEN 1 END)          AS rejected_count,
                COUNT(CASE WHEN mf.review_status = 'corrected' THEN 1 END)         AS corrected_count,
                COUNT(CASE WHEN mf.review_status = 'auto_accepted' THEN 1 END)     AS auto_accepted_count
            FROM companies c
            JOIN filings f ON f.company_id = c.company_id
            JOIN v2_documents d ON d.filing_id = f.filing_id
            LEFT JOIN v2_metric_facts mf ON mf.filing_id = d.filing_id
            GROUP BY c.company_id, c.company_name, c.cik, c.ticker
            ORDER BY c.company_name
        """
        per_company = self.query(per_company_sql)

        totals_sql = """
            SELECT
                COUNT(DISTINCT f.filing_id)                                         AS filing_count,
                COUNT(mf.fact_id)                                                   AS fact_count,
                COUNT(CASE WHEN mf.review_status != 'pending_review' THEN 1 END)   AS reviewed_count,
                COUNT(CASE WHEN mf.review_status = 'pending_review' THEN 1 END)    AS pending_count,
                COUNT(CASE WHEN mf.review_status = 'accepted' THEN 1 END)          AS accepted_count,
                COUNT(CASE WHEN mf.review_status = 'rejected' THEN 1 END)          AS rejected_count,
                COUNT(CASE WHEN mf.review_status = 'corrected' THEN 1 END)         AS corrected_count,
                COUNT(CASE WHEN mf.review_status = 'auto_accepted' THEN 1 END)     AS auto_accepted_count
            FROM filings f
            JOIN v2_documents d ON d.filing_id = f.filing_id
            LEFT JOIN v2_metric_facts mf ON mf.filing_id = d.filing_id
        """
        totals_rows = self.query(totals_sql)
        totals = dict(totals_rows[0]) if totals_rows else {}

        bands_sql = """
            SELECT
                COUNT(CASE WHEN mf.confidence >= 0.9 THEN 1 END)                   AS high_count,
                COUNT(CASE WHEN mf.confidence >= 0.7 AND mf.confidence < 0.9 THEN 1 END) AS medium_count,
                COUNT(CASE WHEN mf.confidence < 0.7 THEN 1 END)                    AS low_count,
                COUNT(mf.fact_id)                                                   AS total_count
            FROM v2_metric_facts mf
        """
        bands_rows = self.query(bands_sql)
        confidence_bands = (
            dict(bands_rows[0])
            if bands_rows
            else {
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "total_count": 0,
            }
        )

        return {
            "per_company": [dict(r) for r in per_company],
            "totals": totals,
            "confidence_bands": confidence_bands,
        }

    def get_analytics_surface_health(self) -> dict:
        """Return availability + row counts for analytics-facing views.

        This helps detect schema drift after DB migrations land but Metabase
        questions/dashboards have not yet been updated.
        """
        rows = self.query(
            """
            SELECT table_name
            FROM information_schema.views
            WHERE table_schema = 'public'
              AND table_name IN (
                'v_analytics_fact_wide',
                'v_analytics_coverage_matrix',
                'v_doc_metric_presence'
              )
            """
        )
        present = {r["table_name"] for r in rows}

        def _count_if_present(view_name: str) -> int | None:
            if view_name not in present:
                return None
            cnt = self.query(f"SELECT COUNT(*) AS n FROM {view_name}")
            return int(cnt[0]["n"]) if cnt else 0

        return {
            "v_analytics_fact_wide": _count_if_present("v_analytics_fact_wide"),
            "v_analytics_coverage_matrix": _count_if_present("v_analytics_coverage_matrix"),
            "v_doc_metric_presence": _count_if_present("v_doc_metric_presence"),
        }

    # =============================================================================
    # V2 Image Review Methods (read/write v2_image_assets + v2_image_review_decisions)
    # =============================================================================

    @staticmethod
    def _compute_image_content_hash(ocr_text: str | None, chart_data_json: str | None) -> str:
        """Compute a content hash for stale-decision detection.

        Recipe (locked): sha256((ocr_text or "") + "\\x1f" + (chart_data_json or ""))
        The unit separator (\\x1f) prevents collisions between the two fields.
        """
        payload = (ocr_text or "") + "\x1f" + (chart_data_json or "")
        return hashlib.sha256(payload.encode()).hexdigest()

    _V2_IMAGE_CANDIDATE_SELECT = """
        v.img_id,
        v.filing_id,
        f.company_id,
        v.filename,
        v.filename AS image_src,
        '/images/cache/'
            || COALESCE(NULLIF(REGEXP_REPLACE(c.cik, '^0+', ''), ''), '0')
            || '/'
            || REPLACE(
                 CASE
                   WHEN f.accession_number LIKE 'presentation:%%'
                     THEN split_part(substring(f.accession_number FROM 14), '/', 2)
                   ELSE f.accession_number
                 END,
                 '-', '')
            || '/' || v.filename AS image_url,
        'https://www.sec.gov/Archives/edgar/data/'
            || COALESCE(NULLIF(REGEXP_REPLACE(c.cik, '^0+', ''), ''), '0')
            || '/'
            || REPLACE(
                 CASE
                   WHEN f.accession_number LIKE 'presentation:%%'
                     THEN split_part(substring(f.accession_number FROM 14), '/', 2)
                   ELSE f.accession_number
                 END,
                 '-', '')
            || '/' || v.filename AS image_src_url,
        v.width AS image_width,
        v.height AS image_height,
        v.nearby_text AS preceding_text,
        v.detected_keywords,
        v.classification,
        v.relevance_score AS cohort_confidence,
        v.predicted_relevance,
        v.review_status,
        v.section_type,
        (v.classification IN ('decorative', 'logo', 'signature')) AS is_decorative,
        NOT (
            (v.classification = 'chart' AND v.relevance_score >= 0.6)
            OR (v.classification IN ('chart', 'table_image')
                AND COALESCE(v.width, 0) >= 300
                AND COALESCE(v.height, 0) >= 300)
        ) AS auto_reject_candidate,
        CASE
            WHEN v.classification = 'chart' AND v.relevance_score >= 0.6
                THEN 'tier_1_cohort'
            WHEN v.classification IN ('chart', 'table_image')
                 AND COALESCE(v.width, 0) >= 300
                 AND COALESCE(v.height, 0) >= 300
                THEN 'tier_2_large'
            ELSE 'tier_3_all'
        END AS detection_tier,
        v.detected_metrics,
        v.created_at,
        d.image_decision_id,
        d.decision,
        (d.decision = 'relevant') AS legacy_decision,
        d.chart_type,
        d.rejection_reason,
        d.reviewer_notes AS decision_notes,
        d.review_time_seconds,
        d.created_at AS decision_created_at,
        d.decided_against_hash,
        v.ocr_text AS current_ocr_text,
        v.chart_data::text AS current_chart_data_json,
        COALESCE(imc_rollup.positive_count, 0) AS positive_count,
        COALESCE(imc_rollup.detected_decided_count, 0) AS detected_decided_count,
        COALESCE(imc_rollup.total_confirmation_count, 0) AS total_confirmation_count,
        COALESCE(imc_rollup.has_add, FALSE) AS has_add
    """

    # Lateral join over per-metric confirmations. Embedded by every consumer of
    # _V2_IMAGE_CANDIDATE_SELECT so the four imc_rollup.* projections resolve.
    # Use COUNT(DISTINCT ...) so multi-reviewer rows don't double-count.
    _V2_IMAGE_CONFIRMATION_ROLLUP_JOIN = """
        LEFT JOIN LATERAL (
            SELECT
                COUNT(DISTINCT confirmed_metric_id) FILTER (
                    WHERE decision IN ('accept', 'correct', 'add')
                      AND confirmed_metric_id IS NOT NULL
                ) AS positive_count,
                COUNT(DISTINCT detected_metric_id) FILTER (
                    WHERE detected_metric_id IS NOT NULL
                      AND decision IN ('accept', 'reject', 'correct')
                ) AS detected_decided_count,
                COUNT(*) AS total_confirmation_count,
                BOOL_OR(decision = 'add') AS has_add
            FROM v2_image_metric_confirmations
            WHERE img_id = v.img_id
        ) imc_rollup ON TRUE
    """

    @staticmethod
    def _derive_image_review_state(row: dict) -> str:
        """Map per-metric confirmation rollup to a thumbnail indicator.

        Returns one of "relevant" (✓), "no_relevant" (✗), or "pending" (no glyph).
        Skip is treated as a punt, not a decision — partial-skip leaves the
        image in pending until every detected metric has accept/reject/correct.
        """
        if row.get("review_status") in ("skipped", "auto_rejected"):
            return "no_relevant"

        detected = row.get("detected_metrics") or []
        detected_count = len(detected) if isinstance(detected, list) else 0
        total = row.get("total_confirmation_count") or 0
        decided = row.get("detected_decided_count") or 0
        positive = row.get("positive_count") or 0

        if detected_count == 0 and total == 0:
            return "pending"
        if decided >= detected_count and positive > 0:
            return "relevant"
        if decided >= detected_count and positive == 0:
            return "no_relevant"
        return "pending"

    @staticmethod
    def _derive_is_stale_vs_decision(row: dict) -> bool:
        """Return True if the image content has changed since the last decision.

        Compares the stored ``decided_against_hash`` on the most-recent
        ``v2_image_review_decisions`` row against a freshly-computed hash of
        the asset's current ``ocr_text`` / ``chart_data``.

        NULL ``decided_against_hash`` → False (grandfather clause for
        pre-deploy rows — do not flag as stale without a baseline hash).
        """
        stored_hash = row.get("decided_against_hash")
        if not stored_hash:
            return False

        current_hash = DatabaseAdapter._compute_image_content_hash(
            row.get("current_ocr_text"),
            row.get("current_chart_data_json"),
        )
        return current_hash != stored_hash

    def get_image_review_candidates_for_filing_v2(
        self,
        filing_id: int,
        status: str | None = None,
        sort_by: str = "relevance",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        V2-native image review candidate query.

        Reads v2_image_assets LEFT JOIN v2_image_review_decisions and projects a row
        shape compatible with the V1 template (`image_src`, `image_url`, `image_width`,
        `image_height`, `preceding_text`, `cohort_confidence`, derived `detection_tier`,
        derived `is_decorative`). Non-decorative images only.

        Sort options: 'relevance' (predicted then cohort), 'tier', 'position' (img_id).
        """
        if status is not None:
            validate_enum(status, IMAGE_REVIEW_FILTER_STATUSES, "review_status")

        valid_sort_options = ("tier", "relevance", "position")
        if sort_by not in valid_sort_options:
            raise ValidationError(
                f"Invalid sort_by '{sort_by}'. Must be one of: {valid_sort_options}"
            )

        status_filter = ""
        params: dict[str, Any] = {
            "filing_id": filing_id,
            "limit": limit,
            "offset": offset,
        }
        if status == "legacy_backfill":
            status_filter = (
                "AND EXISTS ("
                "    SELECT 1 FROM v2_image_review_decisions ird"
                "    WHERE ird.img_id = v.img_id AND ird.decision = 'relevant'"
                ") AND NOT EXISTS ("
                "    SELECT 1 FROM v2_image_metric_confirmations imc"
                "    WHERE imc.img_id = v.img_id"
                ")"
            )
        elif status:
            status_filter = "AND v.review_status = %(status)s"
            params["status"] = status

        if sort_by == "relevance":
            order_by = (
                "v.predicted_relevance DESC NULLS LAST, "
                "v.relevance_score DESC NULLS LAST, v.img_id ASC"
            )
        elif sort_by == "tier":
            order_by = """
                CASE
                    WHEN v.classification = 'chart' AND v.relevance_score >= 0.6 THEN 1
                    WHEN v.classification IN ('chart', 'table_image')
                         AND COALESCE(v.width, 0) >= 300
                         AND COALESCE(v.height, 0) >= 300 THEN 2
                    ELSE 3
                END ASC,
                v.relevance_score DESC NULLS LAST, v.img_id ASC
            """
        else:  # position
            order_by = "v.img_id ASC"

        # Dedup by (filing_id, filename): repeated extraction runs produce fresh
        # img_id UUIDs for the same file, so v2_image_assets can hold multiple
        # rows per physical image. Keep the most recent row per filename —
        # prefer rows that already have a review decision so reviewer work
        # is not hidden behind a newer un-reviewed duplicate.
        sql = f"""
            WITH deduped_img AS (
                SELECT DISTINCT ON (filing_id, filename) img_id
                FROM v2_image_assets
                WHERE filing_id = %(filing_id)s
                ORDER BY
                    filing_id,
                    filename,
                    EXISTS (
                        SELECT 1 FROM v2_image_review_decisions rd
                        WHERE rd.img_id = v2_image_assets.img_id
                    ) DESC,
                    created_at DESC NULLS LAST
            )
            SELECT {self._V2_IMAGE_CANDIDATE_SELECT},
                ic.classification_id,
                ic.predicted_metrics,
                ic.confidence        AS classification_confidence
            FROM v2_image_assets v
            JOIN filings f ON v.filing_id = f.filing_id
            JOIN companies c ON f.company_id = c.company_id
            LEFT JOIN v2_image_review_decisions d ON d.img_id = v.img_id
            LEFT JOIN LATERAL (
                SELECT classification_id, predicted_metrics, confidence
                FROM v2_image_classifications
                WHERE img_id = v.img_id
                ORDER BY created_at DESC
                LIMIT 1
            ) ic ON true
            {self._V2_IMAGE_CONFIRMATION_ROLLUP_JOIN}
            WHERE v.filing_id = %(filing_id)s
              AND v.img_id IN (SELECT img_id FROM deduped_img)
              AND v.classification NOT IN ('decorative', 'logo', 'signature')
              AND v.filename IS NOT NULL
              AND v.filename != ''
              {status_filter}
            ORDER BY {order_by}
            LIMIT %(limit)s OFFSET %(offset)s
        """
        results = self.query(sql, params)
        for row in results:
            row["image_review_state"] = self._derive_image_review_state(row)
            row["is_stale_vs_decision"] = self._derive_is_stale_vs_decision(row)
        return results

    def get_image_review_candidate_v2(self, img_id: str) -> dict | None:
        """V2-native single-image fetch with decision (if any)."""
        sql = f"""
            SELECT {self._V2_IMAGE_CANDIDATE_SELECT},
                f.accession_number, c.company_name, c.cik, c.ticker,
                ic.classification_id,
                ic.predicted_metrics,
                ic.confidence        AS classification_confidence
            FROM v2_image_assets v
            JOIN filings f ON v.filing_id = f.filing_id
            JOIN companies c ON f.company_id = c.company_id
            LEFT JOIN v2_image_review_decisions d ON d.img_id = v.img_id
            LEFT JOIN LATERAL (
                SELECT classification_id, predicted_metrics, confidence
                FROM v2_image_classifications
                WHERE img_id = v.img_id
                ORDER BY created_at DESC
                LIMIT 1
            ) ic ON true
            {self._V2_IMAGE_CONFIRMATION_ROLLUP_JOIN}
            WHERE v.img_id = %(img_id)s
        """
        results = self.query(sql, {"img_id": img_id})
        if not results:
            return None
        results[0]["image_review_state"] = self._derive_image_review_state(results[0])
        results[0]["is_stale_vs_decision"] = self._derive_is_stale_vs_decision(results[0])
        return results[0]

    def get_next_pending_image_candidate_v2(
        self,
        filing_id: int,
        current_img_id: str | None = None,
        include_skipped: bool = False,
    ) -> dict | None:
        """
        Return the next pending (or optionally skipped) V2 image for the filing.

        Ordering matches `get_image_review_candidates_for_filing_v2(sort_by='relevance')`
        so "next" tracks UI order.
        """
        status_list = ["pending", "skipped"] if include_skipped else ["pending"]
        params: dict[str, Any] = {
            "filing_id": filing_id,
            "status_list": status_list,
        }
        cursor_filter = ""
        if current_img_id is not None:
            cursor_filter = """
                AND (
                    v.predicted_relevance < (
                        SELECT predicted_relevance FROM v2_image_assets WHERE img_id = %(current_img_id)s
                    )
                    OR (
                        v.predicted_relevance IS NOT DISTINCT FROM (
                            SELECT predicted_relevance FROM v2_image_assets WHERE img_id = %(current_img_id)s
                        )
                        AND v.img_id > %(current_img_id)s::uuid
                    )
                )
            """
            params["current_img_id"] = current_img_id

        # Dedup by (filing_id, filename) — see get_image_review_candidates_for_filing_v2.
        sql = f"""
            WITH deduped_img AS (
                SELECT DISTINCT ON (filing_id, filename) img_id
                FROM v2_image_assets
                WHERE filing_id = %(filing_id)s
                ORDER BY
                    filing_id,
                    filename,
                    EXISTS (
                        SELECT 1 FROM v2_image_review_decisions rd
                        WHERE rd.img_id = v2_image_assets.img_id
                    ) DESC,
                    created_at DESC NULLS LAST
            )
            SELECT {self._V2_IMAGE_CANDIDATE_SELECT}
            FROM v2_image_assets v
            JOIN filings f ON v.filing_id = f.filing_id
            JOIN companies c ON f.company_id = c.company_id
            LEFT JOIN v2_image_review_decisions d ON d.img_id = v.img_id
            {self._V2_IMAGE_CONFIRMATION_ROLLUP_JOIN}
            WHERE v.filing_id = %(filing_id)s
              AND v.img_id IN (SELECT img_id FROM deduped_img)
              AND v.review_status = ANY(%(status_list)s)
              AND v.classification NOT IN ('decorative', 'logo', 'signature')
              AND v.filename IS NOT NULL
              AND v.filename != ''
              {cursor_filter}
            ORDER BY v.predicted_relevance DESC NULLS LAST,
                     v.relevance_score DESC NULLS LAST, v.img_id ASC
            LIMIT 1
        """
        results = self.query(sql, params)
        return results[0] if results else None

    def insert_image_review_decision_v2(
        self,
        img_id: str,
        decision: str,
        chart_type: str | None = None,
        rejection_reason: str | None = None,
        reviewer_id: str | None = None,
        reviewer_notes: str | None = None,
        review_time_seconds: int | None = None,
    ) -> int:
        """
        V2-native decision insert. Atomically inserts the decision row AND sets
        v2_image_assets.review_status = 'reviewed' in one transaction.
        """
        validate_enum(decision, IMAGE_DECISIONS, "decision")
        if chart_type is not None:
            validate_enum(chart_type, IMAGE_CHART_TYPES, "chart_type")
        if rejection_reason is not None:
            validate_enum(rejection_reason, IMAGE_REJECTION_REASONS, "rejection_reason")
        if decision == "relevant" and not chart_type:
            raise ValidationError("Decision 'relevant' requires chart_type")
        if decision == "not_relevant" and not rejection_reason:
            raise ValidationError("Decision 'not_relevant' requires rejection_reason")

        insert_sql = """
            INSERT INTO v2_image_review_decisions (
                img_id, decision, chart_type, rejection_reason,
                reviewer_id, reviewer_notes, review_time_seconds,
                decided_against_hash
            )
            VALUES (
                %(img_id)s, %(decision)s, %(chart_type)s, %(rejection_reason)s,
                %(reviewer_id)s, %(reviewer_notes)s, %(review_time_seconds)s,
                %(decided_against_hash)s
            )
            RETURNING image_decision_id
        """
        update_status_sql = """
            UPDATE v2_image_assets
            SET review_status = 'reviewed'
            WHERE img_id = %(img_id)s
        """
        fetch_asset_sql = """
            SELECT ocr_text,
                   chart_data::text AS chart_data_json
            FROM v2_image_assets
            WHERE img_id = %(img_id)s
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(fetch_asset_sql, {"img_id": img_id})
                asset_row = cur.fetchone()
                if asset_row:
                    decided_against_hash = self._compute_image_content_hash(
                        asset_row["ocr_text"],
                        asset_row["chart_data_json"],
                    )
                else:
                    decided_against_hash = None

                cur.execute(
                    insert_sql,
                    {
                        "img_id": img_id,
                        "decision": decision,
                        "chart_type": chart_type,
                        "rejection_reason": rejection_reason,
                        "reviewer_id": reviewer_id,
                        "reviewer_notes": reviewer_notes,
                        "review_time_seconds": review_time_seconds,
                        "decided_against_hash": decided_against_hash,
                    },
                )
                result = cur.fetchone()
                decision_id = int(result["image_decision_id"])
                cur.execute(update_status_sql, {"img_id": img_id})

        logger.debug(
            f"Inserted v2 image decision: decision_id={decision_id}, "
            f"img_id={img_id}, decision={decision}"
        )
        return decision_id

    def delete_image_review_decision_v2(self, image_decision_id: int) -> bool:
        """V2-native decision undo. Deletes the decision row and reverts
        v2_image_assets.review_status back to 'pending'."""
        get_img_sql = """
            SELECT img_id FROM v2_image_review_decisions
            WHERE image_decision_id = %(id)s
        """
        delete_sql = """
            DELETE FROM v2_image_review_decisions
            WHERE image_decision_id = %(id)s
        """
        reset_sql = """
            UPDATE v2_image_assets SET review_status = 'pending'
            WHERE img_id = %(img_id)s
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(get_img_sql, {"id": image_decision_id})
                row = cur.fetchone()
                if not row:
                    return False
                img_id = row["img_id"]
                cur.execute(delete_sql, {"id": image_decision_id})
                cur.execute(reset_sql, {"img_id": img_id})

        logger.debug(
            f"Deleted v2 image decision: decision_id={image_decision_id}, "
            f"reset img_id={img_id} to pending"
        )
        return True

    def skip_image_candidate_v2(self, img_id: str) -> bool:
        """Set v2_image_assets.review_status = 'skipped' for a single image."""
        sql = """
            UPDATE v2_image_assets
            SET review_status = 'skipped'
            WHERE img_id = %(img_id)s
            RETURNING img_id
        """
        result = self.query(sql, {"img_id": img_id})
        return len(result) > 0

    def unskip_image_candidate_v2(self, img_id: str) -> bool:
        """Revert a skipped v2_image_assets row back to 'pending'."""
        sql = """
            UPDATE v2_image_assets
            SET review_status = 'pending'
            WHERE img_id = %(img_id)s
              AND review_status = 'skipped'
            RETURNING img_id
        """
        result = self.query(sql, {"img_id": img_id})
        return len(result) > 0

    def mark_image_reviewed_v2(self, img_id: str) -> bool:
        """Flip v2_image_assets.review_status='pending' -> 'reviewed'.

        Idempotent: re-clicking is safe (the WHERE clause matches both 'pending'
        and 'reviewed'). Does NOT override 'skipped' or 'auto_rejected' — the
        reviewer must unskip first to flip those. Mirrors skip_image_candidate_v2's
        bare-UPDATE shape; per-transition audit lives in v2_image_metric_confirmations,
        not on the v2_image_assets row.
        """
        sql = """
            UPDATE v2_image_assets
            SET review_status = 'reviewed'
            WHERE img_id = %(img_id)s
              AND review_status IN ('pending', 'reviewed')
            RETURNING img_id
        """
        result = self.query(sql, {"img_id": img_id})
        return len(result) > 0

    def reopen_image_candidate_v2(self, img_id: str) -> bool:
        """Flip review_status='reviewed' -> 'pending'. Returns True if a row was updated.

        Preserves v2_image_review_decisions and v2_image_metric_confirmations rows
        (ML training signal — see CLAUDE.md).
        """
        sql = """
            UPDATE v2_image_assets
            SET review_status = 'pending'
            WHERE img_id = %(img_id)s
              AND review_status = 'reviewed'
            RETURNING img_id
        """
        result = self.query(sql, {"img_id": img_id})
        return len(result) > 0

    def get_image_review_progress_v2(self, filing_id: int | None = None) -> dict[str, Any]:
        """
        V2-native progress counts. If filing_id is given, counts are filing-scoped;
        otherwise they are across all filings. Only non-decorative images are counted
        (matches queue semantics used by the UI).
        """
        filter_clause = "AND v.filing_id = %(filing_id)s" if filing_id is not None else ""
        params: dict[str, Any] = {}
        if filing_id is not None:
            params["filing_id"] = filing_id

        sql = f"""
            SELECT
                COUNT(*) AS total_candidates,
                COUNT(*) FILTER (WHERE v.review_status = 'pending')        AS pending_count,
                COUNT(*) FILTER (WHERE v.review_status = 'reviewed')       AS reviewed_count,
                COUNT(*) FILTER (WHERE v.review_status = 'skipped')        AS skipped_count,
                COUNT(*) FILTER (WHERE v.review_status = 'auto_rejected')  AS auto_rejected_count
            FROM v2_image_assets v
            WHERE v.classification NOT IN ('decorative', 'logo', 'signature')
              AND v.filename IS NOT NULL AND v.filename != ''
              {filter_clause}
        """
        rows = self.query(sql, params if params else None)
        if not rows:
            return {
                "total_candidates": 0,
                "pending_count": 0,
                "reviewed_count": 0,
                "skipped_count": 0,
                "auto_rejected_count": 0,
                "review_pct": 0.0,
            }
        row = rows[0]
        total = row["total_candidates"] or 0
        reviewed = row["reviewed_count"] or 0
        return {
            "total_candidates": total,
            "pending_count": row["pending_count"] or 0,
            "reviewed_count": reviewed,
            "skipped_count": row["skipped_count"] or 0,
            "auto_rejected_count": row["auto_rejected_count"] or 0,
            "review_pct": round(reviewed / total * 100, 1) if total > 0 else 0.0,
        }

    def get_image_decision_breakdown_v2(self) -> dict:
        """Decision-type breakdown of image review activity.

        Drives the five summary cards on the Images tab of
        ``/v2/review/stats``.

        The Accepted card is **image-distinct** and unions both review
        flows: ``accepted_images`` counts distinct images with any
        positive reviewer signal — ``v2_image_review_decisions.decision='relevant'``
        (legacy flow) UNIONed with
        ``v2_image_metric_confirmations.decision IN ('accept','correct','add')``
        (per-metric flow). ``accepted_images_per_metric`` is the
        per-metric subset of that — distinct images with at least one
        accept/correct/add row — surfaced as a sub-line on the same
        card so reviewers can see the "modern pipeline" number grow as
        the legacy backlog drains.

        The other four cards are per-metric **decision counts** on
        ``v2_image_metric_confirmations``: ``corrected``, ``added``,
        ``rejected``, ``skipped``. Mixed-unit by design — the Accepted
        total measures reviewer effort across both flows; the other
        cards remain decision-type drill-downs useful for keyword-
        detector recall diagnostics (e.g. a tiny ``accepted_images_per_metric``
        relative to ``added`` says the keyword rules are missing the
        right metric on most charts).

        Also returns ``legacy_accepts_pending``: count of distinct
        legacy ``'relevant'`` rows that have NO row in
        ``v2_image_metric_confirmations`` at all — i.e., the reviewer
        marked the image relevant but never assigned a specific metric.
        Powers the backfill banner and goes to zero once the legacy
        review set is migrated. Note the legacy table's CHECK
        constraint enforces ``'relevant'`` / ``'not_relevant'``, not
        the new flow's ``'accept'`` / ``'reject'`` vocabulary.
        """
        sql = """
            WITH breakdown AS (
                SELECT
                    COUNT(*)                                            AS total,
                    COUNT(*) FILTER (WHERE decision = 'correct')        AS corrected,
                    COUNT(*) FILTER (WHERE decision = 'add')            AS added,
                    COUNT(*) FILTER (WHERE decision = 'reject')         AS rejected,
                    COUNT(*) FILTER (WHERE decision = 'skip')           AS skipped,
                    COUNT(DISTINCT img_id) FILTER (
                        WHERE decision IN ('accept', 'correct', 'add')
                    )                                                    AS accepted_images_per_metric
                  FROM v2_image_metric_confirmations
            ),
            legacy AS (
                SELECT COUNT(DISTINCT ird.img_id) AS legacy_accepts_pending
                  FROM v2_image_review_decisions ird
                 WHERE ird.decision = 'relevant'
                   AND NOT EXISTS (
                       SELECT 1
                         FROM v2_image_metric_confirmations imc
                        WHERE imc.img_id = ird.img_id
                   )
            ),
            relevant_images AS (
                SELECT COUNT(*) AS accepted_images FROM (
                    SELECT img_id
                      FROM v2_image_metric_confirmations
                     WHERE decision IN ('accept', 'correct', 'add')
                    UNION
                    SELECT img_id
                      FROM v2_image_review_decisions
                     WHERE decision = 'relevant'
                ) AS u
            )
            SELECT b.total, b.corrected, b.added, b.rejected, b.skipped,
                   b.accepted_images_per_metric,
                   r.accepted_images,
                   l.legacy_accepts_pending
              FROM breakdown b CROSS JOIN legacy l CROSS JOIN relevant_images r
        """
        rows = self.query(sql)
        if not rows:
            return {
                "total": 0,
                "accepted_images": 0,
                "accepted_images_per_metric": 0,
                "corrected": 0,
                "added": 0,
                "rejected": 0,
                "skipped": 0,
                "legacy_accepts_pending": 0,
            }
        return {k: int(v or 0) for k, v in dict(rows[0]).items()}

    def get_image_decision_overall_v2(self) -> dict:
        """Aggregate totals over all v2_image_metric_confirmations rows.

        Returns total_decisions, relevant_count (accept|correct|add),
        not_relevant_count (reject, including sentinel), and percentage breakdowns.
        """
        sql = """
            SELECT
                COUNT(*) AS total_decisions,
                COUNT(*) FILTER (WHERE decision IN ('accept', 'correct', 'add')) AS relevant_count,
                COUNT(*) FILTER (WHERE decision = 'reject') AS not_relevant_count
            FROM v2_image_metric_confirmations
        """
        rows = self.query(sql)
        if not rows:
            return {
                "total_decisions": 0,
                "relevant_count": 0,
                "not_relevant_count": 0,
                "relevant_pct": 0.0,
                "not_relevant_pct": 0.0,
            }
        row = rows[0]
        total = row["total_decisions"] or 0
        relevant = row["relevant_count"] or 0
        not_relevant = row["not_relevant_count"] or 0
        return {
            "total_decisions": total,
            "relevant_count": relevant,
            "not_relevant_count": not_relevant,
            "relevant_pct": round(relevant / total * 100, 1) if total > 0 else 0.0,
            "not_relevant_pct": round(not_relevant / total * 100, 1) if total > 0 else 0.0,
        }

    def get_image_decisions_by_tier_v2(self) -> list[dict]:
        """Per-detection-tier precision counts over v2_image_metric_confirmations.

        Excludes sentinel rows (detected_metric_id IS NULL) and 'add' rows.
        Returns relevant_count, not_relevant_count, total_decisions, precision_pct per tier.
        """
        sql = """
            SELECT
                CASE
                    WHEN v.classification = 'presentation' THEN 'presence_seed'
                    WHEN v.classification = 'chart' AND v.relevance_score >= 0.6
                        THEN 'tier_1_cohort'
                    WHEN v.classification IN ('chart', 'table_image')
                         AND COALESCE(v.width, 0) >= 300
                         AND COALESCE(v.height, 0) >= 300
                        THEN 'tier_2_large'
                    ELSE 'tier_3_all'
                END AS detection_tier,
                COUNT(*) FILTER (WHERE imc.decision IN ('accept', 'correct')) AS relevant_count,
                COUNT(*) FILTER (WHERE imc.decision = 'reject') AS not_relevant_count,
                COUNT(*) AS total_decisions,
                CASE
                    WHEN COUNT(*) FILTER (WHERE imc.decision IN ('accept', 'correct'))
                       + COUNT(*) FILTER (WHERE imc.decision = 'reject') = 0 THEN 0.0
                    ELSE ROUND(
                        100.0
                        * COUNT(*) FILTER (WHERE imc.decision IN ('accept', 'correct'))
                        / (
                            COUNT(*) FILTER (WHERE imc.decision IN ('accept', 'correct'))
                          + COUNT(*) FILTER (WHERE imc.decision = 'reject')
                        ),
                        1
                    )
                END AS precision_pct
            FROM v2_image_metric_confirmations imc
            JOIN v2_image_assets v ON v.img_id = imc.img_id
            WHERE imc.detected_metric_id IS NOT NULL
              AND imc.decision IN ('accept', 'reject', 'correct')
            GROUP BY detection_tier
            ORDER BY detection_tier
        """
        rows = self.query(sql)
        return [dict(r) for r in rows]

    def get_image_rejection_reasons_by_tier_v2(self) -> list[dict]:
        """Per-(detection_tier, rejection_reason) rejection counts.

        Includes the sentinel row (rejection_reason='no_relevant_metrics').
        Returns rejection_count and pct_of_tier_rejections per row.
        """
        sql = """
            SELECT
                CASE
                    WHEN v.classification = 'presentation' THEN 'presence_seed'
                    WHEN v.classification = 'chart' AND v.relevance_score >= 0.6
                        THEN 'tier_1_cohort'
                    WHEN v.classification IN ('chart', 'table_image')
                         AND COALESCE(v.width, 0) >= 300
                         AND COALESCE(v.height, 0) >= 300
                        THEN 'tier_2_large'
                    ELSE 'tier_3_all'
                END AS detection_tier,
                imc.rejection_reason,
                COUNT(*) AS rejection_count,
                ROUND(
                    100.0 * COUNT(*) / SUM(COUNT(*)) OVER (
                        PARTITION BY
                            CASE
                                WHEN v.classification = 'presentation' THEN 'presence_seed'
                                WHEN v.classification = 'chart' AND v.relevance_score >= 0.6
                                    THEN 'tier_1_cohort'
                                WHEN v.classification IN ('chart', 'table_image')
                                     AND COALESCE(v.width, 0) >= 300
                                     AND COALESCE(v.height, 0) >= 300
                                    THEN 'tier_2_large'
                                ELSE 'tier_3_all'
                            END
                    ),
                    1
                ) AS pct_of_tier_rejections
            FROM v2_image_metric_confirmations imc
            JOIN v2_image_assets v ON v.img_id = imc.img_id
            WHERE imc.decision = 'reject'
              AND imc.rejection_reason IS NOT NULL
            GROUP BY detection_tier, imc.rejection_reason
            ORDER BY detection_tier, rejection_count DESC
        """
        rows = self.query(sql)
        return [dict(r) for r in rows]

    def count_image_metric_rejections_for_filing(self, filing_id: int) -> int:
        """
        Count v2_image_metric_confirmations rows with decision='reject' that
        belong to images in this filing. Includes both per-detected-metric
        rejects and the NULL/NULL "no relevant metrics" sentinel reject.

        Used by the unified review header to merge image-metric rejections
        into the page-level "N rejected" badge alongside text-fact rejects.
        """
        sql = """
            SELECT COUNT(*) AS n
              FROM v2_image_metric_confirmations imc
              JOIN v2_image_assets ia ON ia.img_id = imc.img_id
             WHERE ia.filing_id = %(filing_id)s
               AND imc.decision = 'reject'
        """
        rows = self.query(sql, {"filing_id": filing_id})
        return int(rows[0]["n"]) if rows else 0

    # =============================================================================
    # Metric Analytics — Summary tab helpers
    #
    # Powers the "Decisions since last model update" counters and the Recent
    # Activity panels on /v2/review/stats. The model_training_runs table is
    # the anchor for the "since" timestamp (image classifier retrains only —
    # no text-side trainable model exists yet).
    # =============================================================================

    def get_last_training_run(self, model_type: str) -> dict | None:
        """Most recent succeeded training run for the given model_type.

        Returns None if no run has completed yet — callers fall back to the
        on-disk model artifact's mtime, or treat the count as "all decisions
        ever" depending on context.
        """
        sql = """
            SELECT id, model_type, started_at, completed_at, status,
                   num_training_rows, num_positive_rows,
                   model_path, report_path, triggered_by
              FROM model_training_runs
             WHERE model_type = %(model_type)s
               AND status = 'succeeded'
             ORDER BY completed_at DESC
             LIMIT 1
        """
        rows = self.query(sql, {"model_type": model_type})
        return dict(rows[0]) if rows else None

    def count_image_decisions_since(self, ts: datetime | None) -> dict:
        """Count v2_image_metric_confirmations rows created after `ts`.

        Returns {total, positive, negative}. Excludes 'skip' (deferred, not
        decided). Positive = accept|correct|add. Negative = reject. When `ts`
        is None, counts every substantive decision ever recorded.
        """
        sql = """
            SELECT
                COUNT(*) FILTER (WHERE decision != 'skip')                          AS total,
                COUNT(*) FILTER (WHERE decision IN ('accept', 'correct', 'add'))    AS positive,
                COUNT(*) FILTER (WHERE decision = 'reject')                         AS negative
              FROM v2_image_metric_confirmations
             WHERE (%(ts)s::timestamptz IS NULL OR created_at > %(ts)s::timestamptz)
        """
        rows = self.query(sql, {"ts": ts})
        if not rows:
            return {"total": 0, "positive": 0, "negative": 0}
        row = rows[0]
        return {
            "total": int(row["total"] or 0),
            "positive": int(row["positive"] or 0),
            "negative": int(row["negative"] or 0),
        }

    def count_text_decisions_since(self, ts: datetime | None) -> int:
        """Count v2_review_decisions rows created after `ts`.

        Informational only — no text-side trainable model. Surfaces in the
        Summary tab so reviewers can see how much manual ground truth has
        accumulated independent of the image-classifier retrain anchor.
        """
        sql = """
            SELECT COUNT(*) AS n
              FROM v2_review_decisions
             WHERE (%(ts)s::timestamptz IS NULL OR created_at > %(ts)s::timestamptz)
        """
        rows = self.query(sql, {"ts": ts})
        return int(rows[0]["n"]) if rows else 0

    def get_recent_text_corrections(self, limit: int = 10) -> list[dict]:
        """Most recent text-fact corrections (decision='correct').

        Joins v2_review_decisions to v2_metric_facts + filings + companies so
        the Summary panel can show original→corrected metric, value, and a
        link to the source filing.
        """
        sql = """
            SELECT
                rd.created_at,
                rd.reviewer_id,
                rd.assigned_metric_id    AS corrected_metric_id,
                rd.corrected_value,
                rd.reviewer_notes,
                mf.fact_id,
                mf.canonical_metric_id   AS original_metric_id,
                mf.value_raw             AS original_value_raw,
                mf.filing_id,
                c.company_name,
                c.cik
              FROM v2_review_decisions rd
              JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
              JOIN filings f          ON f.filing_id = mf.filing_id
              JOIN companies c        ON c.company_id = f.company_id
             WHERE rd.decision = 'correct'
             ORDER BY rd.created_at DESC
             LIMIT %(limit)s
        """
        rows = self.query(sql, {"limit": limit})
        return [dict(r) for r in rows]

    def get_recent_text_additions(self, limit: int = 10) -> list[dict]:
        """Most recent manually-entered text facts (extraction_method='manual').

        Sourced from POST /api/v2/missed-metric. Joined for filing/company
        context so the Summary panel can link out.
        """
        sql = """
            SELECT
                mf.created_at,
                mf.fact_id,
                mf.canonical_metric_id,
                mf.value_raw,
                mf.unit,
                mf.review_reason,
                mf.filing_id,
                c.company_name,
                c.cik
              FROM v2_metric_facts mf
              JOIN filings f   ON f.filing_id = mf.filing_id
              JOIN companies c ON c.company_id = f.company_id
             WHERE mf.extraction_method = 'manual'
             ORDER BY mf.created_at DESC
             LIMIT %(limit)s
        """
        rows = self.query(sql, {"limit": limit})
        return [dict(r) for r in rows]

    def get_recent_image_additions(self, limit: int = 10) -> list[dict]:
        """Most recent reviewer-added image metrics (decision='add')."""
        sql = """
            SELECT
                imc.created_at,
                imc.id                AS confirmation_id,
                imc.img_id,
                imc.confirmed_metric_id,
                imc.reviewer_id,
                ia.filing_id,
                c.company_name,
                c.cik
              FROM v2_image_metric_confirmations imc
              JOIN v2_image_assets ia ON ia.img_id = imc.img_id
              JOIN filings f          ON f.filing_id = ia.filing_id
              JOIN companies c        ON c.company_id = f.company_id
             WHERE imc.decision = 'add'
             ORDER BY imc.created_at DESC
             LIMIT %(limit)s
        """
        rows = self.query(sql, {"limit": limit})
        return [dict(r) for r in rows]

    def get_recent_image_corrections(self, limit: int = 10) -> list[dict]:
        """Most recent image-metric corrections (decision='correct').

        detected_metric_id and confirmed_metric_id are both populated and
        differ — surfaces the keyword-matcher's mistakes for downstream
        analysis.
        """
        sql = """
            SELECT
                imc.created_at,
                imc.id                  AS confirmation_id,
                imc.img_id,
                imc.detected_metric_id,
                imc.confirmed_metric_id,
                imc.reviewer_id,
                ia.filing_id,
                c.company_name,
                c.cik
              FROM v2_image_metric_confirmations imc
              JOIN v2_image_assets ia ON ia.img_id = imc.img_id
              JOIN filings f          ON f.filing_id = ia.filing_id
              JOIN companies c        ON c.company_id = f.company_id
             WHERE imc.decision = 'correct'
             ORDER BY imc.created_at DESC
             LIMIT %(limit)s
        """
        rows = self.query(sql, {"limit": limit})
        return [dict(r) for r in rows]

    def get_top_text_corrections(self, window: Literal["7d", "all"], limit: int = 10) -> list[dict]:
        """Top metric (original, corrected) pairs by reject volume.

        Aggregates v2_review_decisions joined to v2_metric_facts so the
        Review Activity card on /v2/review/stats can rank where text
        extraction is most often corrected. Value-only corrections retain
        original_metric_id == corrected_metric_id; the template renders those
        as "cm_X (value)" rather than "cm_X -> cm_X".
        """
        where_window = "AND rd.created_at >= NOW() - INTERVAL '7 days'" if window == "7d" else ""
        sql = f"""
            SELECT
                mf.canonical_metric_id   AS original_metric_id,
                rd.assigned_metric_id    AS corrected_metric_id,
                COUNT(*)                 AS count,
                MAX(rd.created_at)       AS last_seen
              FROM v2_review_decisions rd
              JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
             WHERE rd.decision = 'correct'
               {where_window}
             GROUP BY mf.canonical_metric_id, rd.assigned_metric_id
             ORDER BY count DESC, last_seen DESC
             LIMIT %(limit)s
        """
        rows = self.query(sql, {"limit": limit})
        return [dict(r) for r in rows]

    def get_top_text_additions(self, window: Literal["7d", "all"], limit: int = 10) -> list[dict]:
        """Top manually-added text-fact metrics by addition volume."""
        where_window = "AND mf.created_at >= NOW() - INTERVAL '7 days'" if window == "7d" else ""
        sql = f"""
            SELECT
                mf.canonical_metric_id   AS metric_id,
                COUNT(*)                 AS count,
                MAX(mf.created_at)       AS last_seen
              FROM v2_metric_facts mf
             WHERE mf.extraction_method = 'manual'
               {where_window}
             GROUP BY mf.canonical_metric_id
             ORDER BY count DESC, last_seen DESC
             LIMIT %(limit)s
        """
        rows = self.query(sql, {"limit": limit})
        return [dict(r) for r in rows]

    def get_top_image_additions(self, window: Literal["7d", "all"], limit: int = 10) -> list[dict]:
        """Top reviewer-added image metrics (decision='add') by add volume."""
        where_window = "AND imc.created_at >= NOW() - INTERVAL '7 days'" if window == "7d" else ""
        sql = f"""
            SELECT
                imc.confirmed_metric_id  AS metric_id,
                COUNT(*)                 AS count,
                MAX(imc.created_at)      AS last_seen
              FROM v2_image_metric_confirmations imc
             WHERE imc.decision = 'add'
               {where_window}
             GROUP BY imc.confirmed_metric_id
             ORDER BY count DESC, last_seen DESC
             LIMIT %(limit)s
        """
        rows = self.query(sql, {"limit": limit})
        return [dict(r) for r in rows]

    def get_top_image_corrections(
        self, window: Literal["7d", "all"], limit: int = 10
    ) -> list[dict]:
        """Top image-metric (detected -> confirmed) correction pairs.

        Image corrections always change the metric_id (no value-only case),
        so detected_metric_id and confirmed_metric_id always differ.
        """
        where_window = "AND imc.created_at >= NOW() - INTERVAL '7 days'" if window == "7d" else ""
        sql = f"""
            SELECT
                imc.detected_metric_id,
                imc.confirmed_metric_id,
                COUNT(*)                 AS count,
                MAX(imc.created_at)      AS last_seen
              FROM v2_image_metric_confirmations imc
             WHERE imc.decision = 'correct'
               {where_window}
             GROUP BY imc.detected_metric_id, imc.confirmed_metric_id
             ORDER BY count DESC, last_seen DESC
             LIMIT %(limit)s
        """
        rows = self.query(sql, {"limit": limit})
        return [dict(r) for r in rows]

    def count_review_activity(self, window: Literal["7d", "all"]) -> dict[str, int]:
        """Total counts for the four Review Activity card types in one roundtrip.

        Returns {text_corrections, text_additions, image_additions,
        image_corrections}. Drives the per-card header badges on the
        Latest/All-time toggle.
        """
        where_text_decision = (
            "AND created_at >= NOW() - INTERVAL '7 days'" if window == "7d" else ""
        )
        where_facts = "AND created_at >= NOW() - INTERVAL '7 days'" if window == "7d" else ""
        where_imc = "AND created_at >= NOW() - INTERVAL '7 days'" if window == "7d" else ""
        sql = f"""
            SELECT
                (SELECT COUNT(*) FROM v2_review_decisions
                  WHERE decision = 'correct' {where_text_decision})       AS text_corrections,
                (SELECT COUNT(*) FROM v2_metric_facts
                  WHERE extraction_method = 'manual' {where_facts})       AS text_additions,
                (SELECT COUNT(*) FROM v2_image_metric_confirmations
                  WHERE decision = 'add' {where_imc})                     AS image_additions,
                (SELECT COUNT(*) FROM v2_image_metric_confirmations
                  WHERE decision = 'correct' {where_imc})                 AS image_corrections
        """
        rows = self.query(sql, {})
        if not rows:
            return {
                "text_corrections": 0,
                "text_additions": 0,
                "image_additions": 0,
                "image_corrections": 0,
            }
        return {k: int(v or 0) for k, v in dict(rows[0]).items()}

    def get_rejection_reason_rollup(self, side: str, since: datetime | None = None) -> list[dict]:
        """Aggregate rejected decisions by reason for the Summary tab.

        Returns rows of {reason, count, percent}. Percent is share of all
        rejections in the side (text or image). Side='text' reads
        v2_review_decisions.rejection_category; side='image' reads
        v2_image_metric_confirmations.rejection_reason.

        When `since` is None, includes every rejection ever recorded; otherwise
        filters to rows with created_at > since.
        """
        if side not in ("text", "image"):
            raise ValueError(f"Unknown side: {side!r} (expected 'text' or 'image')")

        if side == "text":
            sql = """
                WITH r AS (
                    SELECT rejection_category AS reason
                      FROM v2_review_decisions
                     WHERE decision = 'reject'
                       AND rejection_category IS NOT NULL
                       AND (%(since)s::timestamptz IS NULL OR created_at > %(since)s::timestamptz)
                )
                SELECT
                    reason,
                    COUNT(*)                                                AS count,
                    ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 1) AS percent
                  FROM r
                 GROUP BY reason
                 ORDER BY count DESC
            """
        else:
            # Image side: use rejection_reason. Includes the no_relevant_metrics
            # sentinel (NULL detected_metric_id) since reviewers DO see that as a
            # distinct rejection reason.
            sql = """
                WITH r AS (
                    SELECT rejection_reason AS reason
                      FROM v2_image_metric_confirmations
                     WHERE decision = 'reject'
                       AND rejection_reason IS NOT NULL
                       AND (%(since)s::timestamptz IS NULL OR created_at > %(since)s::timestamptz)
                )
                SELECT
                    reason,
                    COUNT(*)                                                AS count,
                    ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 1) AS percent
                  FROM r
                 GROUP BY reason
                 ORDER BY count DESC
            """

        rows = self.query(sql, {"since": since})
        return [dict(r) for r in rows]

    # =============================================================================
    # Text-decision pattern analysis readers (text_decision_analysis_runs et al.)
    # =============================================================================

    def get_last_text_analysis_run(self) -> dict | None:
        """Most recent succeeded text-decision pattern-analysis run.

        Returns None when no run has succeeded yet — UI then shows "never"
        and decision counters fall back to lifetime totals.
        """
        sql = """
            SELECT id, started_at, completed_at, status,
                   num_decisions_analyzed, num_metrics_analyzed,
                   triggered_by, error
              FROM text_decision_analysis_runs
             WHERE status = 'succeeded'
             ORDER BY completed_at DESC
             LIMIT 1
        """
        rows = self.query(sql)
        return dict(rows[0]) if rows else None

    def is_text_analysis_running(self) -> tuple[bool, str | None]:
        """Concurrency check for the API gate.

        Returns (True, run_id) if any row is currently in 'running' status,
        else (False, None).
        """
        rows = self.query(
            """
            SELECT id FROM text_decision_analysis_runs
             WHERE status = 'running'
             LIMIT 1
            """
        )
        if not rows:
            return False, None
        return True, str(rows[0]["id"])

    def get_text_decision_metric_summary(self, run_id: str) -> list[dict]:
        """All text_decision_metric_summary rows for a given run, ordered by
        rejection volume DESC so the UI can render highest-pain metrics first.
        """
        sql = """
            SELECT metric_id, total_decisions, accept_count, reject_count,
                   correct_count, rejection_categories, top_correction_targets
              FROM text_decision_metric_summary
             WHERE run_id = %(run_id)s
             ORDER BY reject_count DESC, total_decisions DESC, metric_id ASC
        """
        rows = self.query(sql, {"run_id": run_id})
        return [dict(r) for r in rows]

    def get_text_decision_phrase_findings(
        self,
        run_id: str,
        metric_id: str | None = None,
        decision_type: str | None = None,
    ) -> list[dict]:
        """Phrase findings for a run, optionally filtered by metric and/or
        decision_type for drill-down.
        """
        conditions = ["run_id = %(run_id)s"]
        params: dict[str, Any] = {"run_id": run_id}
        if metric_id is not None:
            conditions.append("metric_id = %(metric_id)s")
            params["metric_id"] = metric_id
        if decision_type is not None:
            conditions.append("decision_type = %(decision_type)s")
            params["decision_type"] = decision_type
        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT id, metric_id, decision_type, phrase, phrase_ngram_size,
                   source_field, occurrence_count, pct_of_decisions, examples
              FROM text_decision_phrase_findings
             WHERE {where_clause}
             ORDER BY metric_id ASC, decision_type ASC, source_field ASC,
                      occurrence_count DESC, phrase ASC
        """
        rows = self.query(sql, params)
        return [dict(r) for r in rows]

    # =============================================================================
    # Recommendation-decision readers/writers (text_pattern_recommendation_decisions)
    # =============================================================================

    def upsert_recommendation_decision(
        self,
        *,
        metric_id: str,
        rule: str,
        decision_key: str,
        decision: str,
        reviewer_id: str,
        reviewer_note: str | None = None,
    ) -> dict:
        """Insert or update a recommendation decision row.

        Unique on (metric_id, rule, decision_key, reviewer_id) so a same-
        reviewer change-of-mind upserts cleanly. Returns the resulting row.
        """
        sql = """
            INSERT INTO text_pattern_recommendation_decisions
                (metric_id, rule, decision_key, decision, reviewer_id, reviewer_note)
            VALUES
                (%(metric_id)s, %(rule)s, %(decision_key)s, %(decision)s,
                 %(reviewer_id)s, %(reviewer_note)s)
            ON CONFLICT (metric_id, rule, decision_key, reviewer_id) DO UPDATE
               SET decision      = EXCLUDED.decision,
                   reviewer_note = EXCLUDED.reviewer_note,
                   updated_at    = NOW()
            RETURNING id, metric_id, rule, decision_key, decision,
                      reviewer_id, reviewer_note, pr_number, pr_url,
                      created_at, updated_at
        """
        rows = self.query(
            sql,
            {
                "metric_id": metric_id,
                "rule": rule,
                "decision_key": decision_key,
                "decision": decision,
                "reviewer_id": reviewer_id,
                "reviewer_note": reviewer_note,
            },
        )
        return dict(rows[0])

    def delete_recommendation_decision(self, decision_id: str, reviewer_id: str) -> bool:
        """Delete a decision row scoped to its owning reviewer.

        Returns True when a row was deleted, False when nothing matched
        (id unknown OR row exists but belongs to a different reviewer —
        admins shouldn't accidentally undo each other's decisions).
        """
        sql = """
            DELETE FROM text_pattern_recommendation_decisions
             WHERE id = %(id)s AND reviewer_id = %(reviewer_id)s
            RETURNING id
        """
        rows = self.query(sql, {"id": decision_id, "reviewer_id": reviewer_id})
        return bool(rows)

    def get_recommendation_decisions(self, metric_ids: list[str] | None = None) -> list[dict]:
        """Return all recommendation decision rows, optionally filtered by metric.

        Used at render time by `review_unified.stats()` to merge decisions
        into the freshly computed recommendation list. Sorted newest-first
        per (metric, rule) so the UI can show "Accepted by RGM 2 hours ago"
        with the latest reviewer's action.
        """
        params: dict[str, Any] = {}
        where_clause = ""
        if metric_ids:
            where_clause = " WHERE metric_id = ANY(%(metric_ids)s)"
            params["metric_ids"] = list(metric_ids)
        sql = f"""
            SELECT id, metric_id, rule, decision_key, decision,
                   reviewer_id, reviewer_note, pr_number, pr_url,
                   created_at, updated_at
              FROM text_pattern_recommendation_decisions
             {where_clause}
             ORDER BY metric_id ASC, rule ASC, decision_key ASC,
                      updated_at DESC
        """
        rows = self.query(sql, params)
        return [dict(r) for r in rows]

    # =============================================================================
    # V2 Image Metric Confirmation Methods (v2_image_metric_confirmations)
    # =============================================================================

    def insert_image_metric_confirmations(
        self,
        img_id: str,
        confirmations: list[dict[str, Any]],
        reviewer_id: str,
    ) -> int:
        """
        Upsert per-metric confirmation decisions for a chart image, and
        promote accept/correct/add decisions into v2_metric_facts.

        Each entry in *confirmations* must have at minimum:
          - decision: 'accept' | 'reject' | 'correct' | 'add' | 'skip'
          - detected_metric_id: str | None
          - confirmed_metric_id: str | None
          - rejection_reason: str | None

        Fact-promotion rules (all inside one tx):
          accept  → insert chart fact for (img_id, detected_metric_id) if none exists
          correct → delete fact for detected_metric_id; insert for confirmed_metric_id
          add     → insert chart fact for (img_id, confirmed_metric_id) if none exists
          reject  → delete fact for detected_metric_id (if no other accept remains)
          skip    → delete fact for detected_metric_id (if no other accept remains)

        Returns the number of confirmation rows upserted.
        """
        if not confirmations:
            return 0

        upsert_sql = """
            INSERT INTO v2_image_metric_confirmations (
                img_id, detected_metric_id, confirmed_metric_id,
                decision, rejection_reason, reviewer_id,
                reviewer_notes, decided_against_hash
            ) VALUES (
                %(img_id)s, %(detected_metric_id)s, %(confirmed_metric_id)s,
                %(decision)s, %(rejection_reason)s, %(reviewer_id)s,
                %(reviewer_notes)s, %(decided_against_hash)s
            )
            ON CONFLICT (img_id, reviewer_id, COALESCE(detected_metric_id, confirmed_metric_id, ''))
            DO UPDATE SET
                decision            = EXCLUDED.decision,
                confirmed_metric_id = EXCLUDED.confirmed_metric_id,
                rejection_reason    = EXCLUDED.rejection_reason,
                reviewer_notes      = EXCLUDED.reviewer_notes,
                decided_against_hash = EXCLUDED.decided_against_hash,
                updated_at          = now()
        """

        count = 0
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT filing_id,
                              ocr_text,
                              chart_data::text AS chart_data_json
                       FROM v2_image_assets WHERE img_id = %(img_id)s""",
                    {"img_id": img_id},
                )
                doc_row = cur.fetchone()
                if doc_row is None:
                    raise ValueError(f"Image not found: img_id={img_id}")
                filing_id = doc_row["filing_id"]
                decided_against_hash = self._compute_image_content_hash(
                    doc_row["ocr_text"],
                    doc_row["chart_data_json"],
                )

                for entry in confirmations:
                    decision = entry["decision"]
                    detected_metric_id = entry.get("detected_metric_id")
                    confirmed_metric_id = entry.get("confirmed_metric_id")

                    cur.execute(
                        upsert_sql,
                        {
                            "img_id": img_id,
                            "detected_metric_id": detected_metric_id,
                            "confirmed_metric_id": confirmed_metric_id,
                            "decision": decision,
                            "rejection_reason": entry.get("rejection_reason"),
                            "reviewer_id": reviewer_id,
                            "reviewer_notes": entry.get("reviewer_notes"),
                            "decided_against_hash": decided_against_hash,
                        },
                    )
                    count += 1

                    if decision == "accept":
                        self._promote_chart_fact(
                            cur, filing_id, img_id, detected_metric_id, reviewer_id
                        )
                    elif decision == "correct":
                        self._demote_chart_fact(cur, filing_id, img_id, detected_metric_id)
                        self._promote_chart_fact(
                            cur, filing_id, img_id, confirmed_metric_id, reviewer_id
                        )
                    elif decision == "add":
                        self._promote_chart_fact(
                            cur, filing_id, img_id, confirmed_metric_id, reviewer_id
                        )
                    elif decision in ("reject", "skip"):
                        self._demote_chart_fact(cur, filing_id, img_id, detected_metric_id)

        logger.debug(
            "Upserted %d image metric confirmations: img_id=%s reviewer_id=%s",
            count,
            img_id,
            reviewer_id,
        )
        return count

    def _promote_chart_fact(
        self,
        cur,
        filing_id: int,
        img_id: str,
        metric_id: str | None,
        reviewer_id: str,
    ) -> None:
        """
        Insert a v2_metric_facts row for a reviewer-accepted chart metric.
        Idempotent: skips if ANY chart fact already exists for (filing_id, metric_id).
        The `idx_v2_metric_facts_identity_unique` index does not include
        img_id, so two images disclosing the same metric in the same filing
        collapse to one presence-level fact. Per-image provenance stays in
        v2_image_metric_confirmations. Value-less (presence-only) —
        value_raw is a marker; unit is 'other'.
        """
        if not metric_id:
            return
        cur.execute(
            """
            SELECT fact_id FROM v2_metric_facts
            WHERE filing_id = %(filing_id)s
              AND canonical_metric_id = %(metric_id)s
              AND source_type = 'chart'
            LIMIT 1
            """,
            {"filing_id": filing_id, "metric_id": metric_id},
        )
        if cur.fetchone() is not None:
            return
        cur.execute(
            """
            INSERT INTO v2_metric_facts (
                filing_id, canonical_metric_id, value_raw, unit,
                source_type, source_locator,
                confidence, extraction_method, requires_review, review_status,
                pipeline_version
            ) VALUES (
                %(filing_id)s, %(metric_id)s, '', 'other',
                'chart', %(source_locator)s::jsonb,
                1.0, 'manual', FALSE, 'accepted',
                '2.0.0'
            )
            """,
            {
                "filing_id": filing_id,
                "metric_id": metric_id,
                "source_locator": json.dumps({"img_id": img_id}),
            },
        )

    def _demote_chart_fact(
        self,
        cur,
        filing_id: int,
        img_id: str,
        metric_id: str | None,
    ) -> None:
        """
        Delete the chart-sourced v2_metric_facts row for (filing_id, metric_id)
        only when no accept/correct/add confirmation still references this
        metric from any image in this filing. Mirrors _promote_chart_fact's
        one-fact-per-(filing, metric) semantic. Idempotent.

        Callers must upsert/delete the current confirmation BEFORE invoking
        this helper so the query reflects the post-decision state.
        """
        if not metric_id:
            return
        cur.execute(
            """
            SELECT 1
              FROM v2_image_metric_confirmations imc
              JOIN v2_image_assets ia ON ia.img_id = imc.img_id
             WHERE ia.filing_id = %(filing_id)s
               AND (
                   (imc.decision = 'accept'  AND imc.detected_metric_id  = %(metric_id)s) OR
                   (imc.decision = 'correct' AND imc.confirmed_metric_id = %(metric_id)s) OR
                   (imc.decision = 'add'     AND imc.confirmed_metric_id = %(metric_id)s)
               )
             LIMIT 1
            """,
            {"filing_id": filing_id, "metric_id": metric_id},
        )
        if cur.fetchone() is not None:
            return
        cur.execute(
            """
            DELETE FROM v2_metric_facts
            WHERE filing_id = %(filing_id)s
              AND canonical_metric_id = %(metric_id)s
              AND source_type = 'chart'
            """,
            {"filing_id": filing_id, "metric_id": metric_id},
        )

    def delete_image_metric_confirmation(
        self,
        confirmation_id: str,
        reviewer_id: str,
    ) -> dict[str, Any] | None:
        """
        Delete a single confirmation row (scoped to reviewer_id) and roll back
        any promoted chart fact. Returns the deleted row or None if not found.
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM v2_image_metric_confirmations
                    WHERE id = %(confirmation_id)s
                      AND reviewer_id = %(reviewer_id)s
                    RETURNING
                        id::text AS confirmation_id,
                        img_id::text AS img_id,
                        detected_metric_id,
                        confirmed_metric_id,
                        decision,
                        rejection_reason,
                        reviewer_id
                    """,
                    {"confirmation_id": confirmation_id, "reviewer_id": reviewer_id},
                )
                row = cur.fetchone()
                if row is None:
                    return None

                cur.execute(
                    "SELECT filing_id FROM v2_image_assets WHERE img_id = %(img_id)s",
                    {"img_id": row["img_id"]},
                )
                doc_row = cur.fetchone()
                if doc_row is not None:
                    filing_id = doc_row["filing_id"]
                    metric_id = row["confirmed_metric_id"] or row["detected_metric_id"]
                    self._demote_chart_fact(cur, filing_id, row["img_id"], metric_id)

        logger.debug(
            "Deleted image metric confirmation %s (reviewer=%s, decision=%s)",
            confirmation_id,
            reviewer_id,
            row["decision"],
        )
        return row

    def get_image_metric_confirmations(self, img_id: str) -> list[dict[str, Any]]:
        """
        Return all metric confirmation rows for *img_id*, ordered by created_at.
        """
        sql = """
            SELECT
                id::text AS confirmation_id,
                img_id::text,
                detected_metric_id,
                confirmed_metric_id,
                decision,
                rejection_reason,
                reviewer_id,
                created_at,
                updated_at
            FROM v2_image_metric_confirmations
            WHERE img_id = %(img_id)s
            ORDER BY created_at ASC
        """
        return self.query(sql, {"img_id": img_id})


# =============================================================================
# Convenience Functions
# =============================================================================


def create_pooled_adapter(connection_string: str | None = None) -> DatabaseAdapter:
    """
    Create a DatabaseAdapter backed by the shared connection pool.

    This is a convenience function for scripts that want connection pooling
    without managing pool lifecycle. The pool is created lazily on first call
    and automatically closed at process exit.

    Args:
        connection_string: PostgreSQL connection string. If not provided,
            reads from DATABASE_URL environment variable.

    Returns:
        DatabaseAdapter instance using the shared connection pool.

    Raises:
        ValueError: If connection_string not provided and DATABASE_URL not set.

    Example:
        # In a script
        from src.infra.db import create_pooled_adapter

        db = create_pooled_adapter()  # Uses DATABASE_URL from environment
        results = db.query("SELECT * FROM companies LIMIT 10")
    """
    from src.infra.pool import get_shared_pool

    if connection_string is None:
        connection_string = os.environ.get("DATABASE_URL", "")
        if not connection_string:
            raise ValueError(
                "connection_string not provided and DATABASE_URL environment variable not set"
            )

    pool = get_shared_pool(connection_string)
    return DatabaseAdapter(connection_string, pool=pool)
