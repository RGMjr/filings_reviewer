# Worker Prompt: Split db.py Monolith into Repositories

## Task ID: REV-08
## Priority: P2 (Long-term Maintainability)
## Effort: XL (2-4 weeks)
## Finding IDs: C-D3-003, G-D1-002, A-D1-001

---

## Problem Statement

`src/infra/db.py` is a **4,006 line "God Object"** with:
- **50+ methods** mixing 7 bounded contexts
- **Maintainability Index of 0.0** (unmaintainable)
- **Cyclomatic complexity of 42** (bulk_insert_review_candidates)
- **All 3 models** flagged this as critical

### Bounded Contexts Mixed in db.py

1. **Company/Filing CRUD** (~5 methods)
2. **Segment operations** (~3 methods)
3. **Review candidates** (~7 methods, CC=42 max)
4. **Review decisions** (~8 methods)
5. **Pattern learning** (~5 methods)
6. **Image review** (~8 methods)
7. **Audit logging** (~1 method)
8. **Progress tracking** (~2 methods)

---

## Target Architecture

```
src/infra/
├── db.py                    # Minimal: connection pool + UnitOfWork
├── repositories/
│   ├── __init__.py
│   ├── base.py              # BaseRepository with common patterns
│   ├── company_repo.py      # Company/Filing operations
│   ├── segment_repo.py      # Segment CRUD
│   ├── extraction_repo.py   # Extraction artifacts
│   ├── candidate_repo.py    # Review candidates
│   ├── decision_repo.py     # Review decisions
│   ├── pattern_repo.py      # Learned patterns
│   ├── image_repo.py        # Image review
│   └── audit_repo.py        # Audit logging
└── unit_of_work.py          # Transaction management
```

---

## Acceptance Criteria

1. [ ] Each repository has single responsibility
2. [ ] Each repository < 500 LOC
3. [ ] db.py reduced to connection management only (< 200 LOC)
4. [ ] All existing tests pass without modification
5. [ ] No circular dependencies between repositories
6. [ ] SQL queries co-located with repository
7. [ ] Migration guide documented

---

## Implementation Plan

### Phase 1: Create Infrastructure (Week 1)

#### Step 1.1: Create Base Repository

```python
# src/infra/repositories/base.py
from typing import TypeVar, Generic, Optional, Any
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row

T = TypeVar('T')

class BaseRepository(Generic[T]):
    """Base class for all repositories."""

    def __init__(self, connection_provider):
        self._get_connection = connection_provider

    @contextmanager
    def _cursor(self):
        """Get a cursor with dict row factory."""
        with self._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                yield cur

    def _execute_one(self, sql: str, params: dict = None) -> Optional[dict]:
        """Execute query returning single row."""
        with self._cursor() as cur:
            cur.execute(sql, params or {})
            return cur.fetchone()

    def _execute_many(self, sql: str, params: dict = None) -> list[dict]:
        """Execute query returning multiple rows."""
        with self._cursor() as cur:
            cur.execute(sql, params or {})
            return cur.fetchall()

    def _execute_write(self, sql: str, params: dict = None) -> int:
        """Execute write query, return affected rows."""
        with self._cursor() as cur:
            cur.execute(sql, params or {})
            return cur.rowcount
```

#### Step 1.2: Create Unit of Work

```python
# src/infra/unit_of_work.py
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.infra.repositories import *

class UnitOfWork:
    """
    Manages transactions and provides access to repositories.

    Usage:
        with UnitOfWork(db) as uow:
            company = uow.companies.get_by_cik(cik)
            uow.filings.upsert(filing)
            uow.commit()
    """

    def __init__(self, db_adapter):
        self._db = db_adapter
        self._connection = None

    def __enter__(self):
        self._connection = self._db.get_raw_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._connection.rollback()
        self._connection.close()
        self._connection = None

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    @property
    def companies(self) -> "CompanyRepository":
        return CompanyRepository(lambda: self._connection)

    @property
    def filings(self) -> "FilingRepository":
        return FilingRepository(lambda: self._connection)

    @property
    def candidates(self) -> "CandidateRepository":
        return CandidateRepository(lambda: self._connection)

    # ... other repositories
```

### Phase 2: Extract First Repository (Week 1)

Start with **CompanyRepository** as it's the simplest.

```python
# src/infra/repositories/company_repo.py
from typing import Optional
from .base import BaseRepository

class CompanyRepository(BaseRepository):
    """Repository for company and filing operations."""

    def get_by_cik(self, cik: str) -> Optional[dict]:
        """Get company by CIK."""
        return self._execute_one(
            "SELECT * FROM companies WHERE cik = %(cik)s",
            {"cik": cik}
        )

    def get_by_id(self, company_id: int) -> Optional[dict]:
        """Get company by ID."""
        return self._execute_one(
            "SELECT * FROM companies WHERE company_id = %(id)s",
            {"id": company_id}
        )

    def upsert(self, company: dict) -> int:
        """Upsert company, return company_id."""
        result = self._execute_one("""
            INSERT INTO companies (cik, name, sic_code, sic_description)
            VALUES (%(cik)s, %(name)s, %(sic_code)s, %(sic_description)s)
            ON CONFLICT (cik) DO UPDATE SET
                name = EXCLUDED.name,
                sic_code = EXCLUDED.sic_code,
                sic_description = EXCLUDED.sic_description
            RETURNING company_id
        """, company)
        return result["company_id"]

    def list_with_filings(self, limit: int = 100) -> list[dict]:
        """List companies with filing counts."""
        return self._execute_many("""
            SELECT c.*, COUNT(f.filing_id) as filing_count
            FROM companies c
            LEFT JOIN filings f ON c.company_id = f.company_id
            GROUP BY c.company_id
            ORDER BY c.name
            LIMIT %(limit)s
        """, {"limit": limit})
```

### Phase 3: Extract Remaining Repositories (Week 2)

#### CandidateRepository (Highest complexity)

```python
# src/infra/repositories/candidate_repo.py
class CandidateRepository(BaseRepository):
    """Repository for review candidate operations."""

    def bulk_insert(
        self,
        candidates: list[dict],
        conflict_strategy: str = "skip"
    ) -> tuple[int, int]:
        """
        Bulk insert candidates with conflict handling.

        Returns: (inserted_count, conflict_count)
        """
        # Implement the complex 387-line bulk_insert_review_candidates
        # Split into smaller private methods
        ...

    def _check_existing(self, candidate_keys: list[tuple]) -> set[tuple]:
        """Check which candidates already exist."""
        ...

    def _insert_batch(self, candidates: list[dict]) -> int:
        """Insert a batch of candidates."""
        ...
```

### Phase 4: Update db.py to Facade (Week 3)

```python
# src/infra/db.py (refactored)
class DatabaseAdapter:
    """
    Database connection management and repository access.

    This class is now a thin facade. All domain operations
    are delegated to specialized repositories.

    For new code, prefer using UnitOfWork directly:
        with UnitOfWork(db) as uow:
            uow.companies.upsert(...)
            uow.commit()

    Legacy methods are preserved for backward compatibility
    but delegate to repositories.
    """

    def __init__(self, connection_string: str, use_pool: bool = True):
        self.connection_string = connection_string
        self._pool = self._create_pool() if use_pool else None

    @contextmanager
    def get_connection(self):
        """Get a database connection (pooled or direct)."""
        ...

    def unit_of_work(self) -> UnitOfWork:
        """Create a new unit of work for transactional operations."""
        return UnitOfWork(self)

    # --- Legacy methods (delegate to repositories) ---

    def upsert_company(self, company: dict) -> int:
        """Legacy: Use uow.companies.upsert() instead."""
        with self.unit_of_work() as uow:
            result = uow.companies.upsert(company)
            uow.commit()
            return result

    def get_company_by_cik(self, cik: str) -> Optional[dict]:
        """Legacy: Use uow.companies.get_by_cik() instead."""
        with self.unit_of_work() as uow:
            return uow.companies.get_by_cik(cik)
```

### Phase 5: Update Callers (Week 4)

Gradually update callers to use new patterns:

```python
# BEFORE
def process_filing(db, filing_data):
    company_id = db.upsert_company(company_data)
    filing_id = db.upsert_filing(filing_data)
    db.bulk_insert_review_candidates(candidates)

# AFTER
def process_filing(db, filing_data):
    with db.unit_of_work() as uow:
        company_id = uow.companies.upsert(company_data)
        filing_id = uow.filings.upsert(filing_data)
        uow.candidates.bulk_insert(candidates)
        uow.commit()
```

---

## Migration Strategy

1. **Phase 1**: Create infrastructure, no breaking changes
2. **Phase 2-3**: Extract repositories, db.py delegates to them
3. **Phase 4**: Mark legacy methods as deprecated
4. **Phase 5**: Update callers incrementally
5. **Phase 6**: Remove deprecated methods (future)

All phases maintain backward compatibility.

---

## Verification Commands

```bash
# After each phase, run full test suite
pytest tests/ -v

# Check LOC of db.py
wc -l src/infra/db.py
# Target: < 200 lines

# Check repository sizes
wc -l src/infra/repositories/*.py
# Target: < 500 lines each

# Check cyclomatic complexity
radon cc src/infra/ -a -s

# Integration tests specifically
pytest tests/integration/ -v
```

---

## Risk Mitigation

- **No breaking changes**: Legacy methods preserved
- **Incremental migration**: One repository at a time
- **Full test coverage**: Run tests after each extraction
- **Rollback plan**: Each phase is a separate branch/PR
