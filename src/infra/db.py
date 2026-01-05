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

        logger.debug(
            f"Upserted filing: accession={accession_number}, filing_id={filing_id}"
        )
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
        segment_results = self.query(
            segment_sql, {"source_segment_id": source_segment_id}
        )

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
        expanded_text = " ... ".join(
            seg["raw_text"] for seg in adjacent_results if seg["raw_text"]
        )

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
            segment_html = result.get('segment_html')
            raw_number_text = result.get('raw_number_text')
            triggering_keyword = result.get('triggering_keyword')

            # Initialize dual display field
            result['segment_html_table_only'] = None

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
                    has_table = '<table' in segment_html.lower()

                    if has_table and has_keyword:
                        # Table structure is useful even without the value highlighted
                        # Store it for dual display mode in the UI
                        logger.debug(
                            f"Segment HTML for candidate {result.get('candidate_id')} has table "
                            f"with keyword but value is truncated. Enabling dual display mode."
                        )
                        result['segment_html_table_only'] = segment_html
                    else:
                        logger.debug(
                            f"Segment HTML for candidate {result.get('candidate_id')} doesn't contain "
                            f"value={has_value}, keyword={has_keyword}. Clearing for context_text fallback."
                        )

                    # Clear segment_html to force display of context_text instead
                    result['segment_html'] = None
                    result['segment_type'] = None

        return results

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

    def update_candidate_status(
        self, candidate_id: int, status: str
    ) -> bool:
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
        result = self.execute(
            sql, {"candidate_id": candidate_id, "status": status}, fetch=True
        )
        updated = bool(result)
        if updated:
            logger.debug(f"Updated candidate {candidate_id} status to {status}")
        else:
            logger.warning(f"No candidate found with id {candidate_id}")
        return updated

    def bulk_update_candidate_status(
        self, candidate_ids: list[int], status: str
    ) -> int:
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

        logger.debug(
            f"Bulk updated {rows_updated} candidates to status '{status}'"
        )
        return rows_updated

    def bulk_insert_review_candidates(
        self, candidates: list[dict[str, Any]]
    ) -> list[int]:
        """
        Bulk insert multiple review candidates efficiently.

        Uses PostgreSQL UNNEST for efficient single-statement bulk insert.

        Args:
            candidates: List of candidate dictionaries with fields matching
                        insert_review_candidate parameters

        Returns:
            List of inserted candidate_ids (in same order as input)

        Raises:
            ValidationError: If any candidate has invalid keyword_position
            ValidationError: If any candidate has invalid suggestion_confidence
        """
        if not candidates:
            return []

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

        # Use UNNEST with ORDINALITY for efficient single-statement bulk insert
        # WITH ORDINALITY ensures we preserve input array order via ORDER BY ord
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

        with self.get_connection() as conn:
            with conn.cursor() as cur:
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
                inserted_ids = [row["candidate_id"] for row in results]

        logger.debug(f"Bulk inserted {len(inserted_ids)} review candidates")
        return inserted_ids

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
            validate_enum(
                rejection_category, REJECTION_CATEGORIES, "rejection_category"
            )

        # Business rule: accept/reclassify require assigned_metric_id
        if decision in ("accept", "reclassify") and not assigned_metric_id:
            raise ValidationError(
                f"Decision '{decision}' requires assigned_metric_id"
            )

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
            validate_enum(
                rejection_category, REJECTION_CATEGORIES, "rejection_category"
            )

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

                # Check each candidate
                for candidate_id in candidate_ids:
                    # Skip if candidate doesn't exist
                    if candidate_id not in candidates_data:
                        failed_candidates.append(
                            {
                                "candidate_id": candidate_id,
                                "error": "Candidate not found",
                            }
                        )
                        continue

                    # Skip if already reviewed
                    if candidates_data[candidate_id]["review_status"] != "pending":
                        failed_candidates.append(
                            {
                                "candidate_id": candidate_id,
                                "error": f"Already reviewed (status: {candidates_data[candidate_id]['review_status']})",
                            }
                        )
                        continue

                    # Insert decision for this candidate
                    try:
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
                            RETURNING decision_id
                        """

                        update_status_sql = """
                            UPDATE review_candidates
                            SET review_status = 'reviewed', updated_at = now()
                            WHERE candidate_id = %(candidate_id)s
                        """

                        # Insert decision
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
                            },
                        )
                        result = cur.fetchone()
                        decision_id = result["decision_id"]

                        # Update candidate status - SAME TRANSACTION
                        cur.execute(update_status_sql, {"candidate_id": candidate_id})

                        decision_ids.append(decision_id)

                    except Exception as e:
                        # If any unexpected error, let it bubble up to rollback entire transaction
                        logger.error(
                            f"Error inserting decision for candidate {candidate_id}: {e}"
                        )
                        raise

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
                    (decision_id,)
                )
                result = cur.fetchone()

                if not result:
                    logger.debug(f"Decision {decision_id} not found")
                    return False

                candidate_id = result["candidate_id"]

                # Delete decision
                cur.execute(
                    "DELETE FROM review_decisions WHERE decision_id = %s",
                    (decision_id,)
                )

                # Reset candidate status to pending
                cur.execute(
                    "UPDATE review_candidates SET review_status = 'pending', updated_at = now() WHERE candidate_id = %s",
                    (candidate_id,)
                )

        logger.info(
            f"Deleted decision {decision_id}, reset candidate {candidate_id} to pending"
        )
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

    def get_decision_statistics(
        self, filing_id: int | None = None
    ) -> dict[str, Any]:
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

    def get_decision_stats_by_metric(
        self, metric_id: str | None = None
    ) -> list[dict]:
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

    def get_rejection_reasons(
        self, metric_id: str | None = None
    ) -> list[dict]:
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
                COUNT(rc.candidate_id) FILTER (WHERE rc.review_status = 'reviewed') as reviewed_count
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

    def get_next_candidate_for_review(
        self, filing_id: int | None = None
    ) -> dict | None:
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
                "connection_string not provided and DATABASE_URL environment "
                "variable not set"
            )

    pool = get_shared_pool(connection_string)
    return DatabaseAdapter(connection_string, pool=pool)
