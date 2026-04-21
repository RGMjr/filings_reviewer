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
# Connection: postgresql://dev:dev@localhost:5433/filings_analysis
```

## Production (Neon + Render)

Cloud PostgreSQL format: `postgresql://user:password@host.neon.tech/dbname?sslmode=require`

`render.yaml` defines: `filings-reviewer` web service + `filings-extraction` cron (daily 6am UTC, runs `batch_v2_extraction.py --status fetched --workers 2 --limit 50`).

## Environment Variables

| Var | Required | Purpose |
|-----|----------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection (local or Neon) |
| `SEC_USER_AGENT` | Yes | EDGAR API identification ("Name email@example.com") |
| `FILINGS_API_KEY` | Yes | API auth for web routes |
| `TEST_DATABASE_URL` | Tests only | Separate test database |
| `OPENAI_API_KEY` | LLM features | OpenAI for vision/LLM calls |
| `R2_BUCKET` | Prod / persistent envs | Cloudflare R2 bucket for image cache. When set, overrides `IMAGE_CACHE_DIR` |
| `R2_ACCESS_KEY_ID` | With `R2_BUCKET` | R2 API token access key |
| `R2_SECRET_ACCESS_KEY` | With `R2_BUCKET` | R2 API token secret |
| `R2_ENDPOINT_URL` | With `R2_BUCKET` | R2 S3-compatible endpoint (`https://<account-id>.r2.cloudflarestorage.com`) |
| `IMAGE_CACHE_DIR` | Dev only (optional) | Override local filesystem image-cache root. Ignored when `R2_BUCKET` is set |

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

## SEC EDGAR Integration

- Rate limiting: 100ms minimum between requests (enforced in `sec_client.py`)
- User-Agent header required: set via `SEC_USER_AGENT` env var

## Pre-commit Deployment Checklist

For any change touching routes, migrations, or auth: (1) verify migration files are registered in the migration runner, (2) verify `url_for` endpoints resolve correctly, (3) test API endpoints with both direct calls and browser fetch to catch auth/CORS issues. (Historically, unregistered migrations and broken `url_for` calls caused multiple deployment 500 errors in Apr 2026.)

