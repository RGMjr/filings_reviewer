# Database Migration Helper Skill

**Purpose:** Generate PostgreSQL migration files following project conventions and create corresponding db.py adapter methods with tests.

**When to use:**
- Adding new tables to the database schema
- Adding columns to existing tables
- Creating indexes, constraints, or views
- Need matching db.py methods for new tables
- Need integration tests for database operations

**When NOT to use:**
- Simple data manipulation (INSERT/UPDATE queries)
- One-off analytical queries
- Schema changes without persistence needs
- Non-PostgreSQL databases

---

## Database Migration Helper Methodology

This skill generates production-ready database migrations following the SEC Filings Reviewer project's strict conventions for schema design, naming, and testing.

### Project Schema Conventions

**Primary Keys:**
- Always `{table_name}_id BIGSERIAL PRIMARY KEY`
- Example: `candidate_id BIGSERIAL PRIMARY KEY` for `review_candidates` table

**Foreign Keys:**
- Format: `{reference}_id BIGINT NOT NULL REFERENCES {table}({pk})`
- Use `ON DELETE CASCADE` for dependent data (child records should be deleted)
- Use `ON DELETE SET NULL` for optional references (preserve records but clear FK)
- Example: `filing_id BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE`

**Timestamps:**
- Always include: `created_at TIMESTAMPTZ DEFAULT now()`
- For mutable data: `updated_at TIMESTAMPTZ` (requires trigger)
- Never use `TIMESTAMP` without `TZ`

**JSONB Columns:**
- Use for semi-structured data (features, metadata, config)
- Always add GIN index: `CREATE INDEX idx_{table}_{column} ON {table} USING GIN ({column});`
- Example: `features JSONB` with `CREATE INDEX idx_candidates_features ON review_candidates USING GIN (features);`

**Naming Conventions:**
- Tables: `snake_case`, plural (e.g., `review_candidates`, `learned_patterns`)
- Columns: `snake_case` (e.g., `candidate_id`, `created_at`)
- Indexes: `idx_{table}_{columns}` (e.g., `idx_candidates_filing`, `idx_decisions_metric`)
- Constraints: `{table}_{column}_{type}` or inline CHECK constraints
- Views: `v_{descriptive_name}` (e.g., `v_review_progress_by_filing`)

**CHECK Constraints:**
- Use for enum-like columns (status, types, categories)
- Format: `CONSTRAINT check_{column} CHECK ({column} IN ('val1', 'val2', ...))`
- Example: `CONSTRAINT check_decision CHECK (decision IN ('accept', 'reject', 'reclassify'))`

**Indexes:**
- B-tree (default) for foreign keys: `CREATE INDEX idx_candidates_filing ON review_candidates(filing_id);`
- GIN for JSONB: `CREATE INDEX idx_candidates_features ON review_candidates USING GIN (features);`
- Partial indexes for common filters: `CREATE INDEX idx_candidates_pending ON review_candidates(review_status) WHERE review_status = 'pending';`
- Composite indexes for multi-column queries: `CREATE INDEX idx_filings_scope_status ON filings(is_in_scope_phase1, processing_status, filing_date);`

**Comments:**
- Add table comments: `COMMENT ON TABLE {table} IS 'Description';`
- Add column comments for non-obvious fields: `COMMENT ON COLUMN {table}.{column} IS 'Description';`

**Migration File Numbering:**
- Not strictly sequential (gaps allowed): 01, 02, 03, 04, 05, 07 (skipped 06)
- Format: `{NN}_create_{name}.sql` or `{NN}_add_{name}.sql`
- Scan `sql/` directory to find next available number

**Migration File Structure:**
```sql
-- ============================================================================
-- Migration: {Title}
-- Purpose: {1-2 sentence description}
-- Date: YYYY-MM-DD
-- Based on: {reference doc if applicable}
-- ============================================================================

-- Drop tables if they exist (for development)
DROP TABLE IF EXISTS {dependent_table} CASCADE;
DROP TABLE IF EXISTS {parent_table} CASCADE;

-- ============================================================================
-- TABLE: {table_name}
-- ============================================================================
-- Grain: One row per {entity description}
-- Purpose: {What this table represents and why it exists}

CREATE TABLE {table_name} (
    -- Primary key
    {table}_id BIGSERIAL PRIMARY KEY,

    -- Foreign keys
    {ref}_id BIGINT NOT NULL REFERENCES {ref_table}({ref_pk}) ON DELETE CASCADE,

    -- Data columns
    {column_name} {type} NOT NULL,
    {optional_column} {type},

    -- JSONB for semi-structured data
    {json_column} JSONB,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ,

    -- Constraints
    CONSTRAINT check_{column} CHECK ({column} IN ('val1', 'val2'))
);

-- Indices
CREATE INDEX idx_{table}_{fk} ON {table}({fk_column});
CREATE INDEX idx_{table}_{json} ON {table} USING GIN ({json_column});
CREATE INDEX idx_{table}_{partial} ON {table}({column}) WHERE {condition};

-- Comments
COMMENT ON TABLE {table} IS 'Description';
COMMENT ON COLUMN {table}.{column} IS 'Description';

-- ============================================================================
-- VIEWS for analysis
-- ============================================================================

CREATE OR REPLACE VIEW v_{view_name} AS
SELECT ...;

-- ============================================================================
-- TRIGGERS for updated_at
-- ============================================================================

CREATE TRIGGER trigger_{table}_updated_at
    BEFORE UPDATE ON {table}
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

---

## Skill Instructions

When this skill is invoked, you should:

### Step 1: Validate Schema Design

1. **Check table name:**
   - Is it plural? (candidates, not candidate)
   - Is it snake_case? (review_candidates, not ReviewCandidates)

2. **Check primary key:**
   - Is it `{table}_id BIGSERIAL PRIMARY KEY`?
   - Example: `candidate_id` for `review_candidates`

3. **Check foreign keys:**
   - Do referenced tables exist?
   - Is `ON DELETE` behavior specified (CASCADE or SET NULL)?
   - Are FKs marked `NOT NULL` where appropriate?

4. **Check for timestamps:**
   - Does it have `created_at TIMESTAMPTZ DEFAULT now()`?
   - If mutable, does it have `updated_at TIMESTAMPTZ`?

5. **Check JSONB columns:**
   - Are GIN indexes planned for JSONB columns?

6. **Recommend indexes:**
   - FK columns should have B-tree indexes
   - JSONB columns should have GIN indexes
   - Common WHERE clauses should have partial indexes

### Step 2: Generate Migration File

1. **Determine migration number:**
   - Scan `sql/` directory for existing migrations
   - Find highest number and add 1
   - Example: If highest is `07_`, next is `08_`

2. **Create migration file:**
   - Filename: `sql/{NN}_create_{name}.sql` or `sql/{NN}_add_{name}.sql`
   - Use "create" for new tables, "add" for modifications

3. **Write migration content:**
   - Header comment block (purpose, date, references)
   - DROP IF EXISTS statements (in reverse dependency order)
   - CREATE TABLE statements with all conventions
   - CREATE INDEX statements
   - COMMENT statements
   - CREATE VIEW statements (if applicable)
   - CREATE TRIGGER statements (if has `updated_at`)

### Step 3: Generate Rollback File (Optional)

1. **Create rollback file:**
   - Filename: `sql/{NN}_rollback_{name}.sql`
   - Contains DROP statements in reverse order

2. **Rollback content:**
   ```sql
   -- Rollback for {NN}_create_{name}.sql
   DROP VIEW IF EXISTS v_{view_name};
   DROP TABLE IF EXISTS {child_table} CASCADE;
   DROP TABLE IF EXISTS {parent_table} CASCADE;
   ```

### Step 4: Generate db.py Methods

For each new table, generate methods in `src/infra/db.py`:

1. **Insert method:**
   - Name: `insert_{table_singular}()`
   - Parameters: All columns (excluding auto-generated IDs, defaults)
   - Use `RETURNING {table}_id` clause
   - Return: `int` (the inserted ID)
   - Include validation for enum fields
   - Include docstring with Args, Returns

2. **Get by ID method:**
   - Name: `get_{table_singular}()`
   - Parameters: `{table}_id: int`
   - Return: `Optional[Dict]`
   - Use `fetchone()`

3. **Get all/query method:**
   - Name: `get_{table_plural}()` or `get_{table_plural}_for_{parent}()`
   - Parameters: Filter fields, `limit`, `offset` for pagination
   - Return: `List[Dict]`
   - Use parameterized queries

4. **Update method (if mutable):**
   - Name: `update_{table_singular}()`
   - Parameters: `{table}_id`, fields to update
   - Return: `bool` (success indicator)
   - Use WHERE clause on PK

5. **Delete method (if applicable):**
   - Name: `delete_{table_singular}()`
   - Parameters: `{table}_id: int`
   - Return: `bool` (success indicator)

**Method Template:**
```python
def insert_{table}(
    self,
    {required_param}: {type},
    {optional_param}: Optional[{type}] = None,
) -> int:
    """
    Insert a new {table singular} record.

    Args:
        {param}: Description
        {optional_param}: Description (optional)

    Returns:
        The {table}_id of the inserted record

    Raises:
        ValidationError: If enum field has invalid value
        psycopg.errors.ForeignKeyViolation: If FK reference doesn't exist
        psycopg.errors.UniqueViolation: If unique constraint violated

    Example:
        >>> db = DatabaseAdapter(connection_string)
        >>> {table}_id = db.insert_{table}(
        ...     {param}=value,
        ...     {optional_param}=optional_value
        ... )
    """
    # Validate enum fields
    if {enum_field} is not None:
        validate_enum({enum_field}, {ENUM_CONSTANTS}, "{enum_field}")

    sql = \"\"\"
        INSERT INTO {table_plural} (
            {column1}, {column2}, {column3}
        ) VALUES (
            %({column1})s, %({column2})s, %({column3})s
        )
        RETURNING {table}_id
    \"\"\"

    params = {
        "{column1}": {param1},
        "{column2}": {param2},
        "{column3}": {param3},
    }

    with self.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            result = cur.fetchone()
            if result:
                return result["{table}_id"]
            raise RuntimeError("Insert failed to return ID")
```

### Step 5: Generate Integration Tests

Create `tests/integration/test_db_{table}.py`:

1. **Test class structure:**
   ```python
   """
   Integration tests for DatabaseAdapter {table} table methods.

   Tests CRUD operations on {table_plural} table.

   Requires:
   - TEST_DATABASE_URL environment variable set
   - Schema applied (sql/{NN}_create_{name}.sql)
   """

   import pytest
   from decimal import Decimal

   from src.infra.validation import ValidationError
   from tests.integration.conftest import (
       create_test_company,
       create_test_company_and_filing,
   )


   class Test{TableCamelCase}Methods:
       """Tests for {table_plural} table operations."""

       def test_insert_{table}_minimal(self, clean_db):
           """Test inserting {table singular} with minimal required fields."""
           # Arrange - setup test data
           # Act - call method
           # Assert - verify results

       def test_insert_{table}_full(self, clean_db):
           """Test inserting {table singular} with all optional fields."""
           # Test with JSONB, enums, etc.

       def test_get_{table}_by_id(self, clean_db):
           """Test retrieving {table singular} by ID."""

       def test_get_{table}_not_found(self, clean_db):
           """Test retrieving non-existent {table singular} returns None."""

       def test_constraint_{constraint_name}(self, clean_db):
           """Test {constraint} constraint enforcement."""
           # Use pytest.raises for constraint violations

       def test_foreign_key_cascade(self, clean_db):
           """Test ON DELETE CASCADE behavior."""
           # Verify child records deleted when parent deleted
   ```

2. **Test fixtures:**
   - Use `clean_db` fixture (provides DatabaseAdapter with test DB)
   - Use helper functions from `conftest.py` (create_test_company, etc.)
   - Create specific helpers for complex setups

3. **Test coverage:**
   - Happy path (minimal fields, full fields)
   - Get operations (found, not found)
   - Constraints (FK violations, CHECK violations, UNIQUE violations)
   - Cascades (ON DELETE CASCADE, ON DELETE SET NULL)
   - Edge cases (empty results, pagination, filtering)

4. **Constraint violation tests:**
   ```python
   def test_invalid_enum_value(self, clean_db):
       """Test CHECK constraint on enum field."""
       with pytest.raises(psycopg.errors.CheckViolation):
           clean_db.insert_{table}(
               {field}="invalid_value",  # Not in CHECK constraint
               ...
           )

   def test_foreign_key_violation(self, clean_db):
       """Test FK constraint enforcement."""
       with pytest.raises(psycopg.errors.ForeignKeyViolation):
           clean_db.insert_{table}(
               {fk_field}=999999,  # Non-existent FK
               ...
           )
   ```

---

## Templates

### Migration File Template

```sql
-- ============================================================================
-- Migration: Create {Feature} Schema
-- Purpose: {1-2 sentence description of what this migration does}
-- Date: {YYYY-MM-DD}
-- Based on: {docs reference if applicable}
-- ============================================================================

-- Drop tables if they exist (for development)
DROP TABLE IF EXISTS {child_table} CASCADE;
DROP TABLE IF EXISTS {parent_table} CASCADE;

-- ============================================================================
-- TABLE: {table_name}
-- ============================================================================
-- Grain: One row per {entity}
-- Purpose: {What this table stores and why}

CREATE TABLE {table_name} (
    -- Primary key
    {table}_id BIGSERIAL PRIMARY KEY,

    -- Foreign keys
    {parent}_id BIGINT NOT NULL REFERENCES {parent_table}({parent}_id) ON DELETE CASCADE,
    {optional_parent}_id BIGINT REFERENCES {optional_table}({optional}_id) ON DELETE SET NULL,

    -- Data columns
    {required_column} {TYPE} NOT NULL,
    {optional_column} {TYPE},
    {enum_column} TEXT NOT NULL,

    -- JSONB for semi-structured data
    {metadata_column} JSONB,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ,

    -- Constraints
    CONSTRAINT check_{enum_column} CHECK ({enum_column} IN ('value1', 'value2', 'value3')),
    CONSTRAINT check_{numeric_range} CHECK ({column} >= 0 AND {column} <= 1)
);

-- Indices
CREATE INDEX idx_{table}_{parent} ON {table_name}({parent}_id);
CREATE INDEX idx_{table}_{column} ON {table_name}({column});
CREATE INDEX idx_{table}_{jsonb} ON {table_name} USING GIN ({metadata_column});
CREATE INDEX idx_{table}_{partial} ON {table_name}({column}) WHERE {condition};

-- Comments
COMMENT ON TABLE {table_name} IS '{Description of table purpose}';
COMMENT ON COLUMN {table_name}.{column} IS '{Description of what column stores}';

-- ============================================================================
-- VIEWS for analysis (if applicable)
-- ============================================================================

CREATE OR REPLACE VIEW v_{view_name} AS
SELECT
    {table}.{column},
    COUNT(*) as count,
    ...
FROM {table_name} {table}
JOIN {parent_table} {parent} ON {table}.{parent}_id = {parent}.{parent}_id
GROUP BY {table}.{column}
ORDER BY count DESC;

COMMENT ON VIEW v_{view_name} IS '{Description of what view provides}';

-- ============================================================================
-- TRIGGERS for updated_at (if table has updated_at column)
-- ============================================================================

-- Note: Assumes update_updated_at_column() function exists (from prior migration)
-- If not, add function definition first

CREATE TRIGGER trigger_{table}_updated_at
    BEFORE UPDATE ON {table_name}
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

### db.py Insert Method Template

```python
def insert_{table}(
    self,
    {required_field}: {type},
    {required_field2}: {type},
    {optional_field}: Optional[{type}] = None,
    {jsonb_field}: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Insert a new {table singular} record.

    Args:
        {required_field}: {Description}
        {required_field2}: {Description}
        {optional_field}: {Description} (optional)
        {jsonb_field}: {Description of JSON structure} (optional)

    Returns:
        The {table}_id of the inserted record

    Raises:
        ValidationError: If {enum_field} is not a valid {enum_type}
        psycopg.errors.ForeignKeyViolation: If {fk_field} references non-existent {parent}
        psycopg.errors.UniqueViolation: If {unique_field} already exists
        psycopg.errors.CheckViolation: If {check_field} violates CHECK constraint

    Example:
        >>> db = DatabaseAdapter(connection_string)
        >>> {table}_id = db.insert_{table}(
        ...     {required_field}={example_value},
        ...     {required_field2}={example_value2},
        ...     {optional_field}={example_optional}
        ... )
        >>> print({table}_id)
        42
    """
    # Validate enum fields before query
    if {enum_field} is not None:
        validate_enum({enum_field}, {ENUM_CONSTANTS}, "{enum_field}")

    # Validate numeric ranges (if not in CHECK constraint)
    if {numeric_field} is not None:
        validate_score({numeric_field}, 0.0, 1.0, "{numeric_field}")

    sql = """
        INSERT INTO {table_plural} (
            {column1},
            {column2},
            {column3},
            {jsonb_column}
        ) VALUES (
            %({column1})s,
            %({column2})s,
            %({column3})s,
            %({jsonb_column})s
        )
        RETURNING {table}_id
    """

    params = {
        "{column1}": {param1},
        "{column2}": {param2},
        "{column3}": {param3},
        "{jsonb_column}": json.dumps({jsonb_field}) if {jsonb_field} else None,
    }

    with self.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            result = cur.fetchone()
            if result:
                return result["{table}_id"]
            raise RuntimeError("Insert failed to return ID")
```

### db.py Query Method Template

```python
def get_{table_plural}_for_{parent}(
    self,
    {parent}_id: int,
    {filter_field}: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[Dict]:
    """
    Get {table plural} for a specific {parent}.

    Args:
        {parent}_id: {Parent} to get {table plural} for
        {filter_field}: Optional filter by {filter description}
        limit: Maximum number to return
        offset: Number to skip (for pagination)

    Returns:
        List of {table singular} records with all columns

    Raises:
        ValidationError: If {filter_field} is provided but not valid

    Example:
        >>> db = DatabaseAdapter(connection_string)
        >>> # Get all {table plural} for {parent}
        >>> {table_var} = db.get_{table_plural}_for_{parent}({parent}_id=123)
        >>> # Get filtered with pagination
        >>> {table_var} = db.get_{table_plural}_for_{parent}(
        ...     {parent}_id=123,
        ...     {filter_field}='active',
        ...     limit=50,
        ...     offset=0
        ... )
    """
    # Validate filter field if provided
    if {filter_field} is not None:
        validate_enum({filter_field}, {ENUM_CONSTANTS}, "{filter_field}")

    sql = """
        SELECT * FROM {table_plural}
        WHERE {parent}_id = %({parent}_id)s
    """
    params: Dict[str, Any] = {"{parent}_id": {parent}_id}

    if {filter_field}:
        sql += " AND {filter_column} = %({filter_field})s"
        params["{filter_field}"] = {filter_field}

    sql += " ORDER BY {default_sort_column}"

    if limit:
        sql += " LIMIT %(limit)s OFFSET %(offset)s"
        params["limit"] = limit
        params["offset"] = offset

    return self.query(sql, params)
```

### Integration Test Template

```python
"""
Integration tests for DatabaseAdapter {table} table methods.

Tests CRUD operations on {table_plural} table.

Requires:
- TEST_DATABASE_URL environment variable set
- Schema applied (sql/{NN}_create_{name}.sql)
"""

import pytest
from decimal import Decimal
from typing import Dict

import psycopg.errors

from src.infra.validation import ValidationError
from tests.integration.conftest import (
    create_test_company,
    create_test_company_and_filing,
)


class Test{TableCamelCase}Methods:
    """Tests for {table_plural} table operations."""

    def test_insert_{table}_minimal(self, clean_db):
        """Test inserting {table singular} with minimal required fields."""
        # Arrange
        {parent}_id = create_test_{parent}(clean_db)

        # Act
        {table}_id = clean_db.insert_{table}(
            {parent}_id={parent}_id,
            {required_field1}={value1},
            {required_field2}={value2},
        )

        # Assert
        assert {table}_id > 0

        # Verify retrieval
        {table} = clean_db.get_{table}({table}_id)
        assert {table} is not None
        assert {table}["{parent}_id"] == {parent}_id
        assert {table}["{required_field1}"] == {value1}
        assert {table}["{status_field}"] == "{default_status}"

    def test_insert_{table}_full(self, clean_db):
        """Test inserting {table singular} with all optional fields."""
        # Arrange
        {parent}_id = create_test_{parent}(clean_db)
        {jsonb_data} = {
            "key1": "value1",
            "key2": 123,
            "nested": {"key": "value"},
        }

        # Act
        {table}_id = clean_db.insert_{table}(
            {parent}_id={parent}_id,
            {required_field}={required_value},
            {optional_field}={optional_value},
            {jsonb_field}={jsonb_data},
        )

        # Assert
        assert {table}_id > 0

        {table} = clean_db.get_{table}({table}_id)
        assert {table}["{optional_field}"] == {optional_value}
        assert {table}["{jsonb_field}"]["key1"] == "value1"
        assert {table}["{jsonb_field}"]["nested"]["key"] == "value"

    def test_get_{table}_by_id(self, clean_db):
        """Test retrieving {table singular} by ID."""
        # Arrange
        {parent}_id = create_test_{parent}(clean_db)
        {table}_id = clean_db.insert_{table}(
            {parent}_id={parent}_id,
            {field}={value},
        )

        # Act
        {table} = clean_db.get_{table}({table}_id)

        # Assert
        assert {table} is not None
        assert {table}["{table}_id"] == {table}_id
        assert {table}["{parent}_id"] == {parent}_id

    def test_get_{table}_not_found(self, clean_db):
        """Test retrieving non-existent {table singular} returns None."""
        # Act
        {table} = clean_db.get_{table}(999999)

        # Assert
        assert {table} is None

    def test_get_{table_plural}_for_{parent}(self, clean_db):
        """Test retrieving multiple {table plural} for a {parent}."""
        # Arrange
        {parent}_id = create_test_{parent}(clean_db)

        # Insert multiple {table plural}
        {table}_ids = []
        for i in range(5):
            {table}_id = clean_db.insert_{table}(
                {parent}_id={parent}_id,
                {field}=f"{value_prefix}{i}",
            )
            {table}_ids.append({table}_id)

        # Act
        {table_plural} = clean_db.get_{table_plural}_for_{parent}({parent}_id)

        # Assert
        assert len({table_plural}) == 5

        # Test with limit
        limited = clean_db.get_{table_plural}_for_{parent}({parent}_id, limit=3)
        assert len(limited) == 3

    def test_constraint_check_{enum_field}(self, clean_db):
        """Test CHECK constraint on {enum_field} field."""
        # Arrange
        {parent}_id = create_test_{parent}(clean_db)

        # Act & Assert
        with pytest.raises(psycopg.errors.CheckViolation):
            clean_db.insert_{table}(
                {parent}_id={parent}_id,
                {enum_field}="invalid_value",  # Not in CHECK constraint
                {other_field}={value},
            )

    def test_constraint_foreign_key_{parent}(self, clean_db):
        """Test foreign key constraint on {parent}_id."""
        # Act & Assert
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            clean_db.insert_{table}(
                {parent}_id=999999,  # Non-existent {parent}
                {field}={value},
            )

    def test_cascade_delete_{parent}(self, clean_db):
        """Test ON DELETE CASCADE behavior when {parent} is deleted."""
        # Arrange
        {parent}_id = create_test_{parent}(clean_db)
        {table}_id = clean_db.insert_{table}(
            {parent}_id={parent}_id,
            {field}={value},
        )

        # Verify {table} exists
        assert clean_db.get_{table}({table}_id) is not None

        # Act - Delete parent
        clean_db.delete_{parent}({parent}_id)

        # Assert - Child should be cascade deleted
        assert clean_db.get_{table}({table}_id) is None
```

---

## Examples

### Example 1: Simple Lookup Table

**User Request:**
```
Use database-migration-helper skill to create:

Table: metric_categories
Columns:
- category_id (PK)
- category_name (TEXT NOT NULL UNIQUE)
- description (TEXT)
- created_at (TIMESTAMPTZ)

Include basic CRUD methods and tests.
```

**Claude Response:**

I'll generate a migration for the `metric_categories` lookup table.

**Migration file: `sql/08_create_metric_categories.sql`**

```sql
-- ============================================================================
-- Migration: Create Metric Categories Table
-- Purpose: Lookup table for metric category taxonomy
-- Date: 2025-12-11
-- ============================================================================

DROP TABLE IF EXISTS metric_categories CASCADE;

-- ============================================================================
-- TABLE: metric_categories
-- ============================================================================
-- Grain: One row per metric category
-- Purpose: Categorize metrics for reporting and analysis

CREATE TABLE metric_categories (
    -- Primary key
    category_id BIGSERIAL PRIMARY KEY,

    -- Data columns
    category_name TEXT NOT NULL UNIQUE,
    description TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Indices
CREATE INDEX idx_metric_categories_name ON metric_categories(category_name);

-- Comments
COMMENT ON TABLE metric_categories IS 'Lookup table for metric category taxonomy';
COMMENT ON COLUMN metric_categories.category_name IS 'Unique category name (e.g., "Growth", "Retention")';
```

**db.py methods:**

```python
def insert_metric_category(
    self,
    category_name: str,
    description: Optional[str] = None,
) -> int:
    """
    Insert a new metric category.

    Args:
        category_name: Unique category name
        description: Optional description of the category

    Returns:
        The category_id of the inserted record

    Raises:
        psycopg.errors.UniqueViolation: If category_name already exists

    Example:
        >>> db = DatabaseAdapter(connection_string)
        >>> category_id = db.insert_metric_category(
        ...     category_name="Growth Metrics",
        ...     description="Metrics measuring company growth"
        ... )
    """
    sql = """
        INSERT INTO metric_categories (category_name, description)
        VALUES (%(category_name)s, %(description)s)
        RETURNING category_id
    """
    params = {
        "category_name": category_name,
        "description": description,
    }

    with self.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            result = cur.fetchone()
            if result:
                return result["category_id"]
            raise RuntimeError("Insert failed to return ID")

def get_metric_category(self, category_id: int) -> Optional[Dict]:
    """Get a metric category by ID."""
    sql = "SELECT * FROM metric_categories WHERE category_id = %(category_id)s"
    result = self.query(sql, {"category_id": category_id})
    return result[0] if result else None

def get_all_metric_categories(self) -> List[Dict]:
    """Get all metric categories ordered by name."""
    sql = "SELECT * FROM metric_categories ORDER BY category_name"
    return self.query(sql, {})
```

**Test file: `tests/integration/test_db_metric_categories.py`**

```python
"""Integration tests for metric_categories table methods."""

import pytest
import psycopg.errors


class TestMetricCategoriesMethods:
    """Tests for metric_categories table operations."""

    def test_insert_metric_category(self, clean_db):
        """Test inserting a metric category."""
        category_id = clean_db.insert_metric_category(
            category_name="Growth Metrics",
            description="Metrics measuring company growth",
        )

        assert category_id > 0

        category = clean_db.get_metric_category(category_id)
        assert category["category_name"] == "Growth Metrics"
        assert category["description"] == "Metrics measuring company growth"

    def test_unique_category_name(self, clean_db):
        """Test UNIQUE constraint on category_name."""
        clean_db.insert_metric_category(category_name="Growth")

        with pytest.raises(psycopg.errors.UniqueViolation):
            clean_db.insert_metric_category(category_name="Growth")

    def test_get_all_categories(self, clean_db):
        """Test retrieving all categories."""
        clean_db.insert_metric_category(category_name="Growth")
        clean_db.insert_metric_category(category_name="Retention")

        categories = clean_db.get_all_metric_categories()
        assert len(categories) >= 2
        assert categories[0]["category_name"] == "Growth"
```

---

### Example 2: Table with Foreign Keys and JSONB

**User Request:**
```
Use database-migration-helper skill to create:

Table: extraction_runs
Columns:
- run_id (PK)
- filing_id (FK to filings, CASCADE delete)
- extractor_version (TEXT NOT NULL)
- run_config (JSONB)
- status (TEXT - enum: pending, running, completed, failed)
- started_at (TIMESTAMPTZ)
- completed_at (TIMESTAMPTZ)
- error_message (TEXT)
- created_at (TIMESTAMPTZ)

Include methods and tests.
```

**Claude Response:**

I'll generate a migration for the `extraction_runs` table with FK, JSONB, and enum constraint.

**Migration file: `sql/08_create_extraction_runs.sql`**

```sql
-- ============================================================================
-- Migration: Create Extraction Runs Table
-- Purpose: Track extraction pipeline runs per filing
-- Date: 2025-12-11
-- Based on: Extraction pipeline tracking requirements
-- ============================================================================

DROP TABLE IF EXISTS extraction_runs CASCADE;

-- ============================================================================
-- TABLE: extraction_runs
-- ============================================================================
-- Grain: One row per extraction run attempt for a filing
-- Purpose: Audit trail and debugging for extraction pipeline

CREATE TABLE extraction_runs (
    -- Primary key
    run_id BIGSERIAL PRIMARY KEY,

    -- Foreign key
    filing_id BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,

    -- Run metadata
    extractor_version TEXT NOT NULL,
    run_config JSONB,
    status TEXT NOT NULL DEFAULT 'pending',

    -- Timing
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Error tracking
    error_message TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    CONSTRAINT check_status CHECK (status IN ('pending', 'running', 'completed', 'failed'))
);

-- Indices
CREATE INDEX idx_extraction_runs_filing ON extraction_runs(filing_id);
CREATE INDEX idx_extraction_runs_status ON extraction_runs(status);
CREATE INDEX idx_extraction_runs_config ON extraction_runs USING GIN (run_config);
CREATE INDEX idx_extraction_runs_failed ON extraction_runs(filing_id, status) WHERE status = 'failed';

-- Comments
COMMENT ON TABLE extraction_runs IS 'Audit trail of extraction pipeline runs per filing';
COMMENT ON COLUMN extraction_runs.extractor_version IS 'Version of extraction code (e.g., "v2.1.3")';
COMMENT ON COLUMN extraction_runs.run_config IS 'JSON configuration used for this run (LLM model, prompts, etc.)';
COMMENT ON COLUMN extraction_runs.status IS 'Run status: pending, running, completed, failed';
```

**db.py methods:**

```python
# Add to src/review/models.py or similar:
EXTRACTION_RUN_STATUSES = ["pending", "running", "completed", "failed"]

# In DatabaseAdapter class:
def insert_extraction_run(
    self,
    filing_id: int,
    extractor_version: str,
    run_config: Optional[Dict[str, Any]] = None,
    status: str = "pending",
) -> int:
    """
    Insert a new extraction run record.

    Args:
        filing_id: Filing to run extraction on
        extractor_version: Version of extraction code (e.g., "v2.1.3")
        run_config: JSON configuration for this run (LLM model, prompts, etc.)
        status: Initial status (default: "pending")

    Returns:
        The run_id of the inserted record

    Raises:
        ValidationError: If status is not a valid extraction run status
        psycopg.errors.ForeignKeyViolation: If filing_id doesn't exist

    Example:
        >>> db = DatabaseAdapter(connection_string)
        >>> run_id = db.insert_extraction_run(
        ...     filing_id=123,
        ...     extractor_version="v2.1.3",
        ...     run_config={"llm_model": "gpt-4o-mini", "temperature": 0.1}
        ... )
    """
    # Validate status
    validate_enum(status, EXTRACTION_RUN_STATUSES, "status")

    sql = """
        INSERT INTO extraction_runs (
            filing_id, extractor_version, run_config, status
        ) VALUES (
            %(filing_id)s, %(extractor_version)s, %(run_config)s, %(status)s
        )
        RETURNING run_id
    """

    params = {
        "filing_id": filing_id,
        "extractor_version": extractor_version,
        "run_config": json.dumps(run_config) if run_config else None,
        "status": status,
    }

    with self.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            result = cur.fetchone()
            if result:
                return result["run_id"]
            raise RuntimeError("Insert failed to return ID")

def update_extraction_run_status(
    self,
    run_id: int,
    status: str,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    error_message: Optional[str] = None,
) -> bool:
    """
    Update extraction run status and timing.

    Args:
        run_id: Run to update
        status: New status
        started_at: ISO timestamp when run started (optional)
        completed_at: ISO timestamp when run completed (optional)
        error_message: Error message if status is "failed" (optional)

    Returns:
        True if update succeeded, False if run_id not found

    Raises:
        ValidationError: If status is not valid
    """
    validate_enum(status, EXTRACTION_RUN_STATUSES, "status")

    sql = """
        UPDATE extraction_runs
        SET status = %(status)s,
            started_at = COALESCE(%(started_at)s, started_at),
            completed_at = COALESCE(%(completed_at)s, completed_at),
            error_message = %(error_message)s
        WHERE run_id = %(run_id)s
    """

    params = {
        "run_id": run_id,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "error_message": error_message,
    }

    with self.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount > 0

def get_extraction_runs_for_filing(
    self,
    filing_id: int,
    status: Optional[str] = None,
) -> List[Dict]:
    """
    Get extraction runs for a filing.

    Args:
        filing_id: Filing to get runs for
        status: Optional filter by status

    Returns:
        List of extraction run records ordered by created_at DESC

    Raises:
        ValidationError: If status is provided but not valid
    """
    if status is not None:
        validate_enum(status, EXTRACTION_RUN_STATUSES, "status")

    sql = """
        SELECT * FROM extraction_runs
        WHERE filing_id = %(filing_id)s
    """
    params: Dict[str, Any] = {"filing_id": filing_id}

    if status:
        sql += " AND status = %(status)s"
        params["status"] = status

    sql += " ORDER BY created_at DESC"

    return self.query(sql, params)
```

**Test file: `tests/integration/test_db_extraction_runs.py`**

```python
"""Integration tests for extraction_runs table methods."""

import pytest
import psycopg.errors
from src.infra.validation import ValidationError


class TestExtractionRunsMethods:
    """Tests for extraction_runs table operations."""

    def test_insert_extraction_run_minimal(self, clean_db):
        """Test inserting extraction run with minimal fields."""
        _, filing_id = create_test_company_and_filing(clean_db)

        run_id = clean_db.insert_extraction_run(
            filing_id=filing_id,
            extractor_version="v2.1.3",
        )

        assert run_id > 0

        run = clean_db.get_extraction_run(run_id)
        assert run["filing_id"] == filing_id
        assert run["extractor_version"] == "v2.1.3"
        assert run["status"] == "pending"
        assert run["run_config"] is None

    def test_insert_extraction_run_with_config(self, clean_db):
        """Test inserting extraction run with JSONB config."""
        _, filing_id = create_test_company_and_filing(clean_db)

        config = {
            "llm_model": "gpt-4o-mini",
            "temperature": 0.1,
            "max_tokens": 2000,
        }

        run_id = clean_db.insert_extraction_run(
            filing_id=filing_id,
            extractor_version="v2.1.3",
            run_config=config,
        )

        run = clean_db.get_extraction_run(run_id)
        assert run["run_config"]["llm_model"] == "gpt-4o-mini"
        assert run["run_config"]["temperature"] == 0.1

    def test_update_run_status(self, clean_db):
        """Test updating extraction run status."""
        _, filing_id = create_test_company_and_filing(clean_db)

        run_id = clean_db.insert_extraction_run(
            filing_id=filing_id,
            extractor_version="v2.1.3",
        )

        # Update to running
        success = clean_db.update_extraction_run_status(
            run_id=run_id,
            status="running",
            started_at="2025-12-11T10:00:00Z",
        )

        assert success is True

        run = clean_db.get_extraction_run(run_id)
        assert run["status"] == "running"
        assert run["started_at"] is not None

    def test_invalid_status(self, clean_db):
        """Test CHECK constraint on status field."""
        _, filing_id = create_test_company_and_filing(clean_db)

        with pytest.raises(ValidationError):
            clean_db.insert_extraction_run(
                filing_id=filing_id,
                extractor_version="v2.1.3",
                status="invalid",
            )

    def test_cascade_delete_filing(self, clean_db):
        """Test ON DELETE CASCADE when filing is deleted."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        run_id = clean_db.insert_extraction_run(
            filing_id=filing_id,
            extractor_version="v2.1.3",
        )

        # Verify run exists
        assert clean_db.get_extraction_run(run_id) is not None

        # Delete filing
        clean_db.delete_filing(filing_id)

        # Verify run was cascade deleted
        assert clean_db.get_extraction_run(run_id) is None
```

---

## Validation

Before presenting output, check:

1. **Migration file:**
   - [ ] Has proper header comment with purpose and date
   - [ ] Tables are named in plural snake_case
   - [ ] Primary key is `{table}_id BIGSERIAL PRIMARY KEY`
   - [ ] Foreign keys have `ON DELETE CASCADE` or `SET NULL`
   - [ ] Timestamps use `TIMESTAMPTZ` not `TIMESTAMP`
   - [ ] Enum fields have CHECK constraints
   - [ ] JSONB columns have GIN indexes
   - [ ] FK columns have B-tree indexes
   - [ ] Table and key columns have COMMENT statements
   - [ ] Triggers for `updated_at` columns (if present)

2. **db.py methods:**
   - [ ] Method names follow convention (`insert_{table}`, `get_{table}`, etc.)
   - [ ] Type hints on all parameters and return values
   - [ ] Validation of enum fields before queries
   - [ ] Parameterized queries (no string interpolation)
   - [ ] `RETURNING` clause for insert methods
   - [ ] Comprehensive docstrings with Args, Returns, Raises, Example
   - [ ] Proper error handling in context managers

3. **Integration tests:**
   - [ ] Test class named `Test{TableCamelCase}Methods`
   - [ ] Tests for minimal and full field insertion
   - [ ] Tests for get operations (found and not found)
   - [ ] Tests for CHECK constraints (enum values)
   - [ ] Tests for FK constraints (violation and cascade)
   - [ ] Tests for UNIQUE constraints (if applicable)
   - [ ] Tests use `clean_db` fixture
   - [ ] Tests use helper functions from conftest.py

4. **Consistency:**
   - [ ] Table names match between SQL, db.py, and tests
   - [ ] Column names match exactly (case-sensitive)
   - [ ] Enum constants defined in models.py (if new enums)
   - [ ] All FKs reference existing tables
   - [ ] Migration number doesn't conflict with existing files

---

## Common Patterns

### Pattern: Status Tracking with Timestamps

```sql
-- In table definition:
status TEXT NOT NULL DEFAULT 'pending',
started_at TIMESTAMPTZ,
completed_at TIMESTAMPTZ,

CONSTRAINT check_status CHECK (status IN ('pending', 'running', 'completed', 'failed'))
```

```python
# db.py update method:
def update_{table}_status(
    self,
    {table}_id: int,
    status: str,
    timestamp_field: Optional[str] = None,
) -> bool:
    """Update {table} status and optionally set timestamp."""
    validate_enum(status, {STATUS_CONSTANTS}, "status")

    sql = """
        UPDATE {table_plural}
        SET status = %(status)s,
            {timestamp_field} = CASE
                WHEN %(timestamp_field)s IS NOT NULL
                THEN %(timestamp_field)s
                ELSE {timestamp_field}
            END
        WHERE {table}_id = %({table}_id)s
    """
```

### Pattern: Soft Delete

```sql
-- In table definition:
deleted_at TIMESTAMPTZ,

-- Index for active records only:
CREATE INDEX idx_{table}_active ON {table}({column}) WHERE deleted_at IS NULL;
```

```python
# db.py soft delete method:
def soft_delete_{table}(self, {table}_id: int) -> bool:
    """Mark {table} as deleted without removing from database."""
    sql = """
        UPDATE {table_plural}
        SET deleted_at = now()
        WHERE {table}_id = %({table}_id)s
          AND deleted_at IS NULL
    """
    with self.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"{table}_id": {table}_id})
            return cur.rowcount > 0
```

### Pattern: Pagination Helper

```python
# Standard pagination pattern in query methods:
sql = "SELECT * FROM {table} WHERE ..."
params: Dict[str, Any] = {}

sql += " ORDER BY {default_column}"

if limit:
    sql += " LIMIT %(limit)s OFFSET %(offset)s"
    params["limit"] = limit
    params["offset"] = offset

return self.query(sql, params)
```

---

## Version History

**v1.0 (2025-12-11):**
- Initial skill creation
- Covers migration files, db.py methods, integration tests
- Includes validation checklist and common patterns
- Based on sql/01_create_schema.sql, sql/07_create_review_schema.sql
- Based on src/infra/db.py method patterns
- Based on tests/integration/test_db_review_methods.py test patterns

---

**Last Updated:** 2025-12-11
**Skill Type:** Database & Infrastructure
**Project:** SEC Filings Reviewer
