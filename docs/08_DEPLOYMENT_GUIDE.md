# Deployment Guide

**Version:** 2.0
**Last Updated:** 2025-11-14

---

## Overview

This guide covers deploying the system for production-scale processing of 20,500+ SEC filings.

**Deployment Phases:**
1. Environment setup
2. Pilot run (100 filings)
3. First production batch (S-1s 2024)
4. Full S-1 processing (10 years)
5. 10-K processing (3 years)

---

## Pre-Deployment Checklist

### ✅ Code Readiness
- [ ] All unit tests passing
- [ ] Integration tests passing
- [ ] Code reviewed and approved
- [ ] Documentation complete
- [ ] `.gitignore` configured (exclude `.env`, cache, database)

### ✅ Environment
- [ ] Python 3.11+ installed
- [ ] Virtual environment created
- [ ] Dependencies installed from `requirements.txt`
- [ ] OpenAI API key obtained and funded
- [ ] SEC User-Agent configured (with valid email)

### ✅ Storage
- [ ] `data/` directory created
- [ ] `data/cache/` directory created
- [ ] Sufficient disk space (recommend 10GB+)
- [ ] Database initialized

### ✅ Configuration
- [ ] `.env` file created with API key
- [ ] `config/s1_config.yaml` reviewed
- [ ] Rate limits configured for your OpenAI tier
- [ ] Cost limits set appropriately

---

## Phase 1: Pilot Run (100 Filings)

### Objective
Validate the system on a small sample before full deployment.

### Steps

1. **Select Pilot Dataset**
   ```bash
   # Process 100 S-1 filings from 2024
   python main.py \
       --start-date 2024-01-01 \
       --end-date 2024-12-31 \
       --filing-type S-1 \
       --workers 5 \
       --max-results 100 \
       --max-cost 10.00
   ```

2. **Monitor Progress**
   - Watch console output for errors
   - Check `data/filings_data.db` size growing
   - Monitor OpenAI API usage dashboard

3. **Review Results**
   ```bash
   # Export to CSV
   python -c "from core.storage import export_to_csv; \
              export_to_csv('metrics', 'data/exports/pilot_metrics.csv'); \
              export_to_csv('qa_warnings', 'data/exports/pilot_warnings.csv')"

   # Review in Excel or Pandas
   import pandas as pd
   metrics = pd.read_csv('data/exports/pilot_metrics.csv')
   warnings = pd.read_csv('data/exports/pilot_warnings.csv')

   print(f"Metrics extracted: {len(metrics)}")
   print(f"Avg per filing: {len(metrics) / metrics['filing_id'].nunique():.1f}")
   print(f"QA warnings: {len(warnings)}")
   ```

4. **Manual QA Sample**
   - Select 10 random filings
   - Manually verify metrics against actual SEC filings
   - Calculate precision/recall (see 07_TESTING_STRATEGY.md)

5. **Go/No-Go Decision**
   - ✅ Success rate > 95%
   - ✅ Cost per filing < $0.10
   - ✅ Precision > 90%
   - ✅ Recall > 80%
   - ✅ No critical bugs

   **If not meeting criteria:** Debug, iterate, re-run pilot

---

## Phase 2: S-1 Processing (2024)

### Objective
Process all 2024 S-1 filings (~200-300 filings)

### Steps

1. **Run 2024 Batch**
   ```bash
   python main.py \
       --start-date 2024-01-01 \
       --end-date 2024-12-31 \
       --filing-type S-1 \
       --workers 10 \
       --max-cost 50.00 \
       2>&1 | tee logs/2024_s1_run.log
   ```

2. **Expected Metrics**
   - Filings: ~250
   - Time: ~1-2 hours
   - Cost: ~$8-15
   - Metrics: ~3,750-6,250

3. **Monitor for Issues**
   ```bash
   # Check failures
   sqlite3 data/filings_data.db \
       "SELECT COUNT(*) FROM failed_filings WHERE resolved = 0;"

   # Check cost
   sqlite3 data/filings_data.db \
       "SELECT SUM(cost_usd) FROM cost_tracking;"
   ```

4. **Retry Failed Filings**
   ```bash
   # After batch completes, retry failures
   python main.py --retry-failed
   ```

5. **Export Results**
   ```bash
   # Export all data
   python scripts/export_all.py --output data/exports/2024_s1/
   ```

---

## Phase 3: Full S-1 Processing (10 Years)

### Objective
Process all S-1 filings from 2015-2024

### Strategy
Process year by year to enable checkpointing and monitoring.

### Execution

1. **Process Each Year**
   ```bash
   for year in {2015..2024}; do
       echo "Processing S-1 filings for $year"

       python main.py \
           --start-date ${year}-01-01 \
           --end-date ${year}-12-31 \
           --filing-type S-1 \
           --workers 10 \
           --max-cost 100.00 \
           2>&1 | tee logs/${year}_s1_run.log

       # Check if successful
       if [ $? -eq 0 ]; then
           echo "$year completed successfully"
       else
           echo "$year failed, check logs"
           break
       fi

       # Brief pause between years
       sleep 60
   done
   ```

2. **Expected Totals (10 Years)**
   - Filings: ~2,500
   - Time: ~6-10 hours
   - Cost: $75-150
   - Metrics: ~50,000-75,000

3. **Monitor Progress**
   ```bash
   # Check progress periodically
   watch -n 60 "sqlite3 data/filings_data.db \
       'SELECT filing_type, \
               COUNT(*) as filings, \
               SUM(metrics_extracted) as metrics, \
               ROUND(SUM(total_cost_usd), 2) as cost \
        FROM execution_log \
        WHERE status = \"completed\" \
        GROUP BY filing_type;'"
   ```

4. **Handle Interruptions**
   ```bash
   # If process crashes or is stopped, resume:
   # Check last completed date
   sqlite3 data/filings_data.db \
       "SELECT MAX(date_range_end) FROM execution_log WHERE status = 'completed';"

   # Resume from next date
   python main.py \
       --start-date 2018-01-01 \  # Example: resume from 2018
       --end-date 2024-12-31 \
       --filing-type S-1 \
       --workers 10
   ```

---

## Phase 4: 10-K Processing (3 Years)

### Objective
Process all 10-K filings from 2022-2024

### Preparation

1. **Review 10-K Config**
   ```bash
   # Edit config/10k_config.yaml
   # Adjust keywords and metrics for annual reports
   ```

2. **Test on Sample**
   ```bash
   # Test with 50 10-Ks first
   python main.py \
       --start-date 2024-01-01 \
       --end-date 2024-12-31 \
       --filing-type 10-K \
       --workers 5 \
       --max-results 50 \
       --max-cost 10.00
   ```

3. **Review and Adjust**
   - Check if extraction quality is similar to S-1s
   - Adjust keywords/prompts if needed
   - Re-test

### Execution

1. **Process 10-Ks Year by Year**
   ```bash
   for year in {2022..2024}; do
       echo "Processing 10-K filings for $year"

       python main.py \
           --start-date ${year}-01-01 \
           --end-date ${year}-12-31 \
           --filing-type 10-K \
           --workers 10 \
           --max-cost 500.00 \  # 10-Ks are larger, higher budget
           2>&1 | tee logs/${year}_10k_run.log

       sleep 60
   done
   ```

2. **Expected Totals (3 Years)**
   - Filings: ~18,000
   - Time: ~24-48 hours
   - Cost: $540-1,080
   - Metrics: ~300,000-450,000

---

## Production Best Practices

### 1. Backup Strategy

```bash
# Before major runs, backup database
cp data/filings_data.db data/backups/filings_data_$(date +%Y%m%d).db

# Backup config
cp -r config/ data/backups/config_$(date +%Y%m%d)/

# Backup logs
tar -czf data/backups/logs_$(date +%Y%m%d).tar.gz logs/
```

### 2. Logging

**Configure logging** in `main.py`:
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'logs/run_{datetime.now():%Y%m%d_%H%M%S}.log'),
        logging.StreamHandler()
    ]
)
```

### 3. Error Monitoring

```bash
# Monitor error log in real-time
tail -f logs/run_*.log | grep -i error

# Count errors
grep -i error logs/run_*.log | wc -l

# Extract unique errors
grep -i error logs/run_*.log | sort | uniq -c | sort -rn
```

### 4. Cost Monitoring

```python
# Real-time cost tracking script
# scripts/monitor_cost.py

import sqlite3
import time

db = sqlite3.connect('data/filings_data.db')

while True:
    cursor = db.execute("""
        SELECT
            SUM(cost_usd) as total_cost,
            COUNT(*) as api_calls,
            SUM(input_tokens + output_tokens) as total_tokens
        FROM cost_tracking
        WHERE created_at > datetime('now', '-1 hour')
    """)

    cost, calls, tokens = cursor.fetchone()

    print(f"\nLast Hour:")
    print(f"  Cost: ${cost:.2f}")
    print(f"  API Calls: {calls}")
    print(f"  Tokens: {tokens:,}")

    time.sleep(300)  # Update every 5 min
```

### 5. Progress Dashboard

```python
# scripts/dashboard.py
# Real-time progress monitoring

from rich.console import Console
from rich.table import Table
from rich.live import Live
import sqlite3
import time

def generate_table():
    db = sqlite3.connect('data/filings_data.db')

    # Get stats
    stats = db.execute("""
        SELECT
            filing_type,
            SUM(filings_processed) as processed,
            SUM(filings_failed) as failed,
            ROUND(SUM(total_cost_usd), 2) as cost,
            SUM(metrics_extracted) as metrics
        FROM execution_log
        WHERE status = 'completed'
        GROUP BY filing_type
    """).fetchall()

    table = Table(title="Extraction Progress")
    table.add_column("Filing Type")
    table.add_column("Processed")
    table.add_column("Failed")
    table.add_column("Cost")
    table.add_column("Metrics")

    for row in stats:
        table.add_row(*[str(x) for x in row])

    return table

with Live(generate_table(), refresh_per_second=0.1) as live:
    while True:
        time.sleep(10)
        live.update(generate_table())
```

### 6. Health Checks

```bash
# scripts/health_check.sh
# Run periodically to ensure system health

#!/bin/bash

# Check database is accessible
sqlite3 data/filings_data.db "SELECT 1" > /dev/null
if [ $? -ne 0 ]; then
    echo "ERROR: Database not accessible"
    exit 1
fi

# Check disk space
SPACE=$(df -h data/ | awk 'NR==2 {print $5}' | sed 's/%//')
if [ $SPACE -gt 90 ]; then
    echo "WARNING: Disk space > 90%"
fi

# Check OpenAI API key
if [ -z "$OPENAI_API_KEY" ]; then
    echo "ERROR: OPENAI_API_KEY not set"
    exit 1
fi

echo "Health check passed"
```

---

## Troubleshooting

### Issue: High Failure Rate

```bash
# Check failure reasons
sqlite3 data/filings_data.db \
    "SELECT error_type, COUNT(*) \
     FROM failed_filings \
     WHERE resolved = 0 \
     GROUP BY error_type;"

# Common causes:
# - transient: Network issues, retry
# - permanent: Bad URLs, skip
# - extraction: LLM issues, review prompts
```

### Issue: Cost Overrun

```bash
# Check cost per filing
sqlite3 data/filings_data.db \
    "SELECT AVG(cost_usd) FROM cost_tracking;"

# If > $0.10:
# - Check if GPT-4o being used too much
# - Verify keyword filtering is working
# - Check for repeated processing (deduplication issue)
```

### Issue: Low Quality Extractions

```bash
# Check average confidence
sqlite3 data/filings_data.db \
    "SELECT AVG(confidence) FROM metrics;"

# If < 0.7:
# - Review QA warnings
# - Check if LLM prompts need adjustment
# - Verify table extraction is working
```

### Issue: Slow Processing

```bash
# Check processing rate
# Should be ~5-10 filings/minute with 10 workers

# Causes:
# - Rate limiting too conservative
# - Network latency
# - Workers set too low

# Solution: Increase workers carefully
python main.py --workers 15  # Test with more workers
```

---

## Post-Processing

### 1. Data Validation

```python
# scripts/validate_final_data.py

import pandas as pd
import sqlite3

db = sqlite3.connect('data/filings_data.db')

# Load metrics
metrics = pd.read_sql("SELECT * FROM metrics", db)

print(f"Total metrics: {len(metrics):,}")
print(f"Unique filings: {metrics['filing_id'].nunique():,}")
print(f"Date range: {metrics['filing_date'].min()} to {metrics['filing_date'].max()}")
print(f"\nMetrics by type:")
print(metrics['metric_name'].value_counts().head(20))

# Check for anomalies
print(f"\nNegative values: {(metrics['value_numeric'] < 0).sum()}")
print(f"Null periods: {metrics['period'].isna().sum()}")
print(f"Low confidence (<0.5): {(metrics['confidence'] < 0.5).sum()}")
```

### 2. Export Final Dataset

```bash
# Export everything
python scripts/export_all.py \
    --output data/final_export/ \
    --format csv \
    --include-qa-warnings \
    --include-keywords
```

### 3. Generate Report

```python
# scripts/generate_report.py

# Create PDF report with:
# - Total filings processed
# - Success rate
# - Total cost
# - Metrics extracted
# - Quality metrics
# - Top warnings
# - Recommendations
```

---

## Final Checklist

### ✅ Deployment Complete When:
- [ ] All filings processed (S-1: 10 years, 10-K: 3 years)
- [ ] Success rate > 95%
- [ ] Total cost within budget
- [ ] QA sample validated (precision > 90%, recall > 80%)
- [ ] Database exported to CSV
- [ ] Report generated
- [ ] Data backed up
- [ ] Code archived

### ✅ Deliverables:
- [ ] `customer_metrics.csv` - Main output
- [ ] `qa_warnings.csv` - Quality warnings
- [ ] `execution_log.csv` - Processing history
- [ ] Final report PDF
- [ ] Codebase snapshot
- [ ] Documentation

---

## Long-Term Maintenance

### Quarterly Updates
```bash
# Run quarterly to capture new filings
python main.py \
    --start-date 2025-01-01 \
    --end-date 2025-03-31 \
    --filing-type S-1,10-K \
    --workers 10
```

### Config Updates
- Update keywords as new metrics emerge
- Adjust LLM prompts based on QA feedback
- Add new filing types (10-Q, 8-K) if needed

### Cost Optimization
- Review if GPT-4o-mini remains cheapest option
- Check if OpenAI releases new models
- Consider batch API for large updates

---

## Success Criteria

### Technical Success
✅ Processed 20,500+ filings
✅ Success rate > 95%
✅ Total cost < $1,500
✅ Average processing time < 8 sec/filing

### Business Success
✅ Extracted 300,000-500,000 metrics
✅ Precision > 90%
✅ Recall > 80%
✅ Usable dataset for research

---

**Congratulations on deploying the SEC Filings Analysis System!**

For questions or issues, refer back to the architecture docs or create an issue in the project repository.
