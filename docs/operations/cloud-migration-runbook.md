# Cloud Migration Runbook

**Version:** 1.0
**Last Updated:** 2026-03-13
**Status:** Ready to execute — pending `v2-rewrite` merge to `main`

---

## Overview

This runbook covers migrating the filings reviewer from local Docker PostgreSQL to a cloud database (Neon) and deploying the web app to Google Cloud Run. It is a one-time migration, not a recurring process.

**End state:**
- Database: Neon cloud PostgreSQL (SSL, persistent)
- Web app: Google Cloud Run (containerized, HTTPS)
- Local `.env` pointing to cloud DB for ongoing extraction work

---

## Prerequisites

### Merge gate

**Do not start until `v2-rewrite` has been merged to `main`.** The schema FK ordering fix (commit `39c2354`) must be on `main` before applying migrations to a fresh cloud DB.

```bash
# Verify the fix is on main
git log main --oneline | head -5
# Should show: fix: correct v2 schema FK ordering and add dedup migration
```

### Local tooling

```bash
# PostgreSQL client tools (required for pg_dump / pg_restore)
brew install postgresql

# Google Cloud CLI (required for Cloud Run deployment)
brew install google-cloud-sdk

# Verify all three are available
psql --version
pg_dump --version
gcloud --version
```

### Local Docker DB must be running

```bash
docker compose up -d

# Verify connection
psql $DATABASE_URL -c "SELECT COUNT(*) FROM filings;"
```

### Neon account and project

1. Go to [neon.tech](https://neon.tech) and sign up (free tier available)
2. Create a new project: name it `filings-reviewer`
3. From the project dashboard, copy the connection string — it looks like:
   ```
   postgresql://user:password@ep-something.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
4. Save it as `CLOUD_DATABASE_URL` in your shell for use throughout this runbook:
   ```bash
   export CLOUD_DATABASE_URL="postgresql://user:password@ep-something.us-east-2.aws.neon.tech/neondb?sslmode=require"
   ```

---

## Step 1: Apply Schema to Cloud DB

Run `apply_migrations.py` against the cloud database. On a fresh Neon DB, all migrations will be applied in order. Already-applied migrations will be skipped automatically if you re-run.

```bash
DATABASE_URL="$CLOUD_DATABASE_URL" python3 scripts/apply_migrations.py
```

**Expected output:** Each migration prints `APPLIED: <filename>`. Final summary should show 16 applied, 0 skipped.

**If it halts with a checksum error:** The migration file was edited after it was applied. Check which file is mismatched and investigate before proceeding.

**Verify the V2 tables are present:**

```bash
psql "$CLOUD_DATABASE_URL" -c "
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'public'
      AND tablename LIKE 'v2_%'
    ORDER BY tablename;"
```

Expected: `v2_documents`, `v2_image_assets`, `v2_metric_facts`, `v2_review_decisions`, `v2_segments`, `v2_table_cells`, `v2_tables` (plus any definition/quality tables from later migrations).

---

## Step 2: Export Local Database

Dump the local Docker database to a custom-format file. The `filings_analysis_backup.dump` file may already exist in the project root from a prior attempt — if so, skip to Step 3.

```bash
# From the project root
pg_dump \
    --format=custom \
    --no-owner \
    --no-privileges \
    "$DATABASE_URL" \
    -f filings_analysis_backup.dump

# Verify the dump is non-empty
ls -lh filings_analysis_backup.dump
```

A healthy dump should be several hundred MB. If it's suspiciously small, check that `$DATABASE_URL` points to the local Docker DB and that Docker is running.

---

## Step 3: Restore Data to Cloud DB

Restore data only (schema was already applied in Step 1). The `|| true` suppresses non-fatal errors from sequence conflicts or already-existing rows.

```bash
pg_restore \
    --data-only \
    --no-owner \
    --no-privileges \
    --disable-triggers \
    -d "$CLOUD_DATABASE_URL" \
    filings_analysis_backup.dump || true
```

**Common non-fatal errors to ignore:**
- `ERROR: duplicate key value violates unique constraint` — rows already exist from a prior partial restore
- `ERROR: relation "..." does not exist` — views or temp tables not included in dump

**Fatal errors to investigate:**
- Connection refused / SSL errors — check `CLOUD_DATABASE_URL` and Neon project status
- `ERROR: permission denied` — check the Neon user has write access

---

## Step 4: Reset Sequences

After a data-only restore, PostgreSQL sequences may be out of sync. Reset them to the current max value of each table's primary key.

```bash
psql "$CLOUD_DATABASE_URL" << 'EOF'
DO $$
DECLARE
    seq_rec RECORD;
    max_val BIGINT;
BEGIN
    FOR seq_rec IN
        SELECT
            s.relname AS seq_name,
            t.relname AS tbl_name,
            a.attname AS col_name
        FROM pg_class s
        JOIN pg_depend d ON d.objid = s.oid
        JOIN pg_class t ON d.refobjid = t.oid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
        WHERE s.relkind = 'S'
          AND d.deptype = 'a'
    LOOP
        EXECUTE format(
            'SELECT COALESCE(MAX(%I), 0) FROM %I',
            seq_rec.col_name,
            seq_rec.tbl_name
        ) INTO max_val;

        EXECUTE format(
            'SELECT setval(%L, %s)',
            seq_rec.seq_name,
            GREATEST(max_val, 1)
        );
    END LOOP;
END $$;
EOF
```

---

## Step 5: Verify Cloud DB

Run a quick sanity check on the cloud database to confirm the migration succeeded.

```bash
psql "$CLOUD_DATABASE_URL" -c "
SELECT
    'companies'   AS tbl, COUNT(*) AS rows FROM companies
UNION ALL SELECT 'filings',       COUNT(*) FROM filings
UNION ALL SELECT 'metrics',       COUNT(*) FROM metrics
UNION ALL SELECT 'review_decisions', COUNT(*) FROM review_decisions
ORDER BY tbl;"
```

Cross-check the row counts against local:

```bash
psql "$DATABASE_URL" -c "
SELECT
    'companies'   AS tbl, COUNT(*) AS rows FROM companies
UNION ALL SELECT 'filings',       COUNT(*) FROM filings
UNION ALL SELECT 'metrics',       COUNT(*) FROM metrics
UNION ALL SELECT 'review_decisions', COUNT(*) FROM review_decisions
ORDER BY tbl;"
```

Counts should match. Minor discrepancies from seed data re-insertion are acceptable; large gaps indicate a partial restore.

**Also verify SSL is active:**

```bash
psql "$CLOUD_DATABASE_URL" -c "SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid();"
# ssl column should be 't'
```

---

## Step 6: Backfill Filing HTML

The `filings.html_content` column (migration 14) stores filing HTML in the database for cloud use, since `data/filings/` is not available on Cloud Run. Run this from your laptop where `data/filings/` exists.

```bash
# Preview what would be backfilled
python3 scripts/backfill_filing_html.py --dry-run

# Run the actual backfill (targets cloud DB via DATABASE_URL)
DATABASE_URL="$CLOUD_DATABASE_URL" python3 scripts/backfill_filing_html.py
```

**Note:** `scripts/backfill_filing_html.py` may not exist yet. If it does not, run the equivalent query to check coverage first:

```bash
psql "$CLOUD_DATABASE_URL" -c "
SELECT
    COUNT(*) FILTER (WHERE html_content IS NOT NULL) AS with_html,
    COUNT(*) FILTER (WHERE html_content IS NULL) AS without_html,
    COUNT(*) AS total
FROM filings
WHERE html_storage_path IS NOT NULL;"
```

If the column is empty and the script does not exist, create a task to implement `backfill_filing_html.py` before running extraction on the cloud.

---

## Step 7: Update Local .env

Point your local environment at the cloud database so subsequent extraction runs write to Neon.

```bash
# Edit .env (do not commit this file)
```

Update these lines in `.env`:

```bash
DATABASE_URL=postgresql://user:password@ep-something.us-east-2.aws.neon.tech/neondb?sslmode=require
LLM_CACHE_BACKEND=postgres
```

**Note:** `LLM_CACHE_BACKEND=postgres` switches the LLM response cache from SQLite (`data/llm_cache.db`) to the PostgreSQL `llm_cache` table (migration 15). This is required for the Cloud Run container, which has no persistent local filesystem.

Verify the updated connection:

```bash
source .env   # or restart your shell / IDE
psql "$DATABASE_URL" -c "SELECT version();"
```

---

## Step 8: Deploy Web App to Cloud Run

### 8a. One-time GCP Setup

These steps only need to be done once per GCP project.

```bash
# Install CLI (if not done in Prerequisites)
brew install google-cloud-sdk

# Authenticate and create/select a project
gcloud init
# Follow prompts: sign in with Google account, create or select a project
# Note your PROJECT_ID — you'll use it in the commands below

# Enable required APIs
gcloud services enable run.googleapis.com containerregistry.googleapis.com

# Configure Docker to authenticate with GCR
gcloud auth configure-docker
```

### 8b. Build and Push Container

```bash
export PROJECT_ID=$(gcloud config get-value project)

# Build the image
docker build -t filings-reviewer .

# Tag for GCR
docker tag filings-reviewer gcr.io/${PROJECT_ID}/filings-reviewer:latest

# Push to Google Container Registry
docker push gcr.io/${PROJECT_ID}/filings-reviewer:latest
```

### 8c. Deploy to Cloud Run

```bash
export SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')

gcloud run deploy filings-reviewer \
    --image gcr.io/${PROJECT_ID}/filings-reviewer:latest \
    --platform managed \
    --region us-east1 \
    --allow-unauthenticated \
    --port 8080 \
    --command "uv" \
    --args "run,python3,scripts/run_review_server.py" \
    --set-env-vars "DATABASE_URL=${CLOUD_DATABASE_URL}" \
    --set-env-vars "LLM_CACHE_BACKEND=postgres" \
    --set-env-vars "APP_ENV=production" \
    --set-env-vars "SECRET_KEY=${SECRET_KEY}" \
    --set-env-vars "OPENAI_API_KEY=${OPENAI_API_KEY}"
```

**Note on `--command` / `--args`:** The `Dockerfile` CMD runs pytest (for CI use). Cloud Run overrides it here to start the Flask review server instead. Confirm that `scripts/run_review_server.py` listens on port `8080` (or whatever `$PORT` Cloud Run injects) — if it hardcodes `5000`, update it before deploying.

After deploy, `gcloud` will print a service URL like `https://filings-reviewer-xxxx-ue.a.run.app`.

### 8d. Verify the Deployment

```bash
SERVICE_URL=$(gcloud run services describe filings-reviewer \
    --platform managed \
    --region us-east1 \
    --format 'value(status.url)')

# Health check
curl "${SERVICE_URL}/health"

# Should return HTTP 200 with {"status": "ok"} or similar
```

---

## Verification Checklist

Work through these in order before considering the migration complete.

- [ ] `v2-rewrite` merged to `main`
- [ ] `apply_migrations.py` completes on cloud DB — all migrations `APPLIED` or `SKIPPED`
- [ ] `v2_*` tables present in cloud DB (7+ tables)
- [ ] Row counts match between local and cloud for `companies`, `filings`, `metrics`, `review_decisions`
- [ ] Cloud DB SSL confirmed (`ssl = t`)
- [ ] Filing HTML backfilled (`html_content` not null for filings with `html_storage_path`)
- [ ] Local `.env` updated: `DATABASE_URL` → Neon, `LLM_CACHE_BACKEND=postgres`
- [ ] Single extraction test passes against cloud DB:
  ```bash
  python3 scripts/run_v2_extraction.py --filing-id 7 --verbose
  ```
- [ ] Cloud Run service deployed and `/health` returns 200
- [ ] Review UI loads at Cloud Run URL (`/v2/review/filings`)

---

## Troubleshooting

### Schema migration fails with forward FK reference

This was fixed in commit `39c2354` (moved `v2_segments` before `v2_tables`). If you see it, confirm you are on the post-fix version of `09_v2_schema.sql`:

```bash
grep -n "CREATE TABLE IF NOT EXISTS v2_segments" sql/09_v2_schema.sql
# Should appear around line 84, before v2_tables (which appears around line 120)
```

### Checksum mismatch on local DB after editing 09_v2_schema.sql

If you edit the schema file and need to update the local Docker DB checksum:

```bash
NEW_CHECKSUM=$(python3 -c "import hashlib; print(hashlib.sha256(open('sql/09_v2_schema.sql').read().encode()).hexdigest())")
docker exec filings-postgres psql -U dev -d filings_analysis -c \
    "UPDATE schema_migrations SET checksum = '${NEW_CHECKSUM}' WHERE id = '09_v2_schema.sql';"
```

### pg_restore errors on duplicate keys

Non-fatal. The `|| true` in Step 3 suppresses the exit code. Verify data counts in Step 5 rather than treating these errors as blocking.

### Cloud Run container starts but exits immediately

The `Dockerfile` CMD runs pytest, which exits after tests complete. Make sure the deploy command includes `--command "uv" --args "run,python3,scripts/run_review_server.py"` to override it.

### LLM cache writes fail on Cloud Run

Cloud Run containers have ephemeral filesystems. `LLM_CACHE_BACKEND=postgres` must be set in the Cloud Run environment variables (done in Step 8c) so the cache writes to the `llm_cache` PostgreSQL table instead of `data/llm_cache.db`.

---

## Scripts Referenced

| Script | Status | Purpose |
|--------|--------|---------|
| `scripts/apply_migrations.py` | Exists | Apply schema migrations to any DB via `DATABASE_URL` |
| `scripts/run_v2_extraction.py` | Exists | Single-filing V2 extraction for smoke test |
| `scripts/run_review_server.py` | Exists | Flask web app entry point |
| `scripts/backfill_filing_html.py` | **Does not exist** | Backfill `filings.html_content` from local files |

`backfill_filing_html.py` must be implemented before running cloud extraction. Without it, the cloud DB has no HTML content to parse.

---

## Related Docs

- `docs/operations/v2-deployment-guide.md` — V2 batch extraction runbook (local)
- `docs/operations/setup-guide.md` — Local dev environment setup
- `docs/architecture/data-model.md` — Schema reference
