# Deployment Guide

**Version:** 3.0
**Last Updated:** 2026-02-05

---

## Overview

This guide covers deploying the system for production-scale processing of 20,500+ SEC filings using PostgreSQL-backed infrastructure and the real extraction pipeline.

**Deployment Phases:**
1. Environment setup
2. Pilot run (100 filings)
3. First production batch (S-1s 2024)
4. Full S-1 processing (10 years)
5. 10-K processing (3 years)

---

## Pre-Deployment Checklist

### ✅ Code Readiness
- [ ] All unit tests passing (`pytest -v`)
- [ ] Integration tests passing (`pytest tests/integration/`)
- [ ] Gold standard validation passing (`pytest -m gold_standard`)
- [ ] Code reviewed and approved
- [ ] Documentation complete
- [ ] `.gitignore` configured (exclude `.env`, cache, logs)

### ✅ Environment
- [ ] Python 3.11+ installed
- [ ] Virtual environment created and activated
- [ ] Dependencies installed (`uv sync --all-extras`)
- [ ] OpenAI API key obtained and funded
- [ ] SEC User-Agent configured (with valid email)
- [ ] PostgreSQL client tools installed (`psql`, `pg_dump`)

### ✅ Database Infrastructure
- [ ] Docker Compose installed
- [ ] PostgreSQL running (`docker compose up -d`)
- [ ] Database initialized (`python3 scripts/apply_migrations.py`)
- [ ] Connection verified (`psql $DATABASE_URL`)
- [ ] Sufficient disk space (recommend 20GB+)

### ✅ Configuration
- [ ] `.env` file created from `.env.template`
- [ ] `DATABASE_URL` set to PostgreSQL connection string
- [ ] `OPENAI_API_KEY` configured
- [ ] `SEC_USER_AGENT` includes contact email
- [ ] `config/metric_keywords.yaml` reviewed

---

## Phase 1: Pilot Run (100 Filings)

### Objective
Validate the system on a small sample before full deployment.

### Steps

1. **Start Database**
   ```bash
   # Start PostgreSQL via Docker Compose
   docker compose up -d

   # Verify connection
   psql $DATABASE_URL -c "SELECT COUNT(*) FROM companies;"
   ```

2. **Build Universe Sample**
   ```bash
   # Build universe for January 2024 (test sample)
   python3 scripts/build_universe_real.py \
       --start-date 2024-01-01 \
       --end-date 2024-01-31

   # Check results
   psql $DATABASE_URL -c "
       SELECT form_type, COUNT(*) as count
       FROM filings
       WHERE is_in_scope_phase1 = true
       GROUP BY form_type;"
   ```

3. **Download Filings**
   ```bash
   # Download first 100 pending filings
   python3 scripts/batch_download_filings.py --limit 100

   # Monitor progress
   psql $DATABASE_URL -c "
       SELECT processing_status, COUNT(*)
       FROM filings
       GROUP BY processing_status;"
   ```

4. **Run Extraction Pipeline**
   ```bash
   # Extract metrics from first 100 filings
   python3 scripts/run_extraction_pipeline.py --limit 100

   # Check extraction results
   psql $DATABASE_URL -c "
       SELECT COUNT(DISTINCT filing_id) as filings,
              COUNT(*) as metric_values
       FROM metric_values;"
   ```

5. **Review Results**
   ```bash
   # Export to CSV for manual review
   python3 scripts/export_review_decisions.py \
       --status all \
       --output data/exports/pilot_metrics.csv

   # Check quality metrics
   psql $DATABASE_URL -c "
       SELECT
           AVG(confidence_score) as avg_confidence,
           COUNT(*) FILTER (WHERE confidence_score >= 0.8) as high_conf,
           COUNT(*) FILTER (WHERE confidence_score < 0.8) as low_conf
       FROM metric_values;"
   ```

6. **Manual QA Sample**
   - Select 10 random filings
   - Use web review interface: `python3 scripts/run_review_server.py`
   - Manually verify metrics against actual SEC filings
   - Compare against gold standard: `python3 scripts/validate_against_gold_standard.py --all`

7. **Go/No-Go Decision**
   - ✅ Success rate > 95%
   - ✅ Cost per filing < $0.20
   - ✅ Precision > 90% (vs gold standard)
   - ✅ Recall > 80% (vs gold standard)
   - ✅ No critical bugs

   **If not meeting criteria:** Debug, iterate, re-run pilot

---

## Phase 2: S-1 Processing (2024)

### Objective
Process all 2024 S-1/F-1 filings (~200-300 filings)

### Steps

1. **Build 2024 Universe**
   ```bash
   python3 scripts/build_universe_real.py \
       --start-date 2024-01-01 \
       --end-date 2024-12-31

   # Expected: ~250-300 S-1/F-1 filings
   ```

2. **Download All 2024 Filings**
   ```bash
   python3 scripts/batch_download_filings.py \
       --year 2024 \
       --limit 500 \
       2>&1 | tee logs/2024_download.log
   ```

3. **Run Extraction**
   ```bash
   # Extract from all fetched 2024 filings
   python3 scripts/run_extraction_pipeline.py \
       --limit 500 \
       2>&1 | tee logs/2024_extraction.log
   ```

4. **Expected Metrics**
   - Filings: ~250
   - Time: ~2-4 hours
   - Cost: ~$25-50
   - Metrics: ~3,750-6,250

5. **Monitor for Issues**
   ```bash
   # Check processing status
   psql $DATABASE_URL -c "
       SELECT processing_status, COUNT(*)
       FROM filings
       WHERE EXTRACT(YEAR FROM filing_date) = 2024
       GROUP BY processing_status;"

   # Check for extraction failures
   psql $DATABASE_URL -c "
       SELECT COUNT(*) as failed_filings
       FROM filings f
       WHERE f.processing_status = 'fetched'
         AND NOT EXISTS (
             SELECT 1 FROM metric_values mv
             WHERE mv.filing_id = f.filing_id
         )
         AND EXTRACT(YEAR FROM f.filing_date) = 2024;"
   ```

6. **Retry Failed Extractions**
   ```bash
   # Get failed filing IDs and retry
   python3 scripts/reextract_all_filings.py \
       --limit 50 \
       --dry-run  # Preview first

   # Then execute
   python3 scripts/reextract_all_filings.py --limit 50
   ```

7. **Export Results**
   ```bash
   # Create export directory
   mkdir -p data/exports/2024_s1/

   # Export all accepted metrics
   python3 scripts/export_review_decisions.py \
       --status accepted \
       --format csv \
       --output data/exports/2024_s1/metrics.csv

   # Export as JSON for analysis
   python3 scripts/export_review_decisions.py \
       --status all \
       --format json \
       --output data/exports/2024_s1/all_decisions.json
   ```

---

## Phase 3: Full S-1 Processing (10 Years)

### Objective
Process all S-1/F-1 filings from 2015-2024

### Strategy
Process year by year to enable checkpointing and monitoring.

### Execution

1. **Build Full Universe**
   ```bash
   # Build universe for 10 years (2015-2024)
   python3 scripts/build_universe_real.py \
       --start-date 2015-01-01 \
       --end-date 2024-12-31 \
       2>&1 | tee logs/universe_full.log

   # Check total scope
   psql $DATABASE_URL -c "
       SELECT
           EXTRACT(YEAR FROM filing_date) as year,
           COUNT(*) as filings
       FROM filings
       WHERE is_in_scope_phase1 = true
       GROUP BY year
       ORDER BY year;"
   ```

2. **Download Year by Year**
   ```bash
   # Download all pending filings in batches
   for year in {2015..2024}; do
       echo "Downloading filings for $year"

       python3 scripts/batch_download_filings.py \
           --year $year \
           --limit 500 \
           2>&1 | tee logs/download_${year}.log

       # Check if successful
       if [ $? -eq 0 ]; then
           echo "$year download completed successfully"
       else
           echo "$year download failed, check logs"
           break
       fi

       # Brief pause between years
       sleep 30
   done
   ```

3. **Extract Year by Year**
   ```bash
   # Extract metrics for all fetched filings
   # Process in smaller batches to enable resume capability
   for batch in {1..10}; do
       echo "Processing batch $batch"

       python3 scripts/run_extraction_pipeline.py \
           --limit 250 \
           2>&1 | tee logs/extract_batch_${batch}.log

       sleep 30
   done
   ```

4. **Expected Totals (10 Years)**
   - Filings: ~2,500
   - Time: ~10-15 hours (download + extraction)
   - Cost: $125-250
   - Metrics: ~50,000-75,000

5. **Monitor Progress**
   ```bash
   # Check progress periodically
   watch -n 60 "psql $DATABASE_URL -c \"
       SELECT
           EXTRACT(YEAR FROM f.filing_date) as year,
           COUNT(*) as total_filings,
           COUNT(*) FILTER (WHERE f.processing_status = 'fetched') as fetched,
           COUNT(DISTINCT mv.filing_id) as extracted
       FROM filings f
       LEFT JOIN metric_values mv ON f.filing_id = mv.filing_id
       WHERE f.is_in_scope_phase1 = true
       GROUP BY year
       ORDER BY year;\""
   ```

6. **Handle Interruptions**
   ```bash
   # If process crashes or is stopped, check progress
   psql $DATABASE_URL -c "
       SELECT
           MAX(created_at) as last_extraction,
           COUNT(*) as total_extracted
       FROM metric_values;"

   # Resume extraction from where it stopped
   # Script automatically skips already-processed filings
   python3 scripts/run_extraction_pipeline.py --limit 2500
   ```

7. **Validate Against Gold Standard**
   ```bash
   # Run validation for all companies with gold standard data
   python3 scripts/validate_against_gold_standard.py \
       --all \
       --output data/validation/full_validation.json

   # Review precision/recall metrics
   python3 scripts/validate_against_gold_standard.py \
       --all \
       --verbose
   ```

---

## Phase 4: 10-K Processing (3 Years)

### Objective
Process all 10-K filings from 2022-2024

### Preparation

1. **Review Metric Configuration**
   ```bash
   # Review metric keywords for 10-K relevance
   # Edit config/metric_keywords.yaml if needed
   # 10-Ks may use different terminology than S-1s
   cat config/metric_keywords.yaml
   ```

2. **Test on Sample**
   ```bash
   # Build small universe for testing
   python3 scripts/build_universe_real.py \
       --start-date 2024-01-01 \
       --end-date 2024-03-31

   # Download 10-Ks only (modify query if needed)
   python3 scripts/batch_download_filings.py --limit 50

   # Extract and review
   python3 scripts/run_extraction_pipeline.py --limit 50
   ```

3. **Review and Adjust**
   ```bash
   # Check extraction quality
   psql $DATABASE_URL -c "
       SELECT
           f.form_type,
           AVG(mv.confidence_score) as avg_confidence,
           COUNT(*) as metric_count
       FROM metric_values mv
       JOIN filings f ON mv.filing_id = f.filing_id
       WHERE f.form_type LIKE '10-K%'
       GROUP BY f.form_type;"

   # Adjust keywords/prompts if needed
   # Re-test with reextraction script
   ```

### Execution

1. **Build 10-K Universe**
   ```bash
   # Note: build_universe_real.py currently focuses on S-1/F-1
   # May need to extend for 10-K support or query directly
   # For now, this is a placeholder for future 10-K support

   echo "10-K processing requires extension of universe builder"
   echo "See CLAUDE.md for Phase 2+ roadmap"
   ```

2. **Expected Totals (3 Years) - FUTURE**
   - Filings: ~18,000
   - Time: ~30-50 hours
   - Cost: $900-1,800
   - Metrics: ~300,000-450,000

   *Note: 10-K processing is planned for Phase 2. Current system focuses on S-1/F-1 filings.*

---

## Production Best Practices

### 1. Backup Strategy

```bash
# Before major runs, backup database
pg_dump $DATABASE_URL > data/backups/filings_db_$(date +%Y%m%d).sql

# Compressed backup
pg_dump $DATABASE_URL | gzip > data/backups/filings_db_$(date +%Y%m%d).sql.gz

# Backup config
cp -r config/ data/backups/config_$(date +%Y%m%d)/

# Backup logs
tar -czf data/backups/logs_$(date +%Y%m%d).tar.gz logs/

# Restore from backup if needed
psql $DATABASE_URL < data/backups/filings_db_20260205.sql
```

### 2. Database Maintenance

```bash
# Check database size
psql $DATABASE_URL -c "
    SELECT
        pg_size_pretty(pg_database_size(current_database())) as db_size;"

# Vacuum and analyze for performance
psql $DATABASE_URL -c "VACUUM ANALYZE;"

# Check table sizes
psql $DATABASE_URL -c "
    SELECT
        schemaname,
        tablename,
        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
    FROM pg_tables
    WHERE schemaname = 'public'
    ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
    LIMIT 10;"
```

### 3. Logging

All scripts automatically log to timestamped files in `logs/`:
- `logs/extraction_YYYYMMDD_HHMMSS.log` - Extraction runs
- `logs/batch_download_YYYYMMDD_HHMMSS.log` - Download runs
- `logs/reextract_progress.json` - Reextraction checkpoint

```bash
# Monitor extraction in real-time
tail -f logs/extraction_$(date +%Y%m%d)_*.log

# Count errors
grep -i error logs/extraction_*.log | wc -l

# Extract unique errors
grep -i error logs/extraction_*.log | sort | uniq -c | sort -rn
```

### 4. Error Monitoring

```bash
# Check for processing failures
psql $DATABASE_URL -c "
    SELECT
        f.processing_status,
        COUNT(*) as count
    FROM filings f
    GROUP BY f.processing_status
    ORDER BY count DESC;"

# Identify filings that failed extraction
psql $DATABASE_URL -c "
    SELECT
        f.filing_id,
        f.company_id,
        f.accession_number,
        f.filing_date
    FROM filings f
    WHERE f.processing_status = 'fetched'
      AND NOT EXISTS (
          SELECT 1 FROM metric_values mv
          WHERE mv.filing_id = f.filing_id
      )
    LIMIT 20;"
```

### 5. Cost Monitoring

```bash
# Track OpenAI API costs
# Note: Cost tracking is embedded in LLM client with SQLite cache
# Monitor via OpenAI dashboard: https://platform.openai.com/usage

# Estimate costs per filing
psql $DATABASE_URL -c "
    SELECT
        COUNT(DISTINCT filing_id) as filings_with_metrics,
        COUNT(*) as total_metrics,
        ROUND(COUNT(*)::numeric / COUNT(DISTINCT filing_id), 2) as avg_metrics_per_filing
    FROM metric_values;"

# Expected cost: ~$0.10-0.20 per filing for GPT-4o
# Bulk processing: ~$250-500 per 2,500 filings
```

### 6. Progress Dashboard

Use the web review interface for real-time monitoring:

```bash
# Start review server
python3 scripts/run_review_server.py

# Access at http://localhost:5000
# Review interface shows:
# - Total filings processed
# - Metrics extracted
# - Review status
# - Quality metrics
```

Or query database directly:

```bash
# Real-time stats query
psql $DATABASE_URL -c "
    WITH stats AS (
        SELECT
            COUNT(DISTINCT f.filing_id) as total_filings,
            COUNT(DISTINCT mv.filing_id) as extracted_filings,
            COUNT(*) as total_metrics,
            AVG(mv.confidence_score) as avg_confidence
        FROM filings f
        LEFT JOIN metric_values mv ON f.filing_id = mv.filing_id
        WHERE f.is_in_scope_phase1 = true
    )
    SELECT
        total_filings,
        extracted_filings,
        total_filings - extracted_filings as pending,
        total_metrics,
        ROUND(avg_confidence::numeric, 3) as avg_confidence,
        ROUND(total_metrics::numeric / NULLIF(extracted_filings, 0), 1) as metrics_per_filing
    FROM stats;"
```

### 7. Health Checks

```bash
# Create a health check script
cat > scripts/health_check.sh <<'EOF'
#!/bin/bash

# Check database is accessible
psql $DATABASE_URL -c "SELECT 1" > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Database not accessible"
    exit 1
fi

# Check disk space
SPACE=$(df -h $(pwd) | awk 'NR==2 {print $5}' | sed 's/%//')
if [ $SPACE -gt 90 ]; then
    echo "WARNING: Disk space > 90%"
fi

# Check OpenAI API key
if [ -z "$OPENAI_API_KEY" ]; then
    echo "ERROR: OPENAI_API_KEY not set"
    exit 1
fi

# Check Docker container running
docker compose ps | grep postgres | grep Up > /dev/null
if [ $? -ne 0 ]; then
    echo "ERROR: PostgreSQL container not running"
    exit 1
fi

echo "Health check passed"
EOF

chmod +x scripts/health_check.sh
./scripts/health_check.sh
```

---

## Troubleshooting

### Issue: High Download Failure Rate

```bash
# Check download status
psql $DATABASE_URL -c "
    SELECT processing_status, COUNT(*)
    FROM filings
    GROUP BY processing_status;"

# Common causes:
# - Rate limiting: SEC enforces 100ms between requests
# - Invalid URLs: Check sec_html_url is valid
# - Network issues: Retry with batch_download_filings.py
```

### Issue: Low Extraction Quality

```bash
# Check average confidence scores
psql $DATABASE_URL -c "
    SELECT
        AVG(confidence_score) as avg_confidence,
        MIN(confidence_score) as min_confidence,
        MAX(confidence_score) as max_confidence,
        COUNT(*) FILTER (WHERE confidence_score < 0.7) as low_confidence_count
    FROM metric_values;"

# If avg_confidence < 0.7:
# - Review config/metric_keywords.yaml for keyword accuracy
# - Run gold standard validation to identify issues
# - Check LLM prompts in src/extraction/ for improvements
```

### Issue: Database Connection Errors

```bash
# Check Docker container status
docker compose ps

# Restart PostgreSQL
docker compose restart

# Check logs
docker compose logs postgres

# Verify DATABASE_URL in .env
echo $DATABASE_URL

# Test connection
psql $DATABASE_URL -c "SELECT version();"
```

### Issue: Slow Processing

```bash
# Check processing rate
# Should process ~5-10 filings/minute

# Causes:
# - Database connection pooling issues
# - OpenAI API rate limits
# - Large filing sizes

# Solutions:
# - Process in smaller batches (--limit 50)
# - Monitor OpenAI tier limits
# - Use --csv-only flag to skip database writes during testing
```

### Issue: Out of Disk Space

```bash
# Check space usage
df -h

# Clean up old logs
find logs/ -name "*.log" -mtime +30 -delete

# Clean up old backups
find data/backups/ -name "*.sql.gz" -mtime +90 -delete

# Vacuum database to reclaim space
psql $DATABASE_URL -c "VACUUM FULL;"
```

---

## Post-Processing

### 1. Data Validation

```bash
# Run gold standard validation
python3 scripts/validate_against_gold_standard.py \
    --all \
    --output data/validation/final_validation.json \
    --verbose

# Review results
cat data/validation/final_validation.json | jq '.summary'

# Expected metrics:
# - Precision > 90%
# - Recall > 80%
# - F1 > 85%
```

### 2. Export Final Dataset

```bash
# Create export directory
mkdir -p data/final_export/

# Export all accepted decisions
python3 scripts/export_review_decisions.py \
    --status accepted \
    --format csv \
    --output data/final_export/customer_metrics.csv

# Export all decisions (including rejected) for analysis
python3 scripts/export_review_decisions.py \
    --status all \
    --format csv \
    --output data/final_export/all_decisions.csv

# Export as JSON for programmatic access
python3 scripts/export_review_decisions.py \
    --status accepted \
    --format json \
    --output data/final_export/customer_metrics.json
```

### 3. Generate Summary Report

```bash
# Query summary statistics
psql $DATABASE_URL -c "
    SELECT
        'Total Companies' as metric,
        COUNT(DISTINCT company_id)::text as value
    FROM companies
    UNION ALL
    SELECT
        'Total Filings',
        COUNT(*)::text
    FROM filings
    WHERE is_in_scope_phase1 = true
    UNION ALL
    SELECT
        'Filings Processed',
        COUNT(DISTINCT filing_id)::text
    FROM metric_values
    UNION ALL
    SELECT
        'Total Metrics Extracted',
        COUNT(*)::text
    FROM metric_values
    UNION ALL
    SELECT
        'Avg Confidence Score',
        ROUND(AVG(confidence_score)::numeric, 3)::text
    FROM metric_values
    UNION ALL
    SELECT
        'Date Range',
        MIN(filing_date)::text || ' to ' || MAX(filing_date)::text
    FROM filings
    WHERE is_in_scope_phase1 = true;" \
    > data/final_export/summary.txt

cat data/final_export/summary.txt
```

### 4. Archive Project State

```bash
# Create archive directory with timestamp
ARCHIVE_DIR="data/archives/production_run_$(date +%Y%m%d)"
mkdir -p $ARCHIVE_DIR

# Backup database
pg_dump $DATABASE_URL | gzip > $ARCHIVE_DIR/database.sql.gz

# Copy exports
cp -r data/final_export/ $ARCHIVE_DIR/

# Copy config
cp -r config/ $ARCHIVE_DIR/

# Copy logs
tar -czf $ARCHIVE_DIR/logs.tar.gz logs/

# Copy validation results
cp -r data/validation/ $ARCHIVE_DIR/

echo "Archive created at: $ARCHIVE_DIR"
```

---

## Final Checklist

### ✅ Deployment Complete When:
- [ ] All filings processed (S-1/F-1: 10 years)
- [ ] Success rate > 95%
- [ ] Total cost within budget
- [ ] Gold standard validation: precision > 90%, recall > 80%
- [ ] Database exported to CSV/JSON
- [ ] Summary report generated
- [ ] Data backed up
- [ ] Code archived with git tag

### ✅ Deliverables:
- [ ] `customer_metrics.csv` - Main output (accepted metrics)
- [ ] `all_decisions.csv` - Complete decision log
- [ ] `customer_metrics.json` - JSON export for APIs
- [ ] `final_validation.json` - Gold standard comparison
- [ ] `summary.txt` - Summary statistics
- [ ] Database backup (`.sql.gz`)
- [ ] Codebase snapshot (git tag)
- [ ] Documentation

---

## Long-Term Maintenance

### Quarterly Updates

```bash
# Build universe for new quarter
python3 scripts/build_universe_real.py \
    --start-date 2026-01-01 \
    --end-date 2026-03-31

# Download new filings
python3 scripts/batch_download_filings.py --limit 200

# Extract metrics
python3 scripts/run_extraction_pipeline.py --limit 200

# Validate and export
python3 scripts/validate_against_gold_standard.py --all
python3 scripts/export_review_decisions.py \
    --status accepted \
    --output data/exports/Q1_2026_metrics.csv
```

### Config Updates

```bash
# Update metric keywords as new metrics emerge
vim config/metric_keywords.yaml

# Test changes on sample
python3 scripts/run_extraction_pipeline.py --limit 10 --csv-only

# Validate changes
pytest -m gold_standard --gold-standard-mode=fresh -v

# If validation passes, re-extract all filings
python3 scripts/reextract_all_filings.py --dry-run
python3 scripts/reextract_all_filings.py
```

### Database Optimization

```bash
# Monthly maintenance
psql $DATABASE_URL -c "VACUUM ANALYZE;"

# Quarterly backup
pg_dump $DATABASE_URL | gzip > \
    data/backups/quarterly_backup_$(date +%Y%m%d).sql.gz

# Annual archival
# Archive old data to separate tables or files
# Maintain rolling 3-year window for active analysis
```

### Cost Optimization

- Monitor OpenAI pricing updates
- Consider batch API for large re-extractions
- Evaluate GPT-4o-mini vs GPT-4o trade-offs
- Review keyword filtering to minimize LLM calls

---

## Success Criteria

### Technical Success
✅ Processed 2,500+ S-1/F-1 filings (2015-2024)
✅ Success rate > 95%
✅ Total cost < $500 for full S-1 corpus
✅ Average processing time < 10 sec/filing

### Quality Success
✅ Extracted 50,000-75,000 metrics
✅ Precision > 90% (vs gold standard)
✅ Recall > 80% (vs gold standard)
✅ F1 Score > 85%

### Business Success
✅ Usable dataset for CMASB research
✅ Web review interface operational
✅ Export pipeline working
✅ Documentation complete

---

## Additional Resources

### Key Scripts Reference

| Script | Purpose | Key Flags |
|--------|---------|-----------|
| `build_universe_real.py` | Discover filings from SEC EDGAR | `--start-date`, `--end-date`, `--dry-run` |
| `batch_download_filings.py` | Download HTML/TXT files | `--limit`, `--year`, `--dry-run` |
| `run_extraction_pipeline.py` | Extract metrics from filings | `--limit`, `--cik`, `--accession`, `--csv-only` |
| `reextract_all_filings.py` | Re-run extraction on all filings | `--dry-run`, `--limit`, `--resume-from` |
| `export_review_decisions.py` | Export metrics to CSV/JSON | `--status`, `--format`, `--output` |
| `validate_against_gold_standard.py` | Compare vs gold standard | `--all`, `--company`, `--mode fresh` |
| `run_review_server.py` | Start web review interface | (no flags, runs on port 5000) |
| `apply_migrations.py` | Initialize database schema | (no flags) |

### Database Schema Key Tables

- `companies` - Company master data
- `filings` - Filing metadata with processing status
- `source_segments` - HTML segments from filings
- `metrics` - Canonical metric taxonomy (dimension table)
- `metric_values` - Extracted metric facts
- `metric_definitions` - Per-filing metric definitions and methodology
- `review_candidates` - Candidate metrics for human review
- `review_decisions` - Human review decisions

### Configuration Files

- `.env` - Environment variables (DATABASE_URL, OPENAI_API_KEY, etc.)
- `config/metric_keywords.yaml` - Keyword patterns for metrics (authoritative source)
- `docker-compose.yml` - PostgreSQL container config

---

**Congratulations on deploying the SEC Filings Analysis System!**

For questions or issues, refer to:
- Architecture docs: `docs/architecture/`
- CLAUDE.md: Project overview and commands
- Testing guide: `docs/development/testing.md`
- Review system: `docs/HUMAN_REVIEW_SYSTEM.md`

Or create an issue in the project repository.
