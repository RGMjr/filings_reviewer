# Cloud Deployment Runbook

**Infrastructure:** Render (web service) + Neon (PostgreSQL)
**Last updated:** 2026-04-10

---

## Deployment Status

**Status: LIVE**

| Item | Detail |
|------|--------|
| Service URL | https://filings-reviewer.onrender.com |
| Live since | 2026-04-08 |
| Pre-cutover checklist | Complete |
| DB | Production Neon — all 21 migrations applied; `html_content` and `image_cache` populated |
| Last smoke test | 2026-04-10 — 8/8 passed |

### Pre-cutover checklist (run 2026-04-08)

- Step 1 (add `html_content` column): already applied — column existed in production Neon.
- Step 2 (backfill `html_content`): already complete — all 56 fetched filings populated.
- Render Blueprint deployed, all environment variables set.
- Smoke tests passed: `/health` → 200 (DB connected, pool healthy); `/v2/review/filings` → 200; API key auth passing.

### Post-cutover smoke test (run 2026-04-10)

- Migration 21 (`21_create_image_cache.sql`): table already existed in Neon (applied manually); registered in tracking table and in `apply_all_migrations.py`.
- Smoke tests: 8/8 passed against `https://filings-reviewer.onrender.com`.
- Note: Two migration scripts exist — `apply_migrations.py` (canonical, used for Neon; uses `id`+`checksum` schema) and `apply_all_migrations.py` (uses `migration_name` schema, tracks a different ledger). Both are now up-to-date with migration 21.

---

## Architecture

```
Browser → Render Web Service (waitress + Flask)
                    ↓
          Neon PostgreSQL (pooler endpoint for app)
          Neon PostgreSQL (direct endpoint for migrations)

Image files: Render ephemeral disk — NOT cloud-durable (see Known Limitations)
```

---

## Prerequisites

- Access to the [Render dashboard](https://dashboard.render.com)
- Access to the [Neon console](https://console.neon.tech)
- `psql` installed locally (for running migrations)
- `pg_restore` installed locally (for DB restores from `.dump` files)
- The repo pushed to GitHub (Render deploys from git)

---

## Environment Variables

Set these in the Render service dashboard under **Environment → Environment Variables**.

| Variable | Value | Notes |
|----------|-------|-------|
| `APP_ENV` | `production` | Activates ProductionConfig — required |
| `SECRET_KEY` | `<random 64-char hex>` | Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `FILINGS_API_KEY` | `<random 64-char hex>` | Same generation method |
| `API_KEY_REQUIRED` | `true` | Always true in production |
| `DATABASE_URL` | `<neon pooler URL>` | Use pooler endpoint (see Neon section below) |
| `OPENAI_API_KEY` | `sk-proj-...` | From OpenAI dashboard |
| `LLM_CACHE_ENABLED` | `true` | |
| `LLM_CACHE_VERSION` | `v1` | Bump to invalidate cache |
| `DB_POOL_ENABLED` | `true` | |
| `DB_POOL_MIN_SIZE` | `1` | Keep low on Render free tier |
| `DB_POOL_MAX_SIZE` | `5` | Neon free tier allows ~10 concurrent connections |

---

## Neon DB

### Connection strings

Neon provides two endpoints — use the right one for each purpose:

| Purpose | Endpoint type | When to use |
|---------|--------------|-------------|
| App (`DATABASE_URL`) | **Pooler** | Runtime queries via the Flask app |
| Migrations, `psql`, `pg_restore` | **Direct** | Schema changes and bulk operations |

**Find both in:** Neon console → your project → Connection Details → toggle "Pooler" on/off.

Pooler URL format:
```
postgresql://user:password@ep-xxx-pooler.region.aws.neon.tech/dbname?sslmode=require
```

Direct URL format:
```
postgresql://user:password@ep-xxx.region.aws.neon.tech/dbname?sslmode=require
```

> **Critical:** `pg_restore` and multi-statement DDL migrations MUST use the direct endpoint.
> The pooler endpoint will fail with cryptic errors on these operations.

### Running schema migrations

Always use the **direct** endpoint for migrations:

```bash
export NEON_DIRECT_URL="postgresql://user:password@ep-xxx.region.aws.neon.tech/dbname?sslmode=require"

# Apply a single migration
psql "$NEON_DIRECT_URL" -f sql/16_add_8k_form_type.sql

# Apply all migrations in canonical order (recommended — skips already-applied ones)
DATABASE_URL="$NEON_DIRECT_URL" python3 scripts/apply_all_migrations.py
```

> **Migration ordering note:** `scripts/apply_all_migrations.py` encodes the canonical order for all 21 migrations, including files with duplicate numeric prefixes (`04`, `08`, `09`, `10`, `11`, `12`). Use it instead of a manual shell loop to avoid ordering mistakes.
>
> If you need to apply a single migration manually, use `psql "$NEON_DIRECT_URL" -f sql/<filename>.sql`.

### Restoring from a dump file

Use the **direct** endpoint. The `.dump` file is in pg_custom format:

```bash
pg_restore \
  --no-owner \
  --no-privileges \
  --clean \
  --if-exists \
  -d "$NEON_DIRECT_URL" \
  filings_backup.dump
```

If you see `connection to server failed` errors, confirm you are using the direct URL, not the pooler URL.

### Creating a new backup

```bash
export NEON_DIRECT_URL="postgresql://..."

pg_dump \
  --format=custom \
  --no-owner \
  --no-privileges \
  "$NEON_DIRECT_URL" \
  -f filings_backup.dump
```

Do NOT commit `.dump` files to git — they contain production data.

---

## Render Web Service

### Initial setup (one-time)

1. In the Render dashboard: **New → Web Service**
2. Connect your GitHub repo
3. Configure:
   - **Runtime:** Python 3
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `waitress-serve --port=$PORT --call "src.web.app:create_app"`
   - **Instance type:** Starter (or Free for testing)
4. Add all environment variables from the table above
5. Click **Create Web Service**

### Deploying new code

Render auto-deploys on push to the connected branch (usually `main`).

To trigger a manual deploy: Render dashboard → your service → **Manual Deploy → Deploy latest commit**.

To verify a deploy succeeded: check the **Logs** tab for:
```
Serving on http://0.0.0.0:<PORT>
```

### Checking logs

Render dashboard → your service → **Logs** tab.

For errors, filter by `ERROR` or `Exception`.

---

## Deploying a Schema Migration

When a new SQL migration file is added (e.g., `10_new_table.sql`):

1. Apply to Neon using the direct endpoint (see above)
2. Verify the migration ran without errors
3. Deploy the new code to Render (push to main)

Do NOT deploy code that depends on a new schema before the migration runs.

---

## Smoke Test After Deploy

After each deploy, verify the service is healthy:

```bash
# Production URL
BASE_URL="https://filings-reviewer.onrender.com"
API_KEY="your-filings-api-key"

# Health check (no auth required)
curl "$BASE_URL/health"
# Expected: {"status": "healthy", ...}

# Auth check
curl -H "X-API-Key: $API_KEY" "$BASE_URL/api/review/candidates?limit=1"
# Expected: 200 with JSON body
```

---

## Known Limitations

### Image storage — resolved

Chart images are cached in PostgreSQL (`image_cache` table in Neon) and persist across Render redeploys. The browser loads images directly from SEC EDGAR URLs and falls back to `/images/cache/<cik>/<accession_no>/<filename>` if SEC EDGAR is unavailable. The proxy route lazily populates the cache on first fetch.

### LLM cache — resolved

The LLM cache uses PostgreSQL via `DATABASE_URL` (Neon). Cache entries persist across Render redeploys. No action needed.

### Connection pool sizing

Neon's free tier supports ~10 concurrent connections. Keep `DB_POOL_MAX_SIZE` at 5 or lower to leave headroom for migrations and direct queries.

---

## Troubleshooting

### `pg_restore` fails with "connection refused" or SSL errors

- Confirm you are using the **direct** endpoint, not the pooler.
- Add `?sslmode=require` to the connection string if not present.
- Neon requires SSL — never use `sslmode=disable`.

### App fails to start: `SECRET_KEY not set`

`ProductionConfig` requires `SECRET_KEY`. Confirm the env var is set in the Render dashboard and the service has been redeployed after adding it.

### 401 errors from API

`API_KEY_REQUIRED=true` in production. The client must pass the `X-API-Key` header or `?api_key=` query param matching `FILINGS_API_KEY`.

### DB connection errors at runtime

- Confirm `DATABASE_URL` uses the **pooler** endpoint (not direct).
- Confirm `?sslmode=require` is appended.
- Check `DB_POOL_MAX_SIZE` is not exceeding Neon's connection limit.

### Migrations fail with FK errors

Apply migrations strictly in filename order. If a migration fails midway, check which tables already exist before re-running:

```bash
psql "$NEON_DIRECT_URL" -c "\dt"
```

Then apply only the missing migrations.
