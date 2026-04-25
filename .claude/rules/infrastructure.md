---
paths:
  - "docker-compose*"
  - "Dockerfile"
  - ".env*"
  - "render.yaml"
  - "src/infra/**"
  - "requirements*.txt"
  - "pyproject.toml"
---

# Infrastructure

## Local Development (Docker)

```bash
docker compose up -d   # Start PostgreSQL on port 5433
docker compose down    # Stop
# Connection: postgresql://dev:dev@localhost:5433/filings_analysis_test
```

## Production (Neon + Render)

Cloud PostgreSQL format: `postgresql://user:password@host.neon.tech/dbname?sslmode=require`

`render.yaml` defines 5 services, all pinned to Ohio region via `region: ohio`:
- `filings-reviewer` — web service (URL: `filings-reviewer.onrender.com`)
- `filings-extraction` — cron, daily 6am UTC (`batch_v2_extraction.py --status fetched --workers 2 --limit 50`)
- `filings-onboarding-runner` — background worker (`src.universe.onboarding_runner --watch`)
- `filings-nightly-sweep` — cron, daily 6am UTC (autonomous KNOWN_ISSUES sweeper; gated by `.claude/sweep.pause`)
- `filings-metabase` — web service, self-hosted Metabase for BI/analytics (`metabase/metabase` image, H2 app DB on persistent disk, `autoDeploy: false`; see `docs/operations/analytics-ui-runbook.md`)

Region is pinned so blueprint re-deploys do not scatter services across regions. Render will ignore `region` changes on existing services — if you need to move a service to a different region you must delete and recreate it (env groups `filings-shared-secrets` and `filings-claude-secrets` persist across deletion, so secrets are inherited on recreate).

### pg_dump client version

- `pg_dump` must be greater than or equal to the server major version. Neon is on PG15; use a PG16+ client for safety.
- Install with `brew install postgresql@16` and invoke via the explicit Cellar path or a pinned symlink (do not rely on the default `/opt/homebrew/bin/pg_dump` which resolves to whatever was installed first).
- Run `python3 scripts/check_pg_client_version.py` before taking snapshots. Silent failure (0-byte file with exit 0) is the symptom when this guard is skipped.

### Deploy-Time Migration Contract

`render.yaml` wires `preDeployCommand: python3 scripts/apply_migrations.py` on the `filings-reviewer` web service. Render runs that command before the container starts serving traffic, on every deploy. The script is idempotent via the `schema_migrations` ledger, so re-runs are no-ops once a migration has been applied.

**For schema-change PRs**, the contract is:
1. Add `sql/<timestamp>_<description>.sql` (timestamp filename per `.claude/rules/sql.md`).
2. Register it in `MIGRATIONS` in `scripts/apply_migrations.py`.
3. Merge the PR. The next Render deploy applies the migration automatically.

**Failure mode.** A non-zero exit from the predeploy step aborts the deploy and leaves the previous container serving traffic. Common causes:
- Migration not registered in `apply_migrations.py` (script exits non-zero on unregistered files).
- Checksum mismatch — the migration file was edited after being applied to prod (script refuses to re-apply).
- `DATABASE_URL` not in scope at deploy phase (it should be — the env group `filings-shared-secrets` covers `filings-reviewer`).

**Verification.** Render dashboard → `filings-reviewer` → **Events → Deploy** → predeploy log shows `APPLIED: <filename>` lines for any migrations the deploy applied.

**Limitations.** Only `filings-reviewer` has the predeploy hook. Other services (`filings-extraction`, `filings-onboarding-runner`, `filings-nightly-sweep`, `filings-metabase`) rely on `filings-reviewer` running its predeploy first when a schema change ships — they redeploy in parallel but share the database, so the order doesn't matter for safety, only for log visibility.

## DATABASE_URL vs TEST_DATABASE_URL — IMPORTANT

**In this project's `.env`, `DATABASE_URL` points at the Neon prod database, NOT local Postgres.** The local Docker Postgres is addressed by `TEST_DATABASE_URL`.

| Env var | Points at | Use for |
|---------|-----------|---------|
| `DATABASE_URL` | **Neon prod** (`*.neon.tech`) | Prod-facing work ONLY (Phase 5 backfills, prod runbooks). Confirm with user before any write. |
| `TEST_DATABASE_URL` | **Local Docker** (`localhost:5433/filings_analysis_test`) | All local/dev work: ad-hoc `psql`, diagnostics, pytest, local backfill rehearsals. |

Rules for any DB-touching command in this repo:

1. **Default to `TEST_DATABASE_URL`** for local work. Run the command as
   `DATABASE_URL="$TEST_DATABASE_URL" <cmd>` or pass
   `--database-url "$TEST_DATABASE_URL"` where the script supports it.
2. **Never silently fall back to `$DATABASE_URL`** if `$TEST_DATABASE_URL` is
   unset. Stop and ask the user, or start Docker with `docker compose up -d`.
3. **Assume `$DATABASE_URL` is prod** unless you have explicitly verified
   otherwise for the current shell. Read-only queries against prod still
   require user confirmation.

## Environment Variables

| Var | Required | Purpose |
|-----|----------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection. **In this project's `.env` this is Neon prod.** Do not use for local dev work — see TEST_DATABASE_URL. |
| `SEC_USER_AGENT` | Yes | EDGAR API identification ("Name email@example.com") |
| `FILINGS_API_KEY` | Yes | API auth for web routes |
| `TEST_DATABASE_URL` | Local dev + tests | Local Docker Postgres (`localhost:5433/filings_analysis_test`). **This is the default for any local DB work, not just pytest.** |
| `OPENAI_API_KEY` | LLM features | OpenAI for vision/LLM calls |
| `R2_BUCKET` | Prod / persistent envs | Cloudflare R2 bucket for image cache. When set, overrides `IMAGE_CACHE_DIR` |
| `R2_ACCESS_KEY_ID` | With `R2_BUCKET` | R2 API token access key |
| `R2_SECRET_ACCESS_KEY` | With `R2_BUCKET` | R2 API token secret |
| `R2_ENDPOINT_URL` | With `R2_BUCKET` | R2 S3-compatible endpoint (`https://<account-id>.r2.cloudflarestorage.com`) |
| `IMAGE_CACHE_DIR` | Dev only (optional) | Override local filesystem image-cache root. Ignored when `R2_BUCKET` is set |
| `METABASE_URL` | Optional | Target of the "Data Explorer" nav link in the Flask UI. Defaults to `https://filings-metabase.onrender.com` when unset. |
| `ENABLE_METRIC_CLASSIFY` | Optional | Feature gate for the Vision-API metric-classify stage (`src/extraction_v2/stages/image_classify.py`). Default off. When `true`, every chart / table_image runs `VisionClient.analyze_image_for_metric_classification` and the result lands in `v2_image_classifications`. |
| `VISION_CLASSIFY_PROVIDER` | With `ENABLE_METRIC_CLASSIFY` | Provider for the classify call (default `gemini`). Independent of `VISION_PROVIDER` so classify and OCR can pick different cost-optimal providers. |
| `VISION_CLASSIFY_MODEL` | With `ENABLE_METRIC_CLASSIFY` | Model id (default `gemini-2.5-flash-lite`, per 2026-04-23 bake-off). |
| `VISION_CLASSIFY_THRESHOLD` | With `ENABLE_METRIC_CLASSIFY` | Confidence floor (default `0.5`) for the downstream `predicted_relevant` signal. Records below the floor are still persisted. |
| `GEMINI_API_KEY` | With `VISION_CLASSIFY_PROVIDER=gemini` | Google AI Studio key for Gemini vision calls. Set manually in Render. |
| `FILINGS_REVIEWER_ALLOW_PROD_WRITES` | Required for `R2Storage.put_bytes` | Must be set to `"1"` for any process that writes image bytes to R2. Refused otherwise. Reads (`get_bytes`, `exists`) are unaffected. Set on Render services that run extraction/ingestion (`filings-reviewer`, `filings-extraction`, `filings-onboarding-runner`); leave unset on local dev to prevent accidental prod writes when prod creds are sourced for one-off CLI work. |

## Image Storage

Image bytes (chart/table OCR cache + ingestion-local copies) persist via
`src/infra/image_storage.py`. Two backends selected at runtime via `R2_BUCKET`:

- **Local filesystem** (default, dev/test): `LocalFilesystemStorage` rooted at
  `<repo>/data/image_cache/` (or `IMAGE_CACHE_DIR` override).
- **Cloudflare R2** (prod): `R2Storage` wraps a `boto3` S3-compatible client.
  Bucket is private; reads/writes stream through the application.

`v2_image_assets.file_path` stores an opaque **storage key**
(e.g. `pipeline/<cik>/<accession>/<filename>`), not a filesystem path. Key shape
is validated by `validate_key()` — path-traversal sequences and absolute paths
are rejected at every call site.

### Prod-write guard

`R2Storage.put_bytes` refuses to write unless `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` is in the process environment. The guard prevents accidental prod R2 mutations from local CLI tools (e.g. `python3 -m src.gold_standard.v2_validator`) when a contributor sources prod `.env` for one-off work. Reads (`get_bytes`, `exists`) remain open so diagnostics still work. `LocalFilesystemStorage` is unguarded — dev writes to `data/image_cache/` are always allowed.

Render services that legitimately write images (`filings-reviewer`, `filings-extraction`, `filings-onboarding-runner`) need `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` set in their env. Services that don't write images (`filings-nightly-sweep`, `filings-metabase`) should leave it unset.

## SEC EDGAR Integration

- Rate limiting: 100ms minimum between requests (enforced in `sec_client.py`)
- User-Agent header required: set via `SEC_USER_AGENT` env var

## Pre-commit Deployment Checklist

For any change touching routes, migrations, or auth: (1) verify migration files are registered in the migration runner, (2) verify `url_for` endpoints resolve correctly, (3) test API endpoints with both direct calls and browser fetch to catch auth/CORS issues. (Historically, unregistered migrations and broken `url_for` calls caused multiple deployment 500 errors in Apr 2026.)
