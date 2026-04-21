# Image Storage Architecture

## Overview

Chart and table images extracted from SEC filings live outside the PostgreSQL
database — in Cloudflare R2 (production) or the local filesystem (dev/test).
`v2_image_assets.file_path` stores an opaque **storage key**, not a filesystem
path.

The abstraction layer is `src/infra/image_storage.py`: an `ImageStorage`
Protocol with two implementations, selected at runtime via an environment
variable.

## Backends

| Backend | Selector | Root |
|---|---|---|
| `LocalFilesystemStorage` | `R2_BUCKET` unset | `<repo>/data/image_cache/` (or `IMAGE_CACHE_DIR` override) |
| `R2Storage` | `R2_BUCKET` set | Cloudflare R2 bucket, S3-compatible API via `boto3` |

`get_image_storage()` is `functools.lru_cache`d — callers that mutate the env at
runtime (tests) must call `get_image_storage.cache_clear()`.

## Key convention

Keys are opaque strings validated by `validate_key()`. The regex:
`^[A-Za-z0-9][A-Za-z0-9/_.-]{0,511}$` and rejecting any substring `..`. This
prevents path traversal at every call site and rejects legacy absolute-path
values (e.g. pre-migration `/var/folders/.../g001.jpg`).

Two canonical key prefixes today:

- `pipeline/<cik>/<accession>/<filename>` — written by
  `OCRExtractionStage._download_missing_images` when fetching from SEC EDGAR.
- `ingestion/<filing_id>/<filename>` — written by `IngestionStage` when an
  image file exists alongside the source HTML (gold-standard test fixtures).

## Call sites

Readers (6):
- `src/web/routes/review_unified.py::image_crop` — serves PNG bytes to reviewers.
- `src/web/routes/review_unified.py::_resolve_chart_image_status` — existence check for review-UI placeholder.
- `src/extraction_v2/stages/ocr_extraction.py::process_table_image` — OCR input.
- `src/extraction_v2/stages/ocr_extraction.py::process_chart_image` — vision API input.
- `src/extraction_v2/stages/fact_construction.py` — evidence screenshot copy.
- `scripts/check_image_referential_integrity.py` — CI health check.

Writers (2):
- `src/extraction_v2/stages/ocr_extraction.py::_download_missing_images` — SEC fetches.
- `src/extraction_v2/stages/ingestion.py::IngestionStage.process` — HTML-co-located images.

## Security

- `image_crop` is currently unauthenticated. SEC filings are public, but reviewer
  pool growth will eventually require adding auth. Tracked as follow-up.
- Key validation is the sole defense against path traversal. Legacy absolute
  paths from pre-migration rows return 404.
- R2 bucket is private; access is gated by the API token stored in Render env.
- `image_crop` responses include `Cache-Control: private, max-age=3600` to keep
  repeat clicks off the backend.

## Deployment

**Production (Render):**
- `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL` are
  declared `sync: false` in `render.yaml` for both web and cron services. Values
  are set via the Render dashboard.
- Token rotation: create a new R2 API token, update both services in the Render
  dashboard, trigger a redeploy, then revoke the old token.

**Local dev:**
- Default: no env vars; `LocalFilesystemStorage` under `<repo>/data/image_cache/`
  (gitignored).
- Dev-against-prod-bucket: set the four `R2_*` vars in `.env`. Tests do **not**
  require credentials — they route through a `tmp_path`-rooted local backend
  via module-level autouse fixtures.

## Migration history

Issue #34 in `docs/KNOWN_ISSUES.md`:

- **Phase 1 (commit `cf0c756`)** — Moved local cache from TMPDIR to
  `<repo>/data/image_cache/`; introduced `image_cache_dir()` helper; added
  collision-safe `pipeline/<cik>/<accession>/<filename>` layout.
- **Phase 3 (this document)** — Introduced `ImageStorage` abstraction + R2
  backend for prod persistence. `v2_image_assets.file_path` transitioned from
  absolute path to opaque storage key. Legacy rows surface as 404 in the review
  UI until their filing is re-extracted.

## Tests

- `tests/unit/infra/test_image_storage.py` — protocol + validate_key + both
  backends (R2 via `moto.mock_aws()`) + factory selection.
- `tests/unit/web/test_image_crop.py` — refactored to use
  `LocalFilesystemStorage` rooted at `tmp_path`.
- `tests/unit/extraction_v2/*` — module-level autouse fixtures route
  `IMAGE_CACHE_DIR` under `tmp_path` to isolate each test run.

Test-time dependency: `moto[s3]>=5.0.0` in `requirements-dev.txt`.
