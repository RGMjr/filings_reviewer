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
- `filings-onboarding-runner` — background worker (`src.universe.onboarding_runner --watch`); drains both `v2_ingest_batches` and the `model_training_runs` retrain queue (gh-400, retrain rows are prioritized so UI-triggered retrains don't wait behind a long onboarding batch)
- `filings-nightly-sweep` — cron, daily 6am UTC (autonomous KNOWN_ISSUES sweeper; gated by `SWEEP_FORCE=1` in env group `filings-claude-secrets`)
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
2. Merge the PR. The next Render deploy applies the migration automatically. Registration is automatic — `src.infra.migrations.migration_files()` picks the file up from disk.

**Failure mode.** A non-zero exit from the predeploy step aborts the deploy and leaves the previous container serving traffic. Common causes:
- Checksum mismatch — the migration file was edited after being applied to prod with a non-comment change (script refuses to re-apply). Comment-only edits are normalized away by `_checksum` and do not trip the guard. If the edit truly is comment-only and the ledger predates the normalization (legacy-095 #3), reconcile once with `python3 scripts/apply_migrations.py --reconcile-checksums`.
- `DATABASE_URL` not in scope at deploy phase (it should be — the env group `filings-shared-secrets` covers `filings-reviewer`).

**Verification.** Render dashboard → `filings-reviewer` → **Events → Deploy** → predeploy log shows `APPLIED: <filename>` lines for any migrations the deploy applied.

**Limitations.** Only `filings-reviewer` has the predeploy hook. Other services (`filings-extraction`, `filings-onboarding-runner`, `filings-nightly-sweep`, `filings-metabase`) rely on `filings-reviewer` running its predeploy first when a schema change ships — they redeploy in parallel but share the database, so the order doesn't matter for safety, only for log visibility.

### Healthcheck

`filings-reviewer` declares `healthCheckPath: /health` in `render.yaml`. The endpoint is registered in `src/web/app.py::_register_health_check`, requires no auth, and returns 200 when the DB pool is reachable, 503 otherwise. Render uses it to flip traffic to the new container the moment the app is live (vs. waiting on TCP-probe heuristics) and to abort a deploy whose container never reports healthy. Transient 503s during pool init are tolerated by Render's retry window.

### Multi-stage Dockerfile shape

Both `Dockerfile` and `Dockerfile.nightly-sweep` are multi-stage builds:

- **builder** (`python:3.11-slim`) installs `gcc` + `libpq-dev` and runs `pip install -r requirements.lock` into `/opt/venv`.
- **runtime** (`python:3.11-slim`) installs only `libpq5` (the runtime shared library psycopg links against), copies `/opt/venv` from the builder, and adds the application source. The `gcc`/`libpq-dev` headers and pip's intermediate cache do not ship.

Net effect on Render: smaller cached layers → faster pull from the build cache, faster image pull on the runtime VM, and faster cold-start. The builder/runtime stages share an identical Python base so wheels compiled against builder glibc remain ABI-compatible with runtime.

The nightly-sweep image's runtime stage additionally pulls in `git`, `curl`, `ca-certificates` and the pinned `gh` and `claude` CLI binaries — those tools are invoked by `scripts/run_nightly_sweep.sh` at run time and must live in the runtime stage, not the builder.

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
| `FILING_CACHE_DIR` | Dev only (optional) | Override local filesystem filing-HTML cache root (`<repo>/data/filing_cache/` by default). Ignored when `R2_BUCKET` is set. See **Filing HTML Storage** below. |
| `METABASE_URL` | Optional | Target of the "Data Explorer" nav link in the Flask UI. Defaults to `https://filings-metabase.onrender.com` when unset. |
| `ENABLE_METRIC_CLASSIFY` | Optional | Feature gate for the Vision-API metric-classify stage (`src/extraction_v2/stages/image_classify.py`). Default off. When `true`, every chart / table_image runs `VisionClient.analyze_image_for_metric_classification` and the result lands in `v2_image_classifications`. |
| `VISION_CLASSIFY_PROVIDER` | With `ENABLE_METRIC_CLASSIFY` | Provider for the classify call (default `gemini`). Independent of `VISION_PROVIDER` so classify and OCR can pick different cost-optimal providers. |
| `VISION_CLASSIFY_MODEL` | With `ENABLE_METRIC_CLASSIFY` | Model id (default `gemini-2.5-flash-lite`, per 2026-04-23 bake-off). |
| `VISION_CLASSIFY_THRESHOLD` | With `ENABLE_METRIC_CLASSIFY` | Confidence floor (default `0.5`) for the downstream `predicted_relevant` signal. Records below the floor are still persisted. |
| `VISION_PROVIDER_FULL_PAGE_OCR` | Optional | Provider for the full-page-scan OCR triage site (default `gemini`). Independent of `VISION_PROVIDER`. See `docs/operations/vision-model-selection.md`. |
| `VISION_MODEL_FULL_PAGE_OCR` | Optional | Model for the full-page-scan OCR triage site (default `gemini-2.0-flash`). |
| `VISION_PROVIDER_PRESCAN` | Optional | Provider for the image-level keyword pre-scan site (default `gemini`). Independent of `VISION_PROVIDER`. |
| `VISION_MODEL_PRESCAN` | Optional | Model for the keyword pre-scan site (default `gemini-2.0-flash`). |
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

## Filing HTML Storage

Filing source HTML persists via `src/infra/filing_storage.py` — same pattern as
image storage, parallel surface. Two backends selected at runtime via
`R2_BUCKET`:

- **Local filesystem** (default, dev/test): `LocalFilesystemFilingStorage`
  rooted at `<repo>/data/filing_cache/` (or `FILING_CACHE_DIR` override).
- **Cloudflare R2** (prod): `R2FilingStorage` shares the bucket with image
  bytes; key prefix `filings/` separates filing HTML from `pipeline/` (image
  cache) and `ingestion/` (per-filing image cache).

`filings.html_storage_path` stores opaque storage keys post-gh-300
(e.g. `filings/<cik>/<accession>/primary.htm`), not absolute paths. Key shape
is validated by `image_storage.validate_key()` (shared regex) — path-traversal
sequences and absolute paths are rejected at every call site.

**Reader-side compatibility:** legacy filesystem paths and the `html_content`
DB-blob fallback both still work. Extraction call sites detect
`html_storage_path.startswith("filings/")` and download to a tempfile via the
storage abstraction; otherwise they use the existing disk + DB-blob fallback
logic. See `scripts/batch_v2_extraction.py` and `scripts/run_v2_extraction.py`
for the per-row resolution flow.

**Writer-side (post-gh-315):** `src/filing_fetcher/filing_fetcher.py` uploads
HTML bytes to R2 (or `LocalFilesystemFilingStorage` in dev) immediately after
every successful fetch — both fresh downloads and cache-hits. The R2 key is
verified via a HEAD check before the DB UPDATE; if the verify fails, the fetch
fails-closed (`html_fetch_error` set, `html_storage_path` left NULL).
`scripts/migrate_filing_html_to_r2.py` remains available for back-filling
rows that stalled mid-fetch or predate gh-315.

Legacy filesystem-path detection branches in `scripts/batch_v2_extraction.py`
and `scripts/run_v2_extraction.py` are kept for one release to handle any
remaining pre-gh-315 rows in the corpus; a follow-up fragment (gh-314) will
remove them after the soak window.

### Prod-write guard

`R2FilingStorage.put_bytes` refuses to write unless
`FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` is in the process environment, mirroring
`R2Storage.put_bytes`. Reads (`get_bytes`, `exists`) remain open. The same env
var gates both image and filing R2 writes.

## SEC EDGAR Integration

- Rate limiting: 100ms minimum between requests (enforced in `sec_client.py`)
- User-Agent header required: set via `SEC_USER_AGENT` env var

## Pre-commit Deployment Checklist

For any change touching routes, migrations, or auth: (1) verify migration files are registered in the migration runner, (2) verify `url_for` endpoints resolve correctly, (3) test API endpoints with both direct calls and browser fetch to catch auth/CORS issues. (Historically, unregistered migrations and broken `url_for` calls caused multiple deployment 500 errors in Apr 2026.)
