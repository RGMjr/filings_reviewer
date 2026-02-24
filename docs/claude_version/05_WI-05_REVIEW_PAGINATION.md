# WI-05: Review Query Pagination

**Branch**: `prod/wi-05-review-pagination`
**Depends on**: Nothing (independent)
**Blocks**: Nothing
**Risk level**: Low (additive change, existing callers continue to work with defaults)
**Execution**: `/ralph develop --isolated`

---

## Context

Two methods in `src/infra/db.py` fetch all rows for a given query with no limit:

**`get_v2_filings_with_facts()` at line 3907:**
```python
def get_v2_filings_with_facts(self) -> list[dict]:
    # Returns ALL filings that have V2 extraction results
    # No limit, no offset
    sql = """SELECT ... FROM v2_documents d JOIN filings f ... ORDER BY ..."""
    return self.query(sql)
```

**`get_v2_facts_for_filing()` at line 3946:**
```python
def get_v2_facts_for_filing(
    self,
    filing_id: int,
    status: str | None = None,
    metric_id: str | None = None,
    sort_by: str = "confidence_desc",
) -> list[dict]:
    # Returns ALL facts for a filing — no limit
```

As extraction history grows, these queries grow linearly. A filing with 500+ facts sends all 500 rows to the browser every page load.

The fix is additive: add `limit` and `offset` parameters with defaults that preserve existing behavior. No query string parsing is needed in routes where the reviewer expects to see all facts — but the parameters must exist for routes that want to paginate.

---

## Implementation

### Step 1: Add pagination to `get_v2_filings_with_facts()`

**File**: `src/infra/db.py`, line 3907

**Change**: Add `limit` and `offset` parameters. Append `LIMIT`/`OFFSET` clause when provided.

```python
def get_v2_filings_with_facts(
    self,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """
    Get filings that have V2 extraction results, with fact counts and review progress.

    Args:
        limit: Maximum number of rows to return (None = all rows).
        offset: Number of rows to skip (default 0).
    """
    sql = """
        SELECT
            f.filing_id,
            c.company_name,
            c.cik,
            f.accession_number,
            f.form_type,
            f.filing_date,
            d.doc_id,
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
        GROUP BY f.filing_id, c.company_name, c.cik, f.accession_number,
                 f.form_type, f.filing_date, d.doc_id, d.status,
                 d.fact_count, d.segment_count, d.table_count, d.image_count,
                 d.extract_completed_at
        ORDER BY d.extract_completed_at DESC NULLS LAST
    """
    params: dict = {}
    if limit is not None:
        sql += " LIMIT %(limit)s OFFSET %(offset)s"
        params["limit"] = limit
        params["offset"] = offset

    return self.query(sql, params or None)
```

> **Note on `params or None`**: `db.query()` accepts `params: dict | None`. Passing an empty `{}` is falsy, so `params or None` cleanly passes `None` when no limit is set. This is more readable than a conditional branch.

Also add a count method for pagination metadata:

```python
def count_v2_filings_with_facts(self) -> int:
    """Return total count of filings with V2 extraction results."""
    sql = """
        SELECT COUNT(*) AS total
        FROM v2_documents d
        JOIN filings f ON d.filing_id = f.filing_id
        JOIN companies c ON f.company_id = c.company_id
    """
    rows = self.query(sql)
    return rows[0]["total"] if rows else 0
```

### Step 2: Add pagination to `get_v2_facts_for_filing()`

**File**: `src/infra/db.py`, line 3946

**Change**: Add `limit` and `offset` parameters at the end of the signature (preserves all existing call sites).

The full method already builds `conditions`, `params`, `where_clause`, and `order_clause`. Add the pagination clause after the existing `ORDER BY`:

```python
def get_v2_facts_for_filing(
    self,
    filing_id: int,
    status: str | None = None,
    metric_id: str | None = None,
    sort_by: str = "confidence_desc",
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
```

At the point where the SQL is assembled (after `ORDER BY {order_clause}`), append:

```python
if limit is not None:
    sql += f" LIMIT %(limit)s OFFSET %(offset)s"
    params["limit"] = limit
    params["offset"] = offset
```

Also add a count method:

```python
def count_v2_facts_for_filing(
    self,
    filing_id: int,
    status: str | None = None,
    metric_id: str | None = None,
) -> int:
    """Return total count of V2 facts for a filing with optional filters."""
    conditions = ["mf.doc_id = %(filing_id)s"]
    params: dict = {"filing_id": filing_id}
    if status:
        conditions.append("mf.review_status = %(status)s")
        params["status"] = status
    if metric_id:
        conditions.append("mf.canonical_metric_id = %(metric_id)s")
        params["metric_id"] = metric_id
    where_clause = " AND ".join(conditions)
    sql = f"""
        SELECT COUNT(*) AS total
        FROM v2_metric_facts mf
        WHERE {where_clause}
    """
    rows = self.query(sql, params)
    return rows[0]["total"] if rows else 0
```

### Step 3: Update route handlers

**File**: `src/web/routes/review_v2.py`

Find the route handlers that call these methods and add optional pagination from query string:

For the filings list route (find the route that calls `get_v2_filings_with_facts()`):

```python
@review_v2_bp.route("/v2/")
def index():
    db = get_db()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(per_page, 200)  # Safety cap

    offset = (page - 1) * per_page
    filings = db.get_v2_filings_with_facts(limit=per_page, offset=offset)
    total = db.count_v2_filings_with_facts()

    return render_template(
        "review_v2/index.html",
        filings=filings,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=(total + per_page - 1) // per_page,
    )
```

For the filing detail route (calls `get_v2_facts_for_filing()`):

```python
@review_v2_bp.route("/v2/filing/<int:filing_id>")
def filing_detail(filing_id: int):
    db = get_db()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 100, type=int)
    per_page = min(per_page, 500)  # Safety cap

    status = request.args.get("status")
    metric_id = request.args.get("metric_id")
    sort_by = request.args.get("sort_by", "confidence_desc")

    offset = (page - 1) * per_page
    facts = db.get_v2_facts_for_filing(
        filing_id=filing_id,
        status=status,
        metric_id=metric_id,
        sort_by=sort_by,
        limit=per_page,
        offset=offset,
    )
    total = db.count_v2_facts_for_filing(filing_id, status=status, metric_id=metric_id)

    return render_template(
        "review_v2/filing.html",
        facts=facts,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=(total + per_page - 1) // per_page,
        # ... other template vars
    )
```

**Important**: Read the actual route handlers before modifying them. The route structure above is inferred from the method names — the actual routes may differ. Do not modify routes that do not call these two methods.

---

## Files to Modify

| File | Change |
|------|--------|
| `src/infra/db.py` | Add `limit`/`offset` params to 2 existing methods; add 2 count methods |
| `src/web/routes/review_v2.py` | Add pagination params to calls of the two methods |

---

## Acceptance Criteria

- [ ] `get_v2_filings_with_facts()` with no arguments returns all rows (backward-compatible)
- [ ] `get_v2_filings_with_facts(limit=10, offset=0)` returns exactly 10 rows
- [ ] `get_v2_filings_with_facts(limit=10, offset=10)` returns rows 11–20
- [ ] `get_v2_facts_for_filing(filing_id=X)` with no `limit` returns all facts (backward-compatible)
- [ ] `get_v2_facts_for_filing(filing_id=X, limit=20, offset=0)` returns exactly 20 facts
- [ ] `count_v2_filings_with_facts()` returns a positive integer matching the unfiltered list count
- [ ] `count_v2_facts_for_filing(filing_id=X)` returns the correct total regardless of pagination
- [ ] Review index route responds with `?page=2&per_page=25` query params
- [ ] All existing tests that call these methods still pass (no signature break)

---

## Verification Commands

```bash
# Unit tests for db methods
pytest tests/unit/infra/test_db_v2_pagination.py -v

# Route tests
pytest tests/ -k "review_v2" -q

# Full unit suite
pytest tests/unit/ -q
```

---

## What This Does NOT Do

- Does not add pagination UI to templates (that's a product concern; the data layer is enough for now)
- Does not add indexes (the existing queries are fast enough with typical filing counts; add indexes if explain plan shows seq scans on large tables)
- Does not paginate other `db.py` methods (only the two unbounded ones identified)
- Does not change the JSON API responses if those routes use different methods
