# Batch Ingestion for Transcripts and Presentations

This document covers the batch ingestion system for earnings call transcripts and investor presentations (Beyond SEC feature set, `earnings-call-exploration` branch).

## Overview

The ingestion pipeline fetches documents from external sources, runs them through the V2 pipeline, and optionally persists extracted facts to the database. Three scripts are provided:

| Script | Purpose |
|--------|---------|
| `scripts/ingest_transcripts.py` | Fetch and process earnings call transcripts |
| `scripts/ingest_presentations.py` | Fetch and process investor presentations from SEC EDGAR |
| `scripts/ingest_all.py` | Unified wrapper — runs both in sequence |

A monitoring script (`scripts/check_new_documents.py`) checks for unprocessed documents without ingesting them.

---

## Sources and Requirements

### Transcripts

Two sources are supported:

| Source | Flag | API Key Required | Notes |
|--------|------|-----------------|-------|
| HuggingFace (`kurry/earnings-call-transcripts`) | `--source huggingface` | No | Free; requires network access |
| Financial Modeling Prep (FMP) | `--source fmp` | Yes (`FMP_API_KEY`) | Paid API; more recent data |

Set the FMP key in environment:
```bash
export FMP_API_KEY=your_key_here
```

### Presentations

Presentations are fetched from SEC EDGAR 8-K filings:

| Requirement | Details |
|-------------|---------|
| Network access | Required — connects to `data.sec.gov` |
| API key | None — EDGAR is public |
| `pdfplumber` | Required — converts PDFs to HTML |

SEC EDGAR rate-limits requests. The source automatically respects the 10 req/s limit.

### Database

All scripts default to **dry-run mode** (no DB writes). To persist results:
```bash
export DATABASE_URL=postgresql://user:pass@host/dbname
```
Then add `--persist` to the command.

---

## CLI Usage

### ingest_transcripts.py

```bash
# Dry run — shows what would be ingested, no DB writes
python3 scripts/ingest_transcripts.py \
    --source huggingface \
    --tickers CRM ADBE MSFT \
    --dry-run

# Persist to database
python3 scripts/ingest_transcripts.py \
    --source huggingface \
    --tickers CRM ADBE MSFT

# Use FMP source, limit to 3 transcripts per ticker
python3 scripts/ingest_transcripts.py \
    --source fmp \
    --tickers CRM \
    --limit 3

# Resume after interruption
python3 scripts/ingest_transcripts.py \
    --source huggingface \
    --tickers CRM ADBE \
    --resume

# Circuit breaker: abort after 5 consecutive failures
python3 scripts/ingest_transcripts.py \
    --source huggingface \
    --tickers CRM ADBE \
    --max-failures 5
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--source` | (required) | `huggingface` or `fmp` |
| `--tickers` | (required) | One or more ticker symbols |
| `--limit N` | 5 | Max transcripts per ticker |
| `--dry-run` | off | Run pipeline but skip DB writes |
| `--resume` | off | Skip tickers already in progress file |
| `--max-failures N` | None | Circuit breaker threshold |

### ingest_presentations.py

```bash
# Dry run
python3 scripts/ingest_presentations.py \
    --ticker CRM ADBE MSFT \
    --limit 2 \
    --dry-run

# Persist to database
python3 scripts/ingest_presentations.py \
    --ticker CRM ADBE MSFT \
    --persist

# Resume after interruption
python3 scripts/ingest_presentations.py \
    --ticker CRM \
    --resume
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--ticker` | (required) | One or more ticker symbols |
| `--limit N` | 5 | Max presentations per ticker |
| `--dry-run` | on | Run pipeline but skip DB writes (default) |
| `--persist` | off | Write results to the database |
| `--resume` | off | Skip tickers already in progress file |
| `--max-failures N` | None | Circuit breaker threshold |

### ingest_all.py (unified wrapper)

Runs both transcript and presentation ingestion in sequence and prints a combined summary.

```bash
# Run both sources for given tickers (dry run)
python3 scripts/ingest_all.py \
    --tickers CRM ADBE MSFT \
    --limit 3 \
    --dry-run

# Transcripts only
python3 scripts/ingest_all.py \
    --type transcript \
    --tickers CRM ADBE

# Presentations only, persisted to DB
python3 scripts/ingest_all.py \
    --type presentation \
    --tickers CRM ADBE \
    --persist

# With circuit breaker and resume
python3 scripts/ingest_all.py \
    --tickers CRM ADBE \
    --max-failures 5 \
    --resume
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--type` | both | `transcript`, `presentation`, or omit for both |
| `--tickers` | (required) | One or more ticker symbols |
| `--limit N` | 5 | Max documents per ticker per source |
| `--dry-run` | off | Run pipeline but skip DB writes |
| `--persist` | off | Write results to the database |
| `--max-failures N` | None | Circuit breaker threshold |
| `--resume` | off | Skip already-completed tickers |

---

## Checkpointing and Resume

Each ingestion script writes a progress checkpoint file during the run:

| Script | Progress file |
|--------|--------------|
| `ingest_transcripts.py` | `logs/ingest_transcripts_progress.json` |
| `ingest_presentations.py` | `logs/ingest_presentations_progress.json` |

The checkpoint records the ticker and source_id of each completed document. When `--resume` is passed, documents already recorded in the checkpoint are skipped without re-running the pipeline.

The checkpoint is written after each document, so an interrupted run can be safely resumed without double-processing.

**To start fresh** (ignore previous progress), simply delete the progress file or omit `--resume`.

---

## Circuit Breaker and Failure Handling

The `--max-failures N` flag activates the circuit breaker. If `N` consecutive documents fail (pipeline error or source fetch error), the script aborts and exits with a non-zero return code.

This prevents a systemic issue (e.g., API down, malformed data batch) from silently burning through rate-limit quota.

Failures are logged at WARNING level with the source_id and error message. They are counted toward the circuit breaker only if consecutive — a success resets the counter.

When the circuit breaker trips:
```
Circuit breaker triggered after 5 consecutive failures — aborting.
```

The progress file is still written up to that point, so `--resume` can pick up where the run left off once the underlying issue is resolved.

---

## Monitoring: check_new_documents.py

Use this script to see how many unprocessed documents are available without running the full ingestion pipeline.

```bash
# Check both sources for default tickers
python3 scripts/check_new_documents.py

# Check only transcripts for specific tickers
python3 scripts/check_new_documents.py \
    --source transcript \
    --ticker CRM ADBE

# Check presentations
python3 scripts/check_new_documents.py \
    --source presentation \
    --ticker CRM

# JSON output for scripting/alerting
python3 scripts/check_new_documents.py --json
```

The script checks whether each available document has already been ingested using the database (if `DATABASE_URL` is set) or a local file proxy (if not). It reports:

- `new` — documents available but not yet ingested
- `ingested` — documents already in the system

**Example output:**
```
NEW DOCUMENTS AVAILABLE
=======================
  transcript   CRM   2025-02-04   [new]
  transcript   ADBE  2025-01-16   [new]
  presentation CRM   2025-02-10   [new]

Total new: 3  |  Already ingested: 12  |  Errors: 0
```

The default ticker list covers 10 companies: CRM, ADBE, MSFT, INTU, EA, GDDY, META, GOOGL, AMZN, AAPL.

---

## Cron / Scheduling

To run ingestion automatically on a schedule, add a cron entry. The recommended approach is to run the monitoring check first and only invoke ingestion when new documents are found.

**Example crontab** (weekly on Monday at 06:00):

```cron
# Check for new documents and ingest if found (transcripts + presentations)
0 6 * * 1 cd /path/to/filings_reviewer_beyond_sec && \
    python3 scripts/ingest_all.py \
        --tickers CRM ADBE MSFT INTU EA GDDY META \
        --limit 5 \
        --persist \
        --max-failures 5 \
        --resume \
    >> logs/ingest_cron.log 2>&1
```

**Recommendations:**
- Always use `--max-failures` in cron to prevent runaway failures from consuming quota
- Use `--resume` so interrupted runs don't reprocess documents
- Redirect stdout+stderr to a log file for post-hoc debugging
- Set `DATABASE_URL` in the cron environment or source it from a file:

```cron
0 6 * * 1 . /path/to/.env && cd /path/to/repo && python3 scripts/ingest_all.py ...
```

**Monitoring with check_new_documents.py in cron:**

```cron
# Daily check — write JSON for a separate alerting system
0 8 * * * cd /path/to/filings_reviewer_beyond_sec && \
    python3 scripts/check_new_documents.py --json \
    > logs/new_documents_$(date +\%Y\%m\%d).json 2>&1
```

---

## Return Codes

| Code | Meaning |
|------|---------|
| 0 | All documents processed (or already ingested) |
| 1 | At least one document failed |
| 2 | Circuit breaker tripped |

`ingest_all.py` propagates the worst non-zero return code from its child scripts.

---

## Troubleshooting

### "No documents found for ticker X"

- The source may not have data for that ticker — check source coverage
- For FMP: confirm `FMP_API_KEY` is set and the key has transcript access
- For HuggingFace: the dataset may not include that ticker; check `scripts/spike/collect_samples.py`

### "DATABASE_URL not set — skipping persistence"

Add `DATABASE_URL` to the environment or use `--dry-run` explicitly if persistence is not needed.

### PDF conversion failures (presentations)

`pdfplumber` requires a working PDF rendering environment. On headless servers:
```bash
pip install pdfplumber
# pdfplumber uses pdfminer which is pure Python — no system deps needed
```

If a specific PDF fails, the presentation is skipped and logged. The circuit breaker counts these as failures.

### Rate limit errors (EDGAR)

The SEC EDGAR source automatically sleeps between requests. If you see 429 errors, reduce `--limit` or add a delay by running on a less frequent schedule.
