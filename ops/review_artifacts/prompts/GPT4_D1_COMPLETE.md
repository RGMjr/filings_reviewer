# GPT-4 Code Review: D1 Architecture

**Copy this entire prompt and paste into GPT-4 (or GPT-4o)**

---

You are a senior software engineer conducting an architecture code review of a production Python system that extracts customer metrics from SEC S-1/F-1 filings.

## Project Context

- **Size**: 39,847 LOC source, 81,244 LOC tests (2:1 test ratio)
- **Coverage**: 81.57%
- **Architecture**: 6-stage extraction pipeline + human review system
- **Database**: PostgreSQL with psycopg3
- **LLM**: OpenAI GPT-4o-mini for extraction fallback

## Static Analysis Findings

**Critical Complexity Hotspots:**
1. `_process_segment` (CC=57) - candidate_generator.py:481
2. `find_keywords_near_number` (CC=46) - keyword_matching.py:523
3. `bulk_insert_review_candidates` (CC=42) - db.py:1421

**Maintainability Issues:**
- `db.py`: 4,006 LOC, MI=0.0 (unmaintainable)
- `html_segmenter.py`: 2,028 LOC, MI=0.0
- `pattern_analyzer.py`: 2,544 LOC, MI=0.0

## Files to Review

### src/infra/db.py (4,006 LOC - Largest File)
```python
# Database adapter with 50+ methods
# Key concerns:
# - Single file handling ALL database operations
# - Mix of CRUD, queries, schema, migrations
# - Complex bulk_insert_review_candidates (CC=42)

class DatabaseAdapter:
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self._pool: Pool | None = None

    # 50+ methods for:
    # - Company/filing CRUD
    # - Segment storage
    # - Metric value storage
    # - Review candidate management
    # - Pattern learning
    # - Batch operations
```

### src/extraction/extraction_pipeline.py (619 LOC)
```python
class ExtractionPipeline:
    """
    6-stage pipeline:
    1. HTML Segmentation (HTMLSegmenter)
    2. Metric Classification (MetricClassifier)
    3. Segment Enrichment (SegmentEnricher)
    4. Tiered Segment Selection
    5. Value Extraction (ValueExtractor)
    6. Quality Scoring (QualityScorer)
    """

    def extract(self, filing_id: int, html_content: str) -> ExtractionResult:
        # Stage 1: Parse HTML into segments
        segments = self._segmenter.segment_filing(html_content)

        # Stage 2: Classify segments
        classified = self._classifier.classify_segments(segments)

        # Stage 2b: Enrich with metadata
        enriched = self._enricher.enrich_segments(classified)

        # Stage 2c: Select top segments by tier
        selected = self._select_segments_tiered(enriched)  # CC=30

        # Stage 3: Extract values
        values = self._extractor.extract_values(selected)

        # Stage 4-6: Definitions, quality, store
        ...
```

### Circular Dependency Detected
```
src/extraction/html_segmenter.py imports from src/review/boundary_detection.py
src/review/ modules import from src/extraction/
```

### V1 vs V2 Pipeline
```
src/extraction/     - V1 pipeline (production, 85% coverage)
src/extraction_v2/  - V2 pipeline (development, 0% coverage)
                    - No migration strategy documented
                    - Unclear which to use
```

## Review Questions

1. **Module Boundaries**: Are module boundaries clear? Is there inappropriate coupling?
2. **db.py Monolith**: Is 4,006 LOC in one file acceptable? How should it be decomposed?
3. **Data Flow**: Is the 6-stage pipeline data flow clear and maintainable?
4. **Circular Dependencies**: How serious is the extraction↔review circular dependency?
5. **V1/V2 Strategy**: What's the right migration strategy? Coexist or replace?
6. **Config Approach**: Is YAML for keyword patterns scalable?

## Output Format

Return your findings as JSON:

```json
{
  "dimension": "D1_ARCHITECTURE",
  "model": "gpt4",
  "findings": [
    {
      "id": "G-D1-001",
      "severity": "Critical|High|Medium|Low",
      "category": "architecture",
      "title": "Short title",
      "description": "Detailed description",
      "file": "path/to/file.py",
      "line_range": "100-150",
      "code_before": "problematic pattern",
      "code_after": "suggested improvement",
      "recommendation": "What to do",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "summary": "Overall architecture assessment"
}
```

Provide 8-15 findings covering the key architectural concerns.


---

# ACTUAL SOURCE CODE

## src/infra/db.py (first 800 lines)

```python
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
    IMAGE_TIER_PRIORITY,
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

```

## src/extraction/extraction_pipeline.py

```python
"""
Extraction Pipeline - End-to-end metric extraction orchestration.

This module orchestrates the complete extraction pipeline:
1. HTML Segmentation
2. Metric Classification
3. Value Extraction
4. Definition Extraction
5. Quality Scoring
6. Database Storage
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.infra.db import DatabaseAdapter

from .definition_extractor import DefinitionExtractor
from .html_segmenter import HTMLSegmenter
from .metric_classifier import MetricClassifier
from .models import (
    FilingMetricIncidence,
    MetricDefinition,
    MetricValue,
    SourceSegment,
)
from .quality_scorer import QualityScorer
from .segment_enricher import SegmentEnricher, cluster_goldmine_segments
from .value_extractor import ValueExtractor

if TYPE_CHECKING:
    from ..llm.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result of processing a single filing."""

    filing_id: int
    success: bool
    error: str | None = None
    num_segments: int = 0
    num_values: int = 0
    num_definitions: int = 0
    num_incidences: int = 0


class ExtractionPipeline:
    """
    Orchestrate the complete metric extraction pipeline.

    Pipeline stages:
    1. Segment HTML into source_segments
    2. Classify segments for metric content
    3. Extract numeric values from segments
    4. Extract definitions and methodologies
    5. Compute quality scores and incidence
    6. Write all results to database
    """

    def __init__(
        self, db: DatabaseAdapter, llm_client: Optional["OpenAIClient"] = None
    ):
        """
        Initialize the extraction pipeline.

        Args:
            db: Database adapter
            llm_client: Optional OpenAI client for LLM-enhanced extraction.
                       If provided, extractors will use LLM with rule-based fallback.
                       If not provided, only rule-based extraction will be used.
        """
        self.db = db
        self.llm_client = llm_client
        self.segmenter = HTMLSegmenter()
        self.classifier = MetricClassifier()
        self.enricher = SegmentEnricher()
        self.value_extractor = ValueExtractor(llm_client=llm_client)
        self.definition_extractor = DefinitionExtractor(llm_client=llm_client)
        self.quality_scorer = QualityScorer()

        if llm_client:
            logger.info("✓ Pipeline initialized with LLM-enhanced extraction and enrichment")
        else:
            logger.info("✓ Pipeline initialized with rule-based extraction and enrichment")

    def process_filing(self, filing_id: int) -> ExtractionResult:
        """
        Run full extraction pipeline for a single filing.

        Steps:
            1. Fetch filing metadata from database
            2. Segment HTML
            3. Classify segments
            4. Extract values
            5. Extract definitions
            6. Compute quality scores
            7. Write all to database in a transaction

        Args:
            filing_id: Database filing ID

        Returns:
            ExtractionResult with processing summary
        """
        logger.info(f"Processing filing {filing_id}")

        try:
            # Step 0: Fetch filing metadata
            filing = self._get_filing_metadata(filing_id)
            if not filing:
                return ExtractionResult(
                    filing_id=filing_id,
                    success=False,
                    error="Filing not found in database",
                )

            # Step 1: Segment HTML
            logger.info("  Stage 1: Segmenting HTML")
            segments = self.segmenter.segment_filing(
                filing_id=filing_id, html_path=filing["html_storage_path"]
            )

            if not segments:
                return ExtractionResult(
                    filing_id=filing_id,
                    success=False,
                    error="No segments extracted from HTML",
                )

            # Step 2: Classify segments
            logger.info(f"  Stage 2: Classifying {len(segments)} segments")
            classified_segments = self.classifier.classify_batch(segments)

            # Step 2b: Enrich segments with richness metadata
            logger.info(f"  Stage 2b: Enriching {len(classified_segments)} segments")
            self.enricher.enrich_batch(classified_segments)  # mutates in place

            # Step 2c: Tiered segment selection
            logger.info("  Stage 2c: Selecting segments via tiered prioritization")
            selected_segments = self._select_segments_tiered(classified_segments)

            # Log goldmine statistics
            goldmines = [s for s in selected_segments if (s.richness_score or 0) >= 6.0]
            clusters = cluster_goldmine_segments(goldmines) if goldmines else []
            logger.info(f"  Identified {len(goldmines)} goldmine segments in {len(clusters)} clusters")

            # Step 3: Extract values (from selected segments)
            logger.info(f"  Stage 3: Extracting values from {len(selected_segments)} segments")
            all_values = []
            for seg in selected_segments:
                values = self.value_extractor.extract_from_segment(
                    seg, company_id=filing["company_id"]
                )
                all_values.extend(values)

            # Step 4: Extract definitions (from selected segments)
            logger.info(f"  Stage 4: Extracting definitions from {len(selected_segments)} segments")
            definitions = self.definition_extractor.extract_definitions(
                selected_segments, company_id=filing["company_id"]
            )

            # Step 5: Compute quality scores (based on selected segments)
            logger.info("  Stage 5: Computing quality scores")
            incidences = self.quality_scorer.score_filing(
                filing_id=filing_id,
                company_id=filing["company_id"],
                segments=selected_segments,
                values=all_values,
                definitions=definitions,
            )

            # Step 6: Write to database
            logger.info("  Stage 6: Writing to database")
            self._write_results(
                filing_id, selected_segments, all_values, definitions, incidences
            )

            logger.info(f"✓ Successfully processed filing {filing_id}")
            logger.info(
                f"    Total segments: {len(classified_segments)}, Selected: {len(selected_segments)}, "
                + f"Goldmines: {len(goldmines)}, Values: {len(all_values)}, "
                + f"Definitions: {len(definitions)}, Incidences: {len(incidences)}"
            )

            return ExtractionResult(
                filing_id=filing_id,
                success=True,
                num_segments=len(selected_segments),
                num_values=len(all_values),
                num_definitions=len(definitions),
                num_incidences=len(incidences),
            )

        except (ValueError, KeyError) as e:
            # Data/validation errors - filing data is invalid or missing expected fields
            logger.error(
                f"✗ Data error processing filing {filing_id}: {e}", exc_info=True
            )
            return ExtractionResult(filing_id=filing_id, success=False, error=str(e))

        except OSError as e:
            # File system errors - HTML file not found or unreadable
            logger.error(
                f"✗ File error processing filing {filing_id}: {e}", exc_info=True
            )
            return ExtractionResult(filing_id=filing_id, success=False, error=str(e))

        except Exception as e:
            # Unexpected errors - log with full details for debugging
            logger.critical(
                f"✗ Unexpected error processing filing {filing_id}: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            return ExtractionResult(filing_id=filing_id, success=False, error=str(e))

    def process_batch(self, filing_ids: list[int]) -> dict[str, int]:
        """
        Process multiple filings.

        Args:
            filing_ids: List of filing IDs to process

        Returns:
            Statistics dictionary with counts
        """
        logger.info(f"Processing batch of {len(filing_ids)} filings")

        stats = {
            "total": len(filing_ids),
            "success": 0,
            "failed": 0,
            "total_segments": 0,
            "total_values": 0,
            "total_definitions": 0,
            "total_incidences": 0,
        }

        for i, filing_id in enumerate(filing_ids):
            logger.info(f"[{i+1}/{len(filing_ids)}] Processing filing {filing_id}")

            result = self.process_filing(filing_id)

            if result.success:
                stats["success"] += 1
                stats["total_segments"] += result.num_segments
                stats["total_values"] += result.num_values
                stats["total_definitions"] += result.num_definitions
                stats["total_incidences"] += result.num_incidences
            else:
                stats["failed"] += 1
                logger.error(f"  Failed: {result.error}")

        logger.info("")
        logger.info("=" * 80)
        logger.info("Batch Processing Summary")
        logger.info("=" * 80)
        logger.info(f"Total filings: {stats['total']}")
        logger.info(f"Successful: {stats['success']}")
        logger.info(f"Failed: {stats['failed']}")
        logger.info(f"Total segments: {stats['total_segments']}")
        logger.info(f"Total values: {stats['total_values']}")
        logger.info(f"Total definitions: {stats['total_definitions']}")
        logger.info(f"Total incidences: {stats['total_incidences']}")
        logger.info("=" * 80)

        return stats

    def _get_filing_metadata(self, filing_id: int) -> dict | None:
        """Fetch filing metadata from database."""
        result = self.db.query(
            """
            SELECT filing_id, company_id, cik, accession_number, html_storage_path
            FROM filings
            WHERE filing_id = %(filing_id)s
        """,
            {"filing_id": filing_id},
        )

        if not result:
            return None

        filing = result[0]

        # Check if HTML file exists
        if (
            not filing["html_storage_path"]
            or not Path(filing["html_storage_path"]).exists()
        ):
            logger.error(f"HTML file not found: {filing['html_storage_path']}")
            return None

        return filing

    def _select_segments_tiered(
        self, segments: list[SourceSegment]
    ) -> list[SourceSegment]:
        """
        Select segments using tiered prioritization.

        Tiers (processed in order, deduplicated):
        1. High richness (>= 6.0) - up to 30 segments
        2. Medium richness (4.0-6.0) - up to 40 segments
        3. Critical flags (definitions/methodologies) - remainder up to 80 total

        Args:
            segments: Enriched segments with richness_score populated

        Returns:
            Selected segments, deduplicated and sorted by richness
        """
        RICHNESS_THRESHOLD = 6.0
        MEDIUM_THRESHOLD = 4.0
        MAX_HIGH_RICHNESS = 30
        MAX_MEDIUM_RICHNESS = 40
        MAX_TOTAL = 80

        selected_ids: set[int] = set()  # Use object id for deduplication
        result: list[SourceSegment] = []

        # Tier 1: High richness (goldmines)
        high_richness = sorted(
            [s for s in segments if (s.richness_score or 0) >= RICHNESS_THRESHOLD],
            key=lambda s: s.richness_score or 0,
            reverse=True,
        )[:MAX_HIGH_RICHNESS]

        for seg in high_richness:
            if id(seg) not in selected_ids:
                result.append(seg)
                selected_ids.add(id(seg))

        high_count = len(result)

        # Tier 2: Medium richness (supporting context)
        medium_richness = sorted(
            [
                s
                for s in segments
                if MEDIUM_THRESHOLD <= (s.richness_score or 0) < RICHNESS_THRESHOLD
            ],
            key=lambda s: s.richness_score or 0,
            reverse=True,
        )[:MAX_MEDIUM_RICHNESS]

        for seg in medium_richness:
            if id(seg) not in selected_ids:
                result.append(seg)
                selected_ids.add(id(seg))

        # NEW: Direct Hit Tier (Specific matches with lower richness)
        # Allows short segments that are highly specific (e.g. "Churn rate was 5%")
        # Threshold: 3.0 (Lower than medium)
        DIRECT_HIT_THRESHOLD = 3.0
        direct_hits = [
            s for s in segments
            if (s.richness_score or 0) >= DIRECT_HIT_THRESHOLD
            and (s.richness_score or 0) < MEDIUM_THRESHOLD
            and s.candidate_metric_ids
            and len(s.candidate_metric_ids) == 1 # Very specific
            and s.contains_numeric_disclosure_flag # Must have numbers
        ]

        for seg in direct_hits:
            if len(result) >= MAX_TOTAL:
                break
            if id(seg) not in selected_ids:
                result.append(seg)
                selected_ids.add(id(seg))

        medium_count = len(result) - high_count

        # Tier 3: Critical flags (definitions/methodologies)
        critical = [
            s
            for s in segments
            if (s.contains_definition_flag or s.contains_methodology_flag)
            and id(s) not in selected_ids
        ]

        critical_count = 0
        for seg in critical:
            if len(result) >= MAX_TOTAL:
                break
            result.append(seg)
            selected_ids.add(id(seg))
            critical_count += 1

        logger.info(
            f"  Selected: {high_count} high-richness, {medium_count} medium-richness, "
            f"{critical_count} critical (total: {len(result)})"
        )

        return result

    def _write_results(
        self,
        filing_id: int,
        segments: list[SourceSegment],
        values: list[MetricValue],
        definitions: list[MetricDefinition],
        incidences: list[FilingMetricIncidence],
    ):
        """
        Write all extraction results to database in a transaction.

        Args:
            filing_id: Filing ID
            segments: Source segments
            values: Metric values
            definitions: Metric definitions
            incidences: Filing-metric incidences
        """
        # Use database transaction for atomicity
        # If any insert fails, everything rolls back

        cleanup_sql = [
            "DELETE FROM filing_metric_incidence WHERE filing_id = %(filing_id)s",
            "DELETE FROM metric_definitions WHERE filing_id = %(filing_id)s",
            "DELETE FROM metric_values WHERE filing_id = %(filing_id)s",
            "DELETE FROM source_segments WHERE filing_id = %(filing_id)s",
        ]

        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Remove any prior extraction artifacts for this filing so re-runs are idempotent.
                for statement in cleanup_sql:
                    cur.execute(statement, {"filing_id": filing_id})

                # Insert source segments
                segment_id_map: dict[int, int] = {}
                for seg in segments:
                    cur.execute(
                        """
                        INSERT INTO source_segments (
                            filing_id, segment_type, section_path, section_heading,
                            sequence_index, raw_text, raw_html,
                            candidate_metric_ids,
                            contains_definition_flag,
                            contains_methodology_flag,
                            contains_numeric_disclosure_flag,
                            classifier_confidence,
                            metric_density,
                            distinct_metric_count,
                            contains_temporal_trend,
                            contains_cohort_breakdown,
                            image_count,
                            richness_score
                        ) VALUES (
                            %(filing_id)s, %(segment_type)s, %(section_path)s, %(section_heading)s,
                            %(sequence_index)s, %(raw_text)s, %(raw_html)s,
                            %(candidate_metric_ids)s,
                            %(contains_definition_flag)s,
                            %(contains_methodology_flag)s,
                            %(contains_numeric_disclosure_flag)s,
                            %(classifier_confidence)s,
                            %(metric_density)s,
                            %(distinct_metric_count)s,
                            %(contains_temporal_trend)s,
                            %(contains_cohort_breakdown)s,
                            %(image_count)s,
                            %(richness_score)s
                        )
                        RETURNING source_segment_id
                        """,
                        seg.to_dict(),
                    )
                    result = cur.fetchone()
                    if result:
                        db_id = result["source_segment_id"]
                        segment_id_map[seg.sequence_index] = db_id
                        seg.source_segment_id = db_id

                # Update values with actual segment IDs
                valid_values: list[MetricValue] = []
                for val in values:
                    if val.source_segment_id in segment_id_map:
                        val.source_segment_id = segment_id_map[val.source_segment_id]
                        valid_values.append(val)
                    else:
                        logger.warning(
                            "Skipping metric value for filing %s because segment %s was not persisted",
                            filing_id,
                            val.source_segment_id,
                        )

                # Insert metric values
                for val in valid_values:
                    cur.execute(
                        """
                        INSERT INTO metric_values (
                            filing_id, company_id, metric_id, source_segment_id,
                            source_type, extraction_method,
                            value_numeric, value_text, unit, currency,
                            period_start, period_end, period_type,
                            cohort_type, cohort_bucket_raw, cohort_bucket_normalized,
                            segment_dimension, segment_value,
                            qa_status, qa_notes, alignment_flag
                        ) VALUES (
                            %(filing_id)s, %(company_id)s, %(metric_id)s, %(source_segment_id)s,
                            %(source_type)s, %(extraction_method)s,
                            %(value_numeric)s, %(value_text)s, %(unit)s, %(currency)s,
                            %(period_start)s, %(period_end)s, %(period_type)s,
                            %(cohort_type)s, %(cohort_bucket_raw)s, %(cohort_bucket_normalized)s,
                            %(segment_dimension)s, %(segment_value)s,
                            %(qa_status)s, %(qa_notes)s, %(alignment_flag)s
                        )
                        """,
                        val.to_dict(),
                    )

                # Update definitions with actual segment IDs
                valid_definitions: list[MetricDefinition] = []
                for defn in definitions:
                    if (
                        defn.definition_segment_id is not None
                        and defn.definition_segment_id in segment_id_map
                    ):
                        defn.definition_segment_id = segment_id_map[
                            defn.definition_segment_id
                        ]

                    if (
                        defn.methodology_segment_id is not None
                        and defn.methodology_segment_id in segment_id_map
                    ):
                        defn.methodology_segment_id = segment_id_map[
                            defn.methodology_segment_id
                        ]
                    valid_definitions.append(defn)

                # Insert metric definitions
                for defn in valid_definitions:
                    cur.execute(
                        """
                        INSERT INTO metric_definitions (
                            filing_id, company_id, metric_id,
                            definition_version_in_filing,
                            definition_text_normalized, methodology_text_normalized,
                            definition_raw_text, methodology_raw_text,
                            definition_segment_id, methodology_segment_id,
                            alignment_flag, alignment_notes
                        ) VALUES (
                            %(filing_id)s, %(company_id)s, %(metric_id)s,
                            %(definition_version_in_filing)s,
                            %(definition_text_normalized)s, %(methodology_text_normalized)s,
                            %(definition_raw_text)s, %(methodology_raw_text)s,
                            %(definition_segment_id)s, %(methodology_segment_id)s,
                            %(alignment_flag)s, %(alignment_notes)s
                        )
                        """,
                        defn.to_dict(),
                    )

                # Update incidences with actual segment IDs
                for inc in incidences:
                    if (
                        inc.primary_definition_segment_id is not None
                        and inc.primary_definition_segment_id in segment_id_map
                    ):
                        inc.primary_definition_segment_id = segment_id_map[
                            inc.primary_definition_segment_id
                        ]
                    elif inc.primary_definition_segment_id is not None:
                        # Segment not in map, set to None to avoid FK violation
                        inc.primary_definition_segment_id = None

                    if (
                        inc.primary_methodology_segment_id is not None
                        and inc.primary_methodology_segment_id in segment_id_map
                    ):
                        inc.primary_methodology_segment_id = segment_id_map[
                            inc.primary_methodology_segment_id
                        ]
                    elif inc.primary_methodology_segment_id is not None:
                        # Segment not in map, set to None to avoid FK violation
                        inc.primary_methodology_segment_id = None

                # Insert filing-metric incidences
                for inc in incidences:
                    cur.execute(
                        """
                        INSERT INTO filing_metric_incidence (
                            filing_id, company_id, metric_id,
                            metric_disclosed_flag,
                            num_numeric_segments, num_definition_segments, num_methodology_segments,
                            primary_definition_segment_id, primary_methodology_segment_id,
                            quality_overall_score, quality_definition_score,
                            quality_methodology_score, quality_completeness_score,
                            quality_comparability_score,
                            alignment_flag, quality_notes,
                            has_cohort_breakdown_flag, has_tenure_breakdown_flag,
                            has_acquisition_cohort_flag
                        ) VALUES (
                            %(filing_id)s, %(company_id)s, %(metric_id)s,
                            %(metric_disclosed_flag)s,
                            %(num_numeric_segments)s, %(num_definition_segments)s, %(num_methodology_segments)s,
                            %(primary_definition_segment_id)s, %(primary_methodology_segment_id)s,
                            %(quality_overall_score)s, %(quality_definition_score)s,
                            %(quality_methodology_score)s, %(quality_completeness_score)s,
                            %(quality_comparability_score)s,
                            %(alignment_flag)s, %(quality_notes)s,
                            %(has_cohort_breakdown_flag)s, %(has_tenure_breakdown_flag)s,
                            %(has_acquisition_cohort_flag)s
                        )
                        """,
                        inc.to_dict(),
                    )

        logger.info(f"    Inserted {len(segments)} source segments")
        logger.info(f"    Inserted {len(valid_values)} metric values")
        logger.info(f"    Inserted {len(valid_definitions)} metric definitions")
        logger.info(f"    Inserted {len(incidences)} filing-metric incidences")
```
