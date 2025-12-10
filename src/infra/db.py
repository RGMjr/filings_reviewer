"""
Database adapter for Customer Metrics Filings Analysis.

Provides a clean interface for database operations using psycopg3.
"""

import json
import logging
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Dict, List, Optional

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
        pool: Optional["ConnectionPool"] = None,
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
            raise ValueError(f"Invalid SQL script path: {e}")

        # Validate file extension
        if not sql_file_path.endswith(".sql"):
            raise ValueError("SQL script files must have .sql extension")

        # Validate file exists
        if not path.exists():
            raise ValueError(f"SQL script file not found: {sql_file_path}")

        with open(sql_file_path, "r") as f:
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
        is_post_combination: Optional[bool] = None,
        is_investment_vehicle: Optional[bool] = None,
        is_resource_extraction: Optional[bool] = None,
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
        params: Optional[Dict[str, Any]] = None,
        *,
        fetch: bool = False,
    ) -> Optional[List[Dict[str, Any]]]:
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

    def query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict]:
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
        source_segment_id: Optional[int] = None,
        parsed_value: Optional[Any] = None,
        parsed_unit: Optional[str] = None,
        suggested_metric_id: Optional[str] = None,
        suggestion_confidence: Optional[float] = None,
        features: Optional[Dict[str, Any]] = None,
        review_batch_id: Optional[int] = None,
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
            ValueError: If keyword_position is not 'before' or 'after'
            ValueError: If suggestion_confidence is not between 0 and 1
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

    def get_review_candidate(self, candidate_id: int) -> Optional[Dict]:
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

    def get_review_candidates_for_filing(
        self,
        filing_id: int,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict]:
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
        params: Dict[str, Any] = {"filing_id": filing_id}

        if status:
            sql += " AND review_status = %(status)s"
            params["status"] = status

        sql += " ORDER BY char_position"

        if limit:
            sql += " LIMIT %(limit)s OFFSET %(offset)s"
            params["limit"] = limit
            params["offset"] = offset

        return self.query(sql, params)

    def get_pending_candidates(
        self,
        filing_id: Optional[int] = None,
        batch_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict]:
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
        params: Dict[str, Any] = {"limit": limit}

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
            True if update succeeded

        Raises:
            ValueError: If status is not a valid review status
        """
        # Validate status
        validate_enum(status, REVIEW_STATUSES, "review_status")

        sql = """
            UPDATE review_candidates
            SET review_status = %(status)s, updated_at = now()
            WHERE candidate_id = %(candidate_id)s
        """
        self.execute(sql, {"candidate_id": candidate_id, "status": status})
        logger.debug(f"Updated candidate {candidate_id} status to {status}")
        return True

    def bulk_insert_review_candidates(
        self, candidates: List[Dict[str, Any]]
    ) -> List[int]:
        """
        Bulk insert multiple review candidates efficiently.

        Uses PostgreSQL UNNEST for efficient single-statement bulk insert.

        Args:
            candidates: List of candidate dictionaries with fields matching
                        insert_review_candidate parameters

        Returns:
            List of inserted candidate_ids (in same order as input)

        Raises:
            ValueError: If any candidate has invalid keyword_position
            ValueError: If any candidate has invalid suggestion_confidence
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
        assigned_metric_id: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        rejection_category: Optional[str] = None,
        reviewer_notes: Optional[str] = None,
        review_time_seconds: Optional[int] = None,
    ) -> int:
        """
        Record a human review decision.

        Note: This method automatically updates the candidate's status to 'reviewed'.

        Args:
            candidate_id: Candidate being reviewed
            decision: 'accept', 'reject', or 'reclassify'
            assigned_metric_id: Final metric ID (required for accept/reclassify)
            rejection_reason: Free-text explanation for rejection
            rejection_category: Categorized reason for pattern learning
            reviewer_notes: Optional notes
            review_time_seconds: Time spent on this decision

        Returns:
            decision_id of the inserted record

        Raises:
            ValueError: If decision is not 'accept', 'reject', or 'reclassify'
            ValueError: If rejection_category is not a valid category
            ValueError: If accept/reclassify without assigned_metric_id
            ValueError: If rejection_category provided for non-reject decision
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
            raise ValueError(
                f"Decision '{decision}' requires assigned_metric_id"
            )

        # Business rule: rejection_category only valid for reject
        if decision != "reject" and rejection_category:
            raise ValueError(
                f"rejection_category should only be set when decision='reject', "
                f"got decision='{decision}'"
            )

        sql = """
            INSERT INTO review_decisions (
                candidate_id, decision, assigned_metric_id,
                rejection_reason, rejection_category,
                reviewer_notes, review_time_seconds
            )
            VALUES (
                %(candidate_id)s, %(decision)s, %(assigned_metric_id)s,
                %(rejection_reason)s, %(rejection_category)s,
                %(reviewer_notes)s, %(review_time_seconds)s
            )
            RETURNING decision_id
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "candidate_id": candidate_id,
                        "decision": decision,
                        "assigned_metric_id": assigned_metric_id,
                        "rejection_reason": rejection_reason,
                        "rejection_category": rejection_category,
                        "reviewer_notes": reviewer_notes,
                        "review_time_seconds": review_time_seconds,
                    },
                )
                result = cur.fetchone()
                decision_id = result["decision_id"]

        # Also update the candidate status to 'reviewed'
        self.update_candidate_status(candidate_id, "reviewed")

        logger.debug(
            f"Inserted review decision: decision_id={decision_id}, "
            f"candidate_id={candidate_id}, decision={decision}"
        )
        return decision_id

    def get_decision_for_candidate(self, candidate_id: int) -> Optional[Dict]:
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

    def get_decisions_for_filing(self, filing_id: int) -> List[Dict]:
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
        self, filing_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get statistics on review decisions.

        Args:
            filing_id: Optional filter by filing

        Returns:
            Dict with decision counts and percentages
        """
        where_clause = ""
        params: Dict[str, Any] = {}

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

    # =========================================================================
    # Learned Patterns Methods
    # =========================================================================

    def insert_learned_pattern(
        self,
        pattern_type: str,
        pattern_name: str,
        pattern_definition: Dict[str, Any],
        metric_id: Optional[str] = None,
        pattern_description: Optional[str] = None,
        precision_score: Optional[float] = None,
        recall_score: Optional[float] = None,
        f1_score: Optional[float] = None,
        sample_count: Optional[int] = None,
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
            ValueError: If pattern_type is not valid
            ValueError: If any score is not between 0 and 1
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

    def get_learned_pattern(self, pattern_id: int) -> Optional[Dict]:
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

    def get_approved_patterns(
        self,
        pattern_type: Optional[str] = None,
        metric_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get approved patterns for use in extraction.

        Args:
            pattern_type: Optional filter by pattern type
            metric_id: Optional filter by metric

        Returns:
            List of approved pattern records
        """
        sql = """
            SELECT * FROM learned_patterns
            WHERE status = 'approved'
        """
        params: Dict[str, Any] = {}

        if pattern_type:
            sql += " AND pattern_type = %(pattern_type)s"
            params["pattern_type"] = pattern_type

        if metric_id:
            sql += " AND (metric_id = %(metric_id)s OR metric_id IS NULL)"
            params["metric_id"] = metric_id

        sql += " ORDER BY precision_score DESC NULLS LAST"

        return self.query(sql, params)

    def update_pattern_status(
        self,
        pattern_id: int,
        status: str,
        approved_by: Optional[str] = None,
    ) -> bool:
        """
        Update a pattern's status.

        Args:
            pattern_id: Pattern to update
            status: New status ('candidate', 'approved', 'rejected', 'deprecated')
            approved_by: Who approved (if status='approved')

        Returns:
            True if update succeeded

        Raises:
            ValueError: If status is not a valid pattern status
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
        """
        self.execute(
            sql,
            {"pattern_id": pattern_id, "status": status, "approved_by": approved_by},
        )
        logger.debug(f"Updated pattern {pattern_id} status to {status}")
        return True

    # =========================================================================
    # Helper Methods for Flask Routes
    # =========================================================================

    def get_filings_with_candidates(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """
        Get filings that have review candidates.

        Useful for the filing list page in the review interface.

        Args:
            status: Optional filter by candidate review_status
            limit: Maximum number of filings to return

        Returns:
            List of filings with candidate counts
        """
        status_filter = ""
        params: Dict[str, Any] = {"limit": limit}

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
            LIMIT %(limit)s
        """

        return self.query(sql, params)

    def get_review_progress(self) -> Dict[str, Any]:
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
        self, filing_id: Optional[int] = None
    ) -> Optional[Dict]:
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
        params: Dict[str, Any] = {}

        if filing_id:
            sql += " AND rc.filing_id = %(filing_id)s"
            params["filing_id"] = filing_id

        sql += " ORDER BY rc.filing_id, rc.char_position LIMIT 1"

        results = self.query(sql, params)
        return results[0] if results else None


# =============================================================================
# Convenience Functions
# =============================================================================


def create_pooled_adapter(connection_string: Optional[str] = None) -> DatabaseAdapter:
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
