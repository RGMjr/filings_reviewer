# V2 Deployment Guide

**Version:** 1.1
**Last Updated:** 2026-02-28
**Pipeline Version:** 2.0.0-rc1

---

## Overview

This guide covers deploying the V2 extraction pipeline (`src/extraction_v2/`) to production.
The V2 pipeline is a ground-up redesign offering 10x faster lxml parsing, stable XPath locators,
full table reconstruction, image/OCR integration, and a quality scoring layer.

V2 writes exclusively to `v2_*` tables and does not modify V1 data. Rollback is non-destructive.

---

## 1. Pre-Deployment Checklist

### Database Migrations

All migrations 09-12 must be applied before running V2 extraction. Migration 12 (`sql/12_drop_v1_fk_constraints.sql`) drops FK constraints on `source_segments` from `review_candidates`, `suppressed_candidates`, and `image_review_candidates` — required before V1 table removal and before cutover.

```bash
python3 scripts/apply_migrations.py
```

Verify the required V2 tables exist:

```bash
psql $DATABASE_URL -c "
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'public'
      AND tablename IN (
          'v2_documents',
          'v2_segments',
          'v2_metric_facts',
          'v2_metric_definitions',
          'v2_quality_scores'
      )
    ORDER BY tablename;"
```

Expected output: all five tables listed.

### Required Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string (`postgresql://dev:dev@localhost:5433/filings_analysis`) |
| `TEST_DATABASE_URL` | For validation | Separate test database for gold standard runs |
| `OPENAI_API_KEY` | Yes | OpenAI API key for LLM-assisted stages |
| `SEC_USER_AGENT` | Yes | SEC EDGAR user agent (`"Name email@example.com"`) |

Load environment from `.env`:

```bash
cp .env.template .env
# Edit .env with your values, then verify:
source .env  # or let python-dotenv load it automatically
```

### Database Health Check

```bash
psql $DATABASE_URL -c "SELECT version();"
```

Confirm the connection is live and the schema is accessible:

```bash
psql $DATABASE_URL -c "
    SELECT
        tablename,
        pg_size_pretty(pg_total_relation_size('public.' || tablename)) AS size
    FROM pg_tables
    WHERE schemaname = 'public'
      AND tablename LIKE 'v2_%'
    ORDER BY tablename;"
```

### Dependency Check

```bash
python3 -c "from src.extraction_v2.pipeline import V2Pipeline; print('V2 import OK')"
```

---

## 2. Go / No-Go Criteria

Before promoting V2 to primary, validate extraction quality against the gold standard.

### Minimum Thresholds

| Metric | Minimum | Current Baseline |
|--------|---------|-----------------|
| Precision | 75% | 68.1% |
| Recall | 55% | 63.4% |
| F1 Score | 65% | 65.6% |

> **Note**: Current Baseline values are V2 SEC methodology (15 gold standard companies, V2 pipeline only), as of 2026-04-16 (commit `09a8f64`). These differ from the original V1 GR methodology numbers (P=92.8%, R=77.6%, F1=84.5%) which used a different validation approach. V2 baseline is stored in `data/gold_standard/v2_baseline.json`.

### Run Gold Standard Validation

```bash
pytest -m gold_standard --gold-standard-mode=fresh -v
```

The test suite prints per-company and aggregate scores. Check the final summary block:

```
=== Gold Standard Summary ===
Precision: XX.X%  (threshold: >=75%)
Recall:    XX.X%  (threshold: >=55%)
F1:        XX.X%  (threshold: >=65%)
```

**Go** if all three thresholds are met.
**No-Go** if any threshold is missed — investigate regressions before proceeding. See
`.claude/rules/gold-standard.md` for the full regression workflow.

Current baseline scores are saved to `data/gold_standard/v2_baseline.json`. Pass
`--gold-standard-mode=baseline` to compare against the saved baseline rather than
recomputing fresh extraction.

---

## 3. Batch Extraction Runbook

### Single Filing (Validation / Debug)

Before running the full universe, validate the pipeline on one filing:

```bash
python3 scripts/run_v2_extraction.py --filing-id <ID> --verbose
```

Key flags for `run_v2_extraction.py`:

| Flag | Default | Description |
|------|---------|-------------|
| `--filing-id ID` | — | Filing ID from database (mutually exclusive with `--accession`) |
| `--accession NUM` | — | SEC accession number |
| `--dry-run` | false | Run pipeline without persisting to database |
| `--min-confidence FLOAT` | 0.90 | Minimum confidence for auto-accept |
| `--no-images` | false | Disable image and chart extraction |
| `--skip-quality` | false | Skip quality scoring step |
| `--verbose` / `-v` | false | Enable debug logging |

### Full Batch Extraction

Run `batch_v2_extraction.py` to process the full filing universe in parallel:

```bash
python3 scripts/batch_v2_extraction.py
```

Key flags for `batch_v2_extraction.py`:

| Flag | Default | Description |
|------|---------|-------------|
| `--limit N` | all | Maximum number of filings to process |
| `--workers N` | 4 | Number of parallel worker processes |
| `--batch-size N` | 10 | Checkpoint interval (filings per checkpoint write) |
| `--resume-from ID` | — | Skip filing_ids below this value (resume from checkpoint) |
| `--filing-id ID` | — | Process a single filing by ID |
| `--dry-run` | false | Run without persisting to database |
| `--skip-quality` | false | Skip quality scoring |
| `--no-images` | false | Disable image extraction |
| `--min-confidence FLOAT` | 0.90 | Minimum confidence for auto-accept |
| `--max-consecutive-failures N` | 10 | Circuit breaker: abort if N consecutive failures occur |
| `--verbose` / `-v` | false | Verbose logging |

**Recommended production invocation** (full universe, 4 workers):

```bash
python3 scripts/batch_v2_extraction.py \
    --workers 4 \
    --batch-size 10 \
    2>&1 | tee logs/batch_v2_$(date +%Y%m%d).log
```

**Dry run first** to confirm filing count and configuration:

```bash
python3 scripts/batch_v2_extraction.py --dry-run --limit 5
```

### Monitoring Progress

Progress is logged to stdout every 10 filings:

```
2026-02-26 10:15:30 - __main__ - INFO - Progress: 40/250 (38 ok, 2 failed) | Rate: 8.2/min | ETA: 26s | Facts: 312
```

The checkpoint file is written after each batch:

```bash
cat logs/batch_v2_progress.json
```

```json
{
  "timestamp": "2026-02-26T10:15:30",
  "last_filing_id": 1040,
  "processed": 40,
  "succeeded": 38,
  "failed": 2,
  "total_facts": 312
}
```

**Graceful shutdown**: Press `Ctrl+C` to trigger a clean stop after the current batch completes.
The checkpoint file will reflect the last completed filing. Resume with `--resume-from <last_filing_id>`.

### Resuming After Interruption

```bash
# Check last checkpoint
cat logs/batch_v2_progress.json

# Resume from last known good filing_id
python3 scripts/batch_v2_extraction.py --resume-from <last_filing_id>
```

### Expected Output

After completion, a timestamped summary JSON is written to `logs/`:

```
logs/batch_v2_summary_20260226_101530.json
```

---

## 4. One-Way Cutover Procedure

Follow these steps in order. Each step has a verification gate before proceeding.

### Step 1: Run V2 Batch Extraction on Full Universe

```bash
python3 scripts/batch_v2_extraction.py \
    --workers 4 \
    2>&1 | tee logs/batch_v2_cutover.log
```

Verify completion:

```bash
psql $DATABASE_URL -c "
    SELECT COUNT(DISTINCT filing_id) AS v2_filings,
           COUNT(*) AS v2_facts
    FROM v2_metric_facts;"
```

**Gate**: `v2_filings` count should match the total filing universe (or close to it after accounting for filings without HTML). Check `logs/batch_v2_summary_*.json` for the success/failure breakdown.

### Step 2: Validate Gold Standard

```bash
pytest -m gold_standard --gold-standard-mode=fresh -v
```

**Gate**: All three thresholds must pass (P>=75%, R>=55%, F1>=65%). If any fail, stop and investigate before proceeding.

### Step 3: Confirm V2 Review UI Is Primary

The V2 review interface is fully implemented (WP-21 complete, 2026-02-28) and accessible at `http://localhost:5000/v2/review/filings` when the review server is running:

```bash
python3 scripts/run_review_server.py
```

Verify that the V2 review routes (`review_v2.py`, `api_v2.py`) and templates (`v2_filing_list.html`, `v2_review.html`, `v2_stats.html`) are functional. The V1 routes emit deprecation warnings and redirect to the V2 UI; they are not a fallback entry point after cutover.

### Step 4: Update Ops Context

Record the cutover in `ops/ITERATION_CONTEXT.md`:

```markdown
## V2 Cutover (YYYY-MM-DD)

- Batch extraction completed: N filings, M facts
- Gold standard: P=XX.X%, R=XX.X%, F1=XX.X%
- V2 review UI confirmed as primary
- Rollback: redeploy prior V2 release image (V1 routes no longer a rollback target post-cutover)
```

---

## 5. Monitoring

### Summary JSON Fields

After each batch run, inspect `logs/batch_v2_summary_*.json`:

```json
{
  "run_date": "2026-02-26T10:15:30",
  "total_filings": 250,
  "succeeded": 244,
  "failed": 6,
  "skipped": 0,
  "total_facts": 1872,
  "duration_seconds": 1830.5,
  "aborted_by_circuit_breaker": false,
  "per_filing": [...]
}
```

Key fields to watch:

| Field | What to Check |
|-------|--------------|
| `succeeded` / `total_filings` | Expect >95% success rate |
| `failed` | Any failures warrant log inspection |
| `total_facts` | Sanity-check against expected fact density |
| `aborted_by_circuit_breaker` | `true` means 10+ consecutive failures — investigate |
| `per_filing[*].error` | Individual error messages per failed filing |

### Log Pattern Monitoring

```bash
# Count errors
grep -i "ERROR\|FAILED\|circuit breaker" logs/batch_v2_cutover.log | wc -l

# Unique error types
grep -i "ERROR" logs/batch_v2_cutover.log | sort | uniq -c | sort -rn | head -20

# Check for HTML-not-found failures (most common)
grep "HTML not found" logs/batch_v2_cutover.log

# Check for database write failures
grep "persist" logs/batch_v2_cutover.log | grep -i "fail\|error"
```

### Common Failure Modes

| Failure Pattern | Likely Cause | Resolution |
|----------------|-------------|------------|
| `HTML not found: ...` | `html_storage_path` missing or file not downloaded | Download HTML first; check `filings.html_storage_path` |
| `Quality scoring failed for filing N` | Non-fatal; quality score skipped | Rerun with `--skip-quality` suppressed; check `v2_quality_scores` schema |
| `Circuit breaker triggered` | 10+ consecutive failures | Check DB connectivity, lxml parse failures; narrow with `--filing-id` |
| `PipelineError: stage N failed` | Stage-specific failure (see stage_results) | Run `--filing-id N --verbose` for detailed stage trace |
| `psycopg...connection refused` | Database not running | `docker compose ps`, `docker compose restart` |
| `JSONB serialization error` | Dict passed without `json.dumps()` | Check persistence adapter for JSONB columns |

---

## 6. Rollback Notes

V2 extraction is designed for safe rollback at any point:

- **V2 writes only to `v2_*` tables**: `v2_documents`, `v2_segments`, `v2_metric_facts`,
  `v2_metric_definitions`, `v2_quality_scores`
- **V1 data is untouched**: All V1 extraction results remain in `source_segments`, `candidates`,
  `metric_values`, and related tables
- **No schema changes required for rollback**: Simply stop invoking V2 scripts

> **Note (post-V1-cutover, 2026-04-08):** The V1 review routes at `/filings` are no longer a
> valid rollback target. They now emit warnings and redirect to the V2 UI. Rolling back means
> redeploying the prior V2 release image via the Render dashboard (or equivalent Docker rollback),
> not switching to V1 routes.

To rollback:

1. Stop any running batch extraction processes (`Ctrl+C` for graceful shutdown)
2. Redeploy the prior V2 release image via the Render dashboard (select the previous deploy and
   click "Redeploy") or via Docker by pulling and running the previous tagged image
3. No database cleanup is required — V2 tables remain but are simply not queried

If you need to clear V2 data to rerun from scratch:

```sql
-- Only run if you need a full V2 re-extraction from zero
TRUNCATE v2_quality_scores, v2_metric_facts, v2_metric_definitions,
         v2_segments, v2_documents RESTART IDENTITY CASCADE;
```

**Warning**: The TRUNCATE above is irreversible. Confirm before executing.

---

## Scripts Quick Reference

| Script | Purpose | Key Flags |
|--------|---------|-----------|
| `run_v2_extraction.py` | Single filing V2 extraction | `--filing-id`, `--accession`, `--dry-run`, `--verbose` |
| `batch_v2_extraction.py` | Batch parallel V2 extraction | `--workers`, `--limit`, `--resume-from`, `--dry-run` |
| `apply_migrations.py` | Apply DB schema migrations | (no flags) |
| `validate_against_gold_standard.py` | Compare vs gold standard | `--all`, `--company`, `--mode fresh` |
| `run_review_server.py` | Start Flask review interface | (runs on port 5000) |

---

## Additional Resources

- **V2 pipeline overview**: `docs/V2_MIGRATION_GUIDE.md`
- **Gold standard workflow**: `.claude/rules/gold-standard.md`
- **Architecture reference**: `docs/architecture/extraction-pipeline.md`
- **General setup**: `docs/operations/setup-guide.md`
- **General deployment**: `docs/operations/v2-deployment-guide.md` (this file; pre-V2 guide archived at `docs/archive/ops/deployment-guide-pre-v2.md`)
- **Ops context**: `ops/ITERATION_CONTEXT.md`
