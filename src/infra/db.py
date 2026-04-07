"""
Database adapter for Customer Metrics Filings Analysis.

Provides a clean interface for database operations using psycopg3.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg.rows import dict_row

from src.infra.validation import ValidationError, validate_enum, validate_score
from src.review.models import (
    DECISION_TYPES,
    IMAGE_CHART_TYPES,
    IMAGE_DECISIONS,
    IMAGE_REJECTION_REASONS,
    IMAGE_REVIEW_STATUSES,
    KEYWORD_POSITIONS,
    PATTERN_STATUSES,
    PATTERN_TYPES,
    REJECTION_CATEGORIES,
    REVIEW_STATUSES,
)

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)


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
        """
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
        """
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

    def get_in_scope_filing_count(self) -> int:
        """
        Get count of filings where is_in_scope_phase1 = true.

        Returns:
            Count of in-scope filings
        """
        sql = "SELECT COUNT(*) as count FROM filings WHERE is_in_scope_phase1 = true"
        results = self.query(sql)
        return results[0]["count"] if results else 0

    # =========================================================================
    # Review Candidates Methods
    # =========================================================================

    def insert_review_candidate(
        self,
        filing_id: int,
        company_id: int,
        char_position: int,
        context_text: str,
        raw_number_text: str,
        triggering_keyword: str,
        keyword_distance: int,
        keyword_position: str,
        source_segment_id: int | None = None,
        parsed_value: Any | None = None,
        parsed_unit: str | None = None,
        suggested_metric_id: str | None = None,
        suggestion_confidence: float | None = None,
        features: dict[str, Any] | None = None,
        review_batch_id: int | None = None,
    ) -> int:
        """
        Insert a new review candidate.

        Args:
            filing_id: Foreign key to filings table
            company_id: Foreign key to companies table
            char_position: Character position of number in segment
            context_text: Surrounding text for context
            raw_number_text: The raw number string found
            triggering_keyword: Keyword that triggered this candidate
            keyword_distance: Characters from number to keyword
            keyword_position: 'before' or 'after' the number
            source_segment_id: Optional foreign key to source_segments
            parsed_value: Parsed numeric value
            parsed_unit: Detected unit
            suggested_metric_id: Initial suggested metric
            suggestion_confidence: 0-1 confidence score
            features: ML features as dict (stored as JSONB)
            review_batch_id: Optional batch grouping

        Returns:
            candidate_id of the inserted record

        Raises:
            ValidationError: If keyword_position is not 'before' or 'after'
            ValidationError: If suggestion_confidence is not between 0 and 1
        """
        # Validate enum values
        validate_enum(keyword_position, KEYWORD_POSITIONS, "keyword_position")

        # Validate confidence range
        validate_score(suggestion_confidence, "suggestion_confidence")

        sql = """
            INSERT INTO review_candidates (
                filing_id, company_id, source_segment_id,
                char_position, context_text, raw_number_text,
                parsed_value, parsed_unit,
                triggering_keyword, keyword_distance, keyword_position,
                suggested_metric_id, suggestion_confidence, features,
                review_batch_id
            )
            VALUES (
                %(filing_id)s, %(company_id)s, %(source_segment_id)s,
                %(char_position)s, %(context_text)s, %(raw_number_text)s,
                %(parsed_value)s, %(parsed_unit)s,
                %(triggering_keyword)s, %(keyword_distance)s, %(keyword_position)s,
                %(suggested_metric_id)s, %(suggestion_confidence)s, %(features)s,
                %(review_batch_id)s
            )
            RETURNING candidate_id
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "filing_id": filing_id,
                        "company_id": company_id,
                        "source_segment_id": source_segment_id,
                        "char_position": char_position,
                        "context_text": context_text,
                        "raw_number_text": raw_number_text,
                        "parsed_value": parsed_value,
                        "parsed_unit": parsed_unit,
                        "triggering_keyword": triggering_keyword,
                        "keyword_distance": keyword_distance,
                        "keyword_position": keyword_position,
                        "suggested_metric_id": suggested_metric_id,
                        "suggestion_confidence": suggestion_confidence,
                        "features": json.dumps(features) if features else None,
                        "review_batch_id": review_batch_id,
                    },
                )
                result = cur.fetchone()
                candidate_id = result["candidate_id"]

        logger.debug(f"Inserted review candidate: candidate_id={candidate_id}")
        return candidate_id

    def get_review_candidate(self, candidate_id: int) -> dict | None:
        """
        Get a review candidate by ID.

        Args:
            candidate_id: Primary key

        Returns:
            Candidate record as dict, or None if not found
        """
        sql = "SELECT * FROM review_candidates WHERE candidate_id = %(candidate_id)s"
        results = self.query(sql, {"candidate_id": candidate_id})
        return results[0] if results else None

    def get_expanded_context_for_candidate(
        self, candidate_id: int, num_adjacent: int = 2
    ) -> dict[str, Any] | None:
        """
        Get expanded context for a candidate by fetching adjacent segments.

        Fetches segments before and after the candidate's source segment
        and concatenates their text to provide broader context.

        Args:
            candidate_id: Candidate ID to expand context for
            num_adjacent: Number of adjacent segments to fetch on each side (default: 2)

        Returns:
            Dict with:
                - expanded_context: str - Concatenated text from adjacent segments
                - segment_count: int - Number of segments included
                - can_expand: bool - Whether expansion was possible
            Or None if candidate or source segment not found
        """
        # First, get the candidate and its source segment info
        candidate = self.get_review_candidate(candidate_id)
        if not candidate:
            return None

        source_segment_id = candidate.get("source_segment_id")
        if not source_segment_id:
            # No source segment linked - return current context only
            return {
                "expanded_context": candidate.get("context_text", ""),
                "segment_count": 0,
                "can_expand": False,
            }

        # Get the source segment to find its filing_id and sequence_index
        segment_sql = """
            SELECT filing_id, sequence_index
            FROM source_segments
            WHERE source_segment_id = %(source_segment_id)s
        """
        segment_results = self.query(segment_sql, {"source_segment_id": source_segment_id})

        if not segment_results:
            # Source segment not found - return current context
            return {
                "expanded_context": candidate.get("context_text", ""),
                "segment_count": 0,
                "can_expand": False,
            }

        filing_id = segment_results[0]["filing_id"]
        sequence_index = segment_results[0]["sequence_index"]

        # Fetch adjacent segments (num_adjacent before and after)
        adjacent_sql = """
            SELECT sequence_index, raw_text
            FROM source_segments
            WHERE filing_id = %(filing_id)s
              AND sequence_index >= %(min_index)s
              AND sequence_index <= %(max_index)s
            ORDER BY sequence_index ASC
        """

        min_index = max(0, sequence_index - num_adjacent)
        max_index = sequence_index + num_adjacent

        adjacent_results = self.query(
            adjacent_sql,
            {
                "filing_id": filing_id,
                "min_index": min_index,
                "max_index": max_index,
            },
        )

        if not adjacent_results:
            # No adjacent segments found - return current context
            return {
                "expanded_context": candidate.get("context_text", ""),
                "segment_count": 0,
                "can_expand": False,
            }

        # Concatenate all segment texts with separator
        expanded_text = " ... ".join(seg["raw_text"] for seg in adjacent_results if seg["raw_text"])

        return {
            "expanded_context": expanded_text,
            "segment_count": len(adjacent_results),
            "can_expand": True,
        }

    def get_review_candidates_for_filing(
        self,
        filing_id: int,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get review candidates for a filing.

        Args:
            filing_id: Filing to get candidates for
            status: Optional filter by review_status
            limit: Maximum number to return
            offset: Number to skip (for pagination)

        Returns:
            List of candidate records

        Raises:
            ValidationError: If status is provided but not a valid review status
        """
        # Validate status if provided
        if status is not None:
            validate_enum(status, REVIEW_STATUSES, "review_status")

        sql = """
            SELECT * FROM review_candidates
            WHERE filing_id = %(filing_id)s
        """
        params: dict[str, Any] = {"filing_id": filing_id}

        if status:
            sql += " AND review_status = %(status)s"
            params["status"] = status

        sql += " ORDER BY char_position"

        if limit:
            sql += " LIMIT %(limit)s OFFSET %(offset)s"
            params["limit"] = limit
            params["offset"] = offset

        return self.query(sql, params)

    def get_review_candidates_with_decisions(
        self,
        filing_id: int,
        status: str | None = None,
        metric_id: str | None = None,
        confidence_level: str | None = None,
        sort_by: str = "position",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get review candidates for a filing WITH their decisions (if any).

        This method uses a LEFT JOIN to fetch candidates and decisions in a single
        query, eliminating the N+1 query pattern when displaying candidates with
        their review decisions.

        Args:
            filing_id: Filing to get candidates for
            status: Optional filter by review_status
            metric_id: Optional filter by suggested_metric_id
            confidence_level: Optional filter by confidence tier ('high', 'medium', 'low')
            sort_by: Sort order ('position', 'confidence_asc', 'confidence_desc',
                     'value_asc', 'value_desc')
            limit: Maximum number to return
            offset: Number to skip (for pagination)

        Returns:
            List of candidate records with segment fields (segment_type, segment_html)
            and decision fields (decision_id, decision, assigned_metric_id,
            rejection_category, rejection_reason, reviewer_notes, reviewer_id,
            review_time_seconds, decision_created_at).
            Segment and decision fields are NULL if no source segment or decision exists.

        Raises:
            ValidationError: If status is provided but not a valid review status
        """
        # Validate status if provided
        if status is not None:
            validate_enum(status, REVIEW_STATUSES, "review_status")

        sql = """
            SELECT
                rc.*,
                ss.segment_type,
                ss.raw_html as segment_html,
                rd.decision_id,
                rd.decision,
                rd.assigned_metric_id,
                rd.rejection_category,
                rd.rejection_reason,
                rd.reviewer_notes,
                rd.reviewer_id,
                rd.review_time_seconds,
                rd.created_at as decision_created_at
            FROM review_candidates rc
            LEFT JOIN source_segments ss ON rc.source_segment_id = ss.source_segment_id
            LEFT JOIN (
                SELECT DISTINCT ON (candidate_id)
                    candidate_id,
                    decision_id,
                    decision,
                    assigned_metric_id,
                    rejection_category,
                    rejection_reason,
                    reviewer_notes,
                    reviewer_id,
                    review_time_seconds,
                    created_at
                FROM review_decisions
                WHERE candidate_id IN (
                    SELECT candidate_id FROM review_candidates WHERE filing_id = %(filing_id)s
                )
                ORDER BY candidate_id, created_at DESC
            ) rd ON rc.candidate_id = rd.candidate_id
            WHERE rc.filing_id = %(filing_id)s
        """
        params: dict[str, Any] = {"filing_id": filing_id}

        if status:
            sql += " AND rc.review_status = %(status)s"
            params["status"] = status

        # Add metric filter
        if metric_id:
            sql += " AND rc.suggested_metric_id = %(metric_id)s"
            params["metric_id"] = metric_id

        # Add confidence filter
        if confidence_level == "high":
            sql += " AND rc.suggestion_confidence >= 0.7"
        elif confidence_level == "medium":
            sql += " AND rc.suggestion_confidence >= 0.4 AND rc.suggestion_confidence < 0.7"
        elif confidence_level == "low":
            sql += " AND rc.suggestion_confidence < 0.4"

        # Dynamic ORDER BY based on sort_by parameter
        sort_clauses = {
            "position": "rc.char_position",
            "confidence_asc": "rc.suggestion_confidence ASC, rc.char_position",
            "confidence_desc": "rc.suggestion_confidence DESC, rc.char_position",
            "value_asc": "rc.parsed_value ASC, rc.char_position",
            "value_desc": "rc.parsed_value DESC, rc.char_position",
        }
        order_by = sort_clauses.get(sort_by, "rc.char_position")
        sql += f" ORDER BY {order_by}"

        if limit:
            sql += " LIMIT %(limit)s OFFSET %(offset)s"
            params["limit"] = limit
            params["offset"] = offset

        results = self.query(sql, params)

        # Post-process: Check if segment HTML contains the value/keyword
        # If not, clear segment_html so the UI falls back to context_text display.
        # This handles cases where:
        # - HTML is truncated and the number appears beyond the truncation point
        # - Number appears in context_prefix from a different segment
        # - HTML markup inflates size, causing earlier truncation than raw_text
        for result in results:
            segment_html = result.get("segment_html")
            raw_number_text = result.get("raw_number_text")
            triggering_keyword = result.get("triggering_keyword")

            # Initialize dual display field
            result["segment_html_table_only"] = None

            # Check any segment with HTML (regardless of segment_type)
            if segment_html and raw_number_text and triggering_keyword:
                # Check if the HTML actually contains the value and keyword
                # If not, clear it so UI falls back to context_text (which always has them)
                has_value = raw_number_text in segment_html
                # Case-insensitive keyword check to match _highlight_html behavior
                has_keyword = triggering_keyword.lower() in segment_html.lower()

                if not (has_value and has_keyword):
                    # Check if the HTML contains a table - if so, preserve it for dual display
                    # This allows showing table structure alongside context_text with highlighting
                    has_table = "<table" in segment_html.lower()

                    if has_table and has_keyword:
                        # Table structure is useful even without the value highlighted
                        # Store it for dual display mode in the UI
                        logger.debug(
                            f"Segment HTML for candidate {result.get('candidate_id')} has table "
                            f"with keyword but value is truncated. Enabling dual display mode."
                        )
                        result["segment_html_table_only"] = segment_html
                    else:
                        logger.debug(
                            f"Segment HTML for candidate {result.get('candidate_id')} doesn't contain "
                            f"value={has_value}, keyword={has_keyword}. Clearing for context_text fallback."
                        )

                    # Clear segment_html to force display of context_text instead
                    result["segment_html"] = None
                    result["segment_type"] = None

        return results

    def get_review_candidate_summary(self, filing_id: int) -> dict:
        """
        Get aggregate summary of review candidates for a filing without fetching HTML.

        Returns counts by status, extraction date, and available metric IDs — replacing
        the expensive unfiltered get_review_candidates_with_decisions() call that was
        used only for these aggregates.

        Args:
            filing_id: Filing to summarize

        Returns:
            Dict with keys: total, reviewed, pending, extraction_date, available_metrics
        """
        sql = """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE review_status = 'reviewed') AS reviewed,
                COUNT(*) FILTER (WHERE review_status = 'pending') AS pending,
                MIN(created_at) AS extraction_date,
                ARRAY_AGG(DISTINCT suggested_metric_id)
                    FILTER (WHERE suggested_metric_id IS NOT NULL) AS available_metrics
            FROM review_candidates
            WHERE filing_id = %(filing_id)s
        """
        results = self.query(sql, {"filing_id": filing_id})
        if results:
            row = results[0]
            return {
                "total": row["total"] or 0,
                "reviewed": row["reviewed"] or 0,
                "pending": row["pending"] or 0,
                "extraction_date": row["extraction_date"],
                "available_metrics": row["available_metrics"] or [],
            }
        return {
            "total": 0,
            "reviewed": 0,
            "pending": 0,
            "extraction_date": None,
            "available_metrics": [],
        }

    def get_next_pending_candidate_id(
        self,
        filing_id: int,
        current_candidate_id: int,
        status: str | None = "pending",
        metric_id: str | None = None,
        confidence_level: str | None = None,
        sort_by: str = "position",
    ) -> int | None:
        """
        Find the next candidate ID in the filtered, sorted list after the current one.

        Fetches only IDs (no HTML), making this much cheaper than loading full candidates.
        Wraps around to the beginning if the current candidate is last in the list.

        Args:
            filing_id: Filing to search within
            current_candidate_id: The candidate we're navigating away from
            status: Filter by review_status (None = no filter)
            metric_id: Filter by suggested_metric_id (None = no filter)
            confidence_level: Filter by confidence tier ('high', 'medium', 'low'; None = no filter)
            sort_by: Sort order matching get_review_candidates_with_decisions sort options

        Returns:
            The next candidate_id, or None if no other candidate exists in the filtered list
        """
        sort_map = {
            "position": "char_position",
            "confidence_asc": "suggestion_confidence ASC, char_position",
            "confidence_desc": "suggestion_confidence DESC, char_position",
            "value_asc": "parsed_value ASC, char_position",
            "value_desc": "parsed_value DESC, char_position",
        }
        order_by = sort_map.get(sort_by, "char_position")

        where_clauses = ["filing_id = %(filing_id)s"]
        params: dict[str, Any] = {"filing_id": filing_id}

        if status is not None:
            where_clauses.append("review_status = %(status)s")
            params["status"] = status
        if metric_id is not None:
            where_clauses.append("suggested_metric_id = %(metric_id)s")
            params["metric_id"] = metric_id
        if confidence_level == "high":
            where_clauses.append("suggestion_confidence >= 0.7")
        elif confidence_level == "medium":
            where_clauses.append("suggestion_confidence >= 0.4 AND suggestion_confidence < 0.7")
        elif confidence_level == "low":
            where_clauses.append("suggestion_confidence < 0.4")

        where_sql = " AND ".join(where_clauses)
        sql = f"SELECT candidate_id FROM review_candidates WHERE {where_sql} ORDER BY {order_by}"
        rows = self.query(sql, params)
        ids = [r["candidate_id"] for r in rows]

        if not ids:
            return None

        try:
            current_index = ids.index(current_candidate_id)
            next_index = current_index + 1
            if next_index < len(ids):
                return ids[next_index]
            # Wrap: first in list that isn't the current candidate
            first = ids[0]
            return first if first != current_candidate_id else None
        except ValueError:
            # current_candidate_id filtered out (e.g., just reviewed and status=pending)
            return ids[0] if ids else None

    def get_all_reviewed_candidates_with_decisions(
        self,
        metric_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get all reviewed candidates with decisions across all filings.

        Similar to get_review_candidates_with_decisions() but not filtered
        by filing_id. Used for pattern analysis across the full dataset.

        Only returns candidates that have been reviewed (have decisions).
        Uses an INNER JOIN instead of LEFT JOIN to ensure all returned
        candidates have a decision.

        Args:
            metric_id: Optional filter by suggested_metric_id
            limit: Maximum number to return
            offset: Number to skip (for pagination)

        Returns:
            List of candidate records with decision fields (decision_id, decision,
            assigned_metric_id, rejection_category, rejection_reason, reviewer_notes,
            reviewer_id, review_time_seconds, decision_created_at).

        Example:
            >>> db = DatabaseAdapter(connection_string)
            >>> # Get all reviewed candidates
            >>> all_decisions = db.get_all_reviewed_candidates_with_decisions()
            >>> # Get reviewed candidates for specific metric
            >>> arr_decisions = db.get_all_reviewed_candidates_with_decisions(
            ...     metric_id="annual_recurring_revenue"
            ... )
            >>> # Get first 100 with pagination
            >>> batch = db.get_all_reviewed_candidates_with_decisions(limit=100)
        """
        sql = """
            SELECT
                rc.*,
                rd.decision_id,
                rd.decision,
                rd.assigned_metric_id,
                rd.rejection_category,
                rd.rejection_reason,
                rd.reviewer_notes,
                rd.reviewer_id,
                rd.review_time_seconds,
                rd.created_at as decision_created_at
            FROM review_candidates rc
            INNER JOIN (
                SELECT DISTINCT ON (candidate_id)
                    candidate_id,
                    decision_id,
                    decision,
                    assigned_metric_id,
                    rejection_category,
                    rejection_reason,
                    reviewer_notes,
                    reviewer_id,
                    review_time_seconds,
                    created_at
                FROM review_decisions
                ORDER BY candidate_id, created_at DESC
            ) rd ON rc.candidate_id = rd.candidate_id
            WHERE 1=1
        """
        params: dict[str, Any] = {}

        if metric_id:
            sql += " AND rc.suggested_metric_id = %(metric_id)s"
            params["metric_id"] = metric_id

        sql += " ORDER BY rc.candidate_id"

        if limit:
            sql += " LIMIT %(limit)s OFFSET %(offset)s"
            params["limit"] = limit
            params["offset"] = offset
        else:
            logger.warning(
                "get_all_reviewed_candidates_with_decisions called without limit; "
                "may return unbounded result set as dataset grows"
            )

        return self.query(sql, params)

    def get_pending_candidates(
        self,
        filing_id: int | None = None,
        batch_id: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Get candidates pending review.

        Args:
            filing_id: Optional filter by filing
            batch_id: Optional filter by batch
            limit: Maximum number to return

        Returns:
            List of pending candidate records
        """
        sql = """
            SELECT rc.*, f.accession_number, c.company_name
            FROM review_candidates rc
            JOIN filings f ON rc.filing_id = f.filing_id
            JOIN companies c ON rc.company_id = c.company_id
            WHERE rc.review_status = 'pending'
        """
        params: dict[str, Any] = {"limit": limit}

        if filing_id:
            sql += " AND rc.filing_id = %(filing_id)s"
            params["filing_id"] = filing_id

        if batch_id:
            sql += " AND rc.review_batch_id = %(batch_id)s"
            params["batch_id"] = batch_id

        sql += " ORDER BY rc.filing_id, rc.char_position LIMIT %(limit)s"

        return self.query(sql, params)

    def update_candidate_status(self, candidate_id: int, status: str) -> bool:
        """
        Update a candidate's review status.

        Args:
            candidate_id: Candidate to update
            status: New status ('pending', 'in_progress', 'reviewed', 'skipped')

        Returns:
            True if a row was updated, False if no candidate found with given ID

        Raises:
            ValidationError: If status is not a valid review status
        """
        # Validate status
        validate_enum(status, REVIEW_STATUSES, "review_status")

        sql = """
            UPDATE review_candidates
            SET review_status = %(status)s, updated_at = now()
            WHERE candidate_id = %(candidate_id)s
            RETURNING candidate_id
        """
        result = self.execute(sql, {"candidate_id": candidate_id, "status": status}, fetch=True)
        updated = bool(result)
        if updated:
            logger.debug(f"Updated candidate {candidate_id} status to {status}")
        else:
            logger.warning(f"No candidate found with id {candidate_id}")
        return updated

    def bulk_update_candidate_status(self, candidate_ids: list[int], status: str) -> int:
        """
        Update status for multiple candidates efficiently.

        Uses PostgreSQL ANY() for single-statement bulk update.

        Args:
            candidate_ids: List of candidate IDs to update
            status: New status ('pending', 'in_progress', 'reviewed', 'skipped')

        Returns:
            Number of rows updated

        Raises:
            ValidationError: If status is not a valid review status
        """
        if not candidate_ids:
            return 0

        # Validate status
        validate_enum(status, REVIEW_STATUSES, "review_status")

        sql = """
            UPDATE review_candidates
            SET review_status = %(status)s, updated_at = now()
            WHERE candidate_id = ANY(%(candidate_ids)s)
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {"candidate_ids": candidate_ids, "status": status},
                )
                rows_updated = cur.rowcount

        logger.debug(f"Bulk updated {rows_updated} candidates to status '{status}'")
        return rows_updated

    # =========================================================================
    # Private Helpers for Conflict Resolution
    # =========================================================================

    def _fetch_conflicting_candidates(
        self,
        cur,
        uniqueness_keys: list[tuple],
        has_segment: bool,
    ) -> dict[tuple, dict[str, Any]]:
        """
        Fetch existing candidates that would conflict with the given keys.

        Args:
            cur: Database cursor
            uniqueness_keys: List of uniqueness key tuples:
                - If has_segment=True: (filing_id, segment_id, char_pos, metric_id)
                - If has_segment=False: (filing_id, char_pos, metric_id)
            has_segment: If True, keys include segment_id (non-NULL case)

        Returns:
            Dict mapping uniqueness_key -> existing candidate row dict
        """
        if not uniqueness_keys:
            return {}

        if has_segment:
            # Candidates WITH source_segment_id
            sql = """
                SELECT candidate_id, filing_id, source_segment_id, char_position,
                       suggested_metric_id, suggestion_confidence, context_text,
                       raw_number_text, parsed_value, parsed_unit,
                       triggering_keyword, keyword_distance, keyword_position,
                       features, company_id
                FROM review_candidates
                WHERE (filing_id, source_segment_id, char_position, suggested_metric_id)
                      IN (SELECT * FROM UNNEST(
                          %(filing_ids)s::bigint[],
                          %(segment_ids)s::bigint[],
                          %(char_positions)s::int[],
                          %(metric_ids)s::text[]
                      ))
                  AND source_segment_id IS NOT NULL
            """
            params = {
                "filing_ids": [k[0] for k in uniqueness_keys],
                "segment_ids": [k[1] for k in uniqueness_keys],
                "char_positions": [k[2] for k in uniqueness_keys],
                "metric_ids": [k[3] for k in uniqueness_keys],
            }
        else:
            # Candidates WITHOUT source_segment_id (NULL case)
            sql = """
                SELECT candidate_id, filing_id, source_segment_id, char_position,
                       suggested_metric_id, suggestion_confidence, context_text,
                       raw_number_text, parsed_value, parsed_unit,
                       triggering_keyword, keyword_distance, keyword_position,
                       features, company_id
                FROM review_candidates
                WHERE (filing_id, char_position, suggested_metric_id)
                      IN (SELECT * FROM UNNEST(
                          %(filing_ids)s::bigint[],
                          %(char_positions)s::int[],
                          %(metric_ids)s::text[]
                      ))
                  AND source_segment_id IS NULL
            """
            params = {
                "filing_ids": [k[0] for k in uniqueness_keys],
                "char_positions": [k[1] for k in uniqueness_keys],
                "metric_ids": [k[2] for k in uniqueness_keys],
            }

        cur.execute(sql, params)
        rows = cur.fetchall()

        # Map uniqueness_key -> row
        result: dict[tuple, dict[str, Any]] = {}
        for row in rows:
            if has_segment:
                key = (
                    row["filing_id"],
                    row["source_segment_id"],
                    row["char_position"],
                    row["suggested_metric_id"],
                )
            else:
                key = (
                    row["filing_id"],
                    row["char_position"],
                    row["suggested_metric_id"],
                )
            result[key] = dict(row)

        return result

    def _bulk_log_suppressed(
        self,
        cur,
        entries: list[dict[str, Any]],
    ) -> list[int]:
        """
        Bulk insert suppressed candidate records.

        Args:
            cur: Database cursor
            entries: List of dicts with suppressed_candidates columns

        Returns:
            List of suppressed_id values
        """
        if not entries:
            return []

        # Build arrays for UNNEST
        filing_ids = []
        company_ids = []
        source_segment_ids = []
        char_positions = []
        context_texts = []
        raw_number_texts = []
        parsed_values = []
        parsed_units = []
        triggering_keywords = []
        keyword_distances = []
        keyword_positions = []
        suggested_metric_ids = []
        suggestion_confidences = []
        features_list = []
        winner_candidate_ids = []
        suppression_reasons = []
        winner_confidences = []

        for entry in entries:
            filing_ids.append(entry["filing_id"])
            company_ids.append(entry["company_id"])
            source_segment_ids.append(entry.get("source_segment_id"))
            char_positions.append(entry["char_position"])
            context_texts.append(entry["context_text"])
            raw_number_texts.append(entry["raw_number_text"])
            parsed_values.append(entry.get("parsed_value"))
            parsed_units.append(entry.get("parsed_unit"))
            triggering_keywords.append(entry["triggering_keyword"])
            keyword_distances.append(entry["keyword_distance"])
            keyword_positions.append(entry["keyword_position"])
            suggested_metric_ids.append(entry.get("suggested_metric_id"))
            suggestion_confidences.append(entry.get("suggestion_confidence"))
            features = entry.get("features")
            features_list.append(json.dumps(features) if features else None)
            winner_candidate_ids.append(entry["winner_candidate_id"])
            suppression_reasons.append(entry["suppression_reason"])
            winner_confidences.append(entry.get("winner_confidence"))

        sql = """
            INSERT INTO suppressed_candidates (
                filing_id, company_id, source_segment_id,
                char_position, context_text, raw_number_text,
                parsed_value, parsed_unit,
                triggering_keyword, keyword_distance, keyword_position,
                suggested_metric_id, suggestion_confidence, features,
                winner_candidate_id, suppression_reason, winner_confidence
            )
            SELECT
                filing_id, company_id, source_segment_id,
                char_position, context_text, raw_number_text,
                parsed_value, parsed_unit,
                triggering_keyword, keyword_distance, keyword_position,
                suggested_metric_id, suggestion_confidence, features,
                winner_candidate_id, suppression_reason, winner_confidence
            FROM UNNEST(
                %(filing_ids)s::bigint[],
                %(company_ids)s::bigint[],
                %(source_segment_ids)s::bigint[],
                %(char_positions)s::int[],
                %(context_texts)s::text[],
                %(raw_number_texts)s::text[],
                %(parsed_values)s::numeric[],
                %(parsed_units)s::text[],
                %(triggering_keywords)s::text[],
                %(keyword_distances)s::int[],
                %(keyword_positions)s::text[],
                %(suggested_metric_ids)s::text[],
                %(suggestion_confidences)s::numeric[],
                %(features_list)s::jsonb[],
                %(winner_candidate_ids)s::bigint[],
                %(suppression_reasons)s::text[],
                %(winner_confidences)s::numeric[]
            ) WITH ORDINALITY AS t(
                filing_id, company_id, source_segment_id,
                char_position, context_text, raw_number_text,
                parsed_value, parsed_unit,
                triggering_keyword, keyword_distance, keyword_position,
                suggested_metric_id, suggestion_confidence, features,
                winner_candidate_id, suppression_reason, winner_confidence,
                ord
            )
            ORDER BY ord
            RETURNING suppressed_id
        """

        cur.execute(
            sql,
            {
                "filing_ids": filing_ids,
                "company_ids": company_ids,
                "source_segment_ids": source_segment_ids,
                "char_positions": char_positions,
                "context_texts": context_texts,
                "raw_number_texts": raw_number_texts,
                "parsed_values": parsed_values,
                "parsed_units": parsed_units,
                "triggering_keywords": triggering_keywords,
                "keyword_distances": keyword_distances,
                "keyword_positions": keyword_positions,
                "suggested_metric_ids": suggested_metric_ids,
                "suggestion_confidences": suggestion_confidences,
                "features_list": features_list,
                "winner_candidate_ids": winner_candidate_ids,
                "suppression_reasons": suppression_reasons,
                "winner_confidences": winner_confidences,
            },
        )
        results = cur.fetchall()
        return [row["suppressed_id"] for row in results]

    def _identify_runner_ups(
        self,
        candidates: list[dict[str, Any]],
        final_ids: list[int],
        winner_metrics: dict[int, tuple[str | None, float | None]],
    ) -> list[dict[str, Any]]:
        """
        Identify runner-up candidates for each position.

        Groups by position_key (filing_id, segment_id, char_position).
        For each position with multiple metric suggestions, finds the
        best alternative to the winner.

        Args:
            candidates: Original input candidates
            final_ids: Final candidate_id for each input (in same order)
            winner_metrics: Dict of candidate_id -> (metric_id, confidence)

        Returns:
            List of suppression entries for runner-ups
        """
        # Group candidates by position_key
        # position_key = (filing_id, source_segment_id, char_position)
        from collections import defaultdict

        position_groups: dict[tuple, list[tuple[int, dict[str, Any]]]] = defaultdict(list)

        for idx, candidate in enumerate(candidates):
            position_key = (
                candidate["filing_id"],
                candidate.get("source_segment_id"),
                candidate["char_position"],
            )
            position_groups[position_key].append((idx, candidate))

        runner_up_entries: list[dict[str, Any]] = []

        for _position_key, group in position_groups.items():
            if len(group) < 2:
                # No alternatives at this position
                continue

            # Find the winner at this position
            # The winner is the one whose final_id is in winner_metrics
            # and has the highest confidence
            winner_idx = None
            winner_id = None
            winner_metric = None
            winner_conf = None

            for idx, _cand in group:
                cand_id = final_ids[idx]
                if cand_id in winner_metrics:
                    metric_id, conf = winner_metrics[cand_id]
                    if winner_idx is None or (conf or 0) > (winner_conf or 0):
                        winner_idx = idx
                        winner_id = cand_id
                        winner_metric = metric_id
                        winner_conf = conf

            if winner_id is None:
                # No winner found (shouldn't happen)
                continue

            # Find the best runner-up: highest confidence with different metric
            runner_up_idx = None
            runner_up_conf = -1.0

            for idx, cand in group:
                cand_metric = cand.get("suggested_metric_id")
                cand_conf = cand.get("suggestion_confidence") or 0

                # Must have different metric than winner
                if cand_metric == winner_metric:
                    continue

                # Must be a different candidate (not the winner)
                if idx == winner_idx:
                    continue

                if cand_conf > runner_up_conf:
                    runner_up_idx = idx
                    runner_up_conf = cand_conf

            if runner_up_idx is not None:
                runner_cand = candidates[runner_up_idx]
                runner_up_entries.append(
                    {
                        "filing_id": runner_cand["filing_id"],
                        "company_id": runner_cand["company_id"],
                        "source_segment_id": runner_cand.get("source_segment_id"),
                        "char_position": runner_cand["char_position"],
                        "context_text": runner_cand["context_text"],
                        "raw_number_text": runner_cand["raw_number_text"],
                        "parsed_value": runner_cand.get("parsed_value"),
                        "parsed_unit": runner_cand.get("parsed_unit"),
                        "triggering_keyword": runner_cand["triggering_keyword"],
                        "keyword_distance": runner_cand["keyword_distance"],
                        "keyword_position": runner_cand["keyword_position"],
                        "suggested_metric_id": runner_cand.get("suggested_metric_id"),
                        "suggestion_confidence": runner_cand.get("suggestion_confidence"),
                        "features": runner_cand.get("features"),
                        "winner_candidate_id": winner_id,
                        "suppression_reason": "runner_up",
                        "winner_confidence": winner_conf,
                        "input_index": runner_up_idx,
                    }
                )

        return runner_up_entries

    # =========================================================================
    # Review Candidates - Public Methods
    # =========================================================================

    def bulk_insert_review_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        log_suppressed: bool = False,
    ) -> list[int] | tuple[list[int], list[dict[str, Any]]]:
        """
        Bulk insert review candidates with conflict resolution.

        Handles conflicts by keeping higher-confidence candidates. When
        log_suppressed=True, also captures suppressed alternatives and
        runner-ups for UI display.

        Uses a two-phase algorithm:
        1. Conflict Detection: Pre-fetch existing candidates, resolve by confidence
        2. Runner-Up Capture: Log best alternative metric at each position

        Args:
            candidates: List of candidate dicts. Required keys:
                - filing_id, company_id, char_position, context_text
                - raw_number_text, triggering_keyword, keyword_distance
                - keyword_position
              Optional keys:
                - source_segment_id, parsed_value, parsed_unit
                - suggested_metric_id, suggestion_confidence, features
                - review_batch_id

            log_suppressed: If True, log suppressed candidates to
                suppressed_candidates table and return detailed info.

        Returns:
            If log_suppressed=False (default):
                list[int] - candidate_ids, one per input, in input order.
                           For conflicts where input loses, returns winner's ID.

            If log_suppressed=True:
                tuple[list[int], list[dict]] where:
                    - list[int]: candidate_ids as above
                    - list[dict]: suppression log entries with keys:
                        - suppressed_id: ID in suppressed_candidates table
                        - winner_candidate_id: ID of winning candidate
                        - suppression_reason: 'lower_confidence' | 'runner_up'
                        - input_index: index in original candidates list (or None)

        Guarantees:
            - len(returned_ids) == len(candidates) ALWAYS
            - returned_ids[i] is the candidate_id for candidates[i]
            - Order preserved: zip(candidates, returned_ids, strict=True) is safe

        Raises:
            ValidationError: If any candidate has invalid keyword_position
            ValidationError: If any candidate has invalid suggestion_confidence
        """
        if not candidates:
            return ([], []) if log_suppressed else []

        # Validate all candidates first (fail fast before any DB work)
        for i, candidate in enumerate(candidates):
            keyword_position = candidate["keyword_position"]
            validate_enum(
                keyword_position,
                KEYWORD_POSITIONS,
                f"keyword_position (candidate {i})",
            )

            validate_score(
                candidate.get("suggestion_confidence"),
                "suggestion_confidence",
                context=f"candidate {i}",
            )

        # =====================================================================
        # Phase 1: Within-Batch Deduplication
        # =====================================================================
        # Before checking the database, we first deduplicate within the input batch.
        # This handles the case where the same candidate appears multiple times in
        # a single call (e.g., from overlapping keyword matches).
        #
        # Uniqueness is determined by:
        #   - WITH segment: (filing_id, source_segment_id, char_position, metric_id)
        #   - WITHOUT segment: (filing_id, char_position, metric_id)
        #
        # When duplicates exist, highest confidence wins. Ties go to first occurrence.
        # Losers are tracked in batch_suppressed for later logging.

        # input_keys[i] = (uniqueness_key, has_segment) for candidates[i]
        input_keys: list[tuple[tuple, bool]] = []

        # batch_winners[ukey] = (input_index, confidence) for the best candidate per key
        batch_winners: dict[tuple, tuple[int, float]] = {}

        # batch_suppressed = [(loser_index, winner_index), ...] for within-batch losers
        batch_suppressed: list[tuple[int, int]] = []

        for idx, candidate in enumerate(candidates):
            segment_id = candidate.get("source_segment_id")
            has_segment = segment_id is not None

            # Build uniqueness key - different structure for NULL vs non-NULL segment
            # because PostgreSQL partial indexes require separate handling
            if has_segment:
                ukey: tuple = (
                    candidate["filing_id"],
                    segment_id,
                    candidate["char_position"],
                    candidate.get("suggested_metric_id"),
                )
            else:
                ukey = (
                    candidate["filing_id"],
                    candidate["char_position"],
                    candidate.get("suggested_metric_id"),
                )

            input_keys.append((ukey, has_segment))
            conf = candidate.get("suggestion_confidence") or 0

            if ukey in batch_winners:
                # Duplicate found - compare confidence to determine winner
                existing_idx, existing_conf = batch_winners[ukey]
                if conf > existing_conf:
                    # New candidate wins, previous winner becomes suppressed
                    batch_suppressed.append((existing_idx, idx))
                    batch_winners[ukey] = (idx, conf)
                else:
                    # Existing winner keeps position (ties favor earlier occurrence)
                    batch_suppressed.append((idx, existing_idx))
            else:
                # First occurrence of this key - becomes initial winner
                batch_winners[ukey] = (idx, conf)

        # =====================================================================
        # Phase 2: Database Conflict Resolution
        # =====================================================================
        # Now we check if any batch winners conflict with existing DB rows.
        # This handles idempotent re-runs where candidate generation is executed
        # multiple times for the same filing.
        #
        # We split candidates into two groups based on source_segment_id:
        #   - WITH segment: Uses uq_review_candidates_with_segment partial index
        #   - WITHOUT segment: Uses uq_review_candidates_without_segment partial index
        #
        # PostgreSQL partial indexes don't work with a single ON CONFLICT clause,
        # so we must query each group separately.

        # Separate batch winners by segment presence for partial index compatibility
        with_segment_keys: list[tuple[int, tuple]] = []  # [(input_idx, ukey), ...]
        without_segment_keys: list[tuple[int, tuple]] = []

        for ukey, (input_idx, _) in batch_winners.items():
            _, has_segment = input_keys[input_idx]
            if has_segment:
                with_segment_keys.append((input_idx, ukey))
            else:
                without_segment_keys.append((input_idx, ukey))

        # Prepare result tracking
        final_ids: list[int | None] = [None] * len(candidates)
        suppression_entries: list[dict[str, Any]] = []
        # Track winner metrics for runner-up detection
        winner_metrics: dict[int, tuple[str | None, float | None]] = {}

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Fetch existing conflicts
                existing_with_seg = self._fetch_conflicting_candidates(
                    cur, [k for _, k in with_segment_keys], has_segment=True
                )
                existing_without_seg = self._fetch_conflicting_candidates(
                    cur, [k for _, k in without_segment_keys], has_segment=False
                )

                # Candidates to insert (batch winners that don't lose to DB)
                to_insert: list[tuple[int, dict[str, Any]]] = []
                # Candidates to update (batch winners that beat DB)
                to_update: list[
                    tuple[int, int, dict[str, Any], dict[str, Any]]
                ] = []  # (input_idx, existing_id, new_cand, old_cand)

                # Process with-segment candidates
                for input_idx, ukey in with_segment_keys:
                    candidate = candidates[input_idx]
                    # Convert to float for consistent comparison (DB returns Decimal)
                    new_conf = float(candidate.get("suggestion_confidence") or 0)

                    if ukey in existing_with_seg:
                        existing = existing_with_seg[ukey]
                        existing_conf = float(existing.get("suggestion_confidence") or 0)
                        existing_id = existing["candidate_id"]

                        if new_conf > existing_conf:
                            # New wins: update existing row, log old as suppressed
                            to_update.append((input_idx, existing_id, candidate, existing))
                            final_ids[input_idx] = existing_id
                        else:
                            # Existing wins: skip insert, log new as suppressed
                            final_ids[input_idx] = existing_id
                            if log_suppressed:
                                suppression_entries.append(
                                    {
                                        **candidate,
                                        "winner_candidate_id": existing_id,
                                        "suppression_reason": "lower_confidence",
                                        "winner_confidence": existing_conf,
                                        "input_index": input_idx,
                                    }
                                )
                            # Track winner metric
                            winner_metrics[existing_id] = (
                                existing.get("suggested_metric_id"),
                                existing_conf,
                            )
                    else:
                        # No conflict: insert new
                        to_insert.append((input_idx, candidate))

                # Process without-segment candidates
                for input_idx, ukey in without_segment_keys:
                    candidate = candidates[input_idx]
                    # Convert to float for consistent comparison (DB returns Decimal)
                    new_conf = float(candidate.get("suggestion_confidence") or 0)

                    if ukey in existing_without_seg:
                        existing = existing_without_seg[ukey]
                        existing_conf = float(existing.get("suggestion_confidence") or 0)
                        existing_id = existing["candidate_id"]

                        if new_conf > existing_conf:
                            # New wins
                            to_update.append((input_idx, existing_id, candidate, existing))
                            final_ids[input_idx] = existing_id
                        else:
                            # Existing wins
                            final_ids[input_idx] = existing_id
                            if log_suppressed:
                                suppression_entries.append(
                                    {
                                        **candidate,
                                        "winner_candidate_id": existing_id,
                                        "suppression_reason": "lower_confidence",
                                        "winner_confidence": existing_conf,
                                        "input_index": input_idx,
                                    }
                                )
                            winner_metrics[existing_id] = (
                                existing.get("suggested_metric_id"),
                                existing_conf,
                            )
                    else:
                        to_insert.append((input_idx, candidate))

                # =====================================================================
                # Execute Inserts
                # =====================================================================
                if to_insert:
                    # Sort by input_idx to maintain order in RETURNING
                    to_insert.sort(key=lambda x: x[0])
                    insert_candidates = [c for _, c in to_insert]
                    insert_indices = [idx for idx, _ in to_insert]

                    inserted_ids = self._execute_bulk_insert(cur, insert_candidates)

                    for i, cid in enumerate(inserted_ids):
                        input_idx = insert_indices[i]
                        final_ids[input_idx] = cid
                        # Track winner metric
                        cand = insert_candidates[i]
                        winner_metrics[cid] = (
                            cand.get("suggested_metric_id"),
                            cand.get("suggestion_confidence"),
                        )

                # =====================================================================
                # Execute Updates (winner replaces existing)
                # =====================================================================
                for _input_idx, existing_id, new_cand, old_cand in to_update:
                    # Log old candidate as suppressed
                    if log_suppressed:
                        suppression_entries.append(
                            {
                                "filing_id": old_cand["filing_id"],
                                "company_id": old_cand["company_id"],
                                "source_segment_id": old_cand.get("source_segment_id"),
                                "char_position": old_cand["char_position"],
                                "context_text": old_cand["context_text"],
                                "raw_number_text": old_cand["raw_number_text"],
                                "parsed_value": old_cand.get("parsed_value"),
                                "parsed_unit": old_cand.get("parsed_unit"),
                                "triggering_keyword": old_cand["triggering_keyword"],
                                "keyword_distance": old_cand["keyword_distance"],
                                "keyword_position": old_cand["keyword_position"],
                                "suggested_metric_id": old_cand.get("suggested_metric_id"),
                                "suggestion_confidence": old_cand.get("suggestion_confidence"),
                                "features": old_cand.get("features"),
                                "winner_candidate_id": existing_id,
                                "suppression_reason": "lower_confidence",
                                "winner_confidence": new_cand.get("suggestion_confidence"),
                                "input_index": None,  # From DB, not input
                            }
                        )

                    # Update the existing row with new values
                    self._execute_update(cur, existing_id, new_cand)

                    # Track winner metric
                    winner_metrics[existing_id] = (
                        new_cand.get("suggested_metric_id"),
                        new_cand.get("suggestion_confidence"),
                    )

                # =====================================================================
                # Handle Within-Batch Suppressed
                # =====================================================================
                for loser_idx, winner_idx in batch_suppressed:
                    winner_id = final_ids[winner_idx]
                    if winner_id is not None:
                        final_ids[loser_idx] = winner_id
                        if log_suppressed:
                            loser_cand = candidates[loser_idx]
                            winner_cand = candidates[winner_idx]
                            suppression_entries.append(
                                {
                                    **loser_cand,
                                    "winner_candidate_id": winner_id,
                                    "suppression_reason": "lower_confidence",
                                    "winner_confidence": winner_cand.get("suggestion_confidence"),
                                    "input_index": loser_idx,
                                }
                            )

                # =====================================================================
                # Phase 3: Runner-Up Detection
                # =====================================================================
                # For UI enhancement: at each position (filing, segment, char_position),
                # identify the best ALTERNATIVE metric suggestion. This allows the review
                # UI to show "We suggested X, but also considered Y" for faster
                # reclassification when the reviewer disagrees with the suggestion.
                #
                # Runner-up is logged with reason='runner_up' and differs from
                # 'lower_confidence' in that it has a DIFFERENT metric_id than the winner.
                if log_suppressed:
                    # Sanity check: all candidates should have a final_id by now
                    if not all(fid is not None for fid in final_ids):
                        raise RuntimeError("All final_ids must be set before runner-up detection")

                    runner_ups = self._identify_runner_ups(
                        candidates,
                        final_ids,
                        winner_metrics,  # type: ignore
                    )
                    suppression_entries.extend(runner_ups)

                    # Bulk insert all suppression records (lower_confidence + runner_up)
                    if suppression_entries:
                        suppressed_ids = self._bulk_log_suppressed(cur, suppression_entries)
                        # Annotate entries with their DB IDs for return value
                        for i, entry in enumerate(suppression_entries):
                            entry["suppressed_id"] = suppressed_ids[i]

        # Build result
        result_ids: list[int] = [fid for fid in final_ids if fid is not None]
        if len(result_ids) != len(candidates):
            raise RuntimeError(f"Result length {len(result_ids)} != input length {len(candidates)}")

        logger.debug(
            f"Bulk processed {len(candidates)} review candidates: "
            f"{len(to_insert)} inserted, {len(to_update)} updated, "
            f"{len(batch_suppressed)} batch-deduplicated"
        )

        if log_suppressed:
            return result_ids, suppression_entries
        return result_ids

    def _execute_bulk_insert(self, cur, candidates: list[dict[str, Any]]) -> list[int]:
        """Execute bulk insert and return candidate_ids in order."""
        if not candidates:
            return []

        # Build arrays for UNNEST bulk insert
        filing_ids = []
        company_ids = []
        source_segment_ids = []
        char_positions = []
        context_texts = []
        raw_number_texts = []
        parsed_values = []
        parsed_units = []
        triggering_keywords = []
        keyword_distances = []
        keyword_positions = []
        suggested_metric_ids = []
        suggestion_confidences = []
        features_list = []
        review_batch_ids = []

        for candidate in candidates:
            filing_ids.append(candidate["filing_id"])
            company_ids.append(candidate["company_id"])
            source_segment_ids.append(candidate.get("source_segment_id"))
            char_positions.append(candidate["char_position"])
            context_texts.append(candidate["context_text"])
            raw_number_texts.append(candidate["raw_number_text"])
            parsed_values.append(candidate.get("parsed_value"))
            parsed_units.append(candidate.get("parsed_unit"))
            triggering_keywords.append(candidate["triggering_keyword"])
            keyword_distances.append(candidate["keyword_distance"])
            keyword_positions.append(candidate["keyword_position"])
            suggested_metric_ids.append(candidate.get("suggested_metric_id"))
            suggestion_confidences.append(candidate.get("suggestion_confidence"))
            features = candidate.get("features")
            features_list.append(json.dumps(features) if features else None)
            review_batch_ids.append(candidate.get("review_batch_id"))

        sql = """
            INSERT INTO review_candidates (
                filing_id, company_id, source_segment_id,
                char_position, context_text, raw_number_text,
                parsed_value, parsed_unit,
                triggering_keyword, keyword_distance, keyword_position,
                suggested_metric_id, suggestion_confidence, features,
                review_batch_id
            )
            SELECT
                filing_id, company_id, source_segment_id,
                char_position, context_text, raw_number_text,
                parsed_value, parsed_unit,
                triggering_keyword, keyword_distance, keyword_position,
                suggested_metric_id, suggestion_confidence, features,
                review_batch_id
            FROM UNNEST(
                %(filing_ids)s::bigint[],
                %(company_ids)s::bigint[],
                %(source_segment_ids)s::bigint[],
                %(char_positions)s::int[],
                %(context_texts)s::text[],
                %(raw_number_texts)s::text[],
                %(parsed_values)s::numeric[],
                %(parsed_units)s::text[],
                %(triggering_keywords)s::text[],
                %(keyword_distances)s::int[],
                %(keyword_positions)s::text[],
                %(suggested_metric_ids)s::text[],
                %(suggestion_confidences)s::numeric[],
                %(features_list)s::jsonb[],
                %(review_batch_ids)s::int[]
            ) WITH ORDINALITY AS t(
                filing_id, company_id, source_segment_id,
                char_position, context_text, raw_number_text,
                parsed_value, parsed_unit,
                triggering_keyword, keyword_distance, keyword_position,
                suggested_metric_id, suggestion_confidence, features,
                review_batch_id,
                ord
            )
            ORDER BY ord
            RETURNING candidate_id
        """

        cur.execute(
            sql,
            {
                "filing_ids": filing_ids,
                "company_ids": company_ids,
                "source_segment_ids": source_segment_ids,
                "char_positions": char_positions,
                "context_texts": context_texts,
                "raw_number_texts": raw_number_texts,
                "parsed_values": parsed_values,
                "parsed_units": parsed_units,
                "triggering_keywords": triggering_keywords,
                "keyword_distances": keyword_distances,
                "keyword_positions": keyword_positions,
                "suggested_metric_ids": suggested_metric_ids,
                "suggestion_confidences": suggestion_confidences,
                "features_list": features_list,
                "review_batch_ids": review_batch_ids,
            },
        )
        results = cur.fetchall()
        return [row["candidate_id"] for row in results]

    def _execute_update(self, cur, candidate_id: int, candidate: dict[str, Any]) -> None:
        """Update an existing candidate with new values."""
        features = candidate.get("features")
        features_json = json.dumps(features) if features else None

        sql = """
            UPDATE review_candidates SET
                context_text = %(context_text)s,
                raw_number_text = %(raw_number_text)s,
                parsed_value = %(parsed_value)s,
                parsed_unit = %(parsed_unit)s,
                triggering_keyword = %(triggering_keyword)s,
                keyword_distance = %(keyword_distance)s,
                keyword_position = %(keyword_position)s,
                suggested_metric_id = %(suggested_metric_id)s,
                suggestion_confidence = %(suggestion_confidence)s,
                features = %(features)s,
                review_batch_id = %(review_batch_id)s,
                updated_at = now()
            WHERE candidate_id = %(candidate_id)s
        """

        cur.execute(
            sql,
            {
                "candidate_id": candidate_id,
                "context_text": candidate["context_text"],
                "raw_number_text": candidate["raw_number_text"],
                "parsed_value": candidate.get("parsed_value"),
                "parsed_unit": candidate.get("parsed_unit"),
                "triggering_keyword": candidate["triggering_keyword"],
                "keyword_distance": candidate["keyword_distance"],
                "keyword_position": candidate["keyword_position"],
                "suggested_metric_id": candidate.get("suggested_metric_id"),
                "suggestion_confidence": candidate.get("suggestion_confidence"),
                "features": features_json,
                "review_batch_id": candidate.get("review_batch_id"),
            },
        )

    # =========================================================================
    # Review Decisions Methods
    # =========================================================================

    def insert_review_decision(
        self,
        candidate_id: int,
        decision: str,
        assigned_metric_id: str | None = None,
        rejection_reason: str | None = None,
        rejection_category: str | None = None,
        reviewer_id: str | None = None,
        reviewer_notes: str | None = None,
        review_time_seconds: int | None = None,
    ) -> int:
        """
        Record a human review decision.

        This method atomically inserts the decision AND updates the candidate's
        status to 'reviewed' in a single transaction. Both operations succeed
        together or fail together - there's no risk of partial state.

        Args:
            candidate_id: Candidate being reviewed
            decision: 'accept', 'reject', or 'reclassify'
            assigned_metric_id: Final metric ID (required for accept/reclassify)
            rejection_reason: Free-text explanation for rejection
            rejection_category: Categorized reason for pattern learning
            reviewer_id: Identifier for who made this decision (username, email)
            reviewer_notes: Optional notes
            review_time_seconds: Time spent on this decision

        Returns:
            decision_id of the inserted record

        Raises:
            ValidationError: If decision is not 'accept', 'reject', or 'reclassify'
            ValidationError: If rejection_category is not a valid category
            ValidationError: If accept/reclassify without assigned_metric_id
            ValidationError: If rejection_category provided for non-reject decision
        """
        # Validate decision type
        validate_enum(decision, DECISION_TYPES, "decision")

        # Validate rejection_category if provided
        if rejection_category is not None:
            validate_enum(rejection_category, REJECTION_CATEGORIES, "rejection_category")

        # Business rule: accept/reclassify require assigned_metric_id
        if decision in ("accept", "reclassify") and not assigned_metric_id:
            raise ValidationError(f"Decision '{decision}' requires assigned_metric_id")

        # Business rule: rejection_category only valid for reject
        if decision != "reject" and rejection_category:
            raise ValidationError(
                f"rejection_category should only be set when decision='reject', "
                f"got decision='{decision}'"
            )

        insert_sql = """
            INSERT INTO review_decisions (
                candidate_id, decision, assigned_metric_id,
                rejection_reason, rejection_category,
                reviewer_id, reviewer_notes, review_time_seconds
            )
            VALUES (
                %(candidate_id)s, %(decision)s, %(assigned_metric_id)s,
                %(rejection_reason)s, %(rejection_category)s,
                %(reviewer_id)s, %(reviewer_notes)s, %(review_time_seconds)s
            )
            RETURNING decision_id
        """

        update_status_sql = """
            UPDATE review_candidates
            SET review_status = 'reviewed', updated_at = now()
            WHERE candidate_id = %(candidate_id)s
        """

        # Both operations in same transaction for atomicity
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Insert the decision
                cur.execute(
                    insert_sql,
                    {
                        "candidate_id": candidate_id,
                        "decision": decision,
                        "assigned_metric_id": assigned_metric_id,
                        "rejection_reason": rejection_reason,
                        "rejection_category": rejection_category,
                        "reviewer_id": reviewer_id,
                        "reviewer_notes": reviewer_notes,
                        "review_time_seconds": review_time_seconds,
                    },
                )
                result = cur.fetchone()
                decision_id = result["decision_id"]

                # Update candidate status - SAME TRANSACTION
                cur.execute(update_status_sql, {"candidate_id": candidate_id})

        logger.debug(
            f"Inserted review decision: decision_id={decision_id}, "
            f"candidate_id={candidate_id}, decision={decision}"
        )
        return decision_id

    def insert_bulk_review_decisions(
        self,
        candidate_ids: list[int],
        decision: str,
        assigned_metric_id: str | None = None,
        rejection_category: str | None = None,
        rejection_reason: str | None = None,
        reviewer_id: str | None = None,
        reviewer_notes: str | None = None,
    ) -> tuple[list[int], list[dict[str, Any]]]:
        """
        Insert multiple review decisions in a single transaction.

        All candidates must be pending. Uses a single transaction to ensure
        atomicity - either all decisions are created or none. Each candidate's
        status is updated to 'reviewed' atomically with its decision insert.

        Only 'accept' and 'reject' decisions are supported for bulk operations.
        Reclassify requires individual review since each may need different metric_ids.

        Args:
            candidate_ids: List of candidate IDs to process (1-20 candidates)
            decision: "accept" or "reject" (NOT "reclassify")
            assigned_metric_id: Metric ID for all accept decisions
            rejection_category: Category for all reject decisions
            rejection_reason: Reason text for all reject decisions
            reviewer_id: Identifier for who made these decisions
            reviewer_notes: Optional notes applied to all decisions

        Returns:
            Tuple of (decision_ids, failed_candidates):
            - decision_ids: List of successfully created decision_ids
            - failed_candidates: List of {"candidate_id": int, "error": str} for failures

        Raises:
            ValidationError: If decision is not 'accept' or 'reject'
            ValidationError: If accept without assigned_metric_id
            ValidationError: If reject without rejection_category

        Note:
            Skips candidates that already have decisions (returns in failed list).
            All other database errors cause full transaction rollback.
        """
        # Validate decision type - only accept/reject allowed for bulk
        if decision not in ("accept", "reject"):
            raise ValidationError(
                f"Bulk operations only support 'accept' or 'reject', got '{decision}'"
            )

        # Business rule: accept requires assigned_metric_id
        if decision == "accept" and not assigned_metric_id:
            raise ValidationError("Bulk accept requires assigned_metric_id")

        # Business rule: reject requires rejection_category
        if decision == "reject" and not rejection_category:
            raise ValidationError("Bulk reject requires rejection_category")

        # Validate rejection_category if provided
        if rejection_category is not None:
            validate_enum(rejection_category, REJECTION_CATEGORIES, "rejection_category")

        decision_ids = []
        failed_candidates = []

        # Fetch candidates to verify they exist and are pending
        fetch_sql = """
            SELECT candidate_id, review_status
            FROM review_candidates
            WHERE candidate_id = ANY(%(candidate_ids)s)
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Fetch candidate statuses
                cur.execute(fetch_sql, {"candidate_ids": candidate_ids})
                candidates_data = {row["candidate_id"]: row for row in cur.fetchall()}

                # Filter candidates: collect valid IDs and failures
                valid_ids = []
                for candidate_id in candidate_ids:
                    if candidate_id not in candidates_data:
                        failed_candidates.append(
                            {
                                "candidate_id": candidate_id,
                                "error": "Candidate not found",
                            }
                        )
                    elif candidates_data[candidate_id]["review_status"] != "pending":
                        failed_candidates.append(
                            {
                                "candidate_id": candidate_id,
                                "error": f"Already reviewed (status: {candidates_data[candidate_id]['review_status']})",
                            }
                        )
                    else:
                        valid_ids.append(candidate_id)

                if valid_ids:
                    # Batch insert all decisions (executemany pipelines internally)
                    insert_sql = """
                        INSERT INTO review_decisions (
                            candidate_id, decision, assigned_metric_id,
                            rejection_reason, rejection_category,
                            reviewer_id, reviewer_notes
                        )
                        VALUES (
                            %(candidate_id)s, %(decision)s, %(assigned_metric_id)s,
                            %(rejection_reason)s, %(rejection_category)s,
                            %(reviewer_id)s, %(reviewer_notes)s
                        )
                    """
                    insert_params = [
                        {
                            "candidate_id": cid,
                            "decision": decision,
                            "assigned_metric_id": assigned_metric_id,
                            "rejection_reason": rejection_reason,
                            "rejection_category": rejection_category,
                            "reviewer_id": reviewer_id,
                            "reviewer_notes": reviewer_notes,
                        }
                        for cid in valid_ids
                    ]
                    cur.executemany(insert_sql, insert_params)

                    # Fetch generated decision_ids
                    cur.execute(
                        """SELECT decision_id FROM review_decisions
                           WHERE candidate_id = ANY(%(ids)s)
                           ORDER BY candidate_id""",
                        {"ids": valid_ids},
                    )
                    decision_ids = [row["decision_id"] for row in cur.fetchall()]

                    # Bulk update candidate statuses
                    cur.execute(
                        """UPDATE review_candidates
                           SET review_status = 'reviewed', updated_at = now()
                           WHERE candidate_id = ANY(%(ids)s)""",
                        {"ids": valid_ids},
                    )

        logger.info(
            f"Bulk {decision}: processed {len(decision_ids)} of {len(candidate_ids)} candidates, "
            f"{len(failed_candidates)} failed/skipped"
        )

        return decision_ids, failed_candidates

    def get_decision_for_candidate(self, candidate_id: int) -> dict | None:
        """
        Get the latest decision for a candidate.

        Args:
            candidate_id: Candidate to get decision for

        Returns:
            Decision record as dict, or None if not reviewed
        """
        sql = """
            SELECT * FROM review_decisions
            WHERE candidate_id = %(candidate_id)s
            ORDER BY created_at DESC
            LIMIT 1
        """
        results = self.query(sql, {"candidate_id": candidate_id})
        return results[0] if results else None

    def get_decision_by_id(self, decision_id: int) -> dict | None:
        """
        Get a decision by its ID.

        Args:
            decision_id: Primary key of the decision

        Returns:
            Decision record with candidate_id and filing_id, or None if not found
        """
        sql = """
            SELECT rd.*, rc.filing_id
            FROM review_decisions rd
            JOIN review_candidates rc ON rd.candidate_id = rc.candidate_id
            WHERE rd.decision_id = %(decision_id)s
        """
        results = self.query(sql, {"decision_id": decision_id})
        return results[0] if results else None

    def delete_review_decision(self, decision_id: int) -> bool:
        """
        Delete a review decision and reset candidate status to 'pending'.

        Performs in single transaction:
        1. Get candidate_id from decision
        2. Delete from review_decisions
        3. Update review_candidates.review_status = 'pending'

        Args:
            decision_id: Primary key of the decision to delete

        Returns:
            True if deleted successfully, False if decision not found
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Get candidate_id before deleting
                cur.execute(
                    "SELECT candidate_id FROM review_decisions WHERE decision_id = %s",
                    (decision_id,),
                )
                result = cur.fetchone()

                if not result:
                    logger.debug(f"Decision {decision_id} not found")
                    return False

                candidate_id = result["candidate_id"]

                # Delete decision
                cur.execute("DELETE FROM review_decisions WHERE decision_id = %s", (decision_id,))

                # Reset candidate status to pending
                cur.execute(
                    "UPDATE review_candidates SET review_status = 'pending', updated_at = now() WHERE candidate_id = %s",
                    (candidate_id,),
                )

        logger.info(f"Deleted decision {decision_id}, reset candidate {candidate_id} to pending")
        return True

    def get_decisions_for_filing(self, filing_id: int) -> list[dict]:
        """
        Get all review decisions for a filing.

        Args:
            filing_id: Filing to get decisions for

        Returns:
            List of decision records with candidate info
        """
        sql = """
            SELECT rd.*, rc.context_text, rc.raw_number_text,
                   rc.triggering_keyword, rc.suggested_metric_id
            FROM review_decisions rd
            JOIN review_candidates rc ON rd.candidate_id = rc.candidate_id
            WHERE rc.filing_id = %(filing_id)s
            ORDER BY rd.created_at
        """
        return self.query(sql, {"filing_id": filing_id})

    def get_decision_statistics(self, filing_id: int | None = None) -> dict[str, Any]:
        """
        Get statistics on review decisions.

        Args:
            filing_id: Optional filter by filing

        Returns:
            Dict with decision counts and percentages
        """
        where_clause = ""
        params: dict[str, Any] = {}

        if filing_id:
            where_clause = """
                WHERE rd.candidate_id IN (
                    SELECT candidate_id FROM review_candidates
                    WHERE filing_id = %(filing_id)s
                )
            """
            params["filing_id"] = filing_id

        sql = f"""
            SELECT
                COUNT(*) as total_decisions,
                COUNT(*) FILTER (WHERE decision = 'accept') as accept_count,
                COUNT(*) FILTER (WHERE decision = 'reject') as reject_count,
                COUNT(*) FILTER (WHERE decision = 'reclassify') as reclassify_count,
                AVG(review_time_seconds) as avg_review_time_seconds
            FROM review_decisions rd
            {where_clause}
        """

        results = self.query(sql, params)
        if not results:
            return {
                "total_decisions": 0,
                "accept_count": 0,
                "reject_count": 0,
                "reclassify_count": 0,
                "avg_review_time_seconds": None,
            }

        row = results[0]
        total = row["total_decisions"] or 0

        return {
            "total_decisions": total,
            "accept_count": row["accept_count"] or 0,
            "reject_count": row["reject_count"] or 0,
            "reclassify_count": row["reclassify_count"] or 0,
            "accept_pct": (row["accept_count"] or 0) / total * 100 if total > 0 else 0,
            "reject_pct": (row["reject_count"] or 0) / total * 100 if total > 0 else 0,
            "avg_review_time_seconds": row["avg_review_time_seconds"],
        }

    def get_decisions_by_reviewer(
        self,
        reviewer_id: str,
        decision: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        include_total: bool = False,
    ) -> list[dict] | dict[str, Any]:
        """
        Get all review decisions made by a specific reviewer.

        Args:
            reviewer_id: Identifier of the reviewer (username, email, etc.)
            decision: Optional filter by decision type ('accept', 'reject', 'reclassify')
            limit: Maximum number of results to return (must be > 0 if provided)
            offset: Number of results to skip for pagination (must be >= 0)
            include_total: If True, returns dict with 'results' and 'total' keys

        Returns:
            If include_total=False: List of decision records with candidate context
            info, ordered by created_at descending (most recent first)

            If include_total=True: Dict with:
                - results: List of decision records
                - total: Total count matching filters (ignoring limit/offset)

        Raises:
            ValidationError: If decision filter is not a valid decision type
            ValidationError: If limit is provided and <= 0
            ValidationError: If offset < 0
        """
        # Validate decision type if provided
        if decision is not None:
            validate_enum(decision, DECISION_TYPES, "decision")

        # Validate pagination parameters
        if limit is not None and limit <= 0:
            raise ValidationError(f"limit must be > 0, got {limit}")
        if offset < 0:
            raise ValidationError(f"offset must be >= 0, got {offset}")

        conditions = ["rd.reviewer_id = %(reviewer_id)s"]
        params: dict[str, Any] = {"reviewer_id": reviewer_id}

        if decision:
            conditions.append("rd.decision = %(decision)s")
            params["decision"] = decision

        where_clause = " AND ".join(conditions)

        # Build pagination clause using parameterized queries
        pagination = ""
        if limit is not None:
            pagination = " LIMIT %(limit)s OFFSET %(offset)s"
            params["limit"] = limit
            params["offset"] = offset

        sql = f"""
            SELECT rd.*,
                   rc.filing_id,
                   rc.company_id,
                   rc.context_text,
                   rc.raw_number_text,
                   rc.triggering_keyword,
                   rc.suggested_metric_id,
                   rc.char_position,
                   f.accession_number,
                   c.company_name
            FROM review_decisions rd
            JOIN review_candidates rc ON rd.candidate_id = rc.candidate_id
            JOIN filings f ON rc.filing_id = f.filing_id
            JOIN companies c ON rc.company_id = c.company_id
            WHERE {where_clause}
            ORDER BY rd.created_at DESC
            {pagination}
        """

        results = self.query(sql, params)

        if not include_total:
            return results

        # Get total count for pagination metadata
        count_sql = f"""
            SELECT COUNT(*) as total
            FROM review_decisions rd
            WHERE {where_clause}
        """
        # Remove pagination params for count query
        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        count_result = self.query(count_sql, count_params)
        total = count_result[0]["total"] if count_result else 0

        return {"results": results, "total": total}

    # =========================================================================
    # Analysis View Methods
    # =========================================================================

    def get_decision_stats_by_metric(self, metric_id: str | None = None) -> list[dict]:
        """
        Get decision statistics grouped by suggested metric.

        Queries the v_decision_stats_by_metric view to show acceptance rates
        per metric type. Useful for the pattern analyzer to identify which
        metrics have high/low acceptance rates.

        Args:
            metric_id: Optional filter by specific metric ID

        Returns:
            List of dicts with columns:
            - suggested_metric: The metric ID (or 'unknown')
            - decision: 'accept', 'reject', or 'reclassify'
            - decision_count: Number of decisions of this type
            - pct_of_metric: Percentage of this decision within the metric
        """
        sql = "SELECT * FROM v_decision_stats_by_metric"
        params: dict[str, Any] = {}

        if metric_id:
            sql += " WHERE suggested_metric = %(metric_id)s"
            params["metric_id"] = metric_id

        sql += " ORDER BY suggested_metric, decision"

        return self.query(sql, params)

    def get_rejection_reasons(self, metric_id: str | None = None) -> list[dict]:
        """
        Get rejection reason statistics grouped by metric.

        Queries the v_rejection_reasons view to show patterns in why
        candidates are rejected. Useful for the pattern analyzer to
        identify systematic false positive patterns.

        Args:
            metric_id: Optional filter by specific metric ID

        Returns:
            List of dicts with columns:
            - suggested_metric: The metric ID (or 'unknown')
            - rejection_category: Category of rejection reason
            - rejection_count: Number of rejections with this reason
            - avg_keyword_distance: Average distance from number to keyword
            - common_keyword_position: Most common keyword position ('before'/'after')
        """
        sql = "SELECT * FROM v_rejection_reasons"
        params: dict[str, Any] = {}

        if metric_id:
            sql += " WHERE suggested_metric = %(metric_id)s"
            params["metric_id"] = metric_id

        sql += " ORDER BY suggested_metric, rejection_count DESC"

        return self.query(sql, params)

    def get_daily_decision_counts(self, days: int = 7) -> list[dict]:
        """
        Get decision counts by day for the last N days.

        Returns a time series of decision counts suitable for chart visualization.
        Includes days with zero decisions to ensure continuous timeline.

        Args:
            days: Number of days to include (default: 7)

        Returns:
            List of dicts with:
            - date: Date (datetime.date object)
            - count: Number of decisions made on that date

            Results are ordered by date ascending (oldest first).

        Example:
            >>> db.get_daily_decision_counts(days=7)
            [
                {"date": date(2025, 12, 10), "count": 5},
                {"date": date(2025, 12, 11), "count": 0},
                {"date": date(2025, 12, 12), "count": 12},
                ...
            ]
        """
        sql = """
            WITH date_series AS (
                -- Generate series of dates for last N days
                SELECT generate_series(
                    CURRENT_DATE - %(days)s + 1,
                    CURRENT_DATE,
                    '1 day'::interval
                )::date AS date
            ),
            daily_counts AS (
                -- Count decisions per day
                -- Use DATE() to convert timestamps to dates for grouping
                SELECT
                    DATE(created_at) AS date,
                    COUNT(*) AS count
                FROM review_decisions
                WHERE DATE(created_at) >= CURRENT_DATE - %(days)s + 1
                GROUP BY DATE(created_at)
            )
            -- Left join to include days with zero decisions
            SELECT
                ds.date,
                COALESCE(dc.count, 0) AS count
            FROM date_series ds
            LEFT JOIN daily_counts dc ON ds.date = dc.date
            ORDER BY ds.date ASC
        """

        return self.query(sql, {"days": days})

    # =========================================================================
    # Learned Patterns Methods
    # =========================================================================

    def insert_learned_pattern(
        self,
        pattern_type: str,
        pattern_name: str,
        pattern_definition: dict[str, Any],
        metric_id: str | None = None,
        pattern_description: str | None = None,
        precision_score: float | None = None,
        recall_score: float | None = None,
        f1_score: float | None = None,
        sample_count: int | None = None,
    ) -> int:
        """
        Insert a new learned pattern.

        Args:
            pattern_type: 'accept_rule', 'reject_rule', or 'feature_weight'
            pattern_name: Human-readable name
            pattern_definition: Rule definition as dict (stored as JSONB)
            metric_id: Optional metric-specific pattern
            pattern_description: Longer description
            precision_score: Precision on training data (0-1)
            recall_score: Recall on training data (0-1)
            f1_score: F1 score (0-1)
            sample_count: Number of samples pattern was evaluated on

        Returns:
            pattern_id of the inserted record

        Raises:
            ValidationError: If pattern_type is not valid
            ValidationError: If any score is not between 0 and 1
        """
        # Validate pattern_type
        validate_enum(pattern_type, PATTERN_TYPES, "pattern_type")

        # Validate score ranges
        validate_score(precision_score, "precision_score")
        validate_score(recall_score, "recall_score")
        validate_score(f1_score, "f1_score")

        sql = """
            INSERT INTO learned_patterns (
                pattern_type, metric_id, pattern_name, pattern_description,
                pattern_definition, precision_score, recall_score, f1_score,
                sample_count
            )
            VALUES (
                %(pattern_type)s, %(metric_id)s, %(pattern_name)s, %(pattern_description)s,
                %(pattern_definition)s, %(precision_score)s, %(recall_score)s, %(f1_score)s,
                %(sample_count)s
            )
            RETURNING pattern_id
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "pattern_type": pattern_type,
                        "metric_id": metric_id,
                        "pattern_name": pattern_name,
                        "pattern_description": pattern_description,
                        "pattern_definition": json.dumps(pattern_definition),
                        "precision_score": precision_score,
                        "recall_score": recall_score,
                        "f1_score": f1_score,
                        "sample_count": sample_count,
                    },
                )
                result = cur.fetchone()
                pattern_id = result["pattern_id"]

        logger.debug(f"Inserted learned pattern: pattern_id={pattern_id}")
        return pattern_id

    def get_learned_pattern(self, pattern_id: int) -> dict | None:
        """
        Get a learned pattern by ID.

        Args:
            pattern_id: Primary key

        Returns:
            Pattern record as dict, or None if not found
        """
        sql = "SELECT * FROM learned_patterns WHERE pattern_id = %(pattern_id)s"
        results = self.query(sql, {"pattern_id": pattern_id})
        return results[0] if results else None

    def get_learned_patterns(
        self,
        status: str = "approved",
        pattern_type: str | None = None,
        metric_id: str | None = None,
    ) -> list[dict]:
        """
        Get learned patterns with flexible filtering.

        This is the general-purpose method for loading patterns. Use this
        for E2 RuleApplicator to load approved patterns.

        Args:
            status: Pattern status filter (default: 'approved')
            pattern_type: Optional filter by pattern type
            metric_id: Optional filter by metric (includes global patterns if None)

        Returns:
            List of pattern records ordered by precision score (highest first)

        Raises:
            ValidationError: If status is not a valid pattern status
            ValidationError: If pattern_type is provided but not a valid type

        Example:
            >>> # Get all approved patterns for E2
            >>> patterns = db.get_learned_patterns(status='approved')
            >>> # Get approved reject patterns for a specific metric
            >>> patterns = db.get_learned_patterns(
            ...     status='approved',
            ...     pattern_type='reject_rule',
            ...     metric_id='annual_recurring_revenue'
            ... )
        """
        # Validate status
        validate_enum(status, PATTERN_STATUSES, "pattern_status")

        # Validate pattern_type if provided
        if pattern_type is not None:
            validate_enum(pattern_type, PATTERN_TYPES, "pattern_type")

        sql = """
            SELECT * FROM learned_patterns
            WHERE status = %(status)s
        """
        params: dict[str, Any] = {"status": status}

        if pattern_type:
            sql += " AND pattern_type = %(pattern_type)s"
            params["pattern_type"] = pattern_type

        if metric_id:
            sql += " AND (metric_id = %(metric_id)s OR metric_id IS NULL)"
            params["metric_id"] = metric_id

        sql += " ORDER BY precision_score DESC NULLS LAST, pattern_id"

        return self.query(sql, params)

    def get_approved_patterns(
        self,
        pattern_type: str | None = None,
        metric_id: str | None = None,
    ) -> list[dict]:
        """
        Get approved patterns for use in extraction.

        Args:
            pattern_type: Optional filter by pattern type
            metric_id: Optional filter by metric

        Returns:
            List of approved pattern records

        Raises:
            ValidationError: If pattern_type is provided but not a valid type
        """
        # Validate pattern_type if provided
        if pattern_type is not None:
            validate_enum(pattern_type, PATTERN_TYPES, "pattern_type")

        sql = """
            SELECT * FROM learned_patterns
            WHERE status = 'approved'
        """
        params: dict[str, Any] = {}

        if pattern_type:
            sql += " AND pattern_type = %(pattern_type)s"
            params["pattern_type"] = pattern_type

        if metric_id:
            sql += " AND (metric_id = %(metric_id)s OR metric_id IS NULL)"
            params["metric_id"] = metric_id

        sql += " ORDER BY precision_score DESC NULLS LAST"

        return self.query(sql, params)

    def get_candidate_patterns(
        self,
        pattern_type: str | None = None,
        metric_id: str | None = None,
        min_precision: float | None = None,
        min_sample_count: int | None = None,
    ) -> list[dict]:
        """
        Get patterns pending approval (status='candidate').

        Use this for the pattern management workflow to review and approve
        newly discovered patterns before they're used in extraction.

        Args:
            pattern_type: Optional filter by pattern type
            metric_id: Optional filter by metric (includes global patterns)
            min_precision: Optional minimum precision score filter
            min_sample_count: Optional minimum sample count filter

        Returns:
            List of candidate pattern records, ordered by precision score

        Raises:
            ValidationError: If pattern_type is provided but not a valid type
            ValidationError: If min_precision is not between 0 and 1
        """
        # Validate pattern_type if provided
        if pattern_type is not None:
            validate_enum(pattern_type, PATTERN_TYPES, "pattern_type")

        # Validate min_precision if provided
        validate_score(min_precision, "min_precision")

        sql = """
            SELECT * FROM learned_patterns
            WHERE status = 'candidate'
        """
        params: dict[str, Any] = {}

        if pattern_type:
            sql += " AND pattern_type = %(pattern_type)s"
            params["pattern_type"] = pattern_type

        if metric_id:
            sql += " AND (metric_id = %(metric_id)s OR metric_id IS NULL)"
            params["metric_id"] = metric_id

        if min_precision is not None:
            sql += " AND precision_score >= %(min_precision)s"
            params["min_precision"] = min_precision

        if min_sample_count is not None:
            sql += " AND sample_count >= %(min_sample_count)s"
            params["min_sample_count"] = min_sample_count

        sql += " ORDER BY precision_score DESC NULLS LAST, created_at DESC"

        return self.query(sql, params)

    def update_pattern_status(
        self,
        pattern_id: int,
        status: str,
        approved_by: str | None = None,
    ) -> bool:
        """
        Update a pattern's status.

        Args:
            pattern_id: Pattern to update
            status: New status ('candidate', 'approved', 'rejected', 'deprecated')
            approved_by: Who approved (if status='approved')

        Returns:
            True if a row was updated, False if no pattern found with given ID

        Raises:
            ValidationError: If status is not a valid pattern status
        """
        # Validate status
        validate_enum(status, PATTERN_STATUSES, "pattern_status")

        sql = """
            UPDATE learned_patterns
            SET status = %(status)s,
                approved_at = CASE WHEN %(status)s = 'approved' THEN now() ELSE approved_at END,
                approved_by = COALESCE(%(approved_by)s, approved_by),
                updated_at = now()
            WHERE pattern_id = %(pattern_id)s
            RETURNING pattern_id
        """
        result = self.execute(
            sql,
            {"pattern_id": pattern_id, "status": status, "approved_by": approved_by},
            fetch=True,
        )
        updated = bool(result)
        if updated:
            logger.debug(f"Updated pattern {pattern_id} status to {status}")
        else:
            logger.warning(f"No pattern found with id {pattern_id}")
        return updated

    # =========================================================================
    # Filing and Segment Retrieval Methods (for Candidate Generation)
    # =========================================================================

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
                c.company_name, c.cik, c.industry_code
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE f.filing_id = %(filing_id)s
        """
        results = self.query(sql, {"filing_id": filing_id})
        return results[0] if results else None

    def get_source_segments_for_filing(
        self,
        filing_id: int,
        segment_types: list[str] | None = None,
        with_numeric_disclosure: bool | None = None,
    ) -> list[dict]:
        """
        Get all source segments for a filing.

        Args:
            filing_id: The filing ID to retrieve segments for
            segment_types: Optional filter by segment types (e.g., ['paragraph', 'table'])
            with_numeric_disclosure: Optional filter by contains_numeric_disclosure_flag

        Returns:
            List of source segment dicts ordered by sequence_index
        """
        sql = """
            SELECT
                source_segment_id, filing_id, segment_type,
                section_path, section_heading, sequence_index,
                html_selector, char_start_offset, char_end_offset, page_number,
                raw_text, raw_html,
                candidate_metric_ids, contains_definition_flag,
                contains_methodology_flag, contains_numeric_disclosure_flag,
                classifier_confidence,
                created_at, updated_at
            FROM source_segments
            WHERE filing_id = %(filing_id)s
        """
        params: dict[str, Any] = {"filing_id": filing_id}

        if segment_types:
            sql += " AND segment_type = ANY(%(segment_types)s)"
            params["segment_types"] = segment_types

        if with_numeric_disclosure is not None:
            sql += " AND contains_numeric_disclosure_flag = %(with_numeric_disclosure)s"
            params["with_numeric_disclosure"] = with_numeric_disclosure

        sql += " ORDER BY sequence_index"

        return self.query(sql, params)

    def get_filings_for_candidate_generation(
        self,
        limit: int = 100,
        exclude_with_candidates: bool = True,
    ) -> list[dict]:
        """
        Get filings eligible for candidate generation.

        Args:
            limit: Maximum number of filings to return
            exclude_with_candidates: If True, exclude filings that already have candidates

        Returns:
            List of filings with company info
        """
        sql = """
            SELECT
                f.filing_id, f.accession_number, f.form_type, f.filing_date,
                f.company_id,
                c.company_name, c.cik
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE f.is_in_scope_phase1 = true
        """
        params: dict[str, Any] = {"limit": limit}

        if exclude_with_candidates:
            sql += """
                AND NOT EXISTS (
                    SELECT 1 FROM review_candidates rc
                    WHERE rc.filing_id = f.filing_id
                )
            """

        sql += """
            ORDER BY f.filing_date DESC
            LIMIT %(limit)s
        """

        return self.query(sql, params)

    # =========================================================================
    # Helper Methods for Flask Routes
    # =========================================================================

    def get_filings_with_candidates(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get filings that have review candidates.

        Useful for the filing list page in the review interface.

        Args:
            status: Optional filter by candidate review_status
            limit: Maximum number of filings to return
            offset: Number of filings to skip (for pagination)

        Returns:
            List of filings with candidate counts

        Raises:
            ValidationError: If status is provided but not a valid review status
        """
        # Validate status if provided
        if status is not None:
            validate_enum(status, REVIEW_STATUSES, "review_status")

        status_filter = ""
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if status:
            status_filter = "AND rc.review_status = %(status)s"
            params["status"] = status

        sql = f"""
            SELECT
                f.filing_id, f.accession_number, f.form_type, f.filing_date,
                c.company_name, c.cik,
                COUNT(rc.candidate_id) as total_candidates,
                COUNT(rc.candidate_id) FILTER (WHERE rc.review_status = 'pending') as pending_count,
                COUNT(rc.candidate_id) FILTER (WHERE rc.review_status = 'reviewed') as reviewed_count,
                COUNT(rc.candidate_id) FILTER (WHERE rc.review_status = 'skipped') as skipped_count,
                MIN(rc.created_at) as extraction_date
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            JOIN review_candidates rc ON f.filing_id = rc.filing_id
            WHERE 1=1 {status_filter}
            GROUP BY f.filing_id, f.accession_number, f.form_type, f.filing_date,
                     c.company_name, c.cik
            ORDER BY pending_count DESC, f.filing_date DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """

        return self.query(sql, params)

    def get_filings_with_candidates_count(
        self,
        status: str | None = None,
    ) -> int:
        """
        Get count of filings that have review candidates.

        Args:
            status: Optional filter by candidate review_status

        Returns:
            Total count of filings matching filter

        Raises:
            ValidationError: If status is provided but not a valid review status
        """
        if status is not None:
            validate_enum(status, REVIEW_STATUSES, "review_status")

        status_filter = ""
        params: dict[str, Any] = {}

        if status:
            status_filter = "AND rc.review_status = %(status)s"
            params["status"] = status

        sql = f"""
            SELECT COUNT(DISTINCT f.filing_id) as count
            FROM filings f
            JOIN review_candidates rc ON f.filing_id = rc.filing_id
            WHERE 1=1 {status_filter}
        """

        result = self.query(sql, params)
        return result[0]["count"] if result else 0

    def get_review_progress(self) -> dict[str, Any]:
        """
        Get overall review progress statistics.

        Returns:
            Dict with overall progress metrics
        """
        sql = """
            SELECT
                COUNT(*) as total_candidates,
                COUNT(*) FILTER (WHERE review_status = 'pending') as pending_count,
                COUNT(*) FILTER (WHERE review_status = 'reviewed') as reviewed_count,
                COUNT(*) FILTER (WHERE review_status = 'skipped') as skipped_count,
                COUNT(DISTINCT filing_id) as total_filings,
                COUNT(DISTINCT filing_id) FILTER (WHERE review_status = 'pending') as filings_with_pending
            FROM review_candidates
        """

        results = self.query(sql)
        if not results:
            return {
                "total_candidates": 0,
                "pending_count": 0,
                "reviewed_count": 0,
                "skipped_count": 0,
                "review_pct": 0,
                "total_filings": 0,
                "filings_with_pending": 0,
            }

        row = results[0]
        total = row["total_candidates"] or 0
        reviewed = row["reviewed_count"] or 0

        return {
            "total_candidates": total,
            "pending_count": row["pending_count"] or 0,
            "reviewed_count": reviewed,
            "skipped_count": row["skipped_count"] or 0,
            "review_pct": reviewed / total * 100 if total > 0 else 0,
            "total_filings": row["total_filings"] or 0,
            "filings_with_pending": row["filings_with_pending"] or 0,
        }

    def get_next_candidate_for_review(self, filing_id: int | None = None) -> dict | None:
        """
        Get the next candidate needing review.

        Args:
            filing_id: Optional filter by filing

        Returns:
            Next pending candidate with filing info, or None if all reviewed
        """
        sql = """
            SELECT rc.*, f.accession_number, c.company_name
            FROM review_candidates rc
            JOIN filings f ON rc.filing_id = f.filing_id
            JOIN companies c ON rc.company_id = c.company_id
            WHERE rc.review_status = 'pending'
        """
        params: dict[str, Any] = {}

        if filing_id:
            sql += " AND rc.filing_id = %(filing_id)s"
            params["filing_id"] = filing_id

        sql += " ORDER BY rc.filing_id, rc.char_position LIMIT 1"

        results = self.query(sql, params)
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
        candidate_id: int | None,
        query_params: dict[str, Any] | None,
        response_status: int,
        response_time_ms: int | None,
    ) -> int:
        """
        Insert an audit log entry for a review route request.

        Args:
            session_id: Flask session ID
            ip_address: Client IP address
            user_agent: Browser/client user agent string
            route_name: Flask route name (e.g., 'review.filing_list')
            http_method: HTTP method (GET, POST, etc.)
            url_path: Full URL path
            filing_id: Filing ID if applicable
            candidate_id: Candidate ID if applicable
            query_params: All query parameters as dict
            response_status: HTTP status code
            response_time_ms: Response time in milliseconds

        Returns:
            The log_id of the inserted record

        Raises:
            psycopg.Error: If database insert fails
        """
        import json

        sql = """
            INSERT INTO review_audit_log (
                session_id, ip_address, user_agent,
                route_name, http_method, url_path,
                filing_id, candidate_id, query_params,
                response_status, response_time_ms
            ) VALUES (
                %(session_id)s, %(ip_address)s, %(user_agent)s,
                %(route_name)s, %(http_method)s, %(url_path)s,
                %(filing_id)s, %(candidate_id)s, %(query_params)s,
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
            "candidate_id": candidate_id,
            "query_params": json.dumps(query_params) if query_params else None,
            "response_status": response_status,
            "response_time_ms": response_time_ms,
        }

        result = self.query(sql, params)
        return result[0]["log_id"] if result else 0

    # =========================================================================
    # Image Review Methods
    # =========================================================================

    def get_filings_with_image_candidates(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get filings that have image review candidates.

        Args:
            status: Filter by candidate review_status ('pending', 'reviewed', 'skipped')
                   or None for all statuses
            limit: Maximum number of filings to return
            offset: Number of filings to skip (for pagination)

        Returns:
            List of filings with image candidate counts, ordered by pending_count DESC

        Raises:
            ValidationError: If status is provided but not valid
        """
        if status is not None:
            validate_enum(status, IMAGE_REVIEW_STATUSES, "review_status")

        status_filter = ""
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if status:
            status_filter = "AND irc.review_status = %(status)s"
            params["status"] = status

        sql = f"""
            SELECT
                f.filing_id, f.accession_number, f.form_type, f.filing_date,
                c.company_name, c.cik,
                COUNT(irc.image_candidate_id) as total_candidates,
                COUNT(irc.image_candidate_id) FILTER (WHERE irc.review_status = 'pending') as pending_count,
                COUNT(irc.image_candidate_id) FILTER (WHERE irc.review_status = 'reviewed') as reviewed_count,
                COUNT(irc.image_candidate_id) FILTER (WHERE irc.review_status = 'skipped') as skipped_count,
                MIN(irc.created_at) as first_candidate_date
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            JOIN image_review_candidates irc ON f.filing_id = irc.filing_id
            WHERE 1=1 {status_filter}
            GROUP BY f.filing_id, f.accession_number, f.form_type, f.filing_date,
                     c.company_name, c.cik
            ORDER BY pending_count DESC, f.filing_date DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """

        return self.query(sql, params)

    def get_filings_with_image_candidates_count(
        self,
        status: str | None = None,
    ) -> int:
        """
        Get count of filings that have image review candidates.

        Args:
            status: Filter by candidate review_status, or None for all

        Returns:
            Total count of filings matching filter

        Raises:
            ValidationError: If status is provided but not valid
        """
        if status is not None:
            validate_enum(status, IMAGE_REVIEW_STATUSES, "review_status")

        status_filter = ""
        params: dict[str, Any] = {}

        if status:
            status_filter = "AND irc.review_status = %(status)s"
            params["status"] = status

        sql = f"""
            SELECT COUNT(DISTINCT f.filing_id) as count
            FROM filings f
            JOIN image_review_candidates irc ON f.filing_id = irc.filing_id
            WHERE 1=1 {status_filter}
        """

        result = self.query(sql, params)
        return result[0]["count"] if result else 0

    def get_image_review_candidates_for_filing(
        self,
        filing_id: int,
        status: str | None = None,
        sort_by: str = "tier",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get image review candidates for a specific filing.

        Args:
            filing_id: Filing to get candidates for
            status: Filter by review_status, or None for all
            sort_by: Sort order - 'tier' (detection tier priority), 'confidence',
                    or 'position' (image_index)
            limit: Maximum candidates to return
            offset: Number to skip (for pagination)

        Returns:
            List of candidates with decision data if exists

        Raises:
            ValidationError: If status or sort_by is invalid
        """
        if status is not None:
            validate_enum(status, IMAGE_REVIEW_STATUSES, "review_status")

        valid_sort_options = ("tier", "confidence", "position")
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

        if status:
            status_filter = "AND irc.review_status = %(status)s"
            params["status"] = status

        # Build ORDER BY based on sort_by
        if sort_by == "tier":
            order_by = """
                CASE irc.detection_tier
                    WHEN 'seed_list' THEN 0
                    WHEN 'tier_1_cohort' THEN 1
                    WHEN 'tier_2_large' THEN 2
                    WHEN 'tier_3_all' THEN 3
                    ELSE 4
                END ASC,
                irc.cohort_confidence DESC NULLS LAST,
                irc.image_index ASC
            """
        elif sort_by == "confidence":
            order_by = "irc.cohort_confidence DESC NULLS LAST, irc.image_index ASC"
        else:  # position
            order_by = "irc.image_index ASC"

        sql = f"""
            SELECT
                irc.*,
                ird.image_decision_id,
                ird.decision,
                ird.chart_type,
                ird.rejection_reason,
                ird.reviewer_notes as decision_notes,
                ird.review_time_seconds,
                ird.created_at as decision_created_at
            FROM image_review_candidates irc
            LEFT JOIN image_review_decisions ird
                ON irc.image_candidate_id = ird.image_candidate_id
            WHERE irc.filing_id = %(filing_id)s {status_filter}
            ORDER BY {order_by}
            LIMIT %(limit)s OFFSET %(offset)s
        """

        return self.query(sql, params)

    def get_image_review_candidate(
        self,
        image_candidate_id: int,
    ) -> dict | None:
        """
        Get a single image review candidate with full context.

        Args:
            image_candidate_id: Candidate to retrieve

        Returns:
            Candidate dict with filing info and decision if exists, or None
        """
        sql = """
            SELECT
                irc.*,
                f.accession_number,
                c.company_name,
                ird.image_decision_id,
                ird.decision,
                ird.chart_type,
                ird.rejection_reason,
                ird.reviewer_id,
                ird.reviewer_notes as decision_notes,
                ird.review_time_seconds,
                ird.created_at as decision_created_at
            FROM image_review_candidates irc
            JOIN filings f ON irc.filing_id = f.filing_id
            JOIN companies c ON irc.company_id = c.company_id
            LEFT JOIN image_review_decisions ird
                ON irc.image_candidate_id = ird.image_candidate_id
            WHERE irc.image_candidate_id = %(image_candidate_id)s
        """

        results = self.query(sql, {"image_candidate_id": image_candidate_id})
        return results[0] if results else None

    def get_next_pending_image_candidate(
        self,
        filing_id: int,
        current_candidate_id: int | None = None,
        include_skipped: bool = False,
    ) -> dict | None:
        """
        Get the next pending image candidate for review navigation.

        Uses simple ID-based ordering for "next" navigation. Since candidates
        are inserted in discovery order (tier priority, then confidence, then
        position), using image_candidate_id > current_id gives correct ordering.

        Args:
            filing_id: Filing to search within
            current_candidate_id: Current candidate (to find next after this),
                                 or None to get first pending
            include_skipped: If True, also match skipped candidates

        Returns:
            Next pending (or skipped) candidate or None if all reviewed
        """
        params: dict[str, Any] = {"filing_id": filing_id}

        status_condition = (
            "AND irc.review_status IN ('pending', 'skipped')"
            if include_skipped
            else "AND irc.review_status = 'pending'"
        )

        # Simple "after current" filter using ID ordering
        after_condition = ""
        if current_candidate_id is not None:
            after_condition = "AND irc.image_candidate_id > %(current_candidate_id)s"
            params["current_candidate_id"] = current_candidate_id

        sql = f"""
            SELECT
                irc.image_candidate_id,
                irc.image_src,
                irc.image_url,
                irc.detection_tier,
                irc.cohort_confidence,
                irc.image_index
            FROM image_review_candidates irc
            WHERE irc.filing_id = %(filing_id)s
              {status_condition}
              {after_condition}
            ORDER BY irc.image_candidate_id ASC
            LIMIT 1
        """

        results = self.query(sql, params)
        return results[0] if results else None

    def get_image_review_progress(self) -> dict[str, Any]:
        """
        Get overall image review progress statistics.

        Returns:
            Dict with progress metrics including by-tier breakdown
        """
        sql = """
            SELECT
                COUNT(*) as total_candidates,
                COUNT(*) FILTER (WHERE review_status = 'pending') as pending_count,
                COUNT(*) FILTER (WHERE review_status = 'reviewed') as reviewed_count,
                COUNT(*) FILTER (WHERE review_status = 'skipped') as skipped_count,
                COUNT(DISTINCT filing_id) as total_filings,
                COUNT(DISTINCT filing_id) FILTER (WHERE review_status = 'pending') as filings_with_pending
            FROM image_review_candidates
        """

        results = self.query(sql)
        if not results or results[0]["total_candidates"] is None:
            return {
                "total_candidates": 0,
                "pending_count": 0,
                "reviewed_count": 0,
                "skipped_count": 0,
                "review_pct": 0.0,
                "total_filings": 0,
                "filings_with_pending": 0,
                "by_tier": {},
            }

        row = results[0]
        total = row["total_candidates"] or 0
        reviewed = row["reviewed_count"] or 0

        # Get breakdown by tier
        tier_sql = """
            SELECT
                COALESCE(detection_tier, 'unknown') as tier,
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE review_status = 'pending') as pending,
                COUNT(*) FILTER (WHERE review_status = 'reviewed') as reviewed
            FROM image_review_candidates
            GROUP BY detection_tier
            ORDER BY
                CASE detection_tier
                    WHEN 'seed_list' THEN 0
                    WHEN 'tier_1_cohort' THEN 1
                    WHEN 'tier_2_large' THEN 2
                    WHEN 'tier_3_all' THEN 3
                    ELSE 4
                END
        """
        tier_results = self.query(tier_sql)
        by_tier = {
            r["tier"]: {
                "total": r["total"],
                "pending": r["pending"],
                "reviewed": r["reviewed"],
            }
            for r in tier_results
        }

        return {
            "total_candidates": total,
            "pending_count": row["pending_count"] or 0,
            "reviewed_count": reviewed,
            "skipped_count": row["skipped_count"] or 0,
            "review_pct": round(reviewed / total * 100, 1) if total > 0 else 0.0,
            "total_filings": row["total_filings"] or 0,
            "filings_with_pending": row["filings_with_pending"] or 0,
            "by_tier": by_tier,
        }

    def get_image_decision_statistics(self) -> list[dict]:
        """
        Get image decision statistics by detection tier.

        Returns:
            List of dicts with tier, relevant_count, not_relevant_count, precision_pct
        """
        sql = """
            SELECT
                COALESCE(irc.detection_tier, 'unknown') as detection_tier,
                COUNT(*) FILTER (WHERE ird.decision = 'relevant') as relevant_count,
                COUNT(*) FILTER (WHERE ird.decision = 'not_relevant') as not_relevant_count,
                COUNT(*) as total_decisions,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE ird.decision = 'relevant')
                    / NULLIF(COUNT(*), 0),
                    1
                ) as precision_pct
            FROM image_review_decisions ird
            JOIN image_review_candidates irc
                ON ird.image_candidate_id = irc.image_candidate_id
            GROUP BY COALESCE(irc.detection_tier, 'unknown')
            ORDER BY
                CASE COALESCE(irc.detection_tier, 'unknown')
                    WHEN 'seed_list' THEN 0
                    WHEN 'tier_1_cohort' THEN 1
                    WHEN 'tier_2_large' THEN 2
                    WHEN 'tier_3_all' THEN 3
                    ELSE 4
                END
        """

        return self.query(sql)

    def get_image_overall_decision_statistics(self) -> dict[str, Any]:
        """
        Get overall image decision statistics (aggregate counts).

        Returns:
            Dict with total_decisions, relevant_count, not_relevant_count,
            relevant_pct, not_relevant_pct, avg_review_time_seconds
        """
        sql = """
            SELECT
                COUNT(*) as total_decisions,
                COUNT(*) FILTER (WHERE decision = 'relevant') as relevant_count,
                COUNT(*) FILTER (WHERE decision = 'not_relevant') as not_relevant_count,
                AVG(review_time_seconds) as avg_review_time_seconds
            FROM image_review_decisions
        """
        results = self.query(sql)
        if not results or results[0]["total_decisions"] == 0:
            return {
                "total_decisions": 0,
                "relevant_count": 0,
                "not_relevant_count": 0,
                "relevant_pct": 0.0,
                "not_relevant_pct": 0.0,
                "avg_review_time_seconds": None,
            }

        row = results[0]
        total = row["total_decisions"] or 0
        relevant = row["relevant_count"] or 0
        not_relevant = row["not_relevant_count"] or 0

        return {
            "total_decisions": total,
            "relevant_count": relevant,
            "not_relevant_count": not_relevant,
            "relevant_pct": round(relevant / total * 100, 1) if total > 0 else 0.0,
            "not_relevant_pct": round(not_relevant / total * 100, 1) if total > 0 else 0.0,
            "avg_review_time_seconds": row["avg_review_time_seconds"],
        }

    def get_image_daily_decision_counts(self, days: int = 7) -> list[dict]:
        """
        Get image decision counts by day for the last N days.

        Returns a time series of decision counts suitable for chart visualization.
        Includes days with zero decisions to ensure continuous timeline.

        Args:
            days: Number of days to include (default: 7)

        Returns:
            List of dicts with:
            - date: Date (datetime.date object)
            - count: Number of decisions made on that date

            Results are ordered by date ascending (oldest first).

        Example:
            >>> db.get_image_daily_decision_counts(days=7)
            [
                {"date": date(2025, 12, 10), "count": 5},
                {"date": date(2025, 12, 11), "count": 0},
                {"date": date(2025, 12, 12), "count": 12},
                ...
            ]
        """
        sql = """
            WITH date_series AS (
                -- Generate series of dates for last N days
                SELECT generate_series(
                    CURRENT_DATE - %(days)s + 1,
                    CURRENT_DATE,
                    '1 day'::interval
                )::date AS date
            ),
            daily_counts AS (
                -- Count decisions per day
                -- Use DATE() to convert timestamps to dates for grouping
                SELECT
                    DATE(created_at) AS date,
                    COUNT(*) AS count
                FROM image_review_decisions
                WHERE DATE(created_at) >= CURRENT_DATE - %(days)s + 1
                GROUP BY DATE(created_at)
            )
            -- Left join to include days with zero decisions
            SELECT
                ds.date,
                COALESCE(dc.count, 0) AS count
            FROM date_series ds
            LEFT JOIN daily_counts dc ON ds.date = dc.date
            ORDER BY ds.date ASC
        """

        return self.query(sql, {"days": days})

    def get_image_chart_type_distribution(self) -> list[dict]:
        """
        Get chart type distribution for relevant image decisions.

        Returns:
            List of dicts with chart_type, chart_count, pct_of_relevant
        """
        return self.query(
            "SELECT chart_type, chart_count, pct_of_relevant "
            "FROM v_image_chart_type_distribution "
            "ORDER BY chart_count DESC"
        )

    def get_image_rejection_reason_stats(self) -> list[dict]:
        """
        Get rejection reason breakdown by detection tier.

        Returns:
            List of dicts with detection_tier, rejection_reason, rejection_count, pct_of_tier_rejections
        """
        return self.query(
            "SELECT detection_tier, rejection_reason, rejection_count, pct_of_tier_rejections "
            "FROM v_image_rejection_reasons "
            "ORDER BY detection_tier, rejection_count DESC"
        )

    def insert_image_review_candidate(
        self,
        filing_id: int,
        company_id: int,
        image_src: str,
        image_url: str,
        source_segment_id: int | None = None,
        image_width: int | None = None,
        image_height: int | None = None,
        image_alt: str | None = None,
        preceding_text: str | None = None,
        detected_keywords: list[str] | None = None,
        cohort_keyword_nearby: bool | None = None,
        image_index: int | None = None,
        cohort_confidence: float | None = None,
        is_decorative: bool | None = None,
        detection_tier: str | None = None,
    ) -> int:
        """
        Insert or get an image review candidate.

        Uses upsert with DO NOTHING on conflict - if the candidate already exists
        (same filing_id + image_src), returns the existing candidate_id.

        Args:
            filing_id: Filing containing the image
            company_id: Company of the filing
            image_src: Image filename (e.g., 'mdaa2.jpg')
            image_url: Full SEC URL to image
            source_segment_id: Optional link to source_segments table
            image_width: Image width in pixels
            image_height: Image height in pixels
            image_alt: Alt text from HTML
            preceding_text: Context text before image
            detected_keywords: Keywords found near image
            cohort_keyword_nearby: Whether 'cohort' keyword is within 1500 chars
            image_index: Position of image in filing (1-indexed)
            cohort_confidence: Confidence score 0.0-1.0
            is_decorative: Whether image is likely decorative
            detection_tier: Discovery method ('tier_1_cohort', 'tier_2_large', etc.)

        Returns:
            image_candidate_id (new or existing)

        Raises:
            ValidationError: If cohort_confidence out of range or invalid detection_tier
        """
        # Validate cohort_confidence if provided
        if cohort_confidence is not None:
            validate_score(cohort_confidence, "cohort_confidence")

        # Validate detection_tier if provided
        if detection_tier is not None:
            from src.review.models import IMAGE_DETECTION_TIERS

            validate_enum(detection_tier, IMAGE_DETECTION_TIERS, "detection_tier")

        sql = """
            INSERT INTO image_review_candidates (
                filing_id, company_id, source_segment_id,
                image_src, image_url,
                image_width, image_height, image_alt,
                preceding_text, detected_keywords,
                cohort_keyword_nearby, image_index,
                cohort_confidence, is_decorative, detection_tier
            )
            VALUES (
                %(filing_id)s, %(company_id)s, %(source_segment_id)s,
                %(image_src)s, %(image_url)s,
                %(image_width)s, %(image_height)s, %(image_alt)s,
                %(preceding_text)s, %(detected_keywords)s,
                %(cohort_keyword_nearby)s, %(image_index)s,
                %(cohort_confidence)s, %(is_decorative)s, %(detection_tier)s
            )
            ON CONFLICT (filing_id, image_src) DO NOTHING
            RETURNING image_candidate_id
        """

        params = {
            "filing_id": filing_id,
            "company_id": company_id,
            "source_segment_id": source_segment_id,
            "image_src": image_src,
            "image_url": image_url,
            "image_width": image_width,
            "image_height": image_height,
            "image_alt": image_alt,
            "preceding_text": preceding_text,
            "detected_keywords": detected_keywords,
            "cohort_keyword_nearby": cohort_keyword_nearby,
            "image_index": image_index,
            "cohort_confidence": cohort_confidence,
            "is_decorative": is_decorative,
            "detection_tier": detection_tier,
        }

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                result = cur.fetchone()

                if result:
                    # Inserted successfully
                    return int(result["image_candidate_id"])

                # Conflict - row already exists, fetch existing ID
                cur.execute(
                    """
                    SELECT image_candidate_id
                    FROM image_review_candidates
                    WHERE filing_id = %(filing_id)s AND image_src = %(image_src)s
                    """,
                    {"filing_id": filing_id, "image_src": image_src},
                )
                existing = cur.fetchone()
                return int(existing["image_candidate_id"]) if existing else 0

    def insert_image_review_decision(
        self,
        image_candidate_id: int,
        decision: str,
        chart_type: str | None = None,
        rejection_reason: str | None = None,
        reviewer_id: str | None = None,
        reviewer_notes: str | None = None,
        review_time_seconds: int | None = None,
    ) -> int:
        """
        Record a human review decision for an image candidate.

        Atomically inserts the decision AND updates the candidate's status
        to 'reviewed' in a single transaction.

        Args:
            image_candidate_id: Candidate being reviewed
            decision: 'relevant' or 'not_relevant'
            chart_type: Chart type (required if decision='relevant')
            rejection_reason: Reason (required if decision='not_relevant')
            reviewer_id: Identifier for who made this decision
            reviewer_notes: Optional notes
            review_time_seconds: Time spent on this decision

        Returns:
            image_decision_id of the inserted record

        Raises:
            ValidationError: If decision invalid, or required fields missing
        """
        # Validate decision
        validate_enum(decision, IMAGE_DECISIONS, "decision")

        # Validate chart_type if provided
        if chart_type is not None:
            validate_enum(chart_type, IMAGE_CHART_TYPES, "chart_type")

        # Validate rejection_reason if provided
        if rejection_reason is not None:
            validate_enum(rejection_reason, IMAGE_REJECTION_REASONS, "rejection_reason")

        # Business rule: relevant requires chart_type
        if decision == "relevant" and not chart_type:
            raise ValidationError("Decision 'relevant' requires chart_type")

        # Business rule: not_relevant requires rejection_reason
        if decision == "not_relevant" and not rejection_reason:
            raise ValidationError("Decision 'not_relevant' requires rejection_reason")

        insert_sql = """
            INSERT INTO image_review_decisions (
                image_candidate_id, decision, chart_type,
                rejection_reason, reviewer_id, reviewer_notes,
                review_time_seconds
            )
            VALUES (
                %(image_candidate_id)s, %(decision)s, %(chart_type)s,
                %(rejection_reason)s, %(reviewer_id)s, %(reviewer_notes)s,
                %(review_time_seconds)s
            )
            RETURNING image_decision_id
        """

        update_status_sql = """
            UPDATE image_review_candidates
            SET review_status = 'reviewed', updated_at = now()
            WHERE image_candidate_id = %(image_candidate_id)s
        """

        # Both operations in same transaction for atomicity
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Insert the decision
                cur.execute(
                    insert_sql,
                    {
                        "image_candidate_id": image_candidate_id,
                        "decision": decision,
                        "chart_type": chart_type,
                        "rejection_reason": rejection_reason,
                        "reviewer_id": reviewer_id,
                        "reviewer_notes": reviewer_notes,
                        "review_time_seconds": review_time_seconds,
                    },
                )
                result = cur.fetchone()
                decision_id: int = int(result["image_decision_id"])

                # Update candidate status - SAME TRANSACTION
                cur.execute(update_status_sql, {"image_candidate_id": image_candidate_id})

        logger.debug(
            f"Inserted image review decision: decision_id={decision_id}, "
            f"candidate_id={image_candidate_id}, decision={decision}"
        )
        return decision_id

    def get_image_decision_by_id(
        self,
        image_decision_id: int,
    ) -> dict | None:
        """
        Get an image review decision by its ID.

        Args:
            image_decision_id: Decision ID to retrieve

        Returns:
            Dict with decision details or None if not found
        """
        sql = """
            SELECT
                ird.image_decision_id,
                ird.image_candidate_id,
                ird.decision,
                ird.chart_type,
                ird.rejection_reason,
                ird.reviewer_id,
                ird.reviewer_notes,
                ird.review_time_seconds,
                ird.created_at,
                irc.filing_id
            FROM image_review_decisions ird
            JOIN image_review_candidates irc
                ON ird.image_candidate_id = irc.image_candidate_id
            WHERE ird.image_decision_id = %(image_decision_id)s
        """

        results = self.query(sql, {"image_decision_id": image_decision_id})
        return results[0] if results else None

    def delete_image_review_decision(
        self,
        image_decision_id: int,
    ) -> bool:
        """
        Delete an image review decision and reset candidate status.

        Args:
            image_decision_id: Decision to delete

        Returns:
            True if decision was deleted, False if not found
        """
        # First get the candidate_id so we can reset its status
        get_candidate_sql = """
            SELECT image_candidate_id
            FROM image_review_decisions
            WHERE image_decision_id = %(image_decision_id)s
        """

        delete_sql = """
            DELETE FROM image_review_decisions
            WHERE image_decision_id = %(image_decision_id)s
        """

        reset_status_sql = """
            UPDATE image_review_candidates
            SET review_status = 'pending', updated_at = now()
            WHERE image_candidate_id = %(image_candidate_id)s
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Get the candidate_id first
                cur.execute(get_candidate_sql, {"image_decision_id": image_decision_id})
                result = cur.fetchone()

                if not result:
                    return False

                image_candidate_id = result["image_candidate_id"]

                # Delete the decision
                cur.execute(delete_sql, {"image_decision_id": image_decision_id})

                # Reset candidate status
                cur.execute(reset_status_sql, {"image_candidate_id": image_candidate_id})

        logger.debug(
            f"Deleted image review decision: decision_id={image_decision_id}, "
            f"reset candidate_id={image_candidate_id} to pending"
        )
        return True

    def update_image_candidate_status(
        self,
        image_candidate_id: int,
        status: str,
    ) -> bool:
        """
        Update an image candidate's review status.

        Args:
            image_candidate_id: Candidate to update
            status: New status ('pending', 'reviewed', 'skipped')

        Returns:
            True if updated, False if candidate not found

        Raises:
            ValidationError: If status is invalid
        """
        validate_enum(status, IMAGE_REVIEW_STATUSES, "review_status")

        sql = """
            UPDATE image_review_candidates
            SET review_status = %(status)s, updated_at = now()
            WHERE image_candidate_id = %(image_candidate_id)s
            RETURNING image_candidate_id
        """

        result = self.query(
            sql,
            {"image_candidate_id": image_candidate_id, "status": status},
        )
        return len(result) > 0

    # =============================================================================
    # V2 Extraction Review Methods
    # =============================================================================

    def get_v2_filings_with_facts(
        self,
        document_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get filings that have V2 extraction results, with fact counts and review progress.

        Args:
            document_type: Optional filter — "sec_filing" or "earnings_call".
            limit: Maximum number of rows to return. None returns all rows.
            offset: Number of rows to skip (for pagination).

        Returns:
            List of dicts with filing metadata and V2 extraction stats.
        """
        conditions: list[str] = ["(f.is_spac IS NOT TRUE)"]
        params: dict[str, Any] = {}
        if document_type is not None:
            conditions.append("d.document_type = %(document_type)s")
            params["document_type"] = document_type
        where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT
                f.filing_id,
                c.company_name,
                c.cik,
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
            LEFT JOIN v2_metric_facts mf ON mf.doc_id = d.filing_id
            {where_clause}
            GROUP BY f.filing_id, c.company_name, c.cik, f.accession_number,
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
        document_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Get filings combining V2 text fact counts and image candidate counts.

        Returns one row per filing with review progress for both text facts and
        image candidates. Used by the unified filing list page.

        Args:
            document_type: Optional filter — "sec_filing" or "earnings_call"
                           (applied against v2_documents.document_type).
            limit: Maximum number of rows to return.
            offset: Number of rows to skip (for pagination).

        Returns:
            List of dicts with filing metadata and combined review stats.
        """
        doc_type_filter = ""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if document_type is not None:
            doc_type_filter = "AND d.document_type = %(document_type)s"
            params["document_type"] = document_type

        sql = f"""
            WITH text_progress AS (
                SELECT
                    mf.doc_id                                                              AS filing_id,
                    COUNT(mf.fact_id)                                                      AS fact_count,
                    COUNT(CASE WHEN mf.review_status = 'pending_review'             THEN 1 END) AS facts_pending,
                    COUNT(CASE WHEN mf.review_status IN ('accepted', 'auto_accepted') THEN 1 END) AS facts_accepted,
                    COUNT(CASE WHEN mf.review_status IN ('rejected', 'corrected')   THEN 1 END) AS facts_rejected
                FROM v2_metric_facts mf
                GROUP BY mf.doc_id
            ),
            image_progress AS (
                SELECT
                    irc.filing_id,
                    COUNT(irc.image_candidate_id)                                          AS image_count,
                    COUNT(CASE WHEN irc.review_status = 'pending'   THEN 1 END)            AS images_pending,
                    COUNT(CASE WHEN irc.review_status = 'reviewed'  THEN 1 END)            AS images_reviewed
                FROM image_review_candidates irc
                GROUP BY irc.filing_id
            )
            SELECT
                f.filing_id,
                c.company_name,
                c.cik,
                f.accession_number,
                f.form_type,
                f.filing_date,
                d.document_type,
                COALESCE(tp.fact_count,      0) AS fact_count,
                COALESCE(tp.facts_pending,   0) AS facts_pending,
                COALESCE(tp.facts_accepted,  0) AS facts_accepted,
                COALESCE(tp.facts_rejected,  0) AS facts_rejected,
                COALESCE(ip.image_count,     0) AS image_count,
                COALESCE(ip.images_pending,  0) AS images_pending,
                COALESCE(ip.images_reviewed, 0) AS images_reviewed
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            JOIN v2_documents d ON d.filing_id = f.filing_id
            LEFT JOIN text_progress  tp ON tp.filing_id = f.filing_id
            LEFT JOIN image_progress ip ON ip.filing_id = f.filing_id
            WHERE (f.is_spac IS NOT TRUE)
            {doc_type_filter}
            ORDER BY f.filing_date DESC NULLS LAST, c.company_name
            LIMIT %(limit)s OFFSET %(offset)s
        """
        return self.query(sql, params)

    def get_unified_filings_for_review_count(
        self,
        document_type: str | None = None,
    ) -> int:
        """Return total count of filings eligible for unified review.

        Args:
            document_type: Optional filter — "sec_filing" or "earnings_call".

        Returns:
            Total number of matching filings.
        """
        doc_type_filter = ""
        params: dict[str, Any] = {}
        if document_type is not None:
            doc_type_filter = "AND d.document_type = %(document_type)s"
            params["document_type"] = document_type

        sql = f"""
            SELECT COUNT(*) AS cnt
            FROM filings f
            JOIN v2_documents d ON d.filing_id = f.filing_id
            WHERE (f.is_spac IS NOT TRUE)
            {doc_type_filter}
        """
        result = self.query(sql, params if params else None)
        return result[0]["cnt"] if result else 0

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
        conditions = ["mf.doc_id = %(filing_id)s"]
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
                mf.doc_id,
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
        conditions = ["mf.doc_id = %(filing_id)s"]
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

    def get_segment_context(self, doc_id: int, segment_id: str, window: int = 2) -> list[dict]:
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
                WHERE segment_id = %(segment_id)s AND doc_id = %(doc_id)s
            )
            SELECT s.segment_id::text, s.segment_type, s.segment_text,
                   s.section_path, s.section_type, s.sequence_idx
            FROM v2_segments s, target t
            WHERE s.doc_id = %(doc_id)s
              AND s.sequence_idx BETWEEN t.sequence_idx - %(window)s
                                     AND t.sequence_idx + %(window)s
            ORDER BY s.sequence_idx
            """,
            {"doc_id": doc_id, "segment_id": segment_id, "window": window},
        )

    def get_table_context(self, doc_id: int, table_id: str) -> dict | None:
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
            WHERE table_id = %(table_id)s AND doc_id = %(doc_id)s
            LIMIT 1
            """,
            {"doc_id": doc_id, "table_id": table_id},
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
            SELECT rd.decision_id, rd.fact_id, mf.doc_id AS filing_id
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
            filing_id: Filing ID (maps to v2_metric_facts.doc_id).
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
                doc_id,
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
            LEFT JOIN v2_metric_facts mf ON mf.doc_id = d.filing_id
            GROUP BY c.company_id, c.company_name, c.cik
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
            LEFT JOIN v2_metric_facts mf ON mf.doc_id = d.filing_id
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
