# Cloud Deployment Guide

**Version:** 1.0
**Last Updated:** 2026-03-10

---

## Overview

This guide walks through deploying the SEC Filings Reviewer so it runs independently of your laptop. After completing these steps:

- The **database** runs on managed cloud PostgreSQL (already done)
- The **web review interface** runs in a cloud container
- The **batch scripts** run from any machine with database access
- **Filing HTML** is stored in the database, not the local filesystem
- The **LLM cache** uses PostgreSQL instead of a local SQLite file

**Prerequisites**: You should already have a working local setup (see `setup-guide.md`).

---

## Step 1: Set Up Cloud PostgreSQL

*If you already have a cloud database, skip to Step 2.*

### 1a. Create a cloud database

Any managed PostgreSQL 15+ provider works. [Neon](https://neon.tech) is recommended for getting started (free tier, no VPC setup). Other options: AWS RDS, Azure Database for PostgreSQL, GCP Cloud SQL.

After provisioning, you'll have a connection URL like:
```
postgresql://user:password@ep-xxx.us-east-2.aws.neon.tech/filings_analysis?sslmode=require
```

### 1b. Migrate data from local Docker

Run the migration script from your laptop (where Docker is running):

```bash
CLOUD_DATABASE_URL="postgresql://user:pass@host/db?sslmode=require" \
    bash scripts/migrate_to_cloud.sh
```

This script walks you through 4 steps with confirmation prompts:
1. **Export** local Docker database via `pg_dump`
2. **Create schema** on cloud DB via `apply_migrations.py`
3. **Import data** via `pg_restore`
4. **Reset sequences** for auto-increment columns

### 1c. Verify the connection

```bash
DATABASE_URL="postgresql://user:pass@host/db?sslmode=require" \
    python3 scripts/validate_cloud_connection.py
```

Expected output:
```
Connecting to: postgresql://user:***@host/db?sslmode=require
  PostgreSQL version: PostgreSQL 15.x ...
  Database: filings_analysis
  Server address: x.x.x.x
  SSL in use: True
  Migrations applied: 15
  Public tables: 20+

Connection OK.
```

### 1d. Update your local `.env`

```bash
# Switch from local Docker to cloud
DATABASE_URL=postgresql://user:pass@host/db?sslmode=require

# Keep local Docker for tests (optional)
TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test
```

Everything else continues to work — the codebase uses `DATABASE_URL` everywhere.

---

## Step 2: Backfill Filing HTML into the Database

Filing HTML documents are currently stored as local files under `data/filings/`. Cloud deployments need this content in the database instead.

### 2a. Run the SQL migration

```bash
# Apply to cloud DB (if not already done by migrate_to_cloud.sh)
psql "$DATABASE_URL" -f sql/14_filing_html_content.sql
psql "$DATABASE_URL" -f sql/15_llm_cache_postgres.sql
```

This adds `html_content` and `txt_content` columns to the `filings` table, and creates the `llm_cache` table in PostgreSQL.

### 2b. Backfill local files into the database

**Run this from your laptop** (where the local `data/filings/` directory exists):

```bash
# Preview what will be backfilled
python3 scripts/backfill_html_to_db.py --dry-run

# Run the actual backfill
python3 scripts/backfill_html_to_db.py
```

The script:
- Finds filings where `html_content IS NULL` but `html_storage_path IS NOT NULL`
- Reads each local file and stores its content in the database
- Reports progress every 50 filings

Expected output:
```
==================================================
Backfill Summary
==================================================
  Processed: 84
  Updated:   78
  Skipped:   6 (file not found)
  Failed:    0
==================================================
```

The 6 skipped are transcript stubs (filing IDs 1-6) that have no local HTML — this is expected.

### 2c. Verify

```bash
psql "$DATABASE_URL" -c "
    SELECT
        COUNT(*) FILTER (WHERE html_content IS NOT NULL) AS with_content,
        COUNT(*) FILTER (WHERE html_content IS NULL AND html_storage_path IS NOT NULL) AS missing_content,
        COUNT(*) FILTER (WHERE html_content IS NULL AND html_storage_path IS NULL) AS no_file
    FROM filings;"
```

After backfill, `with_content` should match the number of filings you've downloaded.

---

## Step 3: Enable PostgreSQL LLM Cache

Switch the LLM response cache from local SQLite to cloud PostgreSQL:

```bash
# In your .env
LLM_CACHE_BACKEND=postgres
```

That's it. The `LLMCache` class automatically uses `DATABASE_URL` when the backend is `postgres`. The table was already created by migration `sql/15_llm_cache_postgres.sql`.

The existing SQLite cache entries will expire naturally (30-day TTL). If you want to keep them, an optional backfill script exists, but cache entries are cheap to regenerate.

---

## Step 4: Deploy the Web Review Interface

The web app is a Flask application served by Waitress (production WSGI server). The existing Dockerfile is production-ready.

### Option A: Cloud Run (simplest)

```bash
# Build the container image
docker build -t filings-reviewer .

# Tag for your container registry
docker tag filings-reviewer gcr.io/YOUR_PROJECT/filings-reviewer:latest

# Push to registry
docker push gcr.io/YOUR_PROJECT/filings-reviewer:latest

# Deploy to Cloud Run
gcloud run deploy filings-reviewer \
    --image gcr.io/YOUR_PROJECT/filings-reviewer:latest \
    --platform managed \
    --region us-east1 \
    --allow-unauthenticated \
    --set-env-vars "DATABASE_URL=$DATABASE_URL" \
    --set-env-vars "LLM_CACHE_BACKEND=postgres" \
    --set-env-vars "APP_ENV=production" \
    --set-env-vars "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
    --command "uv,run,python3,scripts/run_review_server.py,--host,0.0.0.0,--port,8080" \
    --port 8080
```

### Option B: Any Docker host (VM, ECS, etc.)

```bash
# Build
docker build -t filings-reviewer .

# Run
docker run -d \
    --name filings-reviewer \
    -p 8000:8000 \
    -e DATABASE_URL="$DATABASE_URL" \
    -e LLM_CACHE_BACKEND=postgres \
    -e APP_ENV=production \
    -e SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
    -e OPENAI_API_KEY="$OPENAI_API_KEY" \
    filings-reviewer \
    uv run python3 scripts/run_review_server.py --host 0.0.0.0 --port 8000
```

### Option C: Direct on a VM (no Docker)

```bash
# On the VM:
git clone https://github.com/RGMjr/filings_reviewer_v2.git
cd filings_reviewer_v2
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --all-extras

# Configure .env with cloud DATABASE_URL, then:
APP_ENV=production python3 scripts/run_review_server.py --host 0.0.0.0 --port 8000
```

### Health check

The web app exposes a `/health` endpoint. Use it for load balancer health checks:
```bash
curl http://your-host:8000/health
```

---

## Step 5: Run Batch Scripts in the Cloud

Batch scripts don't need containerization to work in the cloud. They can run on any machine that has Python, the codebase, and `DATABASE_URL` pointing to the cloud database.

### What each script does

| Script | Purpose | Typical frequency |
|--------|---------|-------------------|
| `build_universe_real.py` | Discover new filings from SEC EDGAR | Quarterly |
| `batch_download_filings.py` | Download filing HTML from SEC | After universe build |
| `batch_v2_extraction.py` | Extract metrics from filings | After download |
| `generate_review_candidates.py` | Generate human review queue | After extraction |

### How filing HTML flows now

After the changes in this migration:

1. **Download**: `batch_download_filings.py` downloads HTML from SEC EDGAR and stores it both locally (as a cache) AND in the database (`html_content` column)
2. **Extraction**: `batch_v2_extraction.py` reads `html_content` from the database first. If NULL, it falls back to `html_storage_path` (local file)
3. **Result**: Once `html_content` is populated, scripts work from any machine — no local files needed

### Running batch scripts from a cloud VM

```bash
# SSH into your VM, clone the repo, install deps (same as Option C above)

# Download new filings (stores HTML in database automatically)
python3 scripts/batch_download_filings.py --limit 100

# Run extraction (reads HTML from database)
python3 scripts/batch_v2_extraction.py --limit 100

# Generate review candidates
python3 scripts/generate_review_candidates.py
```

### Running batch scripts via Docker

```bash
# Download filings
docker run --rm \
    -e DATABASE_URL="$DATABASE_URL" \
    -e SEC_USER_AGENT="Your Name your@email.com" \
    filings-reviewer \
    uv run python3 scripts/batch_download_filings.py --limit 100

# Run extraction
docker run --rm \
    -e DATABASE_URL="$DATABASE_URL" \
    -e OPENAI_API_KEY="$OPENAI_API_KEY" \
    filings-reviewer \
    uv run python3 scripts/batch_v2_extraction.py --limit 100
```

### Scheduling (optional)

For automated runs, use your platform's scheduler:
- **Cron on a VM**: `crontab -e`, add entries for batch scripts
- **Cloud Scheduler + Cloud Run Jobs**: Trigger container runs on a schedule
- **GitHub Actions**: Schedule workflows that SSH into a VM or run containers

No scheduling infrastructure is built into the codebase — scripts are designed to be invoked externally and are safe to re-run (idempotent).

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | (none) | PostgreSQL connection string |
| `OPENAI_API_KEY` | For extraction | (none) | OpenAI API key for LLM calls |
| `SEC_USER_AGENT` | For downloads | (none) | Your name + email for SEC EDGAR |
| `APP_ENV` | No | `development` | Set to `production` for strict validation |
| `SECRET_KEY` | For production | (auto-generated) | Flask session secret |
| `LLM_CACHE_BACKEND` | No | `sqlite` | Set to `postgres` for cloud deployments |
| `LLM_CACHE_ENABLED` | No | `true` | Disable LLM caching entirely |
| `V2_WORKER_COUNT` | No | `4` | Parallel workers for batch extraction |

---

## Verification Checklist

After completing all steps, verify your deployment:

```bash
# 1. Database connection
DATABASE_URL="$DATABASE_URL" python3 scripts/validate_cloud_connection.py

# 2. Filing HTML in database
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM filings WHERE html_content IS NOT NULL;"

# 3. Web app health
curl http://your-host:8000/health

# 4. LLM cache using PostgreSQL
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM llm_cache;"

# 5. Run a single extraction to test end-to-end
python3 scripts/run_v2_extraction.py --filing-id 7
```

---

## What Stays Local

Even after full cloud deployment, some things remain local by design:

- **`TEST_DATABASE_URL`**: Tests run against a local database (Docker). This is intentional — tests should not touch production data.
- **`data/gold_standard/`**: Gold standard validation files are test fixtures committed to the repo. They don't need cloud storage.
- **Local `data/filings/` cache**: The `FilingFetcher` still writes to local disk as a cache. In cloud containers this directory is ephemeral, which is fine — the database is the source of truth.
- **SQLite LLM cache for local dev**: When `LLM_CACHE_BACKEND=sqlite` (default), the cache uses a local file. This is convenient for development.

---

## Troubleshooting

### "Connection refused" to cloud database

1. Check `DATABASE_URL` has `?sslmode=require` for cloud providers
2. Verify the database is provisioned and accepting connections
3. Check IP allowlist / firewall rules on your cloud provider
4. Run `scripts/validate_cloud_connection.py` for diagnostics

### Extraction fails with "HTML file not found"

This means `html_content` is NULL in the database and the local file doesn't exist:

```bash
# Check if the filing has content in the database
psql "$DATABASE_URL" -c "
    SELECT filing_id, html_storage_path,
           CASE WHEN html_content IS NOT NULL THEN 'YES' ELSE 'NO' END AS has_content
    FROM filings WHERE filing_id = <ID>;"
```

Fix: Run `scripts/backfill_html_to_db.py` from the machine that has the local files, or re-download with `batch_download_filings.py` (which now stores content in the DB automatically).

### LLM cache not working in cloud

1. Verify `LLM_CACHE_BACKEND=postgres` is set
2. Verify `sql/15_llm_cache_postgres.sql` migration was applied
3. Check logs for "LLM cache initialized with PostgreSQL backend"

### Container exits immediately

The Dockerfile's default CMD runs tests. Override it for production:
```bash
docker run ... filings-reviewer \
    uv run python3 scripts/run_review_server.py --host 0.0.0.0 --port 8000
```

---

## Architecture After Migration

```
┌─────────────────────┐     ┌──────────────────────────────┐
│  Your Laptop        │     │  Cloud                       │
│                     │     │                              │
│  - Local dev/test   │     │  ┌────────────────────────┐  │
│  - Gold standard    │     │  │ Cloud PostgreSQL       │  │
│    validation       │────▶│  │  - filings (+ content) │  │
│  - SQLite LLM cache │     │  │  - llm_cache           │  │
│    (dev only)       │     │  │  - review_decisions     │  │
│                     │     │  │  - v2_metric_facts      │  │
│                     │     │  └────────┬───────────────┘  │
│                     │     │           │                   │
│                     │     │  ┌────────▼───────────────┐  │
│                     │     │  │ Web Container          │  │
│                     │     │  │  Flask + Waitress       │  │
│                     │     │  │  /health endpoint       │  │
│                     │     │  └────────────────────────┘  │
│                     │     │                              │
│                     │     │  ┌────────────────────────┐  │
│                     │     │  │ Batch Jobs (VM/container)│ │
│                     │     │  │  - download filings     │  │
│                     │     │  │  - run extraction       │  │
│                     │     │  │  - generate candidates  │  │
│                     │     │  └────────────────────────┘  │
│                     │     │                              │
└─────────────────────┘     └──────────────────────────────┘
```

Your laptop is only needed for local development, testing, and gold standard validation. All production operations can run from the cloud.
