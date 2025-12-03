# FilingFetcher Integration Guide

**Date:** 2025-11-24
**Status:** ✅ Complete and Tested

## Overview

This document describes the integration between **UniverseBuilder** and **FilingFetcher** components, enabling automated downloading of SEC filing documents for the filings identified in Phase 1.

## Architecture

### Processing Workflow

```
┌─────────────────┐
│ UniverseBuilder │  Discovers S-1/F-1 filings
│                 │  Sets processing_status='pending'
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Batch Runner   │  Queries for pending filings
│                 │  Orchestrates download process
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ FilingFetcher   │  Downloads HTML/TXT documents
│                 │  Updates processing_status='fetched'
│                 │  Caches files locally
└─────────────────┘
```

### Database Schema

The `filings` table tracks processing state:

```sql
-- Processing status workflow
processing_status TEXT NOT NULL DEFAULT 'pending'
-- Values: 'pending' → 'fetched' → 'processed' → 'failed'

-- Storage tracking
html_storage_path TEXT            -- Path to cached HTML
txt_storage_path TEXT             -- Path to cached TXT
html_fetched_at TIMESTAMPTZ       -- Timestamp of successful fetch
html_fetch_error TEXT             -- Error message if fetch failed
```

**Key Indices:**
- `idx_filings_processing_status` - Fast queries by status
- `idx_filings_scope_status` - Compound index for in-scope + status queries

## Components

### 1. UniverseBuilder
**File:** `src/universe/universe_builder.py`

**Responsibility:** Set initial processing status

```python
# When creating filings
self.db.upsert_filing(
    # ... other fields ...
    processing_status="pending",  # ✅ Sets initial state
)
```

### 2. FilingFetcher
**File:** `src/filing_fetcher/filing_fetcher.py`

**Responsibility:** Download files and update status

```python
# On successful download
UPDATE filings SET
    html_storage_path = %(html_path)s,
    txt_storage_path = %(txt_path)s,
    html_fetched_at = %(fetched_at)s,
    html_fetch_error = NULL,
    processing_status = 'fetched',  # ✅ Updates to fetched
    updated_at = now()
WHERE accession_number = %(accession)s
```

**Key Methods:**
- `fetch_filing()` - Download single filing
- `fetch_batch()` - Download multiple filings with progress tracking
- `get_unfetched_filings()` - Query database for pending filings

### 3. Batch Download Runner
**File:** `scripts/batch_download_filings.py`

**Responsibility:** Orchestrate batch downloading

**Features:**
- ✅ Queries for `processing_status='pending'` filings
- ✅ Converts to `FilingMetadata` objects
- ✅ Calls `FilingFetcher.fetch_batch()`
- ✅ Tracks progress and statistics
- ✅ Handles interruptions gracefully (Ctrl+C)
- ✅ Provides before/after status summary
- ✅ Supports dry-run mode for testing

## Usage

### Basic Usage

```bash
# Download next 50 pending filings
python scripts/batch_download_filings.py --limit 50

# Download from specific year
python scripts/batch_download_filings.py --year 2024 --limit 100

# Dry run - preview without downloading
python scripts/batch_download_filings.py --limit 20 --dry-run
```

### Complete Workflow

```bash
# Step 1: Build universe (identify in-scope filings)
python scripts/build_universe_real.py --start-date 2024-01-01 --end-date 2024-12-31

# Step 2: Download filings (sets processing_status='fetched')
python scripts/batch_download_filings.py --limit 100

# Step 3: Check status
python scripts/batch_download_filings.py --limit 1 --dry-run
```

### Example Output

```
================================================================================
SEC Filings Batch Download Runner
================================================================================
Started at: 2025-11-24 15:57:28
Database: postgresql://localhost/filings_analysis
Storage root: data/filings
Batch size: 10
================================================================================

Found 10 pending filings

Sample of filings to fetch:
--------------------------------------------------------------------------------
Company                        Form       Date         Status
--------------------------------------------------------------------------------
WOLFSPEED, INC.                S-1        2025-11-14   pending
Black Titan Corp               F-1        2025-11-14   pending
...
--------------------------------------------------------------------------------

Starting Batch Download
SEC rate limit: ~10 requests/second
Estimated time: ~1.5 seconds

================================================================================
✓ Batch Download Complete!
================================================================================

Batch Results:
  Total requested: 10
  Successfully fetched: 10
  Skipped (already cached): 0
  Failed: 0

Processing Status Summary:
--------------------------------------------------------------------------------
Status               Before          After           Change
--------------------------------------------------------------------------------
fetched              0               10              +10
pending              7304            7294            -10
--------------------------------------------------------------------------------
TOTAL                7304            7304
```

## Error Handling

### Circuit Breaker
The batch runner includes a circuit breaker that stops after N consecutive failures (default: 10):

```python
fetcher.fetch_batch(
    filings,
    fetch_txt=True,
    max_failures=10  # Stop after 10 consecutive failures
)
```

**Why it's needed:**
- Prevents infinite loops if SEC API is down
- Saves API quota if there's a systematic problem
- Allows graceful recovery from transient issues

### Failure Recovery

Failures are tracked in the database:

```sql
-- Failed filing example
html_fetch_error = "HTTP error fetching 0001234567/0001234567-24-123456: 404 Not Found"
processing_status = "pending"  -- Remains pending so it can be retried
```

**To retry failed filings:**
```bash
# Failed filings remain in 'pending' status, so just run again
python scripts/batch_download_filings.py --limit 100
```

## Performance Considerations

### SEC Rate Limiting
- **Limit:** 10 requests per second
- **Implementation:** `FilingFetcher._rate_limit()` enforces 110ms between requests
- **Batch time:** ~0.15 seconds per filing (including HTML + TXT)

### Caching
FilingFetcher automatically skips re-downloading:
- Files already exist locally → Skip download
- `html_fetched_at IS NOT NULL` → Skip query

### Storage Organization
```
data/filings/
├── {cik}/
│   └── {accession_without_dashes}/
│       ├── primary.htm     # Main HTML filing
│       └── complete.txt    # Complete text filing (optional)
```

**Example:**
```
data/filings/0001234567/000123456724123456/
├── primary.htm
└── complete.txt
```

## Testing

### Unit Tests
All FilingFetcher methods are tested at 100% coverage:
- `tests/unit/filing_fetcher/test_filing_fetcher.py` (48 tests)

**Key test coverage:**
- ✅ Batch processing
- ✅ Status updates
- ✅ Error handling
- ✅ Caching logic
- ✅ Security (path traversal)
- ✅ Content validation

### Integration Testing

```bash
# 1. Dry run - verify queries work
python scripts/batch_download_filings.py --limit 5 --dry-run

# 2. Small batch - test actual downloads
python scripts/batch_download_filings.py --limit 5

# 3. Verify database status
psql filings_analysis -c "
    SELECT processing_status, COUNT(*)
    FROM filings
    WHERE is_in_scope_phase1 = true
    GROUP BY processing_status
"
```

## Monitoring

### Progress Tracking

The batch runner provides real-time progress:
1. Before/after status counts
2. Success/failure statistics
3. Estimated completion time
4. Storage location

### Database Queries

**Check processing status:**
```sql
SELECT
    processing_status,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as pct
FROM filings
WHERE is_in_scope_phase1 = true
GROUP BY processing_status
ORDER BY processing_status;
```

**Find failed filings:**
```sql
SELECT
    c.company_name,
    f.form_type,
    f.filing_date,
    f.html_fetch_error
FROM filings f
JOIN companies c ON f.company_id = c.company_id
WHERE
    f.is_in_scope_phase1 = true
    AND f.html_fetch_error IS NOT NULL
ORDER BY f.filing_date DESC
LIMIT 20;
```

## Next Steps

After downloading filings with processing_status='fetched':

1. **Run Extraction Pipeline**
   ```bash
   python scripts/run_extraction.py --limit 100
   ```
   This will:
   - Segment HTML
   - Classify segments
   - Extract metric values and definitions
   - Update processing_status='processed'

2. **Monitor Processing**
   - Track `processing_status` distribution
   - Review extraction quality scores
   - Identify filings needing manual review

## Troubleshooting

### Issue: No pending filings found

**Cause:** All filings already fetched or no filings in universe

**Solution:**
```bash
# Check status distribution
python scripts/batch_download_filings.py --limit 1 --dry-run

# If needed, rebuild universe
python scripts/build_universe_real.py --start-date 2024-01-01 --end-date 2024-12-31
```

### Issue: High failure rate

**Causes:**
1. SEC API issues (rate limiting, downtime)
2. Invalid URLs in database
3. Network connectivity issues

**Solutions:**
```bash
# 1. Check SEC EDGAR status
curl -I https://www.sec.gov/

# 2. Review failed filings
psql filings_analysis -c "
    SELECT html_fetch_error, COUNT(*)
    FROM filings
    WHERE html_fetch_error IS NOT NULL
    GROUP BY html_fetch_error
"

# 3. Retry with lower batch size
python scripts/batch_download_filings.py --limit 10 --max-failures 3
```

### Issue: Interrupted download

**Solution:** Just run again - progress is saved automatically
```bash
# Resume where you left off
python scripts/batch_download_filings.py --limit 100
```

The script automatically skips already-fetched filings, so interruptions don't cause re-work.

## Summary

The FilingFetcher integration provides:
- ✅ Automated batch downloading of SEC filings
- ✅ Robust error handling and retry logic
- ✅ Progress tracking and monitoring
- ✅ Seamless integration with UniverseBuilder
- ✅ Database-driven workflow with processing_status
- ✅ 100% test coverage

**Status:** Production ready ✅
